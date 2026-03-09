// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! D-Bus service for the sync-center daemon.
//!
//! The GUI (and any other client) communicates entirely through this interface:
//!
//! **Methods**
//! - `SyncNow(profile_id)` — start syncing a single profile
//! - `SyncAll()` — serially sync every enabled profile
//! - `CancelSync()` — SIGTERM the running rsync and empty the queue
//! - `GetStatus()` → JSON — snapshot of current state + per-profile results
//! - `ReloadConfig()` — re-read config.json from disk
//!
//! **Signal**
//! - `StatusChanged(json)` — emitted after every state transition or progress tick

use crate::config::Config;
use crate::mounts::resolve_destination;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::{Mutex, RwLock};
use zbus::{dbus_interface, Connection, SignalContext};

// ─── Shared state ─────────────────────────────────────────────────────────────

/// Per-profile result kept in memory (cleared on daemon restart).
#[derive(Debug, Clone, Default)]
pub struct ProfileResult {
    /// "idle" | "syncing" | "queued" | "success" | "partial" | "error"
    pub state: String,
    /// 0.0–1.0 while syncing, -1.0 = scanning/indeterminate
    pub progress: f64,
    pub last_sync: String,
    pub error: String,
}

#[derive(Clone)]
pub struct DaemonState {
    pub config: Arc<RwLock<Config>>,
    pub active_profile_id: Arc<RwLock<Option<String>>>,
    pub active_progress: Arc<RwLock<f64>>,
    pub results: Arc<RwLock<HashMap<String, ProfileResult>>>,
    pub cancel_flag: Arc<AtomicBool>,
    /// True while a `sync_all` queue task is in flight — even between profiles.
    /// Prevents `sync_now` / `sync_all` from sneaking in during inter-profile gaps
    /// when `active_profile_id` is momentarily `None`.
    pub queue_running: Arc<AtomicBool>,
    pub rsync_pid: Arc<Mutex<Option<u32>>>,
    pub dbus_conn: Arc<Mutex<Option<Connection>>>,
}

impl DaemonState {
    pub fn new(config: Config) -> Self {
        Self {
            config: Arc::new(RwLock::new(config)),
            active_profile_id: Arc::new(RwLock::new(None)),
            active_progress: Arc::new(RwLock::new(-1.0)),
            results: Arc::new(RwLock::new(HashMap::new())),
            cancel_flag: Arc::new(AtomicBool::new(false)),
            queue_running: Arc::new(AtomicBool::new(false)),
            rsync_pid: Arc::new(Mutex::new(None)),
            dbus_conn: Arc::new(Mutex::new(None)),
        }
    }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

fn now_timestamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let h = (secs % 86400) / 3600;
    let m = (secs % 3600) / 60;
    format!("today {:02}:{:02}", h, m)
}

fn parse_progress_pct(line: &str) -> Option<f64> {
    for token in line.split_whitespace() {
        if token.ends_with('%') {
            if let Ok(n) = token.trim_end_matches('%').parse::<f64>() {
                if (0.0..=100.0).contains(&n) {
                    return Some(n / 100.0);
                }
            }
        }
    }
    None
}

async fn build_status_json(state: &DaemonState) -> String {
    let active_id = state.active_profile_id.read().await.clone();
    let progress = *state.active_progress.read().await;
    let results = state.results.read().await.clone();

    let profiles_json: HashMap<String, Value> = results
        .iter()
        .map(|(id, r)| {
            (
                id.clone(),
                json!({
                    "state":     r.state,
                    "progress":  r.progress,
                    "last_sync": r.last_sync,
                    "error":     r.error,
                }),
            )
        })
        .collect();

    json!({
        "active":            active_id.is_some(),
        "active_profile_id": active_id.unwrap_or_default(),
        "active_progress":   progress,
        "profiles":          profiles_json,
    })
    .to_string()
}

async fn emit_status(state: &DaemonState) {
    let json = build_status_json(state).await;
    if let Some(conn) = state.dbus_conn.lock().await.as_ref() {
        if let Ok(ctx) = SignalContext::new(conn, "/org/smpl/SyncCenter") {
            let _ = DbusService::status_changed(&ctx, &json).await;
        }
    }
}

// ─── rsync execution ─────────────────────────────────────────────────────────

fn run_rsync_blocking(
    source: &str,
    destination: &std::path::PathBuf,
    excludes: &[String],
    cancel_flag: Arc<AtomicBool>,
    rsync_pid_slot: Arc<Mutex<Option<u32>>>,
    on_progress: impl Fn(f64) + Send + 'static,
) -> Result<(), String> {
    if let Err(e) = fs::create_dir_all(destination) {
        return Err(format!(
            "Cannot create destination {}: {}",
            destination.display(),
            e
        ));
    }

    let source_slash = if source.ends_with('/') {
        source.to_string()
    } else {
        format!("{}/", source)
    };

    let mut cmd = Command::new("rsync");
    cmd.arg("-a")
        .arg("--delete")
        .arg("-L")
        .arg("--timeout=300")
        .arg("--info=progress2");
    for pattern in excludes {
        cmd.arg("--exclude").arg(pattern);
    }
    cmd.arg(&source_slash).arg(destination);

    let mut child = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                "rsync not found. Install with: sudo pacman -S rsync".to_string()
            } else {
                format!("Failed to start rsync: {}", e)
            }
        })?;

    let pid = child.id();
    if let Ok(mut guard) = rsync_pid_slot.try_lock() {
        *guard = Some(pid);
    }

    let (prog_tx, prog_rx) = std::sync::mpsc::channel::<f64>();
    let stdout = child.stdout.take().expect("stdout was piped");
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().flatten() {
            if let Some(pct) = parse_progress_pct(&line) {
                let _ = prog_tx.send(pct);
            }
        }
    });

    // Drain stderr concurrently so rsync never blocks on a full kernel pipe buffer
    // (default 64 KB).  Without this, a run that emits many per-file errors
    // (e.g. permission-denied on every file) would deadlock: rsync blocks
    // writing stderr, never exits, and our wait-loop spins forever.
    let (stderr_tx, _stderr_rx) = std::sync::mpsc::channel::<String>();
    let stderr_pipe = child.stderr.take().expect("stderr was piped");
    std::thread::spawn(move || {
        let collected = BufReader::new(stderr_pipe)
            .lines()
            .filter_map(|l| l.ok())
            .collect::<Vec<_>>()
            .join("; ");
        let _ = stderr_tx.send(collected);
    });

    loop {
        while let Ok(pct) = prog_rx.try_recv() {
            on_progress(pct);
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                while let Ok(pct) = prog_rx.try_recv() {
                    on_progress(pct);
                }
                if let Ok(mut g) = rsync_pid_slot.try_lock() {
                    *g = None;
                }
                if cancel_flag.load(Ordering::Relaxed) {
                    return Err("cancelled".to_string());
                }
                return match status.code().unwrap_or(-1) {
                    0 => Ok(()),
                    23 => Err("partial:Some files were not transferred (permissions or busy files)"
                        .to_string()),
                    24 => Ok(()), // source files vanished — benign race
                    code => {
                        let stderr = child
                            .stderr
                            .take()
                            .map(|s| {
                                BufReader::new(s)
                                    .lines()
                                    .filter_map(|l| l.ok())
                                    .collect::<Vec<_>>()
                                    .join("; ")
                            })
                            .unwrap_or_default();
                        Err(if stderr.is_empty() {
                            format!("rsync failed (exit {})", code)
                        } else {
                            stderr
                        })
                    }
                };
            }
            Ok(None) => {
                if cancel_flag.load(Ordering::Relaxed) {
                    unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM) };
                    let _ = child.wait();
                    if let Ok(mut g) = rsync_pid_slot.try_lock() {
                        *g = None;
                    }
                    return Err("cancelled".to_string());
                }
                std::thread::sleep(std::time::Duration::from_millis(200));
            }
            Err(e) => return Err(format!("Error waiting for rsync: {}", e)),
        }
    }
}

async fn execute_profile_sync(profile_id: String, state: DaemonState) {
    // Mark syncing / scanning
    {
        let mut results = state.results.write().await;
        let entry = results.entry(profile_id.clone()).or_default();
        entry.state = "syncing".to_string();
        entry.progress = -1.0;
        entry.error = String::new();
    }
    *state.active_profile_id.write().await = Some(profile_id.clone());
    *state.active_progress.write().await = -1.0;
    emit_status(&state).await;

    let (source, dest, excludes) = {
        let cfg = state.config.read().await;
        match cfg.profiles.iter().find(|p| p.id == profile_id) {
            Some(p) => {
                let source = p.syncs.first().map(|s| s.source.clone()).unwrap_or_default();
                let excludes = p.syncs.first().map(|s| s.exclude.clone()).unwrap_or_default();
                let dest = resolve_destination(p);
                (source, dest, excludes)
            }
            None => {
                record_result(&state, &profile_id, Err(format!("Profile '{}' not found", profile_id))).await;
                return;
            }
        }
    };

    let dest = match dest {
        Some(d) => d,
        None => {
            record_result(&state, &profile_id, Err("USB volume not mounted".to_string())).await;
            return;
        }
    };

    // Progress callback — fired from the blocking thread
    let state_prog = state.clone();
    let pid_prog = profile_id.clone();
    let on_progress = move |pct: f64| {
        if let Ok(mut p) = state_prog.active_progress.try_write() {
            *p = pct;
        }
        if let Ok(mut r) = state_prog.results.try_write() {
            if let Some(entry) = r.get_mut(&pid_prog) {
                entry.progress = pct;
            }
        }
        // Emit signal async — fire-and-forget via a one-shot task
        let s2 = state_prog.clone();
        tokio::spawn(async move { emit_status(&s2).await });
    };

    let cancel = state.cancel_flag.clone();
    let pid_slot = state.rsync_pid.clone();

    let result = tokio::task::spawn_blocking(move || {
        run_rsync_blocking(&source, &dest, &excludes, cancel, pid_slot, on_progress)
    })
    .await
    .unwrap_or_else(|e| Err(format!("Task panicked: {}", e)));

    record_result(&state, &profile_id, result).await;
}

async fn record_result(state: &DaemonState, profile_id: &str, result: Result<(), String>) {
    *state.active_profile_id.write().await = None;
    *state.active_progress.write().await = -1.0;
    {
        let mut results = state.results.write().await;
        let entry = results.entry(profile_id.to_string()).or_default();
        entry.progress = 0.0;
        match &result {
            Ok(()) => {
                entry.state = "success".to_string();
                entry.last_sync = now_timestamp();
                entry.error = String::new();
            }
            Err(e) if e == "cancelled" => {
                entry.state = "idle".to_string();
                entry.error = String::new();
            }
            Err(e) if e.starts_with("partial:") => {
                entry.state = "partial".to_string();
                entry.last_sync = now_timestamp();
                entry.error = e["partial:".len()..].to_string();
            }
            Err(e) => {
                entry.state = "error".to_string();
                entry.error = e.clone();
            }
        }
    }
    emit_status(state).await;
}

// ─── D-Bus service ───────────────────────────────────────────────────────────

pub struct DbusService {
    pub state: DaemonState,
}

impl DbusService {
    pub fn new(state: DaemonState) -> Self {
        Self { state }
    }

    pub async fn start(state: DaemonState) -> Result<(), Box<dyn std::error::Error>> {
        let service = DbusService::new(state.clone());
        let connection = zbus::ConnectionBuilder::session()?
            .name("org.smpl.SyncCenter")?
            .serve_at("/org/smpl/SyncCenter", service)?
            .build()
            .await?;
        *state.dbus_conn.lock().await = Some(connection.clone());
        emit_status(&state).await;
        tracing::info!("D-Bus service ready on org.smpl.SyncCenter");
        std::future::pending::<()>().await;
        Ok(())
    }
}

#[dbus_interface(name = "org.smpl.SyncCenter")]
impl DbusService {
    #[dbus_interface(property)]
    async fn is_active(&self) -> bool {
        self.state.active_profile_id.read().await.is_some()
    }

    #[dbus_interface(property)]
    async fn current_profile(&self) -> String {
        self.state
            .active_profile_id
            .read()
            .await
            .clone()
            .unwrap_or_default()
    }

    async fn get_status(&self) -> String {
        build_status_json(&self.state).await
    }

    async fn sync_now(&self, profile_id: String) -> bool {
        if self.state.active_profile_id.read().await.is_some()
            || self.state.queue_running.load(Ordering::Acquire)
        {
            return false;
        }
        self.state.cancel_flag.store(false, Ordering::Release);
        let state = self.state.clone();
        tokio::spawn(async move {
            execute_profile_sync(profile_id, state).await;
        });
        true
    }

    async fn sync_all(&self) -> bool {
        if self.state.active_profile_id.read().await.is_some()
            || self.state.queue_running.load(Ordering::Acquire)
        {
            return false;
        }
        self.state.cancel_flag.store(false, Ordering::Release);
        // Hold the queue lock for the entire lifetime of the serial task so that
        // sync_now cannot sneak in during the inter-profile gap where
        // active_profile_id is momentarily None.
        self.state.queue_running.store(true, Ordering::Release);

        let profile_ids: Vec<String> = self
            .state
            .config
            .read()
            .await
            .profiles
            .iter()
            .filter(|p| p.enabled)
            .map(|p| p.id.clone())
            .collect();

        if profile_ids.is_empty() {
            self.state.queue_running.store(false, Ordering::Release);
            return false;
        }

        {
            let mut results = self.state.results.write().await;
            for id in &profile_ids {
                let entry = results.entry(id.clone()).or_default();
                entry.state = "queued".to_string();
                entry.progress = -1.0;
            }
        }
        emit_status(&self.state).await;

        let state = self.state.clone();
        tokio::spawn(async move {
            for id in profile_ids {
                if state.cancel_flag.load(Ordering::Relaxed) {
                    record_result(&state, &id, Err("cancelled".to_string())).await;
                    continue;
                }
                execute_profile_sync(id, state.clone()).await;
            }
            // Release the queue lock and reset cancel_flag so the next
            // sync_all / sync_now call starts from a clean state.
            state.queue_running.store(false, Ordering::Release);
            state.cancel_flag.store(false, Ordering::Release);
        });
        true
    }

    async fn cancel_sync(&self) -> bool {
        self.state.cancel_flag.store(true, Ordering::Relaxed);
        if let Some(pid) = *self.state.rsync_pid.lock().await {
            unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM) };
        }
        true
    }

    async fn reload_config(&self) -> bool {
        match Config::load() {
            Ok(cfg) => {
                // Collect valid IDs *before* overwriting the config so we
                // can prune stale results from deleted profiles.
                let valid_ids: std::collections::HashSet<String> =
                    cfg.profiles.iter().map(|p| p.id.clone()).collect();
                *self.state.config.write().await = cfg;
                {
                    let mut results = self.state.results.write().await;
                    results.retain(|id, _| valid_ids.contains(id));
                }
                emit_status(&self.state).await;
                true
            }
            Err(_) => false,
        }
    }

    #[dbus_interface(signal)]
    pub async fn status_changed(ctxt: &SignalContext<'_>, json: &str) -> zbus::Result<()>;
}
