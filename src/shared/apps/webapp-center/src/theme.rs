use slint::Color;
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct ThemePalette {
    pub bg: Color,
    pub fg: Color,
    pub fg_dim: Color,
    pub accent: Color,
    pub bg_light: Color,
    pub bg_lighter: Color,
    pub danger: Color,
    pub success: Color,
    pub warning: Color,
    pub info: Color,
    pub opacity: f32,
}

impl Default for ThemePalette {
    fn default() -> Self {
        Self {
            bg: parse_hex_color("#1e1e2e").unwrap(),
            fg: parse_hex_color("#cdd6f4").unwrap(),
            fg_dim: parse_hex_color("#a6adc8").unwrap(),
            accent: parse_hex_color("#89b4fa").unwrap(),
            bg_light: parse_hex_color("#45475a").unwrap(),
            bg_lighter: parse_hex_color("#585b70").unwrap(),
            danger: parse_hex_color("#f38ba8").unwrap(),
            success: parse_hex_color("#a6e3a1").unwrap(),
            warning: parse_hex_color("#f9e2af").unwrap(),
            info: parse_hex_color("#94e2d5").unwrap(),
            opacity: 0.40,
        }
    }
}

pub fn parse_hex_color(hex: &str) -> Option<Color> {
    let hex = hex.trim().trim_start_matches('#');
    if hex.len() != 6 {
        return None;
    }
    let r = u8::from_str_radix(&hex[0..2], 16).ok()?;
    let g = u8::from_str_radix(&hex[2..4], 16).ok()?;
    let b = u8::from_str_radix(&hex[4..6], 16).ok()?;
    Some(Color::from_argb_u8(255, r, g, b))
}

pub fn load_theme_from_eww_scss(path: &str) -> ThemePalette {
    let mut vars: HashMap<String, String> = HashMap::new();

    if let Ok(content) = std::fs::read_to_string(path) {
        for line in content.lines() {
            let t = line.trim();
            if !t.starts_with("$theme-") {
                continue;
            }
            let Some((name, value)) = t.split_once(':') else {
                continue;
            };
            let key = name.trim().trim_start_matches("$theme-").to_string();
            let raw = value.trim().trim_end_matches(';');
            let value_token = raw.split_whitespace().next().unwrap_or("").trim();
            vars.insert(key, value_token.to_string());
        }
    }

    let mut palette = ThemePalette::default();

    let set_color = |field: &str, out: &mut Color| {
        if let Some(v) = vars.get(field).and_then(|s| parse_hex_color(s)) {
            *out = v;
        }
    };

    set_color("bg", &mut palette.bg);
    set_color("fg", &mut palette.fg);
    set_color("fg-dim", &mut palette.fg_dim);
    set_color("accent", &mut palette.accent);
    set_color("bg-light", &mut palette.bg_light);
    set_color("bg-lighter", &mut palette.bg_lighter);
    set_color("danger", &mut palette.danger);
    set_color("success", &mut palette.success);
    set_color("warning", &mut palette.warning);
    set_color("info", &mut palette.info);

    if let Some(v) = vars.get("popup-opacity") {
        if let Ok(parsed) = v.parse::<f32>() {
            palette.opacity = parsed;
        }
    }

    palette
}
