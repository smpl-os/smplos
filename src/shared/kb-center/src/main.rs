mod dictation;
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
        eprintln!("Usage: kb-center [--tab keyboard|dictation] [layout] [variant]");
        eprintln!("  e.g: kb-center --tab dictation");
        eprintln!("       kb-center ru phonetic");
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

    // Parse --tab and positional args
    let mut initial_tab: i32 = 0; // 0 = keyboard, 1 = dictation
    let mut positional: Vec<String> = Vec::new();
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--tab" | "-t" => {
                if let Some(tab) = args.get(i + 1) {
                    match tab.as_str() {
                        "dictation" | "d" | "1" => initial_tab = 1,
                        _ => initial_tab = 0,
                    }
                    i += 1;
                }
            }
            other if !other.starts_with('-') => positional.push(other.to_string()),
            _ => {}
        }
        i += 1;
    }
    let initial_layout = positional.first().map(|s| s.as_str()).unwrap_or("us");
    let initial_variant = positional.get(1).map(|s| s.as_str()).unwrap_or("");

    // Set up Slint backend first so the window appears immediately
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("software")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("kb-center", "kb-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(800.0_f64, 480.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    // Set initial tab from CLI args
    ui.set_initial_tab(initial_tab);

    // Clean up stale progress file from a previous crashed run
    dictation::cleanup_stale_progress();

    // Set initial dictation status + populate language/model lists
    {
        // Language list (display names)
        let lang_names: Vec<SharedString> = dictation::LANGUAGES
            .iter()
            .map(|l| SharedString::from(l.name))
            .collect();
        ui.set_dictation_lang_list(ModelRc::from(Rc::new(VecModel::from(lang_names))));

        // Model list
        let model_entries: Vec<ModelEntry> = dictation::MODELS
            .iter()
            .map(|m| ModelEntry {
                label: m.label.into(),
                size: m.size.into(),
                note: m.note.into(),
                english_only: m.english_only,
            })
            .collect();
        ui.set_dictation_model_list(ModelRc::from(Rc::new(VecModel::from(model_entries))));

        // Defaults
        ui.set_dictation_selected_lang_name("English (recommended)".into());
        ui.set_dictation_selected_model_idx(0); // base.en
        ui.set_dictation_also_english(false);
        ui.set_dictation_show_also_english(false);

        let installed = dictation::is_installed();
        ui.set_dictation_installed(installed);
        if installed {
            if let Some(cfg) = dictation::read_config() {
                // Show human-readable names in the status card
                ui.set_dictation_language(dictation::language_display(&cfg));
                ui.set_dictation_model(dictation::model_display(&cfg.model));

                // Set dropdown selections from config
                if let Some(idx) = dictation::find_language_idx(&cfg.primary_code) {
                    ui.set_dictation_selected_lang_name(
                        dictation::LANGUAGES[idx].name.into(),
                    );
                }
                if let Some(idx) = dictation::find_model_idx(&cfg.model) {
                    ui.set_dictation_selected_model_idx(idx as i32);
                }
                ui.set_dictation_also_english(cfg.also_english);
                let is_en = cfg.primary_code == "en" || cfg.primary_code == "auto";
                ui.set_dictation_show_also_english(!is_en);
                ui.set_dictation_config_missing(false);
            } else {
                // Installed but config is missing or corrupt
                ui.set_dictation_config_missing(true);
                ui.set_dictation_language("(no config)".into());
                ui.set_dictation_model("(no config)".into());
            }
            ui.set_dictation_service_running(dictation::is_service_running());
        }
    }

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

    // ── Dictation callbacks ──

    // Shared state for dictation language filtering (same pattern as keyboard layouts)
    let dictation_filtered_indices: Rc<RefCell<Vec<usize>>> =
        Rc::new(RefCell::new((0..dictation::LANGUAGES.len()).collect()));

    // Filter dictation languages by search text
    {
        let ui_weak = ui.as_weak();
        let dfi = dictation_filtered_indices.clone();
        ui.on_filter_dictation_langs(move |query| {
            let query_lower = query.to_lowercase();
            let mut new_indices = Vec::new();
            let mut filtered_names = Vec::new();

            for (i, lang) in dictation::LANGUAGES.iter().enumerate() {
                if query.is_empty() || lang.name.to_lowercase().contains(&query_lower) {
                    new_indices.push(i);
                    filtered_names.push(SharedString::from(lang.name));
                }
            }

            *dfi.borrow_mut() = new_indices;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_dictation_lang_list(ModelRc::from(Rc::new(VecModel::from(
                    filtered_names,
                ))));
            }
        });
    }

    // Select a dictation language from the dropdown
    {
        let ui_weak = ui.as_weak();
        let dfi = dictation_filtered_indices.clone();
        ui.on_select_dictation_lang(move |idx| {
            let original_idx = {
                let fi = dfi.borrow();
                match fi.get(idx as usize) {
                    Some(&i) => i,
                    None => return,
                }
            };

            let lang = &dictation::LANGUAGES[original_idx];
            if let Some(ui) = ui_weak.upgrade() {
                ui.set_dictation_selected_lang_name(lang.name.into());

                // Show "also English" checkbox for non-English, non-auto languages
                let is_en_or_auto = lang.code == "en" || lang.code == "auto";
                ui.set_dictation_show_also_english(!is_en_or_auto);
                if is_en_or_auto {
                    ui.set_dictation_also_english(false);
                }

                // Auto-select appropriate model:
                // English -> base.en (index 0)
                // Non-English -> switch away from any english-only model
                if lang.code == "en" {
                    ui.set_dictation_selected_model_idx(0); // base.en
                } else {
                    let current = ui.get_dictation_selected_model_idx() as usize;
                    if dictation::is_model_english_only(current) {
                        ui.set_dictation_selected_model_idx(1); // base (multilingual)
                    }
                }

                // Reset the language list back to full after selection
                let all_names: Vec<SharedString> = dictation::LANGUAGES
                    .iter()
                    .map(|l| SharedString::from(l.name))
                    .collect();
                ui.set_dictation_lang_list(ModelRc::from(Rc::new(VecModel::from(all_names))));
                let mut fi = dfi.borrow_mut();
                *fi = (0..dictation::LANGUAGES.len()).collect();
            }
        });
    }

    // Start dictation install (fresh install)
    {
        let ui_weak = ui.as_weak();
        ui.on_start_dictation_install(move || {
            if let Some(ui) = ui_weak.upgrade() {
                // Guard: don't double-launch
                if dictation::is_install_running() {
                    return;
                }

                // Resolve selected language code from the displayed name
                let lang_name = ui.get_dictation_selected_lang_name();
                let lang_code = dictation::LANGUAGES.iter()
                    .find(|l| l.name == lang_name.as_str())
                    .map(|l| l.code)
                    .unwrap_or("en");

                let mut model_idx = ui.get_dictation_selected_model_idx() as usize;

                // Validate: english-only model with non-English language
                if lang_code != "en" && dictation::is_model_english_only(model_idx) {
                    ui.set_dictation_selected_model_idx(1); // auto-fix to base
                    model_idx = 1;
                }

                let model_id = dictation::MODELS.get(model_idx)
                    .map(|m| m.id)
                    .unwrap_or("base");

                let also_english = ui.get_dictation_also_english();

                // Write config before install so voxtype reads it on first run
                if !dictation::write_config(lang_code, model_id, also_english) {
                    ui.set_dictation_progress_text("Error: Could not write config file".into());
                    ui.set_dictation_install_error(true);
                    ui.set_dictation_installing(true);
                    return;
                }

                ui.set_dictation_progress(0.0);
                ui.set_dictation_progress_text("Starting...".into());
                ui.set_dictation_install_error(false);
                ui.set_dictation_installing(true);
                if !dictation::launch_install() {
                    // Spawn failed -- error written to progress file, timer picks it up
                    ui.set_dictation_install_error(true);
                }
            }
        });
    }

    // Reconfigure dictation (change language/model on existing install)
    {
        let ui_weak = ui.as_weak();
        ui.on_start_dictation_reconfigure(move || {
            if let Some(ui) = ui_weak.upgrade() {
                // Guard: don't double-launch
                if dictation::is_install_running() {
                    return;
                }

                let lang_name = ui.get_dictation_selected_lang_name();
                let lang_code = dictation::LANGUAGES.iter()
                    .find(|l| l.name == lang_name.as_str())
                    .map(|l| l.code)
                    .unwrap_or("en");

                let mut model_idx = ui.get_dictation_selected_model_idx() as usize;

                // Validate: english-only model with non-English language
                if lang_code != "en" && dictation::is_model_english_only(model_idx) {
                    ui.set_dictation_selected_model_idx(1);
                    model_idx = 1;
                }

                let model_id = dictation::MODELS.get(model_idx)
                    .map(|m| m.id)
                    .unwrap_or("base");

                let also_english = ui.get_dictation_also_english();

                // Write new config
                if !dictation::write_config(lang_code, model_id, also_english) {
                    ui.set_dictation_progress_text("Error: Could not write config file".into());
                    ui.set_dictation_install_error(true);
                    ui.set_dictation_installing(true);
                    return;
                }

                // Download model + restart service
                ui.set_dictation_progress(0.0);
                ui.set_dictation_progress_text("Starting...".into());
                ui.set_dictation_install_error(false);
                ui.set_dictation_installing(true);
                ui.set_dictation_configuring(false);
                if !dictation::launch_model_download() {
                    ui.set_dictation_install_error(true);
                }
            }
        });
    }

    // Open dictation config in editor
    ui.on_open_dictation_config(|| {
        dictation::open_config();
    });

    // Cancel ongoing install/download
    {
        let ui_weak = ui.as_weak();
        ui.on_cancel_dictation_install(move || {
            if let Some(ui) = ui_weak.upgrade() {
                ui.set_dictation_installing(false);
                ui.set_dictation_install_error(false);
                ui.set_dictation_progress(0.0);
                ui.set_dictation_progress_text("Starting...".into());
                dictation::clear_progress();
            }
        });
    }

    // Restart / start dictation service
    {
        let ui_weak = ui.as_weak();
        ui.on_restart_dictation_service(move || {
            dictation::restart_service();
            // Update status after a short delay
            let ui_weak2 = ui_weak.clone();
            slint::Timer::single_shot(std::time::Duration::from_millis(500), move || {
                if let Some(ui) = ui_weak2.upgrade() {
                    ui.set_dictation_service_running(dictation::is_service_running());
                }
            });
        });
    }

    // Poll for theme changes + dictation status (same pattern as notif-center)
    {
        let ui_weak = ui.as_weak();
        let timer = slint::Timer::default();
        timer.start(
            slint::TimerMode::Repeated,
            std::time::Duration::from_secs(2),
            move || {
                if let Some(ui) = ui_weak.upgrade() {
                    apply_theme(&ui);

                    if ui.get_dictation_installing() {
                        // Poll progress file during install/download
                        let (progress, text) = dictation::read_progress();
                        ui.set_dictation_progress(progress);
                        if !text.is_empty() {
                            ui.set_dictation_progress_text(text.clone().into());
                        }

                        // Detect error state (script writes 0|Error: ...)
                        if progress == 0.0 && text.starts_with("Error") {
                            ui.set_dictation_install_error(true);
                        }

                        // Completion: progress hit 100%
                        if progress >= 1.0 {
                            // Brief delay so user sees "Done!" state
                            let ui_weak2 = ui.as_weak();
                            slint::Timer::single_shot(
                                std::time::Duration::from_secs(2),
                                move || {
                                    if let Some(ui) = ui_weak2.upgrade() {
                                        ui.set_dictation_installing(false);
                                        dictation::clear_progress();

                                        // Reload status
                                        let installed = dictation::is_installed();
                                        ui.set_dictation_installed(installed);
                                        if installed {
                                            if let Some(cfg) = dictation::read_config() {
                                                ui.set_dictation_language(dictation::language_display(&cfg));
                                                ui.set_dictation_model(dictation::model_display(&cfg.model));
                                                if let Some(idx) = dictation::find_language_idx(&cfg.primary_code) {
                                                    ui.set_dictation_selected_lang_name(
                                                        dictation::LANGUAGES[idx].name.into(),
                                                    );
                                                }
                                                if let Some(idx) = dictation::find_model_idx(&cfg.model) {
                                                    ui.set_dictation_selected_model_idx(idx as i32);
                                                }
                                                ui.set_dictation_also_english(cfg.also_english);
                                                let is_en = cfg.primary_code == "en" || cfg.primary_code == "auto";
                                                ui.set_dictation_show_also_english(!is_en);
                                                ui.set_dictation_config_missing(false);
                                            } else {
                                                ui.set_dictation_config_missing(true);
                                                ui.set_dictation_language("(no config)".into());
                                                ui.set_dictation_model("(no config)".into());
                                            }
                                            ui.set_dictation_service_running(dictation::is_service_running());
                                        }
                                    }
                                },
                            );
                        }
                    } else {
                        // Normal status refresh (not during install)
                        let installed = dictation::is_installed();
                        ui.set_dictation_installed(installed);
                        if installed {
                            if let Some(cfg) = dictation::read_config() {
                                ui.set_dictation_language(dictation::language_display(&cfg));
                                ui.set_dictation_model(dictation::model_display(&cfg.model));
                                ui.set_dictation_config_missing(false);
                            } else if !dictation::config_exists() {
                                ui.set_dictation_config_missing(true);
                                ui.set_dictation_language("(no config)".into());
                                ui.set_dictation_model("(no config)".into());
                            }
                            ui.set_dictation_service_running(dictation::is_service_running());
                        }
                    }
                }
            },
        );
        std::mem::forget(timer);
    }

    ui.run()
}
