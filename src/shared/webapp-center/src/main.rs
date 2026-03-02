mod backend;
mod theme;

use backend::{delete_all_webapps, delete_webapp, list_vpn_interfaces, save_webapp, scan_webapps, WebApp};
use i_slint_backend_winit::WinitWindowAccessor;
use slint::{Model, ModelRc, SharedString, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

fn to_ui_item(app: &WebApp) -> WebAppItem {
    WebAppItem {
        name: app.name.clone().into(),
        slug: app.slug.clone().into(),
        url: app.url.clone().into(),
        secure: app.secure,
        vpn_iface: app.vpn_iface.clone().into(),
        vpn_required: app.vpn_required,
        icon: app.icon.clone().into(),
        marked: false,
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
    theme.set_danger(palette.danger);
    theme.set_success(palette.success);
    theme.set_warning(palette.warning);
    theme.set_info(palette.info);
    theme.set_opacity(palette.opacity);
}

fn refresh_model(
    ui: &MainWindow,
    state: &Rc<RefCell<Vec<WebApp>>>,
    model: &Rc<VecModel<WebAppItem>>,
) {
    let apps = scan_webapps();
    *state.borrow_mut() = apps.clone();

    model.set_vec(apps.iter().map(to_ui_item).collect::<Vec<_>>());
    ui.set_webapps(ModelRc::from(model.clone()));

    let len = model.row_count() as i32;
    let current = ui.get_selected_index();
    let clamped = if len == 0 {
        -1
    } else if current < 0 {
        0
    } else if current >= len {
        len - 1
    } else {
        current
    };
    ui.set_selected_index(clamped);

    let title = if len > 0 {
        format!("Web Apps ({})", len)
    } else {
        "Web Apps".to_string()
    };
    ui.set_title_text(title.into());
}

fn refresh_vpn_list(ui: &MainWindow) {
    let ifaces = list_vpn_interfaces();
    let vpn_model: Vec<SharedString> = ifaces.into_iter().map(|s| s.into()).collect();
    ui.set_vpn_interfaces(ModelRc::from(Rc::new(VecModel::from(vpn_model))));
}

fn main() -> Result<(), slint::PlatformError> {
    let mut start_on_create = false;

    for arg in std::env::args() {
        match arg.as_str() {
            "-v" | "--version" => {
                println!("webapp-center v{}", env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            "-c" | "--create" => {
                start_on_create = true;
            }
            _ => {}
        }
    }

    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("webapp-center", "webapp-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(440.0_f64, 520.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    let state: Rc<RefCell<Vec<WebApp>>> = Rc::new(RefCell::new(Vec::new()));
    let model = Rc::new(VecModel::<WebAppItem>::default());

    refresh_model(&ui, &state, &model);
    refresh_vpn_list(&ui);

    // Start on create screen if -c flag passed
    if start_on_create {
        ui.invoke_show_create_screen();
    }

    // Refresh callback
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_refresh(move || {
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
                refresh_vpn_list(&ui);
            }
        });
    }

    // Toggle mark on single item
    {
        let model = model.clone();
        ui.on_toggle_mark(move |index| {
            let idx = index as usize;
            if idx < model.row_count() {
                if let Some(mut item) = model.row_data(idx) {
                    item.marked = !item.marked;
                    model.set_row_data(idx, item);
                }
            }
        });
    }

    // Delete single app
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_delete_app(move |index| {
            let idx = index as usize;
            let borrowed = state.borrow();
            if idx < borrowed.len() {
                let app = borrowed[idx].clone();
                drop(borrowed);
                delete_webapp(&app);
                if let Some(ui) = ui_weak.upgrade() {
                    refresh_model(&ui, &state, &model);
                }
            }
        });
    }

    // Delete all apps
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_delete_all(move || {
            let apps = state.borrow().clone();
            delete_all_webapps(&apps);
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
            }
        });
    }

    // Delete marked items (or selected if none marked)
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_delete_marked(move |selected_index| {
            let borrowed = state.borrow();
            let marked: Vec<usize> = (0..model.row_count())
                .filter(|&i| model.row_data(i).map(|item| item.marked).unwrap_or(false))
                .collect();

            if !marked.is_empty() {
                let to_delete: Vec<WebApp> = marked
                    .iter()
                    .filter_map(|&i| borrowed.get(i).cloned())
                    .collect();
                drop(borrowed);
                for app in &to_delete {
                    delete_webapp(app);
                }
            } else {
                let idx = selected_index as usize;
                if idx < borrowed.len() {
                    let app = borrowed[idx].clone();
                    drop(borrowed);
                    delete_webapp(&app);
                } else {
                    return;
                }
            }
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
            }
        });
    }

    // Save app (create or edit)
    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_save_app(move |name, url, secure, vpn, vpn_required| {
            let editing_index = ui_weak.upgrade().map(|ui| ui.get_form_editing_index()).unwrap_or(-1);

            // If editing, delete old entry first
            if editing_index >= 0 {
                let idx = editing_index as usize;
                let borrowed = state.borrow();
                if idx < borrowed.len() {
                    let old = borrowed[idx].clone();
                    drop(borrowed);
                    delete_webapp(&old);
                }
            }

            match save_webapp(
                name.as_str(),
                url.as_str(),
                secure,
                vpn.as_str(),
                vpn_required,
            ) {
                Ok(_slug) => {
                    if let Some(ui) = ui_weak.upgrade() {
                        refresh_model(&ui, &state, &model);
                        ui.invoke_go_back_to_list();
                    }
                }
                Err(msg) => {
                    if let Some(ui) = ui_weak.upgrade() {
                        ui.set_form_error(msg.into());
                    }
                }
            }
        });
    }

    // Close
    {
        ui.on_close(move || {
            std::process::exit(0);
        });
    }

    // Drag
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

    // Periodic theme refresh
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

    ui.invoke_focus_list();
    ui.run()
}
