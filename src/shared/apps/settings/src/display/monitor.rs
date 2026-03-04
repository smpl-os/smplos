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

/// Edge-snapping: given a monitor being dragged, snap it to the nearest
/// edge of another monitor.
pub fn snap_to_nearest_edge(
    dragged_x: i32,
    dragged_y: i32,
    dragged_w: i32,
    dragged_h: i32,
    others: &[(i32, i32, i32, i32)],
    threshold: i32,
) -> (i32, i32) {
    let mut best_x = dragged_x;
    let mut best_y = dragged_y;
    let mut best_dist = i32::MAX;

    for &(ox, oy, ow, oh) in others {
        let snap_candidates: [(i32, i32); 8] = [
            (ox - dragged_w, dragged_y),
            (ox + ow, dragged_y),
            (dragged_x, oy - dragged_h),
            (dragged_x, oy + oh),
            (dragged_x, oy),
            (dragged_x, oy + oh - dragged_h),
            (ox, dragged_y),
            (ox + ow - dragged_w, dragged_y),
        ];

        for (cx, cy) in snap_candidates {
            let dx = (cx - dragged_x).abs();
            let dy = (cy - dragged_y).abs();
            let dist = dx + dy;
            if dist < best_dist && dist < threshold {
                best_dist = dist;
                best_x = cx;
                best_y = cy;
            }
        }
    }

    (best_x, best_y)
}

/// Calculate a uniform scale factor so all monitors fit inside the given canvas dimensions.
pub fn canvas_scale_factor(monitors: &[Monitor], canvas_w: f64, canvas_h: f64) -> f64 {
    if monitors.is_empty() {
        return 1.0;
    }

    let mut min_x = i32::MAX;
    let mut min_y = i32::MAX;
    let mut max_x = i32::MIN;
    let mut max_y = i32::MIN;

    for m in monitors {
        min_x = min_x.min(m.x);
        min_y = min_y.min(m.y);
        max_x = max_x.max(m.x + m.width);
        max_y = max_y.max(m.y + m.height);
    }

    let total_w = (max_x - min_x) as f64;
    let total_h = (max_y - min_y) as f64;

    if total_w <= 0.0 || total_h <= 0.0 {
        return 1.0;
    }

    let margin = 40.0;
    let scale_x = (canvas_w - margin * 2.0) / total_w;
    let scale_y = (canvas_h - margin * 2.0) / total_h;

    scale_x.min(scale_y).min(0.25)
}
