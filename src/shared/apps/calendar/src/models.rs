use chrono::{DateTime, Local, NaiveDate};

/// A persisted calendar event (read from the database).
#[derive(Debug, Clone)]
pub struct Event {
    pub id: i64,
    pub title: String,
    pub description: String,
    pub start: DateTime<Local>,
    pub end: DateTime<Local>,
    pub all_day: bool,
    pub recurrence: Recurrence,
    /// The last date (inclusive) on which the recurrence should generate
    /// instances. `None` means it repeats forever.
    pub recurrence_end: Option<NaiveDate>,
    /// Optional CSS hex colour string, e.g. `"#89b4fa"`.  When `None` the
    /// UI falls back to the theme accent colour.
    pub color: Option<String>,
    /// How many minutes before the event start to fire a notification.
    /// 0 = no reminder.
    pub alert_minutes: i32,
}

/// An event payload used when creating a new event.
#[derive(Debug, Clone)]
pub struct NewEvent {
    pub title: String,
    pub description: String,
    pub start: DateTime<Local>,
    pub end: DateTime<Local>,
    pub all_day: bool,
    pub recurrence: Recurrence,
    pub recurrence_end: Option<NaiveDate>,
    pub color: Option<String>,
    pub alert_minutes: i32,
}

/// Supported recurrence patterns (mirrors the UI dropdown order).
#[derive(Debug, Clone, PartialEq)]
pub enum Recurrence {
    None,
    Daily,
    Weekly,
    Biweekly,
    Monthly,
    Yearly,
}

impl Recurrence {
    /// Parse the string stored in the database.
    pub fn from_str(s: &str) -> Self {
        match s {
            "daily"    => Self::Daily,
            "weekly"   => Self::Weekly,
            "biweekly" => Self::Biweekly,
            "monthly"  => Self::Monthly,
            "yearly"   => Self::Yearly,
            _          => Self::None,
        }
    }

    /// Serialise to the string stored in the database.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::None     => "none",
            Self::Daily    => "daily",
            Self::Weekly   => "weekly",
            Self::Biweekly => "biweekly",
            Self::Monthly  => "monthly",
            Self::Yearly   => "yearly",
        }
    }

    /// Human-readable label shown in the form dropdown.
    pub fn display(&self) -> &'static str {
        match self {
            Self::None     => "Does not repeat",
            Self::Daily    => "Daily",
            Self::Weekly   => "Weekly",
            Self::Biweekly => "Every 2 weeks",
            Self::Monthly  => "Monthly",
            Self::Yearly   => "Yearly",
        }
    }

    /// Convert from the 0-based UI dropdown index.
    pub fn from_index(i: i32) -> Self {
        match i {
            1 => Self::Daily,
            2 => Self::Weekly,
            3 => Self::Biweekly,
            4 => Self::Monthly,
            5 => Self::Yearly,
            _ => Self::None,
        }
    }

    /// Convert to the 0-based UI dropdown index.
    pub fn to_index(&self) -> i32 {
        match self {
            Self::None     => 0,
            Self::Daily    => 1,
            Self::Weekly   => 2,
            Self::Biweekly => 3,
            Self::Monthly  => 4,
            Self::Yearly   => 5,
        }
    }
}
