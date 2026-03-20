//! smpl-calendar-alertd — lightweight reminder daemon.
//!
//! Wakes every 30 seconds, queries the calendar SQLite database for events
//! with `alert_minutes > 0` whose alert window falls in the near future,
//! fires `notify-send`, and records sent alerts so they aren't repeated.
//!
//! Designed to be spawned once by `smpl-calendar` and stay running in the
//! background for the duration of the user session.

use chrono::{DateTime, Duration, Local, Months, TimeZone};
use rusqlite::{params, Connection};
use std::path::PathBuf;
use std::process::Command;

// ── DB path (shared with smpl-calendar) ────────────────────────────────────────

fn db_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home).join(".local/share/smplos/calendar/events.db")
}

// ── Minimal event struct (only fields needed for alerts) ──────────────────────

#[derive(Debug, Clone)]
struct AlertEvent {
    id: i64,
    title: String,
    start_ts: i64,
    alert_minutes: i32,
    recurrence: String,
}

// ── Recurrence expansion ──────────────────────────────────────────────────────

fn advance(dt: DateTime<Local>, rec: &str) -> DateTime<Local> {
    match rec {
        "daily"    => dt + Duration::days(1),
        "weekly"   => dt + Duration::weeks(1),
        "biweekly" => dt + Duration::weeks(2),
        "monthly"  => dt.checked_add_months(Months::new(1)).unwrap_or(dt),
        "yearly"   => dt.checked_add_months(Months::new(12)).unwrap_or(dt),
        _          => dt + Duration::days(36500), // none — far future
    }
}

/// For a recurring event, find the next occurrence at or after `after`.
fn next_occurrence(start_ts: i64, rec: &str, after: DateTime<Local>) -> Option<DateTime<Local>> {
    let mut current = Local.timestamp_opt(start_ts, 0).single()?;
    // Fast-forward (capped at 1000 iterations)
    for _ in 0..1000 {
        if current >= after {
            return Some(current);
        }
        current = advance(current, rec);
    }
    None
}

// ── Sent-alerts tracking (in-DB table) ────────────────────────────────────────

fn ensure_sent_table(conn: &Connection) {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS sent_alerts (
            event_id   INTEGER NOT NULL,
            alert_ts   INTEGER NOT NULL,
            PRIMARY KEY (event_id, alert_ts)
        );",
    )
    .ok();
}

fn was_sent(conn: &Connection, event_id: i64, alert_ts: i64) -> bool {
    conn.query_row(
        "SELECT 1 FROM sent_alerts WHERE event_id=?1 AND alert_ts=?2",
        params![event_id, alert_ts],
        |_| Ok(true),
    )
    .unwrap_or(false)
}

fn mark_sent(conn: &Connection, event_id: i64, alert_ts: i64) {
    conn.execute(
        "INSERT OR IGNORE INTO sent_alerts (event_id, alert_ts) VALUES (?1, ?2)",
        params![event_id, alert_ts],
    )
    .ok();
}

/// Purge old sent_alerts entries (older than 48 hours) to keep the table small.
fn purge_old(conn: &Connection) {
    let cutoff = (Local::now() - Duration::hours(48)).timestamp();
    conn.execute("DELETE FROM sent_alerts WHERE alert_ts < ?1", params![cutoff])
        .ok();
}

// ── Notification ──────────────────────────────────────────────────────────────

fn send_notification(title: &str, start: DateTime<Local>, minutes_before: i32) {
    let time_str = start.format("%H:%M").to_string();
    let date_str = start.format("%A, %B %e").to_string();
    let body = if minutes_before <= 0 {
        format!("Starting now ({time_str} {date_str})")
    } else if minutes_before < 60 {
        format!("In {minutes_before} min ({time_str} {date_str})")
    } else {
        let hours = minutes_before / 60;
        format!(
            "In {} hour{} ({time_str} {date_str})",
            hours,
            if hours > 1 { "s" } else { "" }
        )
    };

    let _ = Command::new("notify-send")
        .args([
            "-a", "smpl-calendar",
            "-i", "x-office-calendar",
            "-u", "normal",
            title,
            &body,
        ])
        .spawn();
}

// ── Main loop ─────────────────────────────────────────────────────────────────

fn check_alerts(conn: &Connection) {
    let now = Local::now();
    // Look ahead window: events starting within the next 24h + 5min margin
    let look_ahead_ts = (now + Duration::hours(24) + Duration::minutes(5)).timestamp();

    // Query all events with reminders that might fire in the next 24h
    let sql = "
        SELECT id, title, start_ts, alert_minutes, recurrence
        FROM   events
        WHERE  alert_minutes > 0
          AND  (
            (recurrence = 'none' AND start_ts <= ?1 AND start_ts >= ?2)
            OR recurrence != 'none'
          )
    ";
    let past_24h = (now - Duration::hours(24)).timestamp();

    let mut stmt = match conn.prepare_cached(sql) {
        Ok(s) => s,
        Err(_) => return,
    };
    let events: Vec<AlertEvent> = match stmt.query_map(params![look_ahead_ts, past_24h], |row| {
        Ok(AlertEvent {
            id: row.get(0)?,
            title: row.get(1)?,
            start_ts: row.get(2)?,
            alert_minutes: row.get(3)?,
            recurrence: row.get(4)?,
        })
    }) {
        Ok(rows) => rows.flatten().collect(),
        Err(_) => return,
    };

    for ev in &events {
        // Determine the relevant occurrence start time
        let occurrence_start = if ev.recurrence == "none" {
            match Local.timestamp_opt(ev.start_ts, 0).single() {
                Some(dt) => dt,
                None => continue,
            }
        } else {
            // Find next occurrence that hasn't passed yet (or is about to alert)
            let look_from = now - Duration::minutes(ev.alert_minutes as i64 + 5);
            match next_occurrence(ev.start_ts, &ev.recurrence, look_from) {
                Some(dt) => dt,
                None => continue,
            }
        };

        // Alert should fire at: start_time - alert_minutes
        let alert_time = occurrence_start - Duration::minutes(ev.alert_minutes as i64);

        // Fire if alert_time is in the past or within the next 30 seconds
        let fire_window = now + Duration::seconds(30);
        if alert_time <= fire_window && occurrence_start > now - Duration::minutes(5) {
            let alert_ts = occurrence_start.timestamp();
            if !was_sent(conn, ev.id, alert_ts) {
                send_notification(&ev.title, occurrence_start, ev.alert_minutes);
                mark_sent(conn, ev.id, alert_ts);
            }
        }
    }
}

fn main() {
    // Single-instance check: if another alertd is running, exit quietly
    let output = Command::new("pgrep")
        .args(["-x", "smpl-calendar-al"]) // pgrep truncates to 15 chars
        .output();
    if let Ok(out) = output {
        let pids: Vec<&str> = std::str::from_utf8(&out.stdout)
            .unwrap_or("")
            .lines()
            .filter(|l| !l.is_empty())
            .collect();
        // If more than 1 process (ourselves), exit
        if pids.len() > 1 {
            return;
        }
    }

    let path = db_path();
    if !path.exists() {
        // No calendar DB yet — wait for it
        eprintln!("smpl-calendar-alertd: no database at {}, waiting...", path.display());
        std::thread::sleep(std::time::Duration::from_secs(60));
        if !path.exists() {
            return;
        }
    }

    let conn = match Connection::open_with_flags(
        &path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("smpl-calendar-alertd: failed to open DB: {e}");
            return;
        }
    };

    ensure_sent_table(&conn);

    let mut tick = 0u64;
    loop {
        check_alerts(&conn);

        // Purge old sent_alerts every ~10 minutes (20 ticks * 30s)
        if tick.is_multiple_of(20) {
            purge_old(&conn);
        }

        tick += 1;
        std::thread::sleep(std::time::Duration::from_secs(30));
    }
}
