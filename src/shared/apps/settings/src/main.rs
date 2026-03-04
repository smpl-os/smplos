mod dictation;
mod display;
mod layouts;
mod theme;
mod xkb_labels;

use display::backend::DisplayBackend;
use display::monitor::{canvas_scale_factor, snap_to_nearest_edge, Monitor, MonitorConfig};
use slint::Model;
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

macro_rules! debug_log {
    ($($arg:tt)*) => {
        if cfg!(debug_assertions) {
            eprintln!($($arg)*);
        }
    };
}
pub(crate) use debug_log;

// ── Single-instance guard ────────────────────────────────────────────────────

fn acquire_single_instance() {
    use std::os::unix::io::AsRawFd;
    let run_dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string());
    let lock_path = format!("{}/settings.lock", run_dir);
    let file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .unwrap_or_else(|e| {
            eprintln!("[settings] cannot open lock file: {}", e);
            std::process::exit(1);
        });
    let fd = file.as_raw_fd();
    let ret = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
    if ret != 0 {
        eprintln!("[settings] another instance is already running");
        std::process::exit(0);
    }
    std::mem::forget(file);
}

// ── Theme application ────────────────────────────────────────────────────────

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

// ── Keyboard helpers ─────────────────────────────────────────────────────────

fn to_key_model(keys: &[xkb_labels::KeyInfo]) -> slint::ModelRc<KeyData> {
    let entries: Vec<KeyData> = keys
        .iter()
        .map(|k| KeyData {
            base: k.base.clone().into(),
            english: k.english.clone().into(),
            w: k.width,
            is_modifier: k.is_modifier,
        })
        .collect();
    slint::ModelRc::from(Rc::new(slint::VecModel::from(entries)))
}

fn set_keyboard_preview(ui: &MainWindow, layout: &str, variant: &str) {
    let (name, r0, r1, r2, r3, r4) = xkb_labels::resolve(layout, variant);
    ui.set_layout_name(name.into());
    ui.set_row0(to_key_model(&r0));
    ui.set_row1(to_key_model(&r1));
    ui.set_row2(to_key_model(&r2));
    ui.set_row3(to_key_model(&r3));
    ui.set_row4(to_key_model(&r4));
}

fn push_active_to_ui(ui: &MainWindow, active: &[layouts::ActiveLayout]) {
    let entries: Vec<LayoutEntry> = active
        .iter()
        .map(|a| LayoutEntry {
            code: a.code.clone().into(),
            variant: a.variant.clone().into(),
            description: a.description.clone().into(),
        })
        .collect();
    ui.set_active_layouts(slint::ModelRc::from(Rc::new(slint::VecModel::from(entries))));
    layouts::sync_to_compositor(active);
}

// ── Display helpers ──────────────────────────────────────────────────────────

const CANVAS_W: f64 = 580.0;
const CANVAS_H: f64 = 200.0;

struct DisplayState {
    backend: Box<dyn DisplayBackend>,
    monitors: Vec<Monitor>,
    original: Vec<Monitor>,
    offset_x: f64,
    offset_y: f64,
    scale: f64,
    primary: String,
}

impl DisplayState {
    fn new(backend: Box<dyn DisplayBackend>) -> Self {
        Self {
            backend,
            monitors: Vec::new(),
            original: Vec::new(),
            offset_x: 0.0,
            offset_y: 0.0,
            scale: 0.1,
            primary: String::new(),
        }
    }

    fn load_monitors(&mut self) -> Result<(), String> {
        self.monitors = self.backend.query_monitors()?;
        self.original = self.monitors.clone();
        self.primary = self
            .monitors
            .iter()
            .find(|m| m.focused)
            .or(self.monitors.first())
            .map(|m| m.name.clone())
            .unwrap_or_default();
        self.recalc_canvas();
        Ok(())
    }

    fn recalc_canvas(&mut self) {
        self.scale = canvas_scale_factor(&self.monitors, CANVAS_W, CANVAS_H);
        let min_x = self.monitors.iter().map(|m| m.x).min().unwrap_or(0) as f64;
        let min_y = self.monitors.iter().map(|m| m.y).min().unwrap_or(0) as f64;
        self.offset_x = -min_x;
        self.offset_y = -min_y;
    }

    fn to_slint_model(&self) -> Vec<MonitorInfo> {
        let margin = 20.0;
        self.monitors
            .iter()
            .map(|m| {
                let modes: Vec<slint::SharedString> = m
                    .available_modes
                    .iter()
                    .map(|mode| slint::SharedString::from(mode.label()))
                    .collect();

                let cur_mode_idx = m
                    .available_modes
                    .iter()
                    .position(|mode| {
                        mode.width == m.width
                            && mode.height == m.height
                            && (mode.refresh_rate - m.refresh_rate).abs() < 1.0
                    })
                    .unwrap_or(0) as i32;

                MonitorInfo {
                    id: m.id,
                    name: slint::SharedString::from(&m.name),
                    description: slint::SharedString::from(&m.description),
                    width: m.width,
                    height: m.height,
                    refresh_rate: m.refresh_rate as f32,
                    pos_x: m.x,
                    pos_y: m.y,
                    scale: m.scale as f32,
                    enabled: m.enabled,
                    is_primary: m.name == self.primary,
                    canvas_x: ((m.x as f64 + self.offset_x) * self.scale + margin) as f32,
                    canvas_y: ((m.y as f64 + self.offset_y) * self.scale + margin) as f32,
                    canvas_w: (m.width as f64 * self.scale) as f32,
                    canvas_h: (m.height as f64 * self.scale) as f32,
                    available_modes: slint::ModelRc::new(slint::VecModel::from(modes)),
                    current_mode_index: cur_mode_idx,
                }
            })
            .collect()
    }

    fn configs_from_current(&self) -> Vec<MonitorConfig> {
        self.monitors
            .iter()
            .map(|m| MonitorConfig {
                name: m.name.clone(),
                width: m.width,
                height: m.height,
                refresh_rate: m.refresh_rate,
                x: m.x,
                y: m.y,
                scale: m.scale,
                enabled: m.enabled,
            })
            .collect()
    }

    fn has_changes(&self) -> bool {
        if self.monitors.len() != self.original.len() {
            return true;
        }
        for (m, o) in self.monitors.iter().zip(self.original.iter()) {
            if m.x != o.x
                || m.y != o.y
                || m.width != o.width
                || m.height != o.height
                || (m.refresh_rate - o.refresh_rate).abs() > 0.1
                || (m.scale - o.scale).abs() > 0.01
                || m.enabled != o.enabled
            {
                return true;
            }
        }
        false
    }
}

fn push_display_state_to_ui(ui: &MainWindow, state: &DisplayState) {
    let model = state.to_slint_model();
    let model_rc = slint::ModelRc::new(slint::VecModel::from(model));
    ui.set_disp_monitors(model_rc);
    ui.set_disp_has_changes(state.has_changes());

    let idx = ui.get_disp_selected_index();
    if idx >= 0 && (idx as usize) < state.monitors.len() {
        let m = &state.monitors[idx as usize];
        let modes: Vec<slint::SharedString> = m
            .available_modes
            .iter()
            .map(|mode| slint::SharedString::from(mode.label()))
            .collect();
        ui.set_disp_selected_modes(slint::ModelRc::new(slint::VecModel::from(modes)));

        let mode_idx = m
            .available_modes
            .iter()
            .position(|mode| {
                mode.width == m.width
                    && mode.height == m.height
                    && (mode.refresh_rate - m.refresh_rate).abs() < 1.0
            })
            .unwrap_or(0);
        ui.set_disp_selected_mode_index(mode_idx as i32);
        ui.set_disp_selected_scale(m.scale as f32);
    }
}

// ── Power + About helpers ────────────────────────────────────────────────────

fn get_power_profile() -> String {
    std::process::Command::new("powerprofilesctl")
        .arg("get")
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        })
        .unwrap_or_else(|| "balanced".to_string())
}

fn set_power_profile(profile: &str) {
    let _ = std::process::Command::new("powerprofilesctl")
        .args(["set", profile])
        .output();
}

fn get_about_info() -> (String, String, String, String) {
    let version = std::fs::read_to_string("/etc/os-release")
        .ok()
        .and_then(|c| {
            c.lines()
                .find(|l| l.starts_with("VERSION_ID="))
                .map(|l| l.trim_start_matches("VERSION_ID=").trim_matches('"').to_string())
        })
        .unwrap_or_else(|| "dev".to_string());

    let kernel = std::process::Command::new("uname")
        .arg("-r")
        .output()
        .ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();

    let uptime = std::process::Command::new("uptime")
        .arg("-p")
        .output()
        .ok()
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .trim()
                .strip_prefix("up ")
                .unwrap_or("unknown")
                .to_string()
        })
        .unwrap_or_default();

    let hostname = std::fs::read_to_string("/etc/hostname")
        .unwrap_or_else(|_| "smplOS".to_string())
        .trim()
        .to_string();

    (version, kernel, uptime, hostname)
}

// ── Main ─────────────────────────────────────────────────────────────────────

fn main() -> Result<(), slint::PlatformError> {
    acquire_single_instance();
    dictation::cleanup_stale_progress();

    // Parse CLI args
    let mut initial_tab = 0;
    let mut initial_layout = "us".to_string();
    let mut initial_variant = String::new();
    let mut use_demo = false;

    let args: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-v" | "--version" => {
                println!("settings v{}", env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            "--tab" => {
                if i + 1 < args.len() {
                    initial_tab = match args[i + 1].as_str() {
                        "keyboard" => 0,
                        "dictation" => 1,
                        "display" => 2,
                        "power" => 3,
                        "about" => 4,
                        _ => 0,
                    };
                    i += 1;
                }
            }
            "--demo" => {
                use_demo = true;
            }
            other => {
                // Positional: layout [variant]
                if initial_layout == "us" && !other.starts_with('-') {
                    initial_layout = other.to_string();
                    if i + 1 < args.len() && !args[i + 1].starts_with('-') {
                        initial_variant = args[i + 1].clone();
                        i += 1;
                    }
                }
            }
        }
        i += 1;
    }

    // Set up winit backend
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("software")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("settings", "settings")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(900.0_f64, 560.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);
    ui.set_initial_tab(initial_tab);

    // ── Keyboard tab init ────────────────────────────────────────────────────

    // Dictation data for UI
    {
        let lang_names: Vec<slint::SharedString> = dictation::LANGUAGES
            .iter()
            .map(|l| slint::SharedString::from(l.name))
            .collect();
        ui.set_dictation_lang_list(slint::ModelRc::from(Rc::new(slint::VecModel::from(lang_names))));

        let model_entries: Vec<ModelEntry> = dictation::MODELS
            .iter()
            .map(|m| ModelEntry {
                label: m.label.into(),
                size: m.size.into(),
                note: m.note.into(),
                english_only: m.english_only,
            })
            .collect();
        ui.set_dictation_model_list(slint::ModelRc::from(Rc::new(slint::VecModel::from(model_entries))));

        ui.set_dictation_selected_lang_name("English (recommended)".into());
        ui.set_dictation_selected_model_idx(0);
        ui.set_dictation_also_english(false);
        ui.set_dictation_show_also_english(false);

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

    layouts::cleanup_legacy_config();
    set_keyboard_preview(&ui, &initial_layout, &initial_variant);

    let available: Rc<RefCell<Vec<layouts::AvailableLayout>>> =
        Rc::new(RefCell::new(Vec::new()));
    let filtered_indices: Rc<RefCell<Vec<usize>>> = Rc::new(RefCell::new(Vec::new()));
    let active_layouts: Rc<RefCell<Vec<layouts::ActiveLayout>>> = Rc::new(RefCell::new(vec![
        layouts::ActiveLayout {
            code: initial_layout.to_string(),
            variant: initial_variant.to_string(),
            description: String::new(),
        },
    ]));

    // Deferred layout loading
    {
        let ui_weak = ui.as_weak();
        let avail = available.clone();
        let fi = filtered_indices.clone();
        let al = active_layouts.clone();
        let init_layout = initial_layout.to_string();
        let init_variant = initial_variant.to_string();
        slint::Timer::single_shot(std::time::Duration::from_millis(0), move || {
            debug_log!("[settings] deferred load starting...");
            let loaded = layouts::list_available_layouts();
            debug_log!("[settings] loaded {} available layouts", loaded.len());
            let display_strings: Vec<slint::SharedString> = loaded
                .iter()
                .map(|a| slint::SharedString::from(a.display()))
                .collect();

            let all_indices: Vec<usize> = (0..loaded.len()).collect();
            *fi.borrow_mut() = all_indices;

            {
                let mut active = al.borrow_mut();
                if let Some(saved) = layouts::load_from_os_config(&loaded) {
                    debug_log!("[settings] source: input.conf ({} layouts)", saved.len());
                    *active = saved;
                } else if let Some(from_compositor) = layouts::load_from_compositor(&loaded) {
                    debug_log!("[settings] source: compositor ({} layouts)", from_compositor.len());
                    *active = from_compositor;
                } else {
                    debug_log!("[settings] source: default (us)");
                    if let Some(first) = active.first_mut() {
                        first.description =
                            layouts::describe(&loaded, &init_layout, &init_variant);
                    }
                }
            }

            *avail.borrow_mut() = loaded;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_available_layouts(slint::ModelRc::from(Rc::new(slint::VecModel::from(
                    display_strings,
                ))));
                let active = al.borrow();
                push_active_to_ui(&ui, &active);

                if init_layout != "us" || !init_variant.is_empty() {
                    set_keyboard_preview(&ui, &init_layout, &init_variant);
                } else if active.len() > 1 {
                    set_keyboard_preview(&ui, &active[1].code, &active[1].variant);
                } else if let Some(first) = active.first() {
                    set_keyboard_preview(&ui, &first.code, &first.variant);
                }

                ui.set_loading(false);
            }
        });
    }

    // Show placeholder active layouts
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
        ui.set_active_layouts(slint::ModelRc::from(Rc::new(slint::VecModel::from(entries))));
    }

    // ── Display tab init ─────────────────────────────────────────────────────

    let display_backend: Box<dyn DisplayBackend> = if use_demo {
        eprintln!("Running display tab in demo mode with mock monitors");
        Box::new(display::demo::DemoBackend::new())
    } else {
        match display::backend::detect_backend() {
            Ok(b) => b,
            Err(e) => {
                debug_log!("[settings] display backend: {e} -- using demo");
                Box::new(display::demo::DemoBackend::new())
            }
        }
    };

    let disp_state = Rc::new(RefCell::new(DisplayState::new(display_backend)));
    if let Err(e) = disp_state.borrow_mut().load_monitors() {
        debug_log!("[settings] failed to query monitors: {e}");
    }
    push_display_state_to_ui(&ui, &disp_state.borrow());
    ui.set_disp_status_text(slint::SharedString::from(format!(
        "Backend: {} | {} monitor(s)",
        disp_state.borrow().backend.name(),
        disp_state.borrow().monitors.len()
    )));

    // ── Power tab init ───────────────────────────────────────────────────────

    {
        let profile = get_power_profile();
        let idx: i32 = match profile.as_str() {
            "power-saver" => 0,
            "balanced" => 1,
            "performance" => 2,
            _ => 1,
        };
        ui.set_power_profile_index(idx);
    }

    // ── About tab init ───────────────────────────────────────────────────────

    {
        let (version, kernel, uptime, hostname) = get_about_info();
        ui.set_about_version(slint::SharedString::from(format!("v{}", version)));
        ui.set_about_kernel(slint::SharedString::from(kernel));
        ui.set_about_uptime(slint::SharedString::from(uptime));
        ui.set_about_hostname(slint::SharedString::from(hostname));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // CALLBACKS
    // ══════════════════════════════════════════════════════════════════════════

    ui.on_close(|| std::process::exit(0));

    // Window drag
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

    // ── Keyboard callbacks ───────────────────────────────────────────────────

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

            {
                let current = al.borrow();
                if current.len() >= 2 {
                    return;
                }
                if current.iter().any(|a| a.code == entry.code && a.variant == entry.variant) {
                    return;
                }
            }

            al.borrow_mut().push(layouts::ActiveLayout {
                code: entry.code.clone(),
                variant: entry.variant.clone(),
                description: entry.description.clone(),
            });

            if let Some(ui) = ui_weak.upgrade() {
                let active = al.borrow();
                push_active_to_ui(&ui, &active);
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
                if current[idx].code == "us" {
                    return;
                }
            }

            al.borrow_mut().remove(idx);

            if let Some(ui) = ui_weak.upgrade() {
                let active = al.borrow();
                push_active_to_ui(&ui, &active);
                if let Some(first) = active.first() {
                    set_keyboard_preview(&ui, &first.code, &first.variant);
                }
            }
        });
    }

    // Preview layout
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

    // Preview from dropdown
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

    // Filter layouts
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
                    filtered_strings.push(slint::SharedString::from(a.display()));
                }
            }

            *fi.borrow_mut() = new_indices;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_available_layouts(slint::ModelRc::from(Rc::new(slint::VecModel::from(
                    filtered_strings,
                ))));
                ui.set_selected_dropdown_index(-1);
            }
        });
    }

    // ── Dictation callbacks ──────────────────────────────────────────────────

    let dictation_filtered_indices: Rc<RefCell<Vec<usize>>> =
        Rc::new(RefCell::new((0..dictation::LANGUAGES.len()).collect()));

    // Filter dictation languages
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
                    filtered_names.push(slint::SharedString::from(lang.name));
                }
            }

            *dfi.borrow_mut() = new_indices;

            if let Some(ui) = ui_weak.upgrade() {
                ui.set_dictation_lang_list(slint::ModelRc::from(Rc::new(slint::VecModel::from(
                    filtered_names,
                ))));
            }
        });
    }

    // Select dictation language
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

                let is_en_or_auto = lang.code == "en" || lang.code == "auto";
                ui.set_dictation_show_also_english(!is_en_or_auto);
                if is_en_or_auto {
                    ui.set_dictation_also_english(false);
                }

                if lang.code == "en" {
                    ui.set_dictation_selected_model_idx(0);
                } else {
                    let current = ui.get_dictation_selected_model_idx() as usize;
                    if dictation::is_model_english_only(current) {
                        ui.set_dictation_selected_model_idx(1);
                    }
                }

                let all_names: Vec<slint::SharedString> = dictation::LANGUAGES
                    .iter()
                    .map(|l| slint::SharedString::from(l.name))
                    .collect();
                ui.set_dictation_lang_list(slint::ModelRc::from(Rc::new(slint::VecModel::from(all_names))));
                let mut fi = dfi.borrow_mut();
                *fi = (0..dictation::LANGUAGES.len()).collect();
            }
        });
    }

    // Start dictation install
    {
        let ui_weak = ui.as_weak();
        ui.on_start_dictation_install(move || {
            if let Some(ui) = ui_weak.upgrade() {
                if dictation::is_install_running() {
                    return;
                }

                let lang_name = ui.get_dictation_selected_lang_name();
                let lang_code = dictation::LANGUAGES.iter()
                    .find(|l| l.name == lang_name.as_str())
                    .map(|l| l.code)
                    .unwrap_or("en");

                let mut model_idx = ui.get_dictation_selected_model_idx() as usize;

                if lang_code != "en" && dictation::is_model_english_only(model_idx) {
                    ui.set_dictation_selected_model_idx(1);
                    model_idx = 1;
                }

                let model_id = dictation::MODELS.get(model_idx)
                    .map(|m| m.id)
                    .unwrap_or("base");

                let also_english = ui.get_dictation_also_english();

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
                    ui.set_dictation_install_error(true);
                }
            }
        });
    }

    // Reconfigure dictation
    {
        let ui_weak = ui.as_weak();
        ui.on_start_dictation_reconfigure(move || {
            if let Some(ui) = ui_weak.upgrade() {
                if dictation::is_install_running() {
                    return;
                }

                let lang_name = ui.get_dictation_selected_lang_name();
                let lang_code = dictation::LANGUAGES.iter()
                    .find(|l| l.name == lang_name.as_str())
                    .map(|l| l.code)
                    .unwrap_or("en");

                let mut model_idx = ui.get_dictation_selected_model_idx() as usize;

                if lang_code != "en" && dictation::is_model_english_only(model_idx) {
                    ui.set_dictation_selected_model_idx(1);
                    model_idx = 1;
                }

                let model_id = dictation::MODELS.get(model_idx)
                    .map(|m| m.id)
                    .unwrap_or("base");

                let also_english = ui.get_dictation_also_english();

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
                ui.set_dictation_configuring(false);
                if !dictation::launch_model_download() {
                    ui.set_dictation_install_error(true);
                }
            }
        });
    }

    ui.on_open_dictation_config(|| {
        dictation::open_config();
    });

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

    {
        let ui_weak = ui.as_weak();
        ui.on_restart_dictation_service(move || {
            dictation::restart_service();
            let ui_weak2 = ui_weak.clone();
            slint::Timer::single_shot(std::time::Duration::from_millis(500), move || {
                if let Some(ui) = ui_weak2.upgrade() {
                    ui.set_dictation_service_running(dictation::is_service_running());
                }
            });
        });
    }

    // ── Display callbacks ────────────────────────────────────────────────────

    // Select monitor
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_select_monitor(move |idx| {
            let ui = ui_handle.unwrap();
            let st = state.borrow();
            if let Some(m) = st.monitors.get(idx as usize) {
                let modes: Vec<slint::SharedString> = m
                    .available_modes
                    .iter()
                    .map(|mode| slint::SharedString::from(mode.label()))
                    .collect();
                ui.set_disp_selected_modes(slint::ModelRc::new(slint::VecModel::from(modes)));

                let mode_idx = m
                    .available_modes
                    .iter()
                    .position(|mode| {
                        mode.width == m.width
                            && mode.height == m.height
                            && (mode.refresh_rate - m.refresh_rate).abs() < 1.0
                    })
                    .unwrap_or(0);
                ui.set_disp_selected_mode_index(mode_idx as i32);
                ui.set_disp_selected_scale(m.scale as f32);
            }
        });
    }

    // Drag finished
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_drag_finished(move |idx, canvas_x, canvas_y| {
            let mut st = state.borrow_mut();
            let idx = idx as usize;
            if idx >= st.monitors.len() { return; }

            let real_x = ((canvas_x as f64 - 20.0) / st.scale - st.offset_x) as i32;
            let real_y = ((canvas_y as f64 - 20.0) / st.scale - st.offset_y) as i32;
            st.monitors[idx].x = real_x;
            st.monitors[idx].y = real_y;

            let others: Vec<(i32, i32, i32, i32)> = st
                .monitors.iter().enumerate()
                .filter(|(i, _)| *i != idx)
                .map(|(_, m)| (m.x, m.y, m.width, m.height))
                .collect();

            let m = &st.monitors[idx];
            let snap_threshold = (50.0 / st.scale) as i32;
            let (sx, sy) = snap_to_nearest_edge(m.x, m.y, m.width, m.height, &others, snap_threshold);
            st.monitors[idx].x = sx;
            st.monitors[idx].y = sy;

            st.recalc_canvas();
            let ui = ui_handle.unwrap();
            push_display_state_to_ui(&ui, &st);
        });
    }

    // Change resolution
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_change_resolution(move |mon_idx, mode_idx| {
            let mut st = state.borrow_mut();
            let mi = mon_idx as usize;
            let modi = mode_idx as usize;
            if mi < st.monitors.len() && modi < st.monitors[mi].available_modes.len() {
                let mode = st.monitors[mi].available_modes[modi].clone();
                st.monitors[mi].width = mode.width;
                st.monitors[mi].height = mode.height;
                st.monitors[mi].refresh_rate = mode.refresh_rate;
                st.recalc_canvas();
            }
            let ui = ui_handle.unwrap();
            push_display_state_to_ui(&ui, &st);
        });
    }

    // Change scale
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_change_scale(move |mon_idx, scale| {
            let mut st = state.borrow_mut();
            let mi = mon_idx as usize;
            if mi < st.monitors.len() {
                st.monitors[mi].scale = scale as f64;
                st.recalc_canvas();
            }
            let ui = ui_handle.unwrap();
            push_display_state_to_ui(&ui, &st);
        });
    }

    // Set primary
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_set_primary(move |mon_idx| {
            let mut st = state.borrow_mut();
            let mi = mon_idx as usize;
            if mi < st.monitors.len() {
                st.primary = st.monitors[mi].name.clone();
                let name = st.primary.clone();
                let _ = st.backend.set_primary(&name);
            }
            let ui = ui_handle.unwrap();
            push_display_state_to_ui(&ui, &st);
            ui.set_disp_status_text(slint::SharedString::from("Primary monitor updated"));
        });
    }

    // Apply
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_apply_changes(move || {
            let mut st = state.borrow_mut();
            let configs = st.configs_from_current();
            let ui = ui_handle.unwrap();

            match st.backend.apply(&configs) {
                Ok(()) => {
                    match st.backend.persist(&configs) {
                        Ok(path) => {
                            ui.set_disp_status_text(slint::SharedString::from(format!(
                                "Applied and saved to {path}"
                            )));
                        }
                        Err(e) => {
                            ui.set_disp_status_text(slint::SharedString::from(format!(
                                "Applied live but failed to save: {e}"
                            )));
                        }
                    }
                    st.original = st.monitors.clone();
                }
                Err(e) => {
                    ui.set_disp_status_text(slint::SharedString::from(format!("Apply failed: {e}")));
                }
            }
            push_display_state_to_ui(&ui, &st);
        });
    }

    // Revert
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_revert_changes(move || {
            let mut st = state.borrow_mut();
            st.monitors = st.original.clone();
            st.recalc_canvas();
            let ui = ui_handle.unwrap();
            push_display_state_to_ui(&ui, &st);
            ui.set_disp_status_text(slint::SharedString::from("Reverted to original layout"));
            ui.set_disp_selected_index(-1);
        });
    }

    // Refresh
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_refresh_monitors(move || {
            let mut st = state.borrow_mut();
            let ui = ui_handle.unwrap();
            match st.load_monitors() {
                Ok(()) => {
                    push_display_state_to_ui(&ui, &st);
                    ui.set_disp_status_text(slint::SharedString::from(format!(
                        "{} monitor(s) detected", st.monitors.len()
                    )));
                    ui.set_disp_selected_index(-1);
                }
                Err(e) => {
                    ui.set_disp_status_text(slint::SharedString::from(format!("Refresh failed: {e}")));
                }
            }
        });
    }

    // Identify
    {
        let state = disp_state.clone();
        let ui_handle = ui.as_weak();
        ui.on_disp_identify_monitors(move || {
            let st = state.borrow();
            let ui = ui_handle.unwrap();
            match st.backend.identify(&st.monitors) {
                Ok(()) => {
                    ui.set_disp_status_text(slint::SharedString::from("Identifying monitors..."));
                }
                Err(e) => {
                    ui.set_disp_status_text(slint::SharedString::from(format!("Identify failed: {e}")));
                }
            }
        });
    }

    // ── Power callbacks ──────────────────────────────────────────────────────

    ui.on_set_power_profile(move |idx| {
        let profile = match idx {
            0 => "power-saver",
            1 => "balanced",
            2 => "performance",
            _ => "balanced",
        };
        set_power_profile(profile);
    });

    // ── Theme polling timer ──────────────────────────────────────────────────

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
                        let (progress, text) = dictation::read_progress();
                        ui.set_dictation_progress(progress);
                        if !text.is_empty() {
                            ui.set_dictation_progress_text(text.clone().into());
                        }

                        if progress == 0.0 && text.starts_with("Error") {
                            ui.set_dictation_install_error(true);
                        }

                        if progress >= 1.0 {
                            let ui_weak2 = ui.as_weak();
                            slint::Timer::single_shot(
                                std::time::Duration::from_secs(2),
                                move || {
                                    if let Some(ui) = ui_weak2.upgrade() {
                                        ui.set_dictation_installing(false);
                                        dictation::clear_progress();

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

                    // Refresh about uptime
                    let uptime = std::process::Command::new("uptime")
                        .arg("-p")
                        .output()
                        .ok()
                        .map(|o| {
                            String::from_utf8_lossy(&o.stdout)
                                .trim()
                                .strip_prefix("up ")
                                .unwrap_or("unknown")
                                .to_string()
                        })
                        .unwrap_or_default();
                    ui.set_about_uptime(slint::SharedString::from(uptime));
                }
            },
        );
        std::mem::forget(timer);
    }

    ui.run()
}
