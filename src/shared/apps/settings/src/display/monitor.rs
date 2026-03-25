use serde::Deserialize;

/// A single available display mode (resolution + refresh rate).
#[derive(Debug, Clone, Deserialize)]
pub struct MonitorMode {
    pub width: i32,
    pub height: i32,
    #[serde(rename = "refreshRate")]
    pub refresh_rate: f64,
}

impl MonitorMode {
    pub fn label(&self) -> String {
        format!("{}x{}@{:.0}Hz", self.width, self.height, self.refresh_rate)
    }
}

/// Represents one physical display as reported by the compositor.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct Monitor {
    pub id: i32,
    pub name: String,
    pub description: String,
    pub width: i32,
    pub height: i32,
    pub refresh_rate: f64,
    pub x: i32,
    pub y: i32,
    pub scale: f64,
    pub transform: i32,
    pub enabled: bool,
    pub dpms: bool,
    pub focused: bool,
    pub available_modes: Vec<MonitorMode>,
}

/// Configuration to apply to a single monitor.
#[derive(Debug, Clone)]
pub struct MonitorConfig {
    pub name: String,
    pub width: i32,
    pub height: i32,
    pub refresh_rate: f64,
    pub x: i32,
    pub y: i32,
    pub scale: f64,
    pub enabled: bool,
}

impl MonitorConfig {
    pub fn to_hyprland_line(&self) -> String {
        if !self.enabled {
            return format!("monitor = {}, disable", self.name);
        }
        format!(
            "monitor = {}, {}x{}@{:.2}, {}x{}, {:.2}",
            self.name, self.width, self.height, self.refresh_rate, self.x, self.y, self.scale,
        )
    }
}

/// Calculate a uniform scale factor so all monitors fit inside the given canvas dimensions.
pub fn canvas_scale_factor(monitors: &[Monitor], canvas_w: f64, canvas_h: f64) -> f64 {
    if monitors.is_empty() {
        return 1.0;
    }

    let mut min_x = f64::MAX;
    let mut min_y = f64::MAX;
    let mut max_x = f64::MIN;
    let mut max_y = f64::MIN;

    for m in monitors {
        // Positions are logical pixels; width/height are physical — divide by scale.
        let logical_w = m.width as f64 / m.scale;
        let logical_h = m.height as f64 / m.scale;
        min_x = min_x.min(m.x as f64);
        min_y = min_y.min(m.y as f64);
        max_x = max_x.max(m.x as f64 + logical_w);
        max_y = max_y.max(m.y as f64 + logical_h);
    }

    let total_w = max_x - min_x;
    let total_h = max_y - min_y;

    if total_w <= 0.0 || total_h <= 0.0 {
        return 1.0;
    }

    let margin = 40.0;
    let scale_x = (canvas_w - margin * 2.0) / total_w;
    let scale_y = (canvas_h - margin * 2.0) / total_h;

    scale_x.min(scale_y).min(0.25)
}
