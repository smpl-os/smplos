// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center GUI — thin control surface over the daemon via D-Bus.
//!
//! The GUI itself does not run rsync.  All sync operations are delegated to
//! `sync-center-daemon` via the `org.smpl.SyncCenter` D-Bus interface.
//! The GUI subscribes to the `StatusChanged` signal and updates its Slint
//! model on every change (progress ticks, completion, errors).

use sync_center::config::{
    Config, DirectorySync, PostSyncAction, SyncProfile as ConfigProfile, VolumeIdentifier,
};
use sync_center::mounts::{device_for_mount_path, uuid_for_device};
use std::env;
use std::fs;
use std::process::{Command, Stdio};
use std::rc::Rc;
use std::cell::RefCell;
use std::time::{SystemTime, UNIX_EPOCH};
use rfd::FileDialog;
use slint::{Model, ModelRc, SharedString, VecModel};

slint::include_modules!();

// ─── USB volume helpers ───────────────────────────────────────────────────────

struct UsbVolumeChoice {
    label: SharedString,
    uuid: SharedString,
}

fn list_usb_volumes() -> Vec<UsbVolumeChoice> {
    let user = env::var("USER").unwrap_or_default();
    let base = format!("/run/media/{}", user);
    let mut volumes = Vec::new();
    if let Ok(entries) = fs::read_dir(base) {
        for entry in entries.flatten() {
            if let Ok(meta) = entry.metadata() {
                if meta.is_dir() {
                    if let Some(name) = entry.file_name().to_str() {
                        let mount_path = entry.path().to_string_lossy().to_string();
                        let uuid = device_for_mount_path(&mount_path)
                            .and_then(|dev| uuid_for_device(&dev))
                            .unwrap_or_else(|| "UUID unavailable".to_string());
                        volumes.push(UsbVolumeChoice {
                            label: SharedString::from(name),
                            uuid: SharedString::from(uuid),
                        });
                    }
                }
            }
        }
    }
    volumes
}

fn set_volume_choices(ui: &MainWindow) {
    let volumes = list_usb_volumes();
    let labels: Vec<SharedString> = volumes.iter().map(|v| v.label.clone()).collect();
    let uuids: Vec<SharedString> = volumes.iter().map(|v| v.uuid.clone()).collect();

    ui.set_dialog_volume_choices(ModelRc::from(Rc::new(VecModel::from(labels))));
    ui.set_dialog_volume_uuid_choices(ModelRc::from(Rc::new(VecModel::from(uuids))));

    let count = ui.get_dialog_volume_choices().row_count();
    if count == 0 {
        ui.set_dialog_volume_choice_index(-1);
        return;
    }

    let mut idx = ui.get_dialog_volume_choice_index();
    if idx < 0 || (idx as usize) >= count {
        idx = 0;
        ui.set_dialog_volume_choice_index(0);
    }

    let id_mode = ui.get_dialog_volume_identifier_index();
    if id_mode == 0 {
        if let Some(label) = ui.get_dialog_volume_choices().row_data(idx as usize) {
            ui.set_dialog_volume_identifier_value(label);
        }
    } else if id_mode == 1 {
        if let Some(uuid) = ui.get_dialog_volume_uuid_choices().row_data(idx as usize) {
            ui.set_dialog_volume_identifier_value(uuid);
        }
    }
}

// ─── Daemon lifecycle ─────────────────────────────────────────────────────────

fn start_daemon() -> Result<(), Box<dyn std::error::Error>> {
    let mut path = env::current_exe()?;
    path.pop();
    path.push("sync-center-daemon");
    if !path.exists() {
        return Err("Daemon binary not found".into());
    }
    Command::new(path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    Ok(())
}

/// Returns `true` if the daemon has claimed its well-known D-Bus name.
/// More reliable than `pgrep` because it confirms the daemon is fully
/// initialised and ready to accept method calls, not just that the process
/// has been forked.
fn is_daemon_running() -> bool {
    let Ok(conn) = zbus::blocking::Connection::session() else {
        return false;
    };
    conn.call_method(
        Some("org.freedesktop.DBus"),
        "/org/freedesktop/DBus",
        Some("org.freedesktop.DBus"),
        "NameHasOwner",
        &"org.smpl.SyncCenter",
    )
    .ok()
    .and_then(|m| m.body::<bool>().ok())
    .unwrap_or(false)
}

// ─── D-Bus proxy (blocking, GUI thread) ──────────────────────────────────────

/// Thin blocking wrapper around `org.smpl.SyncCenter`.
struct DaemonProxy {
    conn: zbus::blocking::Connection,
}

impl DaemonProxy {
    fn new() -> Option<Self> {
        zbus::blocking::Connection::session()
            .ok()
            .map(|conn| Self { conn })
    }

    fn call<B, R>(&self, method: &str, body: &B) -> Option<R>
    where
        B: serde::Serialize + zvariant::DynamicType,
        R: serde::de::DeserializeOwned + zvariant::Type,
    {
        self.conn
            .call_method(
                Some("org.smpl.SyncCenter"),
                "/org/smpl/SyncCenter",
                Some("org.smpl.SyncCenter"),
                method,
                body,
            )
            .ok()
            .and_then(|m| m.body::<R>().ok())
    }

    fn sync_now(&self, profile_id: &str) -> bool {
        self.call::<_, bool>("SyncNow", &profile_id).unwrap_or(false)
    }
    fn sync_all(&self) -> bool {
        self.call::<_, bool>("SyncAll", &()).unwrap_or(false)
    }
    fn cancel_sync(&self) -> bool {
        self.call::<_, bool>("CancelSync", &()).unwrap_or(false)
    }
    fn get_status(&self) -> Option<serde_json::Value> {
        self.call::<_, String>("GetStatus", &())
            .and_then(|s| serde_json::from_str(&s).ok())
    }
    fn reload_config(&self) {
        let _ = self.call::<_, bool>("ReloadConfig", &());
    }
}

// ─── Profile model helpers ────────────────────────────────────────────────────

fn to_ui_profile(p: &ConfigProfile) -> SyncProfile {
    let (label, source, dest) = match p.syncs.first() {
        Some(sync) => (
            match &p.identifier {
                VolumeIdentifier::Label { value } => value.clone(),
                VolumeIdentifier::UUID { value } => value.clone(),
                VolumeIdentifier::Marker { path } => path.clone(),
            },
            sync.source.clone(),
            sync.destination.clone(),
        ),
        None => (String::new(), String::new(), String::new()),
    };

    SyncProfile {
        id: p.id.clone().into(),
        name: p.name.clone().into(),
        enabled: p.enabled,
        volume_label: label.into(),
        source_path: source.into(),
        destination_path: dest.into(),
        last_sync: "".into(),
        status: "idle".into(),
        is_syncing: false,
        error_text: "".into(),
        progress: 0.0,
    }
}

fn now_timestamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let h = (secs % 86400) / 3600;
    let m = (secs % 3600) / 60;
    format!("today {:02}:{:02}", h, m)
}

// ─── Status JSON → Slint model ────────────────────────────────────────────────

/// Apply a daemon status snapshot to the Slint profiles model.
///
/// Only updates the fields that can change during/after a sync (is_syncing,
/// status, progress, last_sync, error_text).  The GUI retains its own
/// knowledge of name, paths, etc. so there's no flicker.
fn apply_status_to_model(model: &ModelRc<SyncProfile>, status: &serde_json::Value) {
    let profiles_obj = match status.get("profiles").and_then(|v| v.as_object()) {
        Some(o) => o,
        None => return,
    };

    for i in 0..model.row_count() {
        let mut p = match model.row_data(i) {
            Some(p) => p,
            None => continue,
        };
        let id = p.id.to_string();
        let entry = match profiles_obj.get(&id) {
            Some(e) => e,
            None => {
                // Profile known to GUI but not yet in daemon results — idle
                p.is_syncing = false;
                model.set_row_data(i, p);
                continue;
            }
        };

        let state = entry.get("state").and_then(|v| v.as_str()).unwrap_or("idle");
        let progress = entry.get("progress").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
        let last_sync = entry.get("last_sync").and_then(|v| v.as_str()).unwrap_or("");
        let error = entry.get("error").and_then(|v| v.as_str()).unwrap_or("");

        p.is_syncing = state == "syncing" || state == "queued";
        p.progress = if p.is_syncing { progress } else { 0.0 };
        p.status = state.into();
        if !last_sync.is_empty() {
            p.last_sync = last_sync.into();
        }
        p.error_text = error.into();
        model.set_row_data(i, p);
    }
}

// ─── Export / Import ──────────────────────────────────────────────────────────

fn export_profiles_to_file(config: &Config) -> String {
    let profiles_json = match serde_json::to_string_pretty(&config.profiles) {
        Ok(j) => j,
        Err(e) => return format!("Serialization error: {}", e),
    };
    match FileDialog::new()
        .set_title("Export Profiles")
        .set_file_name("sync-center-profiles.json")
        .add_filter("JSON", &["json"])
        .save_file()
    {
        Some(p) => match fs::write(&p, &profiles_json) {
            Ok(_) => format!("✓ Exported {} profile(s) to {}", config.profiles.len(), p.display()),
            Err(e) => format!("Cannot write file: {}", e),
        },
        None => String::new(),
    }
}

fn import_profiles_from_file(config: &mut Config) -> String {
    let path = match FileDialog::new()
        .set_title("Import Profiles")
        .add_filter("JSON", &["json"])
        .pick_file()
    {
        Some(p) => p,
        None => return String::new(),
    };
    let contents = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(e) => return format!("Cannot read file: {}", e),
    };
    let imported: Vec<ConfigProfile> = match serde_json::from_str(&contents) {
        Ok(v) => v,
        Err(e) => return format!("Invalid JSON: {}", e),
    };
    let existing_ids: std::collections::HashSet<String> =
        config.profiles.iter().map(|p| p.id.clone()).collect();
    let mut added = 0usize;
    for profile in imported {
        if !existing_ids.contains(&profile.id) {
            config.profiles.push(profile);
            added += 1;
        }
    }
    if let Err(e) = config.save() {
        return format!("Cannot save config: {}", e);
    }
    format!("✓ Imported {} new profile(s)", added)
}

// ─── Status signal subscriber ─────────────────────────────────────────────────

/// Spawn a background thread that subscribes to `StatusChanged` on D-Bus and
/// pushes updates to the Slint model via `invoke_from_event_loop`.
///
/// An outer reconnect loop retries after any connection or subscription error
/// (e.g. daemon restart, session-bus hiccup).  After reconnecting it re-fetches
/// `GetStatus` to fill the gap.  The thread exits when the Slint event loop
/// is gone (window destroyed).
fn start_signal_listener(window_weak: slint::Weak<MainWindow>) {
    std::thread::spawn(move || {
        // Outer reconnect loop.
        loop {
            // Check whether the Slint event loop is still alive before each
            // reconnect attempt.  invoke_from_event_loop returns Err once the
            // event loop has exited.
            if slint::invoke_from_event_loop(|| {}).is_err() {
                break;
            }

            let conn = match zbus::blocking::Connection::session() {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("Signal listener: D-Bus connect failed: {} — retrying in 2 s", e);
                    std::thread::sleep(std::time::Duration::from_secs(2));
                    continue;
                }
            };

            // Build a match rule for the StatusChanged signal.
            let rule = match zbus::MatchRule::builder()
                .msg_type(zbus::MessageType::Signal)
                .interface("org.smpl.SyncCenter")
                .and_then(|b| b.member("StatusChanged"))
                .map(|b| b.build())
            {
                Ok(r) => r,
                // Hard-coded strings are wrong — no point retrying.
                Err(e) => {
                    eprintln!("Signal listener: bad match rule: {}", e);
                    break;
                }
            };

            let mut iter = match zbus::blocking::MessageIterator::for_match_rule(
                rule,
                &conn,
                Some(64),
            ) {
                Ok(i) => i,
                Err(e) => {
                    eprintln!("Signal listener: subscribe failed: {} — retrying in 2 s", e);
                    std::thread::sleep(std::time::Duration::from_secs(2));
                    continue;
                }
            };

            // Inner receive loop — runs until the iterator is exhausted or errors.
            loop {
                match iter.next() {
                    Some(Ok(msg)) => {
                        if let Ok(json_str) = msg.body::<String>() {
                            if let Ok(status) =
                                serde_json::from_str::<serde_json::Value>(&json_str)
                            {
                                let w = window_weak.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(window) = w.upgrade() {
                                        let model = window.get_profiles();
                                        apply_status_to_model(&model, &status);
                                    }
                                });
                            }
                        }
                    }
                    Some(Err(e)) => {
                        eprintln!(
                            "Signal listener error: {} — reconnecting in 2 s",
                            e
                        );
                        break; // fall through to reconnect
                    }
                    None => break, // iterator exhausted
                }
            }

            // Re-fetch the full status snapshot to cover the gap while we
            // were disconnected, then wait before reconnecting.
            if let Some(proxy) = DaemonProxy::new() {
                if let Some(status) = proxy.get_status() {
                    let w = window_weak.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(window) = w.upgrade() {
                            let model = window.get_profiles();
                            apply_status_to_model(&model, &status);
                        }
                    });
                }
            }

            std::thread::sleep(std::time::Duration::from_secs(2));
        }
    });
}

// ─── main ─────────────────────────────────────────────────────────────────────

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("sync-center", "sync-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(800.0_f64, 600.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let main_window = MainWindow::new()?;
    main_window.set_app_version(env!("SYNC_CENTER_VERSION").into());

    // Ensure daemon is running. If we just spawned it, poll the D-Bus name
    // every 100 ms (up to 3 s) instead of using a fixed sleep: on fast
    // machines we proceed sooner; on slow ones we don't time out prematurely.
    if !is_daemon_running() {
        let _ = start_daemon();
        let deadline =
            std::time::Instant::now() + std::time::Duration::from_secs(3);
        loop {
            std::thread::sleep(std::time::Duration::from_millis(100));
            if is_daemon_running() {
                break;
            }
            if std::time::Instant::now() >= deadline {
                break;
            }
        }
    }
    main_window.set_daemon_running(is_daemon_running());

    // Load config (GUI still manages config; daemon is notified to reload after saves)
    let config = Config::load().unwrap_or_default();
    let config_rc = Rc::new(RefCell::new(config));

    // Build initial profile list from config
    let initial_profiles: Vec<SyncProfile> = config_rc
        .borrow()
        .profiles
        .iter()
        .map(to_ui_profile)
        .collect();
    let profiles_model = Rc::new(VecModel::from(initial_profiles));
    main_window.set_profiles(ModelRc::from(profiles_model.clone()));

    set_volume_choices(&main_window);

    // Subscribe to StatusChanged BEFORE fetching the initial snapshot so no
    // signal emitted between subscription and the get_status call is lost.
    start_signal_listener(main_window.as_weak());

    // Ask daemon for current status so profiles already syncing (e.g. from a
    // previous GUI session) are shown correctly on launch.
    if let Some(proxy) = DaemonProxy::new() {
        if let Some(status) = proxy.get_status() {
            apply_status_to_model(&ModelRc::from(profiles_model.clone()), &status);
        }
    }

    // ── on_add_profile ────────────────────────────────────────────────────────
    main_window.on_add_profile({
        let window = main_window.as_weak();
        move || {
            if let Some(ui) = window.upgrade() {
                ui.set_dialog_error_message("".into());
                set_volume_choices(&ui);
                let id_index = ui.get_dialog_volume_identifier_index();
                if (id_index == 0 || id_index == 1) && ui.get_dialog_volume_identifier_value().is_empty() {
                    let choices = ui.get_dialog_volume_choices();
                    let uuid_choices = ui.get_dialog_volume_uuid_choices();
                    let idx = ui.get_dialog_volume_choice_index();
                    if idx >= 0 && (idx as usize) < choices.row_count() {
                        if id_index == 0 {
                            if let Some(label) = choices.row_data(idx as usize) {
                                ui.set_dialog_volume_identifier_value(label);
                            }
                        } else if (idx as usize) < uuid_choices.row_count() {
                            if let Some(uuid) = uuid_choices.row_data(idx as usize) {
                                ui.set_dialog_volume_identifier_value(uuid);
                            }
                        }
                    }
                }
            }
        }
    });

    // ── on_edit_profile ───────────────────────────────────────────────────────
    main_window.on_edit_profile({
        move |_idx| { /* Future: populate dialog for editing */ }
    });

    // ── on_sync_profile ───────────────────────────────────────────────────────
    main_window.on_sync_profile({
        let window = main_window.as_weak();
        let profiles_model = profiles_model.clone();
        move |idx| {
            let idx_usize = idx as usize;
            let p = match profiles_model.row_data(idx_usize) {
                Some(p) => p,
                None => return,
            };

            // If already syncing → cancel via daemon
            if p.is_syncing {
                if let Some(proxy) = DaemonProxy::new() {
                    proxy.cancel_sync();
                }
                return;
            }

            // Tell daemon to sync this profile
            let profile_id = p.id.to_string();
            if let Some(proxy) = DaemonProxy::new() {
                if !proxy.sync_now(&profile_id) {
                    // Daemon refused (already busy) — show in UI
                    if let Some(ui) = window.upgrade() {
                        let model = ui.get_profiles();
                        if let Some(mut row) = model.row_data(idx_usize) {
                            row.error_text = "Another sync is already running".into();
                            model.set_row_data(idx_usize, row);
                        }
                    }
                }
            } else {
                // Daemon not reachable — show error
                if let Some(ui) = window.upgrade() {
                    let model = ui.get_profiles();
                    if let Some(mut row) = model.row_data(idx_usize) {
                        row.status = "error".into();
                        row.error_text = "Daemon not running".into();
                        model.set_row_data(idx_usize, row);
                    }
                }
            }
        }
    });

    // ── on_toggle_profile ─────────────────────────────────────────────────────
    main_window.on_toggle_profile({
        let config_rc = config_rc.clone();
        let profiles_model = profiles_model.clone();
        move |idx| {
            let idx_usize = idx as usize;
            if let Some(mut p) = profiles_model.row_data(idx_usize) {
                p.enabled = !p.enabled;
                profiles_model.set_row_data(idx_usize, p.clone());
                if let Ok(mut cfg) = config_rc.try_borrow_mut() {
                    if let Some(cp) = cfg.profiles.get_mut(idx_usize) {
                        cp.enabled = p.enabled;
                        let _ = cfg.save();
                    }
                }
            }
        }
    });

    // ── on_delete_profile ─────────────────────────────────────────────────────
    main_window.on_delete_profile({
        let config_rc = config_rc.clone();
        let profiles_model = profiles_model.clone();
        move |idx| {
            let idx_usize = idx as usize;
            // Guard: refuse if syncing (UI also disables the button)
            if profiles_model.row_data(idx_usize).map(|p| p.is_syncing).unwrap_or(false) {
                return;
            }
            if idx_usize < profiles_model.row_count() {
                profiles_model.remove(idx_usize);
            }
            if let Ok(mut cfg) = config_rc.try_borrow_mut() {
                if idx_usize < cfg.profiles.len() {
                    cfg.profiles.remove(idx_usize);
                    let _ = cfg.save();
                }
            }
        }
    });

    // ── on_start_sync ─────────────────────────────────────────────────────────
    main_window.on_start_sync({
        let window = main_window.as_weak();
        let profiles_model = profiles_model.clone();
        move || {
            // Check if any profile is already syncing
            let any_syncing = (0..profiles_model.row_count())
                .any(|i| profiles_model.row_data(i).map(|p| p.is_syncing).unwrap_or(false));
            if any_syncing {
                return;
            }
            if let Some(proxy) = DaemonProxy::new() {
                if !proxy.sync_all() {
                    if let Some(ui) = window.upgrade() {
                        // No enabled profiles or already running
                        let _ = ui; // nothing to show; daemon handles it
                    }
                }
            }
        }
    });

    // ── on_stop_sync ──────────────────────────────────────────────────────────
    main_window.on_stop_sync({
        move || {
            if let Some(proxy) = DaemonProxy::new() {
                proxy.cancel_sync();
            }
        }
    });

    // ── on_refresh ────────────────────────────────────────────────────────────
    main_window.on_refresh({
        let window = main_window.as_weak();
        let profiles_model = profiles_model.clone();
        move || {
            if let Some(ui) = window.upgrade() {
                set_volume_choices(&ui);
                ui.set_daemon_running(is_daemon_running());
                // Re-fetch current daemon status
                if let Some(proxy) = DaemonProxy::new() {
                    if let Some(status) = proxy.get_status() {
                        apply_status_to_model(&ModelRc::from(profiles_model.clone()), &status);
                    }
                }
            }
        }
    });

    // ── on_browse_source ──────────────────────────────────────────────────────
    main_window.on_browse_source({
        let window = main_window.as_weak();
        move || {
            if let Some(ui) = window.upgrade() {
                if let Some(path) = FileDialog::new().pick_folder() {
                    ui.set_dialog_source_path(path.display().to_string().into());
                }
            }
        }
    });

    // ── on_save_profile ───────────────────────────────────────────────────────
    main_window.on_save_profile({
        let window = main_window.as_weak();
        let config_rc = config_rc.clone();
        let profiles_model = profiles_model.clone();
        move || -> bool {
            let ui = match window.upgrade() {
                Some(u) => u,
                None => return false,
            };
            let id_index = ui.get_dialog_volume_identifier_index();
            let id_type = if id_index == 0 { "label" } else if id_index == 1 { "uuid" } else { "marker" };

            if (id_index == 0 || id_index == 1) && ui.get_dialog_volume_identifier_value().is_empty() {
                let choices = ui.get_dialog_volume_choices();
                let uuid_choices = ui.get_dialog_volume_uuid_choices();
                let sel = ui.get_dialog_volume_choice_index();
                if sel >= 0 && (sel as usize) < choices.row_count() {
                    if id_index == 0 {
                        if let Some(label) = choices.row_data(sel as usize) {
                            ui.set_dialog_volume_identifier_value(label);
                        }
                    } else if (sel as usize) < uuid_choices.row_count() {
                        if let Some(uuid) = uuid_choices.row_data(sel as usize) {
                            ui.set_dialog_volume_identifier_value(uuid);
                        }
                    }
                }
            }

            let name = ui.get_dialog_profile_name().to_string();
            let source = ui.get_dialog_source_path().to_string();
            let dest = ui.get_dialog_destination_path().to_string();
            let id_value = ui.get_dialog_volume_identifier_value().to_string();

            if ui.get_dialog_volume_choices().row_count() == 0 {
                ui.set_dialog_error_message("No mounted USB volume found. Mount your USB drive first.".into());
                return false;
            }

            let mut missing = Vec::new();
            if name.trim().is_empty() { missing.push("Name"); }
            if source.trim().is_empty() { missing.push("Source"); }
            if dest.trim().is_empty() { missing.push("Destination"); }
            if id_value.trim().is_empty() { missing.push("USB identifier"); }
            if !missing.is_empty() {
                ui.set_dialog_error_message(format!("Missing required fields: {}", missing.join(", ")).into());
                return false;
            }
            ui.set_dialog_error_message("".into());

            let identifier = match id_type {
                "label" => VolumeIdentifier::Label { value: id_value.clone() },
                "uuid"  => VolumeIdentifier::UUID  { value: id_value.clone() },
                _       => VolumeIdentifier::Marker { path: id_value.clone() },
            };

            let excludes: Vec<String> = ui
                .get_dialog_exclude_patterns()
                .split(',')
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string())
                .collect();

            let id = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| format!("profile-{}", d.as_secs()))
                .unwrap_or_else(|_| "profile-unknown".to_string());

            let profile = ConfigProfile {
                id,
                name,
                enabled: true,
                identifier,
                syncs: vec![DirectorySync {
                    source,
                    destination: dest,
                    bidirectional: false,
                    delete_missing: false,
                    exclude: excludes,
                }],
                post_sync_action: PostSyncAction::Notify,
            };

            if let Ok(mut cfg) = config_rc.try_borrow_mut() {
                cfg.profiles.push(profile.clone());
                if let Err(e) = cfg.save() {
                    ui.set_dialog_error_message(format!("Could not save config: {}", e).into());
                    return false;
                }
                // Tell daemon to reload so it knows about the new profile
                if let Some(proxy) = DaemonProxy::new() {
                    proxy.reload_config();
                }
            } else {
                ui.set_dialog_error_message("Config is busy, please try again.".into());
                return false;
            }

            profiles_model.push(to_ui_profile(&profile));

            ui.set_dialog_profile_name("".into());
            ui.set_dialog_source_path("".into());
            ui.set_dialog_destination_path("".into());
            ui.set_dialog_volume_identifier_value("".into());
            ui.set_dialog_exclude_patterns("".into());
            ui.set_dialog_error_message("".into());
            true
        }
    });

    // ── on_export_profiles ────────────────────────────────────────────────────
    main_window.on_export_profiles({
        let window = main_window.as_weak();
        let config_rc = config_rc.clone();
        move || {
            let msg = match config_rc.try_borrow() {
                Ok(cfg) => export_profiles_to_file(&cfg),
                Err(_) => "Config is busy, please try again.".to_string(),
            };
            if !msg.is_empty() {
                if let Some(ui) = window.upgrade() {
                    ui.set_help_import_export_success(msg.starts_with('✓'));
                    ui.set_help_import_export_message(msg.into());
                }
            }
        }
    });

    // ── on_import_profiles ────────────────────────────────────────────────────
    main_window.on_import_profiles({
        let window = main_window.as_weak();
        let config_rc = config_rc.clone();
        let profiles_model = profiles_model.clone();
        move || {
            let msg = match config_rc.try_borrow_mut() {
                Ok(mut cfg) => {
                    let result = import_profiles_from_file(&mut cfg);
                    if result.starts_with('✓') {
                        let new_profiles: Vec<SyncProfile> =
                            cfg.profiles.iter().map(to_ui_profile).collect();
                        while profiles_model.row_count() > 0 {
                            profiles_model.remove(0);
                        }
                        for p in new_profiles {
                            profiles_model.push(p);
                        }
                        // Tell daemon about the new profiles
                        if let Some(proxy) = DaemonProxy::new() {
                            proxy.reload_config();
                        }
                    }
                    result
                }
                Err(_) => "Config is busy, please try again.".to_string(),
            };
            if !msg.is_empty() {
                if let Some(ui) = window.upgrade() {
                    ui.set_help_import_export_success(msg.starts_with('✓'));
                    ui.set_help_import_export_message(msg.into());
                }
            }
        }
    });

    // ── Window drag & close ───────────────────────────────────────────────────
    main_window.on_move_window({
        let window = main_window.as_weak();
        move |dx, dy| {
            if let Some(ui) = window.upgrade() {
                let scale = ui.window().scale_factor();
                let pos = ui.window().position();
                ui.window().set_position(slint::WindowPosition::Physical(
                    slint::PhysicalPosition::new(
                        pos.x + (dx * scale) as i32,
                        pos.y + (dy * scale) as i32,
                    ),
                ));
            }
        }
    });

    main_window.on_close({
        move || std::process::exit(0)
    });

    main_window.run()?;
    Ok(())
}
