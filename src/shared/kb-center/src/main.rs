mod layouts;
mod theme;
mod xkb_labels;

/// Debug logging -- compiles to nothing in release builds.
/// Usage: `debug_log!("message {}", value);`
macro_rules! debug_log {
    ($($arg:tt)*) => {
        if cfg!(debug_assertions) {
            eprintln!($($arg)*);
        }
    };
}
pub(crate) use debug_log;

use layouts::ActiveLayout;
use slint::{Model, ModelRc, SharedString, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

/// Ensure only one instance of kb-center runs at a time.
/// Returns the lock file handle (must be kept alive for the process lifetime).
fn acquire_single_instance() -> Option<std::fs::File> {
    use std::io::Write;

    let run_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    let lock_path = format!("{}/kb-center.lock", run_dir);

    // Try to open/create the lock file
    let file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .ok()?;

    // Try exclusive lock (non-blocking)
    use std::os::unix::io::AsRawFd;
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc != 0 {
        // Another instance holds the lock
        return None;
    }

    // Write our PID for debugging
    let mut f = file;
    let _ = f.set_len(0);
    let _ = write!(f, "{}", std::process::id());
    Some(f)
}

fn apply_theme(ui: &MainWindow) {
    let palette = theme::load_theme_from_eww_scss(&format!(
        "{}/.config/eww/theme-colors.scss",
        std::env::var("HOME").unwrap_or_default()
    ));

    let theme = Theme::get(ui);
    theme.set_bg(palette.bg.darker(0.05));
    theme.set_fg(palette.fg);
    theme.set_fg_dim(palette.fg_dim);
    theme.set_accent(palette.accent);
    theme.set_bg_light(palette.bg_light);
    theme.set_bg_lighter(palette.bg_lighter);
    theme.set_danger(palette.danger);
    theme.set_success(palette.success);
    theme.set_warning(palette.warning);
    theme.set_info(palette.info);
    theme.set_opacity(palette.opacity);
}

fn to_key_model(row: Vec<xkb_labels::KeyInfo>) -> ModelRc<KeyData> {
    ModelRc::from(Rc::new(VecModel::from(
        row.into_iter()
            .map(|k| KeyData {
                base: k.base.into(),
                english: k.english.into(),
                w: k.width,
                is_modifier: k.is_modifier,
            })
            .collect::<Vec<_>>(),
    )))
}

fn set_keyboard_preview(ui: &MainWindow, layout: &str, variant: &str) {
    let (name, r0, r1, r2, r3, r4) = xkb_labels::resolve(layout, variant);
    ui.set_layout_name(name.into());
    ui.set_row0(to_key_model(r0));
    ui.set_row1(to_key_model(r1));
    ui.set_row2(to_key_model(r2));
    ui.set_row3(to_key_model(r3));
    ui.set_row4(to_key_model(r4));
}

/// Push the in-memory active list to the UI model and sync to compositor.
fn push_active_to_ui(ui: &MainWindow, active: &[ActiveLayout]) {
    debug_log!("[kb-center] push_active_to_ui: {} layouts", active.len());
    let entries: Vec<LayoutEntry> = active
        .iter()
        .map(|a| LayoutEntry {
            code: a.code.clone().into(),
            variant: a.variant.clone().into(),
            description: a.description.clone().into(),
        })
        .collect();
    ui.set_active_layouts(ModelRc::from(Rc::new(VecModel::from(entries))));

    // Best-effort sync to compositor (Hyprland on Wayland, setxkbmap on X11)
    layouts::sync_to_compositor(active);
}

fn main() -> Result<(), slint::PlatformError> {
    let args: Vec<String> = std::env::args().collect();

    if args.iter().any(|a| a == "-h" || a == "--help") {
        eprintln!("Usage: kb-center [layout] [variant]");
        eprintln!("  e.g: kb-center ru phonetic");
        eprintln!("       kb-center fr");
        eprintln!("       kb-center");
        std::process::exit(0);
    }

    if args.iter().any(|a| a == "-v" || a == "--version") {
        println!("kb-center v{}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }

    // Single-instance guard — exit if already running
    let _lock = match acquire_single_instance() {
        Some(lock) => lock,
        None => {
            debug_log!("[kb-center] already running, exiting");
            std::process::exit(0);
        }
    };

    let initial_layout = args.get(1).map(|s| s.as_str()).unwrap_or("us");
    let initial_variant = args.get(2).map(|s| s.as_str()).unwrap_or("");

    // Set up Slint backend first so the window appears immediately
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("kb-center", "kb-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(640.0_f64, 440.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    // One-time cleanup of old per-app config (OS config is the source of truth).
    layouts::cleanup_legacy_config();

    // Show initial keyboard preview immediately (fast, single layout)
    set_keyboard_preview(&ui, initial_layout, initial_variant);

    // Shared state — populated after deferred load
    let available: Rc<RefCell<Vec<layouts::AvailableLayout>>> =
        Rc::new(RefCell::new(Vec::new()));
    let filtered_indices: Rc<RefCell<Vec<usize>>> = Rc::new(RefCell::new(Vec::new()));
    let active_layouts: Rc<RefCell<Vec<ActiveLayout>>> = Rc::new(RefCell::new(vec![
        ActiveLayout {
            code: initial_layout.to_string(),
            variant: initial_variant.to_string(),
            description: String::new(),
        },
    ]));

    // Deferred layout loading — UI renders instantly, then we populate
    {
        let ui_weak = ui.as_weak();
        let avail = available.clone();
        let fi = filtered_indices.clone();
        let al = active_layouts.clone();
        let init_layout = initial_layout.to_string();
        let init_variant = initial_variant.to_string();
        slint::Timer::single_shot(std::time::Duration::from_millis(0), move || {
            debug_log!("[kb-center] deferred load starting...");
            let loaded = layouts::list_available_layouts();
            debug_log!("[kb-center] loaded {} available layouts", loaded.len());
            let display_strings: Vec<SharedString> = loaded
                .iter()
                .map(|a| SharedString::from(a.display()))
                .collect();

            let all_indices: Vec<usize> = (0..loaded.len()).collect();
            *fi.borrow_mut() = all_indices;

            // Load active layouts: OS config (input.conf) > compositor seed > default
            // OS config is the single source of truth.
            {
                let mut active = al.borrow_mut();
                if let Some(saved) = layouts::load_from_os_config(&loaded) {
                    debug_log!("[kb-center] source: input.conf ({} layouts)", saved.len());
                    *active = saved;
                } else if let Some(from_compositor) = layouts::load_from_compositor(&loaded) {
                    debug_log!("[kb-center] source: compositor ({} layouts)", from_compositor.len());
                    *active = from_compositor;
                } else {
                    debug_log!("[kb-center] source: default (us)");
                    // Fix up description for the default entry
                    if let Some(first) = active.first_mut() {
                        first.description =
                            layouts::describe(&loaded, &init_layout, &init_variant);
                    }
                }
                if cfg!(debug_assertions) {
                    for a in active.iter() {
                        eprintln!("[kb-center]   - {} {} ({})", a.code, a.variant, a.description);
                    }
                }
            }

            *avail.borrow_mut() = loaded;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_available_layouts(ModelRc::from(Rc::new(VecModel::from(
                    display_strings,
                ))));
                let active = al.borrow();
                push_active_to_ui(&ui, &active);

                // Preview: CLI arg > 2nd active layout (non-English) > 1st
                if init_layout != "us" || !init_variant.is_empty() {
                    // CLI explicitly requested a layout
                    set_keyboard_preview(&ui, &init_layout, &init_variant);
                } else if active.len() > 1 {
                    // Default to showing the 2nd layout (the non-English one)
                    set_keyboard_preview(&ui, &active[1].code, &active[1].variant);
                } else if let Some(first) = active.first() {
                    set_keyboard_preview(&ui, &first.code, &first.variant);
                }

                ui.set_loading(false);
            }
        });
    }

    // Show placeholder active layouts in UI only (no save/sync — deferred load will do that)
    {
        let active = active_layouts.borrow();
        let entries: Vec<LayoutEntry> = active
            .iter()
            .map(|a| LayoutEntry {
                code: a.code.clone().into(),
                variant: a.variant.clone().into(),
                description: a.description.clone().into(),
            })
            .collect();
        ui.set_active_layouts(ModelRc::from(Rc::new(VecModel::from(entries))));
    }

    // Close
    ui.on_close(|| std::process::exit(0));

    // Drag (manual position tracking)
    {
        let ui_weak = ui.as_weak();
        ui.on_move_window(move |dx, dy| {
            if let Some(ui) = ui_weak.upgrade() {
                let scale = ui.window().scale_factor();
                let pos = ui.window().position();
                ui.window().set_position(slint::WindowPosition::Physical(
                    slint::PhysicalPosition::new(
                        pos.x + (dx * scale) as i32,
                        pos.y + (dy * scale) as i32,
                    ),
                ));
            }
        });
    }

    // Add layout
    {
        let ui_weak = ui.as_weak();
        let avail = available.clone();
        let fi = filtered_indices.clone();
        let al = active_layouts.clone();
        ui.on_add_layout(move |idx| {
            let original_idx = {
                let fi = fi.borrow();
                match fi.get(idx as usize) {
                    Some(&i) => i,
                    None => return,
                }
            };

            let avail = avail.borrow();
            let entry = match avail.get(original_idx) {
                Some(e) => e,
                None => return,
            };

            // Max 2 layouts
            {
                let current = al.borrow();
                if current.len() >= 2 {
                    debug_log!("[kb-center] max 2 layouts, ignoring add");
                    return;
                }
                // Don't add duplicates
                if current.iter().any(|a| a.code == entry.code && a.variant == entry.variant) {
                    return;
                }
            }

            al.borrow_mut().push(ActiveLayout {
                code: entry.code.clone(),
                variant: entry.variant.clone(),
                description: entry.description.clone(),
            });

            if let Some(ui) = ui_weak.upgrade() {
                let active = al.borrow();
                push_active_to_ui(&ui, &active);
                // Preview the newly added layout
                set_keyboard_preview(&ui, &entry.code, &entry.variant);
            }
        });
    }

    // Remove layout
    {
        let ui_weak = ui.as_weak();
        let al = active_layouts.clone();
        ui.on_remove_layout(move |idx| {
            let idx = idx as usize;
            {
                let current = al.borrow();
                if idx >= current.len() || current.len() <= 1 {
                    return;
                }
                // Never remove English (us) layout
                if current[idx].code == "us" {
                    return;
                }
            }

            al.borrow_mut().remove(idx);

            if let Some(ui) = ui_weak.upgrade() {
                let active = al.borrow();
                push_active_to_ui(&ui, &active);
                // Preview the first remaining layout
                if let Some(first) = active.first() {
                    set_keyboard_preview(&ui, &first.code, &first.variant);
                }
            }
        });
    }

    // Preview layout (click a row)
    {
        let ui_weak = ui.as_weak();
        ui.on_preview_layout(move |idx| {
            if let Some(ui) = ui_weak.upgrade() {
                let model = ui.get_active_layouts();
                if let Some(entry) = model.row_data(idx as usize) {
                    set_keyboard_preview(&ui, entry.code.as_str(), entry.variant.as_str());
                }
            }
        });
    }

    // Preview from dropdown selection
    {
        let ui_weak = ui.as_weak();
        let avail = available.clone();
        let fi = filtered_indices.clone();
        ui.on_preview_dropdown(move |idx| {
            let original_idx = {
                let fi = fi.borrow();
                match fi.get(idx as usize) {
                    Some(&i) => i,
                    None => return,
                }
            };
            let avail = avail.borrow();
            let entry = match avail.get(original_idx) {
                Some(e) => e,
                None => return,
            };
            if let Some(ui) = ui_weak.upgrade() {
                set_keyboard_preview(&ui, &entry.code, &entry.variant);
            }
        });
    }

    // Filter dropdown by search text
    {
        let ui_weak = ui.as_weak();
        let avail = available.clone();
        let fi = filtered_indices.clone();
        ui.on_filter_layouts(move |query| {
            let query_lower = query.to_lowercase();
            let mut new_indices = Vec::new();
            let mut filtered_strings = Vec::new();

            let avail = avail.borrow();
            for (i, a) in avail.iter().enumerate() {
                if query.is_empty() || a.display().to_lowercase().contains(&query_lower) {
                    new_indices.push(i);
                    filtered_strings.push(SharedString::from(a.display()));
                }
            }

            *fi.borrow_mut() = new_indices;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_available_layouts(ModelRc::from(Rc::new(VecModel::from(
                    filtered_strings,
                ))));
                ui.set_selected_dropdown_index(-1);
            }
        });
    }

    // Poll for theme changes (same pattern as notif-center)
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
