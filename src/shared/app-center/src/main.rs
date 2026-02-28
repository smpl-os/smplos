mod catalog;
mod installer;
mod sources;
mod theme;

use catalog::{merge_results, AppEntry, Source};
use i_slint_backend_winit::WinitWindowAccessor;
use slint::{Model, ModelRc, SharedString, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

fn to_ui_item(app: &AppEntry) -> AppItem {
    AppItem {
        name: app.name.clone().into(),
        id: app.id.clone().into(),
        version: app.version.clone().into(),
        description: app.description.clone().into(),
        source: SharedString::from(app.source_label()),
        icon_path: app.icon_path.clone().into(),
        homepage: app.homepage.clone().into(),
        votes: app.votes as i32,
        popularity: app.popularity as f32,
        installed: app.installed,
    }
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
    theme.set_red(palette.red);
    theme.set_green(palette.green);
    theme.set_yellow(palette.yellow);
    theme.set_cyan(palette.cyan);
    theme.set_opacity(palette.opacity);
}

/// Perform a search across enabled sources.
fn do_search(query: &str, aur: bool, flatpak: bool, appimage: bool) -> Vec<AppEntry> {
    if query.is_empty() {
        return Vec::new();
    }

    let mut results = Vec::new();

    if aur {
        results.extend(sources::aur::search(query));
    }
    if flatpak {
        results.extend(sources::flathub::search(query));
    }
    if appimage {
        results.extend(sources::appimage::search(query));
    }

    merge_results(results, query)
}

fn update_results(
    ui: &MainWindow,
    state: &Rc<RefCell<Vec<AppEntry>>>,
    model: &Rc<VecModel<AppItem>>,
    results: Vec<AppEntry>,
) {
    *state.borrow_mut() = results.clone();
    model.set_vec(results.iter().map(to_ui_item).collect::<Vec<_>>());
    ui.set_results(ModelRc::from(model.clone()));

    let len = model.row_count() as i32;
    if len > 0 {
        ui.set_selected_index(0);
    } else {
        ui.set_selected_index(-1);
    }

    ui.set_status_text(
        if len > 0 {
            SharedString::from(format!("{} results", len))
        } else {
            SharedString::default()
        },
    );
    ui.set_searching(false);
}

fn main() -> Result<(), slint::PlatformError> {
    for arg in std::env::args() {
        if arg == "-v" || arg == "--version" {
            println!("app-center v{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
    }

    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-software")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("app-center", "app-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(560.0_f64, 620.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    let state: Rc<RefCell<Vec<AppEntry>>> = Rc::new(RefCell::new(Vec::new()));
    let model = Rc::new(VecModel::<AppItem>::default());

    // -- Search callback --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_search(move |query| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let q = query.to_string();

            if q.is_empty() {
                update_results(&ui, &state, &model, Vec::new());
                return;
            }

            ui.set_searching(true);

            let aur = ui.get_filter_aur();
            let flatpak = ui.get_filter_flatpak();
            let appimage = ui.get_filter_appimage();

            // Run search (blocking but fast for AUR; local for cached Flatpak/AppImage)
            let results = do_search(&q, aur, flatpak, appimage);
            update_results(&ui, &state, &model, results);
        });
    }

    // -- Filter changed: re-run current search --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_filter_changed(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            let q = ui.get_search_text().to_string();
            if q.is_empty() {
                return;
            }

            let aur = ui.get_filter_aur();
            let flatpak = ui.get_filter_flatpak();
            let appimage = ui.get_filter_appimage();

            let results = do_search(&q, aur, flatpak, appimage);
            update_results(&ui, &state, &model, results);
        });
    }

    // -- Tab switching --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_switch_tab(move |tab_index| {
            let Some(ui) = ui_weak.upgrade() else { return };

            if tab_index == 1 {
                let recommended = sources::recommended::get_recommended();
                update_results(&ui, &state, &model, recommended);
            } else {
                let q = ui.get_search_text().to_string();
                if q.is_empty() {
                    update_results(&ui, &state, &model, Vec::new());
                } else {
                    let aur = ui.get_filter_aur();
                    let flatpak = ui.get_filter_flatpak();
                    let appimage = ui.get_filter_appimage();
                    let results = do_search(&q, aur, flatpak, appimage);
                    update_results(&ui, &state, &model, results);
                }
            }
        });
    }

    // -- Select app: show detail view --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        ui.on_select_app(move |index| {
            let Some(ui) = ui_weak.upgrade() else { return };
            let idx = index as usize;
            let borrowed = state.borrow();
            if idx >= borrowed.len() {
                return;
            }

            let app = &borrowed[idx];
            ui.set_selected_index(index);
            ui.set_install_status(SharedString::default());
            ui.set_console_output(SharedString::default());
            ui.set_process_finished(false);
            ui.set_process_success(false);

            // For Flatpak apps, fetch richer details
            if app.source == Source::Flatpak && !app.id.is_empty() {
                if let Some(detail) = sources::flathub::get_details(&app.id) {
                    ui.set_detail_description(SharedString::from(&detail.description));
                } else {
                    ui.set_detail_description(SharedString::default());
                }
            } else {
                ui.set_detail_description(SharedString::default());
            }

            ui.set_show_detail(true);
        });
    }

    // -- Active process state --
    struct ActiveInstall {
        idx: usize,
        is_install: bool,
        process: installer::StreamingProcess,
    }
    let active_install: Rc<RefCell<Option<ActiveInstall>>> = Rc::new(RefCell::new(None));

    // Helper: handle immediate (non-streaming) results
    fn handle_immediate(
        ui: &MainWindow,
        state: &Rc<RefCell<Vec<AppEntry>>>,
        model: &Rc<VecModel<AppItem>>,
        idx: usize,
        is_install: bool,
        result: &installer::ImmediateResult,
    ) {
        ui.set_installing(false);
        ui.set_process_finished(true);
        ui.set_process_success(result.success);
        ui.set_console_output(SharedString::from(&result.message));
        if result.success {
            let new_state = is_install;
            let mut borrowed = state.borrow_mut();
            if let Some(entry) = borrowed.get_mut(idx) {
                entry.installed = new_state;
            }
            drop(borrowed);
            if let Some(mut item) = model.row_data(idx) {
                item.installed = new_state;
                model.set_row_data(idx, item);
            }
        }
    }

    // -- Install app --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        let active = active_install.clone();
        ui.on_install_app(move |index| {
            let Some(ui) = ui_weak.upgrade() else { return };
            if ui.get_installing() { return; }
            let idx = index as usize;
            let borrowed = state.borrow();
            if idx >= borrowed.len() { return; }

            let app = borrowed[idx].clone();
            drop(borrowed);

            ui.set_installing(true);
            ui.set_console_output(SharedString::default());
            ui.set_console_last_line(SharedString::default());
            ui.set_process_finished(false);
            ui.set_process_success(false);

            match installer::spawn_install(&app.source, &app.id) {
                installer::SpawnResult::Streaming(process) => {
                    *active.borrow_mut() = Some(ActiveInstall {
                        idx,
                        is_install: true,
                        process,
                    });
                }
                installer::SpawnResult::Immediate(result) => {
                    handle_immediate(&ui, &state, &model, idx, true, &result);
                }
            }
        });
    }

    // -- Uninstall app --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        let active = active_install.clone();
        ui.on_uninstall_app(move |index| {
            let Some(ui) = ui_weak.upgrade() else { return };
            if ui.get_installing() { return; }
            let idx = index as usize;
            let borrowed = state.borrow();
            if idx >= borrowed.len() { return; }

            let app = borrowed[idx].clone();
            drop(borrowed);

            ui.set_installing(true);
            ui.set_console_output(SharedString::default());
            ui.set_console_last_line(SharedString::default());
            ui.set_process_finished(false);
            ui.set_process_success(false);

            match installer::spawn_uninstall(&app.source, &app.id, &app.name) {
                installer::SpawnResult::Streaming(process) => {
                    *active.borrow_mut() = Some(ActiveInstall {
                        idx,
                        is_install: false,
                        process,
                    });
                }
                installer::SpawnResult::Immediate(result) => {
                    handle_immediate(&ui, &state, &model, idx, false, &result);
                }
            }
        });
    }

    // -- Console input --
    {
        let active = active_install.clone();
        ui.on_send_console_input(move |text| {
            if let Some(ref mut ai) = *active.borrow_mut() {
                ai.process.send_input(&text);
            }
        });
    }

    // -- Cancel install --
    {
        let ui_weak = ui.as_weak();
        let active = active_install.clone();
        ui.on_cancel_install(move || {
            let Some(ui) = ui_weak.upgrade() else { return };
            let mut guard = active.borrow_mut();
            if let Some(ref mut ai) = *guard {
                ai.process.kill();
            }
            *guard = None;
            drop(guard);

            ui.set_installing(false);
            ui.set_process_finished(true);
            ui.set_process_success(false);
            ui.set_console_output(SharedString::from("Cancelled by user"));
            ui.set_console_last_line(SharedString::default());
        });
    }

    // -- Poll active process for output and completion --
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        let active = active_install.clone();
        // Accumulate full output in Rust (not on the UI during install)
        let full_output: Rc<RefCell<String>> = Rc::new(RefCell::new(String::new()));
        let poll_timer = slint::Timer::default();
        poll_timer.start(
            slint::TimerMode::Repeated,
            std::time::Duration::from_millis(50),
            move || {
                let Some(ui) = ui_weak.upgrade() else { return };
                let mut guard = active.borrow_mut();
                let Some(ref mut ai) = *guard else { return };

                // Append new output lines, track last meaningful line
                let new_lines = ai.process.poll_output();
                if !new_lines.is_empty() {
                    let mut buf = full_output.borrow_mut();
                    for line in &new_lines {
                        if !buf.is_empty() {
                            buf.push('\n');
                        }
                        buf.push_str(line);

                        // Update live status with last non-junk line
                        let trimmed = line.trim();
                        if !trimmed.is_empty()
                            && !trimmed.chars().all(|c| c == '#' || c == ' ')
                        {
                            ui.set_console_last_line(SharedString::from(trimmed));
                        }
                    }
                }

                // Check if process finished
                if let Some(success) = ai.process.try_wait() {
                    let idx = ai.idx;
                    let is_install = ai.is_install;
                    drop(guard);

                    ui.set_installing(false);
                    ui.set_process_finished(true);
                    ui.set_process_success(success);

                    // Set full output (shown only on failure in the UI)
                    ui.set_console_output(SharedString::from(
                        full_output.borrow().as_str(),
                    ));
                    full_output.borrow_mut().clear();

                    if success {
                        let new_state = is_install;
                        let mut borrowed = state.borrow_mut();
                        if let Some(entry) = borrowed.get_mut(idx) {
                            entry.installed = new_state;
                        }
                        drop(borrowed);
                        if let Some(mut item) = model.row_data(idx) {
                            item.installed = new_state;
                            model.set_row_data(idx, item);
                        }
                    }

                    *active.borrow_mut() = None;
                }
            },
        );
        std::mem::forget(poll_timer);
    }

    // -- Open homepage --
    {
        let state = state.clone();
        ui.on_open_homepage(move |index| {
            let idx = index as usize;
            let borrowed = state.borrow();
            if let Some(app) = borrowed.get(idx) {
                if !app.homepage.is_empty() {
                    let _ = std::process::Command::new("xdg-open")
                        .arg(&app.homepage)
                        .spawn();
                }
            }
        });
    }

    // -- Refresh catalogs --
    {
        let ui_weak = ui.as_weak();
        ui.on_refresh_catalog(move || {
            if let Some(ui) = ui_weak.upgrade() {
                // Delete cache files to force re-download
                let cache = catalog::cache_dir();
                let _ = std::fs::remove_file(cache.join("appimage-catalog.json"));
                ui.set_status_text("Catalogs cleared - search again to refresh".into());
            }
        });
    }

    // -- Close --
    {
        ui.on_close(move || {
            std::process::exit(0);
        });
    }

    // -- Drag --
    {
        let ui_weak = ui.as_weak();
        ui.on_start_drag(move || {
            if let Some(ui) = ui_weak.upgrade() {
                ui.window().with_winit_window(
                    |winit_win: &i_slint_backend_winit::winit::window::Window| {
                        let _ = winit_win.drag_window();
                    },
                );
            }
        });
    }

    // -- Periodic theme refresh --
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

    ui.invoke_focus_search();
    ui.run()
}
