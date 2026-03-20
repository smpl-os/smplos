use crate::models::{Event, NewEvent, Recurrence};
use crate::provider::CalendarProvider;
use chrono::{DateTime, Datelike, Duration, Local, Months, NaiveDate, TimeZone};
use rusqlite::{params, Connection};
use std::path::PathBuf;

// ── Schema ────────────────────────────────────────────────────────────────────

const SCHEMA: &str = "
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    start_ts        INTEGER NOT NULL,
    end_ts          INTEGER NOT NULL,
    all_day         INTEGER NOT NULL DEFAULT 0,
    recurrence      TEXT    NOT NULL DEFAULT 'none',
    recurrence_end  INTEGER,
    color           TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events (start_ts);
CREATE INDEX IF NOT EXISTS idx_events_end   ON events (end_ts);
";

// ── Provider ──────────────────────────────────────────────────────────────────

pub struct LocalProvider {
    conn: Connection,
}

impl LocalProvider {
    /// Open (or create) the local calendar database.
    ///
    /// Stored at `~/.local/share/smplos/calendar/events.db`.
    /// WAL mode + NORMAL sync keeps it fast while still crash-safe.
    pub fn open() -> anyhow::Result<Self> {
        let path = Self::db_path();
        std::fs::create_dir_all(path.parent().unwrap())?;
        let conn = Connection::open(&path)?;
        conn.execute_batch(SCHEMA)?;
        // Migrations
        Self::migrate_alert_minutes(&conn)?;
        Ok(Self { conn })
    }

    fn db_path() -> PathBuf {
        let home = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(home).join(".local/share/smplos/calendar/events.db")
    }

    /// Add alert_minutes column if it doesn't exist yet (migration).
    fn migrate_alert_minutes(conn: &Connection) -> anyhow::Result<()> {
        let has_col: bool = conn
            .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='events'")
            .and_then(|mut s| s.query_row([], |r| r.get::<_, String>(0)))
            .map(|sql| sql.contains("alert_minutes"))
            .unwrap_or(false);
        if !has_col {
            conn.execute_batch(
                "ALTER TABLE events ADD COLUMN alert_minutes INTEGER NOT NULL DEFAULT 0;",
            )?;
        }
        Ok(())
    }

    // ── Row → model mapping ───────────────────────────────────────────────────

    fn row_to_event(row: &rusqlite::Row) -> rusqlite::Result<Event> {
        let id: i64            = row.get(0)?;
        let title: String      = row.get(1)?;
        let desc: String       = row.get(2)?;
        let start_ts: i64      = row.get(3)?;
        let end_ts: i64        = row.get(4)?;
        let all_day: bool      = row.get::<_, i32>(5)? != 0;
        let rec_str: String    = row.get(6)?;
        let rec_end: Option<i64> = row.get(7)?;
        let color: Option<String> = row.get(8)?;
        let alert_minutes: i32 = row.get::<_, Option<i32>>(9)?.unwrap_or(0);

        let start = Local.timestamp_opt(start_ts, 0)
            .single()
            .unwrap_or_else(Local::now);
        let end = Local.timestamp_opt(end_ts, 0)
            .single()
            .unwrap_or_else(Local::now);
        let recurrence_end = rec_end.and_then(|ts| {
            Local.timestamp_opt(ts, 0)
                .single()
                .map(|dt| dt.date_naive())
        });

        Ok(Event { id, title, description: desc, start, end, all_day,
                   recurrence: Recurrence::from_str(&rec_str),
                   recurrence_end, color, alert_minutes })
    }

    // ── Recurring-event expansion ─────────────────────────────────────────────

    /// Expand a single recurring root event into all concrete instances that
    /// fall within `[range_start, range_end)` (Unix seconds).
    ///
    /// We expand lazily (at query time) rather than storing exceptions in the
    /// database.  This keeps the schema trivial and queries O(1) for typical
    /// monthly views.  A hard cap of 400 instances prevents runaway loops.
    fn expand_recurring(
        event: &Event,
        range_start: i64,
        range_end: i64,
    ) -> Vec<Event> {
        let duration = event.end - event.start;

        let range_start_dt = Local.timestamp_opt(range_start, 0)
            .single()
            .unwrap_or_else(Local::now);
        let range_end_dt = Local.timestamp_opt(range_end, 0)
            .single()
            .unwrap_or_else(Local::now);

        // Honour the user-set recurrence end date.
        let effective_end: DateTime<Local> = event
            .recurrence_end
            .and_then(|d| d.and_hms_opt(23, 59, 59))
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .unwrap_or(range_end_dt);

        let stop = effective_end.min(range_end_dt);

        let mut instances = Vec::new();
        let mut current = event.start;
        let mut count = 0_u32;

        // Fast-forward to the first occurrence at or after range_start.
        // For daily/weekly, we can jump directly; for monthly/yearly we iterate
        // (at most 12 * range_years steps which is always tiny).
        while current < range_start_dt && count < 400 {
            current = Self::advance(current, &event.recurrence);
            count += 1;
        }
        count = 0;

        while current < stop && count < 400 {
            let mut instance = event.clone();
            instance.start = current;
            instance.end   = current + duration;
            instances.push(instance);
            current = Self::advance(current, &event.recurrence);
            count  += 1;
        }

        instances
    }

    /// Advance a timestamp by exactly one recurrence period.
    fn advance(dt: DateTime<Local>, rec: &Recurrence) -> DateTime<Local> {
        match rec {
            Recurrence::Daily    => dt + Duration::days(1),
            Recurrence::Weekly   => dt + Duration::weeks(1),
            Recurrence::Biweekly => dt + Duration::weeks(2),
            Recurrence::Monthly  => dt.checked_add_months(Months::new(1)).unwrap_or(dt),
            Recurrence::Yearly   => dt.checked_add_months(Months::new(12)).unwrap_or(dt),
            // None should never be reached here, but handle gracefully.
            Recurrence::None     => dt + Duration::days(36500),
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Unix-second timestamps bracketing an entire calendar month.
    fn month_range(year: i32, month: u32) -> (i64, i64) {
        let first = NaiveDate::from_ymd_opt(year, month, 1)
            .and_then(|d| d.and_hms_opt(0, 0, 0))
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp())
            .unwrap_or(0);

        let next_month = if month == 12 {
            NaiveDate::from_ymd_opt(year + 1, 1, 1)
        } else {
            NaiveDate::from_ymd_opt(year, month + 1, 1)
        };
        let last = next_month
            .and_then(|d| d.and_hms_opt(0, 0, 0))
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp())
            .unwrap_or(i64::MAX);

        (first, last)
    }

    /// Fetch all root event rows whose start or recurrence could overlap
    /// `[range_start, range_end)`.
    fn query_range(&self, range_start: i64, range_end: i64) -> Vec<Event> {
        // We fetch events that:
        //   a) start within the range (non-recurring), OR
        //   b) start before the range ends AND are recurring (need expansion).
        // This may over-fetch slightly, but expansion handles the exact filter.
        let sql = "
            SELECT id, title, description, start_ts, end_ts, all_day,
                   recurrence, recurrence_end, color, alert_minutes
            FROM   events
            WHERE  (start_ts < ? AND end_ts > ?)
                OR (recurrence != 'none' AND start_ts < ?)
            ORDER  BY start_ts
        ";
        let mut stmt = self.conn.prepare_cached(sql).unwrap();
        stmt.query_map(
            params![range_end, range_start, range_end],
            Self::row_to_event,
        )
        .unwrap()
        .flatten()
        .collect()
    }
}

// ── CalendarProvider impl ─────────────────────────────────────────────────────

impl CalendarProvider for LocalProvider {
    fn events_for_month(&self, year: i32, month: u32) -> Vec<Event> {
        let (start, end) = Self::month_range(year, month);
        let rows = self.query_range(start, end);

        let mut out = Vec::new();
        for ev in &rows {
            if ev.recurrence == Recurrence::None {
                out.push(ev.clone());
            } else {
                out.extend(Self::expand_recurring(ev, start, end));
            }
        }
        out.sort_by_key(|e| e.start);
        out
    }

    fn events_for_day(&self, date: NaiveDate) -> Vec<Event> {
        let day_start = date
            .and_hms_opt(0, 0, 0)
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp())
            .unwrap_or(0);
        let day_end = date
            .and_hms_opt(23, 59, 59)
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp())
            .unwrap_or(i64::MAX);

        let rows = self.query_range(day_start, day_end + 1);

        let mut out = Vec::new();
        for ev in &rows {
            if ev.recurrence == Recurrence::None {
                // Check actual overlap with the day
                if ev.start.timestamp() <= day_end && ev.end.timestamp() >= day_start {
                    out.push(ev.clone());
                }
            } else {
                let instances = Self::expand_recurring(ev, day_start, day_end + 1);
                out.extend(instances);
            }
        }

        // All-day first, then chronological by start
        out.sort_by(|a, b| {
            b.all_day.cmp(&a.all_day).then(a.start.cmp(&b.start))
        });
        out
    }

    fn days_with_events(&self, year: i32, month: u32) -> Vec<u32> {
        let events = self.events_for_month(year, month);
        let mut days: Vec<u32> = events
            .iter()
            .filter(|e| e.start.year() == year && e.start.month() == month)
            .map(|e| e.start.day())
            .collect();
        days.sort_unstable();
        days.dedup();
        days
    }

    fn create_event(&mut self, ev: NewEvent) -> anyhow::Result<Event> {
        let now = Local::now().timestamp();
        let rec_end_ts = ev.recurrence_end
            .and_then(|d| d.and_hms_opt(0, 0, 0))
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp());

        self.conn.execute(
            "INSERT INTO events
             (title, description, start_ts, end_ts, all_day, recurrence,
              recurrence_end, color, alert_minutes, created_at, updated_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?10)",
            params![
                ev.title,
                ev.description,
                ev.start.timestamp(),
                ev.end.timestamp(),
                ev.all_day as i32,
                ev.recurrence.as_str(),
                rec_end_ts,
                ev.color,
                ev.alert_minutes,
                now,
            ],
        )?;
        let id = self.conn.last_insert_rowid();

        Ok(Event {
            id,
            title: ev.title,
            description: ev.description,
            start: ev.start,
            end: ev.end,
            all_day: ev.all_day,
            recurrence: ev.recurrence,
            recurrence_end: ev.recurrence_end,
            color: ev.color,
            alert_minutes: ev.alert_minutes,
        })
    }

    fn update_event(&mut self, ev: Event) -> anyhow::Result<()> {
        let now = Local::now().timestamp();
        let rec_end_ts = ev.recurrence_end
            .and_then(|d| d.and_hms_opt(0, 0, 0))
            .and_then(|ndt| Local.from_local_datetime(&ndt).single())
            .map(|dt| dt.timestamp());

        self.conn.execute(
            "UPDATE events
             SET title=?2, description=?3, start_ts=?4, end_ts=?5,
                 all_day=?6, recurrence=?7, recurrence_end=?8,
                 color=?9, alert_minutes=?10, updated_at=?11
             WHERE id=?1",
            params![
                ev.id,
                ev.title,
                ev.description,
                ev.start.timestamp(),
                ev.end.timestamp(),
                ev.all_day as i32,
                ev.recurrence.as_str(),
                rec_end_ts,
                ev.color,
                ev.alert_minutes,
                now,
            ],
        )?;
        Ok(())
    }

    fn delete_event(&mut self, id: i64) -> anyhow::Result<()> {
        self.conn.execute("DELETE FROM events WHERE id=?1", params![id])?;
        Ok(())
    }
}
