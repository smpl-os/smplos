mod backend;
mod demo;
mod hyprland;
mod monitor;
mod theme;

use backend::DisplayBackend;
use monitor::{canvas_scale_factor, snap_to_nearest_edge, Monitor, MonitorConfig};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

const CANVAS_W: f64 = 640.0;
const CANVAS_H: f64 = 220.0;

/// State shared between Slint callbacks.
struct AppState {
    backend: Box<dyn DisplayBackend>,
    monitors: Vec<Monitor>,
    original: Vec<Monitor>,
    offset_x: f64,
    offset_y: f64,
    scale: f64,
    primary: String,
}

impl AppState {
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

fn apply_theme(ui: &App) {
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

fn push_state_to_ui(ui: &App, state: &AppState) {
    let model = state.to_slint_model();
    let model_rc = slint::ModelRc::new(slint::VecModel::from(model));
    ui.set_monitors(model_rc);
    ui.set_has_changes(state.has_changes());

    let idx = ui.get_selected_index();
    if idx >= 0 && (idx as usize) < state.monitors.len() {
        let m = &state.monitors[idx as usize];
        let modes: Vec<slint::SharedString> = m
            .available_modes
            .iter()
            .map(|mode| slint::SharedString::from(mode.label()))
            .collect();
        ui.set_selected_modes(slint::ModelRc::new(slint::VecModel::from(modes)));

        let mode_idx = m
            .available_modes
            .iter()
            .position(|mode| {
                mode.width == m.width
                    && mode.height == m.height
                    && (mode.refresh_rate - m.refresh_rate).abs() < 1.0
            })
            .unwrap_or(0);
        ui.set_selected_mode_index(mode_idx as i32);
        ui.set_selected_scale(m.scale as f32);
    }
}

fn main() -> Result<(), slint::PlatformError> {
    let use_demo = std::env::args().any(|a| a == "--demo");

    for arg in std::env::args() {
        if arg == "-v" || arg == "--version" {
            println!("disp-center v{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
    }

    // Set up winit backend with app_id for Hyprland matching, no CSD, femtovg renderer
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            attrs
                .with_name("disp-center", "disp-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(680.0_f64, 520.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let display_backend: Box<dyn DisplayBackend> = if use_demo {
        eprintln!("Running in demo mode with mock monitors");
        Box::new(demo::DemoBackend::new())
    } else {
        match backend::detect_backend() {
            Ok(b) => b,
            Err(e) => {
                eprintln!("Error: {e}");
                eprintln!("Tip: run with --demo to test the UI with mock monitors");
                std::process::exit(1);
            }
        }
    };

    let state = Rc::new(RefCell::new(AppState::new(display_backend)));

    if let Err(e) = state.borrow_mut().load_monitors() {
        eprintln!("Failed to query monitors: {e}");
        std::process::exit(1);
    }

    let ui = App::new()?;
    apply_theme(&ui);
    push_state_to_ui(&ui, &state.borrow());
    ui.set_status_text(slint::SharedString::from(format!(
        "Backend: {} | {} monitor(s) detected",
        state.borrow().backend.name(),
        state.borrow().monitors.len()
    )));

    // -- Close --
    ui.on_close(|| { std::process::exit(0); });

    // -- Window drag (manual position tracking, works reliably on X11) --
    {
        let ui_weak = ui.as_weak();
        ui.on_move_window(move |dx, dy| {
            if let Some(ui) = ui_weak.upgrade() {
                use i_slint_backend_winit::WinitWindowAccessor;
                ui.window().with_winit_window(|winit_win: &i_slint_backend_winit::winit::window::Window| {
                    if let Ok(pos) = winit_win.outer_position() {
                        let new_x = pos.x + dx as i32;
                        let new_y = pos.y + dy as i32;
                        winit_win.set_outer_position(
                            i_slint_backend_winit::winit::dpi::PhysicalPosition::new(new_x, new_y)
                        );
                    }
                });
            }
        });
    }

    // -- Select monitor --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_select_monitor(move |idx| {
            let ui = ui_handle.unwrap();
            let st = state.borrow();
            if let Some(m) = st.monitors.get(idx as usize) {
                let modes: Vec<slint::SharedString> = m
                    .available_modes
                    .iter()
                    .map(|mode| slint::SharedString::from(mode.label()))
                    .collect();
                ui.set_selected_modes(slint::ModelRc::new(slint::VecModel::from(modes)));

                let mode_idx = m
                    .available_modes
                    .iter()
                    .position(|mode| {
                        mode.width == m.width
                            && mode.height == m.height
                            && (mode.refresh_rate - m.refresh_rate).abs() < 1.0
                    })
                    .unwrap_or(0);
                ui.set_selected_mode_index(mode_idx as i32);
                ui.set_selected_scale(m.scale as f32);
            }
        });
    }

    // -- Drag finished --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_drag_finished(move |idx, canvas_x, canvas_y| {
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
            push_state_to_ui(&ui, &st);
        });
    }

    // -- Change resolution --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_change_resolution(move |mon_idx, mode_idx| {
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
            push_state_to_ui(&ui, &st);
        });
    }

    // -- Change scale --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_change_scale(move |mon_idx, scale| {
            let mut st = state.borrow_mut();
            let mi = mon_idx as usize;
            if mi < st.monitors.len() {
                st.monitors[mi].scale = scale as f64;
                st.recalc_canvas();
            }
            let ui = ui_handle.unwrap();
            push_state_to_ui(&ui, &st);
        });
    }

    // -- Set primary --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_set_primary(move |mon_idx| {
            let mut st = state.borrow_mut();
            let mi = mon_idx as usize;
            if mi < st.monitors.len() {
                st.primary = st.monitors[mi].name.clone();
                let name = st.primary.clone();
                let _ = st.backend.set_primary(&name);
            }
            let ui = ui_handle.unwrap();
            push_state_to_ui(&ui, &st);
            ui.set_status_text(slint::SharedString::from("Primary monitor updated"));
        });
    }

    // -- Apply --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_apply_changes(move || {
            let mut st = state.borrow_mut();
            let configs = st.configs_from_current();
            let ui = ui_handle.unwrap();

            match st.backend.apply(&configs) {
                Ok(()) => {
                    match st.backend.persist(&configs) {
                        Ok(path) => {
                            ui.set_status_text(slint::SharedString::from(format!(
                                "Applied and saved to {path}"
                            )));
                        }
                        Err(e) => {
                            ui.set_status_text(slint::SharedString::from(format!(
                                "Applied live but failed to save: {e}"
                            )));
                        }
                    }
                    st.original = st.monitors.clone();
                }
                Err(e) => {
                    ui.set_status_text(slint::SharedString::from(format!("Apply failed: {e}")));
                }
            }
            push_state_to_ui(&ui, &st);
        });
    }

    // -- Revert --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_revert_changes(move || {
            let mut st = state.borrow_mut();
            st.monitors = st.original.clone();
            st.recalc_canvas();
            let ui = ui_handle.unwrap();
            push_state_to_ui(&ui, &st);
            ui.set_status_text(slint::SharedString::from("Reverted to original layout"));
            ui.set_selected_index(-1);
        });
    }

    // -- Refresh --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_refresh_monitors(move || {
            let mut st = state.borrow_mut();
            let ui = ui_handle.unwrap();
            match st.load_monitors() {
                Ok(()) => {
                    push_state_to_ui(&ui, &st);
                    ui.set_status_text(slint::SharedString::from(format!(
                        "{} monitor(s) detected", st.monitors.len()
                    )));
                    ui.set_selected_index(-1);
                }
                Err(e) => {
                    ui.set_status_text(slint::SharedString::from(format!("Refresh failed: {e}")));
                }
            }
        });
    }

    // -- Identify --
    {
        let state = state.clone();
        let ui_handle = ui.as_weak();
        ui.on_identify_monitors(move || {
            let st = state.borrow();
            let ui = ui_handle.unwrap();
            match st.backend.identify(&st.monitors) {
                Ok(()) => {
                    ui.set_status_text(slint::SharedString::from("Identifying monitors..."));
                }
                Err(e) => {
                    ui.set_status_text(slint::SharedString::from(format!("Identify failed: {e}")));
                }
            }
        });
    }

    // -- Theme polling timer (auto-update when EWW theme changes) --
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
