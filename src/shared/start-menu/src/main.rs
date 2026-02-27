mod theme;

use i_slint_backend_winit::WinitWindowAccessor;
use slint::{Image, Model, ModelRc, SharedString, VecModel};
use std::cell::RefCell;
use std::collections::HashMap;
use std::path::Path;
use std::rc::Rc;

slint::include_modules!();

// ── App index entry (parsed from ~/.cache/smplos/app_index) ──

#[derive(Clone, Debug)]
struct AppEntry {
    name: String,
    exec: String,
    category: String,
    #[allow(dead_code)]
    icon: String,
}

// ── Category definitions ──

const CATEGORIES: &[(&str, &str, &str)] = &[
    ("internet",    "Internet", "\u{f0ac3}"),  // 󰫃 globe
    ("multimedia",  "Media",    "\u{f038a}"),  // 󰎊 music
    ("office",      "Office",   "\u{f0219}"),  // 󰈙 document
    ("development", "Dev",      "\u{f0169}"),  // 󰅩 code
    ("graphics",    "Graphics", "\u{f03e8}"),  // 󰏨 palette
    ("apps",        "Apps",     "\u{f00bb}"),  // 󰂻 grid
    ("settings",    "Settings", "\u{f0493}"),  // 󰒓 gear
];

fn category_label(key: &str) -> &str {
    CATEGORIES
        .iter()
        .find(|(k, _, _)| *k == key)
        .map(|(_, v, _)| *v)
        .unwrap_or(key)
}

// ── Load the app index cache ──

fn load_apps() -> Vec<AppEntry> {
    let home = std::env::var("HOME").unwrap_or_default();
    let path = format!("{}/.cache/smplos/app_index", home);

    let content = std::fs::read_to_string(&path).unwrap_or_else(|_| {
        // Try rebuilding the cache if it doesn't exist
        let _ = std::process::Command::new("rebuild-app-cache").status();
        std::fs::read_to_string(&path).unwrap_or_default()
    });

    let mut apps = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let parts: Vec<&str> = line.splitn(4, ';').collect();
        if parts.len() < 3 {
            continue;
        }

        let name = parts[0].to_string();
        let exec = parts[1].to_string();
        let category = parts[2].to_string();
        let icon = parts.get(3).unwrap_or(&"").to_string();

        // Deduplicate by lowercase name
        if !seen.insert(name.to_lowercase()) {
            continue;
        }

        apps.push(AppEntry {
            name,
            exec,
            category,
            icon,
        });
    }

    apps
}

// ── Pinned apps persistence ──

fn load_pinned() -> Vec<String> {
    let home = std::env::var("HOME").unwrap_or_default();
    let path = format!("{}/.config/smplos/pinned-apps.txt", home);
    std::fs::read_to_string(&path)
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| l.trim().to_string())
        .collect()
}

fn save_pinned(pinned: &[String]) {
    let home = std::env::var("HOME").unwrap_or_default();
    let dir = format!("{}/.config/smplos", home);
    let _ = std::fs::create_dir_all(&dir);
    let path = format!("{}/pinned-apps.txt", dir);
    let _ = std::fs::write(&path, pinned.join("\n") + "\n");
}

// ── Icon resolution ──

/// Search directories for icon name, preferring SVG then PNG at useful sizes.
const ICON_SEARCH_DIRS: &[&str] = &[
    "/usr/share/icons/hicolor/scalable/apps",
    "/usr/share/icons/hicolor/48x48/apps",
    "/usr/share/icons/hicolor/64x64/apps",
    "/usr/share/icons/hicolor/128x128/apps",
    "/usr/share/icons/hicolor/32x32/apps",
    // Flatpak system-wide exports (symlinks to per-app icons)
    "/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps",
    "/var/lib/flatpak/exports/share/icons/hicolor/128x128/apps",
    "/var/lib/flatpak/exports/share/icons/hicolor/64x64/apps",
    "/var/lib/flatpak/exports/share/icons/hicolor/48x48/apps",
    "/usr/share/pixmaps",
];

fn resolve_icon_path(icon_name: &str) -> Option<String> {
    if icon_name.is_empty() {
        return None;
    }
    // If it's already an absolute path, use it directly
    if icon_name.starts_with('/') {
        if Path::new(icon_name).exists() {
            return Some(icon_name.to_string());
        }
        return None;
    }
    // Static dirs (system icons + system Flatpak)
    for dir in ICON_SEARCH_DIRS {
        for ext in &["svg", "png"] {
            let path = format!("{}/{}.{}", dir, icon_name, ext);
            if Path::new(&path).exists() {
                return Some(path);
            }
        }
    }
    // User-level icons (webapps, user-installed themes, Flatpak exports)
    if let Ok(home) = std::env::var("HOME") {
        let user_dirs = [
            // User icon theme (webapps save here via webapp-center)
            format!("{}/.local/share/icons/hicolor/scalable/apps", home),
            format!("{}/.local/share/icons/hicolor/256x256/apps", home),
            format!("{}/.local/share/icons/hicolor/128x128/apps", home),
            format!("{}/.local/share/icons/hicolor/64x64/apps", home),
            format!("{}/.local/share/icons/hicolor/48x48/apps", home),
            // User-level Flatpak exports
            format!("{}/.local/share/flatpak/exports/share/icons/hicolor/scalable/apps", home),
            format!("{}/.local/share/flatpak/exports/share/icons/hicolor/128x128/apps", home),
            format!("{}/.local/share/flatpak/exports/share/icons/hicolor/64x64/apps", home),
            format!("{}/.local/share/flatpak/exports/share/icons/hicolor/48x48/apps", home),
        ];
        for dir in &user_dirs {
            for ext in &["svg", "png"] {
                let path = format!("{}/{}.{}", dir, icon_name, ext);
                if Path::new(&path).exists() {
                    return Some(path);
                }
            }
        }
    }
    None
}

/// Pre-load all app icons into a cache keyed by icon name.
fn build_icon_cache(apps: &[AppEntry]) -> HashMap<String, Image> {
    let mut cache = HashMap::new();
    let mut found = 0;
    let mut missing: Vec<String> = Vec::new();
    for app in apps {
        if app.icon.is_empty() || cache.contains_key(&app.icon) {
            continue;
        }
        if let Some(path) = resolve_icon_path(&app.icon) {
            if let Ok(img) = Image::load_from_path(Path::new(&path)) {
                cache.insert(app.icon.clone(), img);
                found += 1;
            } else {
                eprintln!("[icon] failed to load: {} -> {}", app.icon, path);
            }
        } else {
            missing.push(app.icon.clone());
        }
    }
    eprintln!("[icon] loaded {}, missing {}: {:?}", found, missing.len(),
        missing.iter().take(10).collect::<Vec<_>>());
    cache
}

// ── Filter: global search or category browse ──

fn filter_apps(all: &[AppEntry], category_key: &str, query: &str) -> Vec<AppEntry> {
    let q = query.trim().to_lowercase();

    all.iter()
        .filter(|app| {
            // Non-empty query: search globally across all categories
            if !q.is_empty() {
                let hay = app.name.to_lowercase();
                return hay.contains(&q);
            }

            // Empty query: filter by selected category
            app.category == category_key
        })
        .cloned()
        .collect()
}

// ── Convert to Slint model item ──

fn to_ui_item(app: &AppEntry, icon_cache: &HashMap<String, Image>, pinned: &[String]) -> AppItem {
    let initial = app
        .name
        .chars()
        .next()
        .map(|c| c.to_uppercase().to_string())
        .unwrap_or_default();

    let (icon_image, has_icon) = match icon_cache.get(&app.icon) {
        Some(img) => (img.clone(), true),
        None => (Image::default(), false),
    };

    let is_web_app = app.exec.contains("launch-webapp");

    let source = if is_web_app {
        "Web App"
    } else if app.exec.contains("flatpak run") || app.exec.contains("/flatpak/") {
        "Flatpak"
    } else if app.exec.ends_with(".AppImage") || app.exec.ends_with(".appimage") {
        "AppImage"
    } else if app.exec.starts_with("smplos-settings") {
        ""
    } else {
        "AUR"
    };

    AppItem {
        name: SharedString::from(&app.name),
        exec: SharedString::from(&app.exec),
        category: SharedString::from(category_label(&app.category)),
        category_key: SharedString::from(&app.category),
        initial: SharedString::from(&initial),
        icon_image,
        has_icon,
        is_web_app,
        source: SharedString::from(source),
        is_pinned: pinned.contains(&app.exec),
    }
}

// ── Update the visible app list ──

fn update_view(
    ui: &MainWindow,
    all_apps: &[AppEntry],
    model: &Rc<VecModel<AppItem>>,
    icon_cache: &HashMap<String, Image>,
    category_key: &str,
    query: &str,
    pinned: &[String],
) {
    let filtered = filter_apps(all_apps, category_key, query);
    model.set_vec(filtered.iter().map(|a| to_ui_item(a, icon_cache, pinned)).collect::<Vec<_>>());
    ui.set_apps(ModelRc::from(model.clone()));
    ui.set_app_count(model.row_count() as i32);
    ui.set_selected_app(if model.row_count() > 0 { 0 } else { -1 });
    ui.set_is_searching(!query.trim().is_empty());
}

fn update_pinned_model(
    ui: &MainWindow,
    all_apps: &[AppEntry],
    pinned_model: &Rc<VecModel<AppItem>>,
    icon_cache: &HashMap<String, Image>,
    pinned: &[String],
) {
    let items: Vec<AppItem> = pinned
        .iter()
        .filter_map(|exec| all_apps.iter().find(|a| &a.exec == exec))
        .map(|a| to_ui_item(a, icon_cache, pinned))
        .collect();
    let count = items.len() as i32;
    pinned_model.set_vec(items);
    ui.set_pinned_apps(ModelRc::from(pinned_model.clone()));
    ui.set_pinned_count(count);
}

// ── Theme ──

fn apply_theme(ui: &MainWindow) {
    let palette = theme::load_theme_from_eww_scss(&format!(
        "{}/.config/eww/theme-colors.scss",
        std::env::var("HOME").unwrap_or_default()
    ));

    let theme = Theme::get(ui);
    theme.set_bg(palette.bg);
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
    theme.set_border_radius(palette.border_radius);
}

// ── Entry point ──

fn main() -> Result<(), slint::PlatformError> {
    for arg in std::env::args() {
        if arg == "-v" || arg == "--version" {
            println!("start-menu v{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
    }

    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("renderer-software")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("start-menu", "start-menu")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(520.0_f64, 580.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    let ui = MainWindow::new()?;
    apply_theme(&ui);

    // ── Load all apps from cache ──
    let all_apps = Rc::new(load_apps());
    let icon_cache = Rc::new(build_icon_cache(&all_apps));
    let model = Rc::new(VecModel::<AppItem>::default());
    let pinned = Rc::new(RefCell::new(load_pinned()));
    let pinned_model = Rc::new(VecModel::<AppItem>::default());

    // ── Build category sidebar ──
    let cat_model = Rc::new(VecModel::<CategoryItem>::default());
    {
        let mut items = Vec::new();
        for (key, display, icon) in CATEGORIES {
            let count = all_apps.iter().filter(|a| a.category == *key).count();
            // Skip empty categories (but always keep settings)
            if count == 0 && *key != "settings" {
                continue;
            }
            items.push(CategoryItem {
                key: SharedString::from(*key),
                label: SharedString::from(*display),
                icon: SharedString::from(*icon),
            });
        }
        cat_model.set_vec(items);
    }
    ui.set_categories(ModelRc::from(cat_model.clone()));
    ui.set_category_count(cat_model.row_count() as i32);

    // ── Initial view: empty (no category selected, no search) ──
    ui.set_active_category(-1);
    ui.set_app_count(0);

    // ── Load pinned apps ──
    update_pinned_model(&ui, &all_apps, &pinned_model, &icon_cache, &pinned.borrow());

    // ── Filter callback (search text or category changed) ──
    {
        let ui_weak = ui.as_weak();
        let all_apps = all_apps.clone();
        let icon_cache = icon_cache.clone();
        let model = model.clone();
        let cat_model = cat_model.clone();
        let pinned = pinned.clone();

        ui.on_filter_changed(move || {
            let Some(ui) = ui_weak.upgrade() else {
                return;
            };
            ui.set_show_context_menu(false);
            let search = ui.get_search_text().to_string();
            let cat_idx = ui.get_active_category() as usize;

            // No category selected and no search => show nothing
            if search.is_empty() && cat_idx >= cat_model.row_count() {
                model.set_vec(Vec::new());
                ui.set_apps(ModelRc::from(model.clone()));
                ui.set_app_count(0);
                ui.set_selected_app(-1);
                ui.set_is_searching(false);
                return;
            }

            let cat_key = cat_model
                .row_data(cat_idx)
                .map(|c| c.key.to_string())
                .unwrap_or_else(|| "all".to_string());

            update_view(&ui, &all_apps, &model, &icon_cache, &cat_key, &search, &pinned.borrow());
        });
    }

    // ── Launch app ──
    {
        let model = model.clone();
        ui.on_launch_app(move |index| {
            let idx = index as usize;
            if let Some(item) = model.row_data(idx) {
                let exec = item.exec.to_string();
                let _ = std::process::Command::new("sh")
                    .arg("-c")
                    .arg(&exec)
                    .spawn();
                std::process::exit(0);
            }
        });
    }

    // ── Launch pinned app ──
    {
        let pinned_model = pinned_model.clone();
        ui.on_launch_pinned(move |index| {
            let idx = index as usize;
            if let Some(item) = pinned_model.row_data(idx) {
                let exec = item.exec.to_string();
                let _ = std::process::Command::new("sh")
                    .arg("-c")
                    .arg(&exec)
                    .spawn();
                std::process::exit(0);
            }
        });
    }

    // ── Toggle pin ──
    {
        let ui_weak = ui.as_weak();
        let all_apps = all_apps.clone();
        let icon_cache = icon_cache.clone();
        let model = model.clone();
        let pinned = pinned.clone();
        let pinned_model = pinned_model.clone();
        let cat_model = cat_model.clone();

        ui.on_toggle_pin(move |exec| {
            let Some(ui) = ui_weak.upgrade() else { return; };
            let exec = exec.to_string();
            {
                let mut p = pinned.borrow_mut();
                if let Some(pos) = p.iter().position(|e| *e == exec) {
                    p.remove(pos);
                } else {
                    p.push(exec);
                }
                save_pinned(&p);
            }
            let p = pinned.borrow();
            update_pinned_model(&ui, &all_apps, &pinned_model, &icon_cache, &p);
            // Refresh current view to update is_pinned flags
            let search = ui.get_search_text().to_string();
            let cat_idx = ui.get_active_category() as usize;
            if !search.is_empty() || cat_idx < cat_model.row_count() {
                let cat_key = cat_model
                    .row_data(cat_idx)
                    .map(|c| c.key.to_string())
                    .unwrap_or_else(|| "all".to_string());
                update_view(&ui, &all_apps, &model, &icon_cache, &cat_key, &search, &p);
            }
        });
    }

    // ── Close ──
    ui.on_close(|| {
        std::process::exit(0);
    });

    // ── Open Web App Center ──
    ui.on_open_webapp_center(|| {
        let _ = std::process::Command::new("sh")
            .arg("-c")
            .arg("webapp-center")
            .spawn();
        std::process::exit(0);
    });

    // ── Power actions ──
    ui.on_power_action(|action| {
        let cmd = match action.as_str() {
            "lock" => "lock-screen",
            "restart" => "systemctl reboot",
            "shutdown" => "systemctl poweroff",
            _ => return,
        };
        let _ = std::process::Command::new("sh")
            .arg("-c")
            .arg(cmd)
            .spawn();
        std::process::exit(0);
    });

    // ── Window drag ──
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

    ui.set_version(format!("v{}", env!("CARGO_PKG_VERSION")).into());
    ui.invoke_focus_search();
    ui.run()
}
