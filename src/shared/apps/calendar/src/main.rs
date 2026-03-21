mod local_provider;
mod models;
mod provider;
mod theme;

use chrono::{Datelike, Local, NaiveDate, TimeZone, Timelike};
use local_provider::LocalProvider;
use models::{NewEvent, Recurrence};
use provider::CalendarProvider;
use slint::{ModelRc, SharedString, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

// ── Launch alert daemon if not already running ─────────────────────────────────

fn ensure_alertd() {
    // Check if already running (pgrep truncates name to 15 chars)
    let already = std::process::Command::new("pgrep")
        .args(["-x", "smpl-calendar-al"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    if !already {
        // Find the alertd binary next to our own binary
        let self_exe = std::env::current_exe().unwrap_or_default();
        let alertd = self_exe
            .parent()
            .unwrap_or(std::path::Path::new("/usr/local/bin"))
            .join("smpl-calendar-alertd");

        if alertd.exists() {
            let _ = std::process::Command::new(&alertd)
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn();
        }
    }
}

// ── Window sizes are defined in Slint's `global Sizes` — see ui/main.slint ───
// Rust reads them via ui.global::<Sizes>() after MainWindow::new().

// ── Calendar state ─────────────────────────────────────────────────────────────

struct CalState {
    year:         i32,
    month:        u32,
    selected_day: u32,
    provider:     LocalProvider,
}

impl CalState {
    fn new() -> anyhow::Result<Self> {
        let now = Local::now();
        Ok(Self {
            year:         now.year(),
            month:        now.month(),
            selected_day: now.day(),
            provider:     LocalProvider::open()?,
        })
    }
}

// ── Date helpers ───────────────────────────────────────────────────────────────

fn days_in_month(year: i32, month: u32) -> u32 {
    let next = if month == 12 {
        NaiveDate::from_ymd_opt(year + 1, 1, 1)
    } else {
        NaiveDate::from_ymd_opt(year, month + 1, 1)
    };
    next.and_then(|d| d.pred_opt()).map(|d| d.day()).unwrap_or(30)
}

const MONTH_NAMES: [&str; 12] = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
];

fn month_name(year: i32, month: u32) -> String {
    format!("{} {}", MONTH_NAMES[(month - 1) as usize], year)
}

/// Map UI dropdown index to alert minutes.
fn alert_minutes_from_idx(idx: i32) -> i32 {
    match idx {
        1 => 15,
        2 => 30,
        3 => 60,
        4 => 480,
        5 => 1440,
        _ => 0,
    }
}

/// Map alert minutes back to UI dropdown index.
fn alert_idx_from_minutes(mins: i32) -> i32 {
    match mins {
        15   => 1,
        30   => 2,
        60   => 3,
        480  => 4,
        1440 => 5,
        _    => 0,
    }
}

/// Format "Wednesday, March 18, 2026"
fn format_day_label(year: i32, month: u32, day: u32) -> String {
    use chrono::Weekday;
    let date = NaiveDate::from_ymd_opt(year, month, day)
        .unwrap_or_else(|| NaiveDate::from_ymd_opt(year, month, 1).unwrap());
    let weekday = match date.weekday() {
        Weekday::Mon => "Monday",
        Weekday::Tue => "Tuesday",
        Weekday::Wed => "Wednesday",
        Weekday::Thu => "Thursday",
        Weekday::Fri => "Friday",
        Weekday::Sat => "Saturday",
        Weekday::Sun => "Sunday",
    };
    let today = Local::now().date_naive();
    let prefix = if date == today { "Today" } else { weekday };
    format!(
        "{}, {} {}, {}",
        prefix,
        MONTH_NAMES[(month - 1) as usize],
        day,
        year
    )
}

// ── Build the 42-cell grid for a given month ───────────────────────────────────

fn build_day_cells(
    year: i32,
    month: u32,
    selected_day: u32,
    month_events: &[models::Event],
) -> Vec<DayCell> {
    use chrono::Datelike;
    use std::collections::HashMap;

    let today = Local::now().date_naive();
    let first = NaiveDate::from_ymd_opt(year, month, 1).unwrap();
    let first_col = first.weekday().num_days_from_monday() as i32;
    let dim = days_in_month(year, month) as i32;

    // Group events by day number for fast lookup
    let mut events_by_day: HashMap<u32, Vec<&models::Event>> = HashMap::new();
    for ev in month_events {
        events_by_day.entry(ev.start.day()).or_default().push(ev);
    }

    // Prev month info (for padding cells before day 1)
    let (prev_year, prev_month) = if month == 1 { (year - 1, 12) } else { (year, month - 1) };
    let prev_dim = days_in_month(prev_year, prev_month) as i32;

    // Helper: build (title, time) strings for the i-th event of a day (or empty strings)
    let ev_str = |evs: &[&models::Event], idx: usize| -> (i32, SharedString, SharedString) {
        if let Some(ev) = evs.get(idx) {
            let time = if ev.all_day {
                String::new()
            } else {
                format!("{:02}:{:02}", ev.start.hour(), ev.start.minute())
            };
            (ev.id as i32, ev.title.clone().into(), time.into())
        } else {
            (0, SharedString::default(), SharedString::default())
        }
    };

    (0..42)
        .map(|i| {
            let day_num = i - first_col + 1;
            let row = i / 7;
            let col = i % 7;

            if day_num < 1 {
                // Padding from previous month
                let prev_day = (prev_dim + day_num) as u32;
                DayCell {
                    day: prev_day as i32, row, col,
                    is_today: false, is_selected: false,
                    has_events: false, event_count: 0,
                    is_other_month: true, month_offset: -1,
                    ev1_id: 0, ev1_title: SharedString::default(), ev1_time: SharedString::default(),
                    ev2_id: 0, ev2_title: SharedString::default(), ev2_time: SharedString::default(),
                    ev3_id: 0, ev3_title: SharedString::default(), ev3_time: SharedString::default(),
                }
            } else if day_num > dim {
                // Padding from next month
                let next_day = (day_num - dim) as u32;
                DayCell {
                    day: next_day as i32, row, col,
                    is_today: false, is_selected: false,
                    has_events: false, event_count: 0,
                    is_other_month: true, month_offset: 1,
                    ev1_id: 0, ev1_title: SharedString::default(), ev1_time: SharedString::default(),
                    ev2_id: 0, ev2_title: SharedString::default(), ev2_time: SharedString::default(),
                    ev3_id: 0, ev3_title: SharedString::default(), ev3_time: SharedString::default(),
                }
            } else {
                // Current month day
                let day = day_num as u32;
                let date = NaiveDate::from_ymd_opt(year, month, day).unwrap();
                let empty: Vec<&models::Event> = vec![];
                let evs = events_by_day.get(&day).map(|v| v.as_slice()).unwrap_or(&empty);
                let count = evs.len();

                // For today: show 3 events nearest to current time
                // (first event that hasn't ended yet, plus the next 2)
                let start_idx = if date == today && count > 3 {
                    let now = Local::now();
                    let first_upcoming = evs.iter().position(|e| e.end > now).unwrap_or(count.saturating_sub(3));
                    // Show one before the upcoming if possible, for context
                    first_upcoming.saturating_sub(0).min(count.saturating_sub(3))
                } else {
                    0
                };

                let (ev1_id, ev1_title, ev1_time) = ev_str(evs, start_idx);
                let (ev2_id, ev2_title, ev2_time) = ev_str(evs, start_idx + 1);
                let (ev3_id, ev3_title, ev3_time) = ev_str(evs, start_idx + 2);

                DayCell {
                    day: day as i32, row, col,
                    is_today:    date == today,
                    is_selected: day == selected_day,
                    has_events:  count > 0,
                    event_count: count as i32,
                    is_other_month: false, month_offset: 0,
                    ev1_id, ev1_title, ev1_time,
                    ev2_id, ev2_title, ev2_time,
                    ev3_id, ev3_title, ev3_time,
                }
            }
        })
        .collect()
}

// ── Build the event list for the selected day ─────────────────────────────────

fn build_event_items(events: &[models::Event], day_tag: Option<u32>) -> Vec<CalEvent> {
    let now = Local::now();
    events
        .iter()
        .map(|ev| {
            let time_label = if ev.all_day {
                "All day".to_string()
            } else {
                format!(
                    "{:02}:{:02} \u{2013} {:02}:{:02}",
                    ev.start.hour(),
                    ev.start.minute(),
                    ev.end.hour(),
                    ev.end.minute()
                )
            };
            let day = day_tag.unwrap_or_else(|| ev.start.day()) as i32;
            let is_past = ev.end <= now;
            CalEvent {
                id:               ev.id as i32,
                title:            ev.title.clone().into(),
                description:      ev.description.clone().into(),
                time_label:       time_label.into(),
                has_recurrence:   ev.recurrence != Recurrence::None,
                recurrence_label: SharedString::from(ev.recurrence.display()),
                start_hour:       ev.start.hour() as i32,
                start_min:        ev.start.minute() as i32,
                end_hour:         ev.end.hour() as i32,
                end_min:          ev.end.minute() as i32,
                all_day:          ev.all_day,
                recurrence_idx:   ev.recurrence.to_index(),
                is_past,
                day,
            }
        })
        .collect()
}

// ── Full UI refresh ────────────────────────────────────────────────────────────

fn refresh_ui(ui: &MainWindow, state: &CalState) {
    let year  = state.year;
    let month = state.month;
    let day   = state.selected_day;

    // Single month query — used for both the grid cells and the day panel
    let month_events = state.provider.events_for_month(year, month);

    // Month grid (cells carry embedded first-3-events data)
    let cells = build_day_cells(year, month, day, &month_events);
    let cell_model = VecModel::from(cells);
    ui.set_day_cells(ModelRc::from(Rc::new(cell_model)));

    // Day events (selected day — used for the slide-in day panel)
    let date = NaiveDate::from_ymd_opt(year, month, day)
        .unwrap_or_else(|| NaiveDate::from_ymd_opt(year, month, 1).unwrap());
    let day_events = state.provider.events_for_day(date);
    let ev_items = build_event_items(&day_events, Some(day));
    let ev_model = VecModel::from(ev_items);
    ui.set_day_events(ModelRc::from(Rc::new(ev_model)));

    // Labels
    ui.set_month_name(month_name(year, month).into());
    ui.set_year(year);
    ui.set_month(month as i32);
    ui.set_selected_day(day as i32);
    ui.set_selected_date_label(format_day_label(year, month, day).into());

    // Current time for "now" line in the day panel
    let now = Local::now();
    let today = now.date_naive();
    let selected_date = NaiveDate::from_ymd_opt(year, month, day)
        .unwrap_or_else(|| NaiveDate::from_ymd_opt(year, month, 1).unwrap());
    ui.set_is_today_selected(selected_date == today);
    ui.set_current_hour(now.hour() as i32);
    ui.set_current_min(now.minute() as i32);
}

// ── Apply smplOS theme ─────────────────────────────────────────────────────────

fn apply_theme(ui: &MainWindow) {
    let palette = theme::load_theme_from_eww_scss(&format!(
        "{}/.config/eww/theme-colors.scss",
        std::env::var("HOME").unwrap_or_default()
    ));
    let t = Theme::get(ui);
    t.set_bg(palette.bg);
    t.set_fg(palette.fg);
    t.set_fg_dim(palette.fg_dim);
    t.set_accent(palette.accent);
    t.set_bg_light(palette.bg_light);
    t.set_bg_lighter(palette.bg_lighter);
    t.set_danger(palette.danger);
    t.set_success(palette.success);
    t.set_warning(palette.warning);
    t.set_info(palette.info);
    t.set_opacity(palette.opacity);
    t.set_border_radius(palette.border_radius);
}

// ── Entry point ────────────────────────────────────────────────────────────────

fn main() -> Result<(), slint::PlatformError> {
    for arg in std::env::args() {
        if arg == "-v" || arg == "--version" {
            println!("smpl-calendar v{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
    }

    // Start in details mode if --details flag given
    let start_details = std::env::args().any(|a| a == "--details");
    // Create UI first to read sizes from the Slint global, then init backend.
    // smpl_common::init must be called before MainWindow::new(), so we use
    // the Slint defaults as initial hint and set_size immediately after.
    smpl_common::init("smpl-calendar", 230.0, 500.0)?;

    // Start the reminder daemon (stays alive for the session)
    ensure_alertd();

    let ui   = MainWindow::new()?;

    // Read the single source of truth from Slint
    let compact_w = ui.global::<Sizes>().get_compact_w();
    let compact_h = ui.global::<Sizes>().get_compact_h();
    let details_w = ui.global::<Sizes>().get_details_w();
    let details_h = ui.global::<Sizes>().get_details_h();

    // Ensure initial window size matches
    ui.window().set_size(slint::LogicalSize::new(compact_w, compact_h));
    let state = Rc::new(RefCell::new(
        CalState::new().expect("failed to open calendar database"),
    ));

    apply_theme(&ui);

    if start_details {
        ui.set_is_details(true);
        ui.window().set_size(slint::LogicalSize::new(details_w, details_h));
    }

    refresh_ui(&ui, &state.borrow());

    // ── prev-month ────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_prev_month(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut s = state.borrow_mut();
            if s.month == 1 {
                s.month = 12;
                s.year -= 1;
            } else {
                s.month -= 1;
            }
            // Clamp selected day to valid range
            s.selected_day = s.selected_day.min(days_in_month(s.year, s.month));
            drop(s);
            refresh_ui(&ui, &state.borrow());
        });
    }

    // ── next-month ────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_next_month(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut s = state.borrow_mut();
            if s.month == 12 {
                s.month = 1;
                s.year += 1;
            } else {
                s.month += 1;
            }
            s.selected_day = s.selected_day.min(days_in_month(s.year, s.month));
            drop(s);
            refresh_ui(&ui, &state.borrow());
        });
    }

    // ── select-day ────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_select_day(move |day| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut s = state.borrow_mut();
            s.selected_day = day as u32;
            drop(s);
            refresh_ui(&ui, &state.borrow());
            // Auto-open day panel in details mode when a day is clicked
            if ui.get_is_details() {
                ui.set_show_day_panel(true);
            }
        });
    }

    // ── open-details ──────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        ui.on_open_details(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            ui.set_is_details(true);
            // Defer so layout switches to details min-width first
            let weak = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(10), move || {
                let Some(ui) = weak.upgrade() else { return };
                ui.window().set_size(slint::LogicalSize::new(details_w, details_h));
            });
        });
    }

    // ── close-details ─────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        ui.on_close_details(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            ui.set_is_details(false);
            ui.set_show_form(false);
            ui.set_show_day_panel(false);
            // Compositor needs ~100ms to process the layout change.
            // Fire set_size at 50ms and again at 150ms to cover the window.
            let weak1 = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(50), move || {
                let Some(ui) = weak1.upgrade() else { return };
                ui.window().set_size(slint::LogicalSize::new(compact_w, compact_h));
            });
            let weak2 = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(150), move || {
                let Some(ui) = weak2.upgrade() else { return };
                ui.window().set_size(slint::LogicalSize::new(compact_w, compact_h));
            });
        });
    }

    // ── navigate-to-month-day (click other-month cell) ────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_navigate_to_month_day(move |offset, day| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut s = state.borrow_mut();
            match offset {
                -1 => {
                    if s.month == 1 { s.month = 12; s.year -= 1; }
                    else { s.month -= 1; }
                }
                1 => {
                    if s.month == 12 { s.month = 1; s.year += 1; }
                    else { s.month += 1; }
                }
                _ => {}
            }
            s.selected_day = (day as u32).min(days_in_month(s.year, s.month));
            drop(s);
            refresh_ui(&ui, &state.borrow());
            if ui.get_is_details() {
                ui.set_show_day_panel(true);
            }
        });
    }

    // ── new-event ─────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_new_event(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            let s = state.borrow();
            let date_str = format!("{:04}-{:02}-{:02}", s.year, s.month, s.selected_day);
            drop(s);
            ui.set_form_editing_id(-1);
            ui.set_form_title("".into());
            ui.set_form_desc("".into());
            ui.set_form_start_h(9);
            ui.set_form_start_m(0);
            ui.set_form_end_h(10);
            ui.set_form_end_m(0);
            ui.set_form_all_day(false);
            ui.set_form_rec_idx(0);
            ui.set_form_alert_idx(0);
            ui.set_form_date_str(date_str.into());
            ui.set_form_date_invalid(false);
            ui.set_show_form(true);
        });
    }

    // ── edit-event ────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_edit_event(move |id| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let s = state.borrow();
            let date = NaiveDate::from_ymd_opt(s.year, s.month, s.selected_day)
                .unwrap_or_else(|| NaiveDate::from_ymd_opt(s.year, s.month, 1).unwrap());
            let events = s.provider.events_for_day(date);
            if let Some(ev) = events.iter().find(|e| e.id == id as i64) {
                ui.set_form_editing_id(id);
                ui.set_form_title(ev.title.clone().into());
                ui.set_form_desc(ev.description.clone().into());
                ui.set_form_start_h(ev.start.hour() as i32);
                ui.set_form_start_m(ev.start.minute() as i32);
                ui.set_form_end_h(ev.end.hour() as i32);
                ui.set_form_end_m(ev.end.minute() as i32);
                ui.set_form_all_day(ev.all_day);
                ui.set_form_rec_idx(ev.recurrence.to_index());
                ui.set_form_alert_idx(alert_idx_from_minutes(ev.alert_minutes));
                ui.set_form_date_str(ev.start.format("%Y-%m-%d").to_string().into());
                ui.set_form_date_invalid(false);
                ui.set_show_form(true);
            }
        });
    }

    // ── delete-event ──────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_delete_event(move |id| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut s = state.borrow_mut();
            let _ = s.provider.delete_event(id as i64);
            drop(s);
            refresh_ui(&ui, &state.borrow());
        });
    }

    // ── save-event ────────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        let state   = state.clone();
        ui.on_save_event(move || {
            let Some(ui) = ui_weak.upgrade() else { return };

            let title = ui.get_form_title().to_string();
            if title.trim().is_empty() {
                return; // don't save empty title
            }

            let s_h  = ui.get_form_start_h()  as u32;
            let s_m  = ui.get_form_start_m()  as u32;
            let e_h  = ui.get_form_end_h()    as u32;
            let e_m  = ui.get_form_end_m()    as u32;
            let all_day   = ui.get_form_all_day();
            let rec_idx   = ui.get_form_rec_idx();
            let alert_idx = ui.get_form_alert_idx();
            let editing_id = ui.get_form_editing_id();

            // Parse and validate the date string
            let date_str = ui.get_form_date_str().to_string();
            let date = match NaiveDate::parse_from_str(&date_str, "%Y-%m-%d") {
                Ok(d) => {
                    ui.set_form_date_invalid(false);
                    d
                }
                Err(_) => {
                    ui.set_form_date_invalid(true);
                    return; // don't save with invalid date
                }
            };

            let mut s = state.borrow_mut();

            let make_dt = |h: u32, m: u32| {
                date.and_hms_opt(h, m, 0)
                    .and_then(|ndt| Local.from_local_datetime(&ndt).single())
                    .unwrap_or_else(Local::now)
            };

            let start = if all_day { make_dt(0,  0) } else { make_dt(s_h, s_m) };
            let end   = if all_day { make_dt(23, 59) } else { make_dt(e_h, e_m) };
            let end   = if end <= start { start + chrono::Duration::hours(1) } else { end };

            let recurrence = Recurrence::from_index(rec_idx);

            if editing_id < 0 {
                // Create
                let new_ev = NewEvent {
                    title,
                    description:    ui.get_form_desc().to_string(),
                    start,
                    end,
                    all_day,
                    recurrence,
                    recurrence_end: None,
                    color:          None,
                    alert_minutes:  alert_minutes_from_idx(alert_idx),
                };
                let _ = s.provider.create_event(new_ev);
            } else {
                // Update — look up on the currently-viewed date (original day before
                // the user might have changed the date field) then apply new values.
                let orig_date = NaiveDate::from_ymd_opt(s.year, s.month, s.selected_day)
                    .unwrap_or_else(|| NaiveDate::from_ymd_opt(s.year, s.month, 1).unwrap());
                let events = s.provider.events_for_day(orig_date);
                if let Some(mut ev) = events.into_iter().find(|e| e.id == editing_id as i64) {
                    ev.title       = title;
                    ev.description = ui.get_form_desc().to_string();
                    ev.start       = start;
                    ev.end         = end;
                    ev.all_day     = all_day;
                    ev.recurrence  = recurrence;
                    ev.alert_minutes = alert_minutes_from_idx(alert_idx);
                    let _ = s.provider.update_event(ev);
                }
            }

            // Navigate to the saved date so the user sees their event
            s.year         = date.year();
            s.month        = date.month();
            s.selected_day = date.day();
            drop(s);
            ui.set_show_form(false);
            refresh_ui(&ui, &state.borrow());
        });
    }

    // ── cancel-form ───────────────────────────────────────────────────────────
    {
        let ui_weak = ui.as_weak();
        ui.on_cancel_form(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            ui.set_show_form(false);
        });
    }

    // ── close ─────────────────────────────────────────────────────────────────
    ui.on_close(|| std::process::exit(0));

    // ── window drag (works on X11 + Wayland, no float rule needed) ───────────────
    // Receives (dx, dy) deltas from Slint's moved event
    // (self.mouse-x - self.pressed-x) in logical pixels.
    // set_position() is standard Slint API, no Wayland serial or compositor
    // drag protocol needed — identical to how the settings app does it.
    {
        let ui_weak = ui.as_weak();
        ui.on_move_window(move |dx, dy| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let scale = ui.window().scale_factor();
            let pos   = ui.window().position();
            ui.window().set_position(slint::WindowPosition::Physical(
                slint::PhysicalPosition::new(
                    pos.x + (dx * scale) as i32,
                    pos.y + (dy * scale) as i32,
                ),
            ));
        });
    }

    // ── window resize (edge drag) ────────────────────────────────────────────
    // edge: 0=top, 1=right, 2=bottom, 3=left,
    //       4=top-left, 5=top-right, 6=bottom-left, 7=bottom-right
    {
        let ui_weak = ui.as_weak();
        ui.on_resize_window(move |dx, dy, edge| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let scale = ui.window().scale_factor();
            let pos   = ui.window().position();
            let size  = ui.window().size();

            let min_w: f32 = if ui.get_is_details() { 700.0 } else { 230.0 };
            let min_h: f32 = if ui.get_is_details() { 400.0 } else { 300.0 };

            let mut new_x = pos.x as f32;
            let mut new_y = pos.y as f32;
            let mut new_w = size.width as f32;
            let mut new_h = size.height as f32;

            let pdx = dx * scale;
            let pdy = dy * scale;

            match edge {
                0 => { // top
                    new_y += pdy;
                    new_h -= pdy;
                }
                1 => { // right
                    new_w += pdx;
                }
                2 => { // bottom
                    new_h += pdy;
                }
                3 => { // left
                    new_x += pdx;
                    new_w -= pdx;
                }
                4 => { // top-left
                    new_x += pdx; new_w -= pdx;
                    new_y += pdy; new_h -= pdy;
                }
                5 => { // top-right
                    new_w += pdx;
                    new_y += pdy; new_h -= pdy;
                }
                6 => { // bottom-left
                    new_x += pdx; new_w -= pdx;
                    new_h += pdy;
                }
                7 => { // bottom-right
                    new_w += pdx;
                    new_h += pdy;
                }
                _ => {}
            }

            let min_w_phys = min_w * scale;
            let min_h_phys = min_h * scale;

            // Clamp to min size — if we'd go below min, don't move origin
            if new_w < min_w_phys {
                if edge == 3 || edge == 4 || edge == 6 {
                    new_x = pos.x as f32 + (size.width as f32 - min_w_phys);
                }
                new_w = min_w_phys;
            }
            if new_h < min_h_phys {
                if edge == 0 || edge == 4 || edge == 5 {
                    new_y = pos.y as f32 + (size.height as f32 - min_h_phys);
                }
                new_h = min_h_phys;
            }

            ui.window().set_size(slint::PhysicalSize::new(new_w as u32, new_h as u32));
            ui.window().set_position(slint::WindowPosition::Physical(
                slint::PhysicalPosition::new(new_x as i32, new_y as i32),
            ));
        });
    }

    // ── Periodic theme refresh ──
    {
        let ui_weak = ui.as_weak();
        let timer = slint::Timer::default();
        timer.start(
            slint::TimerMode::Repeated,
            std::time::Duration::from_secs(2),
            move || {
                if let Some(ui) = ui_weak.upgrade() {
                    apply_theme(&ui);
                }
            },
        );
        std::mem::forget(timer);
    }

    ui.run()
}
