use crate::display::monitor::{Monitor, MonitorConfig};

/// Trait for compositor-specific display management.
pub trait DisplayBackend {
    fn query_monitors(&self) -> Result<Vec<Monitor>, String>;
    fn apply(&self, configs: &[MonitorConfig]) -> Result<(), String>;
    fn persist(&self, configs: &[MonitorConfig]) -> Result<String, String>;
    fn set_primary(&self, monitor_name: &str) -> Result<(), String>;
    fn identify(&self, monitors: &[Monitor]) -> Result<(), String>;
    fn name(&self) -> &'static str;
}

/// Detect the running compositor and return the appropriate backend.
pub fn detect_backend() -> Result<Box<dyn DisplayBackend>, String> {
    if std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_ok() {
        return Ok(Box::new(crate::display::hyprland::HyprlandBackend::new()));
    }

    if std::env::var("WAYLAND_DISPLAY").is_ok() {
        return Err("Wayland compositor detected but not Hyprland. Only Hyprland is currently supported.".into());
    }

    if std::env::var("DISPLAY").is_ok() {
        return Err("X11 detected. Only Hyprland is currently supported. X11/xrandr backend coming soon.".into());
    }

    Err("No display server detected.".into())
}
