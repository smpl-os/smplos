mod backend;
mod theme;

use backend::{clear_all_notifications, dismiss_notification, get_notifications, open_notification, Notification};
use i_slint_backend_winit::WinitWindowAccessor;
use slint::{Model, ModelRc, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

fn to_ui_item(n: &Notification) -> NotificationItem {
    NotificationItem {
        id: n.id,
        icon: n.icon.clone().into(),
        summary: n.summary.clone().into(),
        body: n.body.clone().into(),
        date: n.date.clone().into(),
        time: n.time.clone().into(),
    }
}

fn apply_theme(ui: &MainWindow) {
    let palette = theme::load_theme_from_eww_scss(&format!(
        "{}/.config/eww/theme-colors.scss",
        std::env::var("HOME").unwrap_or_default()
    ));

    let theme = Theme::get(ui);
    theme.set_bg(palette.bg.darker(0.05)); // Match EWW's darken($bg, 5%)
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
    state: &Rc<RefCell<Vec<Notification>>>,
    model: &Rc<VecModel<NotificationItem>>,
) {
    let notifications = get_notifications();
    *state.borrow_mut() = notifications.clone();

    model.set_vec(notifications.iter().map(to_ui_item).collect::<Vec<_>>());
    ui.set_notifications(ModelRc::from(model.clone()));

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
        format!("Notifications ({})", len)
    } else {
        "Notifications".to_string()
    };
    ui.set_notif_count_text(title.into());
}

fn main() -> Result<(), slint::PlatformError> {
    for arg in std::env::args() {
        if arg == "-v" || arg == "--version" {
            println!("notif-center v{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
    }

    // Set up backend with app_id, no CSD, and correct size
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            attrs
                .with_name("notif-center", "notif-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(384.0_f64, 520.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    let state: Rc<RefCell<Vec<Notification>>> = Rc::new(RefCell::new(Vec::new()));
    let model = Rc::new(VecModel::<NotificationItem>::default());

    refresh_model(&ui, &state, &model);

    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_refresh(move || {
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
            }
        });
    }

    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_dismiss(move |id| {
            dismiss_notification(id);
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
            }
        });
    }

    {
        let ui_weak = ui.as_weak();
        let state = state.clone();
        let model = model.clone();
        ui.on_clear_all(move || {
            clear_all_notifications();
            if let Some(ui) = ui_weak.upgrade() {
                refresh_model(&ui, &state, &model);
            }
        });
    }

    {
        // Debug callback kept for compatibility with UI wiring.
        ui.on_debug_pointer(|_, _| {});
    }

    {
        let state = state.clone();
        ui.on_activate(move |id| {
            let _ = state
                .borrow()
                .iter()
                .find(|n| n.id == id)
                .map(|n| open_notification(&n.appname, &n.desktop_entry, &n.action));
        });
    }

    {
        ui.on_close(move || {
            std::process::exit(0);
        });
    }

    {
        let ui_weak = ui.as_weak();
        ui.on_start_drag(move || {
            if let Some(ui) = ui_weak.upgrade() {
                ui.window().with_winit_window(|winit_win: &i_slint_backend_winit::winit::window::Window| {
                    let _ = winit_win.drag_window();
                });
            }
        });
    }

    {
        let ui_weak = ui.as_weak();
        let timer = slint::Timer::default();
        timer.start(
            slint::TimerMode::Repeated,
            std::time::Duration::from_secs(2),
            move || {
                if let Some(ui) = ui_weak.upgrade() {
                    apply_theme(&ui);
                    ui.invoke_refresh();
                }
            },
        );
        std::mem::forget(timer);
    }

    ui.invoke_focus_list();
    ui.run()
}
