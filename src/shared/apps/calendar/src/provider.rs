use crate::models::{Event, NewEvent};
use chrono::NaiveDate;

/// Abstraction over any calendar data source.
///
/// Today this is implemented by `LocalProvider` (SQLite).
/// Tomorrow it can be implemented by a `NextcloudProvider` (CalDAV/HTTP)
/// — the entire application only talks through this trait.
pub trait CalendarProvider {
    // ── Reads ─────────────────────────────────────────────────────────────────

    /// Return all event instances (including expanded recurring occurrences)
    /// whose time range overlaps the given calendar month.
    fn events_for_month(&self, year: i32, month: u32) -> Vec<Event>;

    /// Return all event instances for a specific calendar day, sorted by
    /// start time (all-day events first).
    fn events_for_day(&self, date: NaiveDate) -> Vec<Event>;

    /// Return the set of day-numbers (1–31) within the given month that
    /// have at least one event.  Used for the dot indicators in the grid.
    /// Return the set of day-numbers (1–31) in [year, month] that have at least one event.
    /// Used when only indicator dots are needed (compact mini-grid). Part of the trait
    /// API for future providers (e.g. Nextcloud) — may not be called internally.
    #[allow(dead_code)]
    fn days_with_events(&self, year: i32, month: u32) -> Vec<u32>;

    // ── Writes ────────────────────────────────────────────────────────────────

    /// Persist a new event and return it with its assigned `id`.
    fn create_event(&mut self, event: NewEvent) -> anyhow::Result<Event>;

    /// Overwrite every field of an existing event (identified by `event.id`).
    fn update_event(&mut self, event: Event) -> anyhow::Result<()>;

    /// Delete the event with the given `id`.
    ///
    /// For recurring events this deletes *all* future instances (i.e. the
    /// root row).  Per-instance exceptions are out of scope for v1.
    fn delete_event(&mut self, id: i64) -> anyhow::Result<()>;
}
