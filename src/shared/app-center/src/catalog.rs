use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, SystemTime};

/// Which package source an app comes from.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Source {
    Aur,
    Flatpak,
    AppImage,
    Script,
}

impl Source {
    pub fn label(&self) -> &'static str {
        match self {
            Source::Aur => "AUR",
            Source::Flatpak => "Flatpak",
            Source::AppImage => "AppImage",
            Source::Script => "Setup",
        }
    }
}

/// Unified app entry from any source.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AppEntry {
    pub name: String,
    pub id: String,
    pub version: String,
    pub description: String,
    pub source: Source,
    pub icon_url: String,
    pub icon_path: String,
    pub homepage: String,
    pub votes: i64,
    pub popularity: f64,
    pub installed: bool,
}

impl AppEntry {
    pub fn source_label(&self) -> &'static str {
        self.source.label()
    }
}

/// Returns the cache directory, creating it if needed.
pub fn cache_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let dir = PathBuf::from(home)
        .join(".cache")
        .join("smplos")
        .join("app-center");
    let _ = fs::create_dir_all(&dir);
    dir
}

/// Checks if a cached file is fresh (younger than max_age).
pub fn cache_is_fresh(path: &PathBuf, max_age: Duration) -> bool {
    if let Ok(meta) = fs::metadata(path) {
        if let Ok(modified) = meta.modified() {
            if let Ok(elapsed) = SystemTime::now().duration_since(modified) {
                return elapsed < max_age;
            }
        }
    }
    false
}

/// Read cached JSON, returning None if file missing or parse fails.
pub fn read_cache<T: for<'de> Deserialize<'de>>(path: &PathBuf) -> Option<T> {
    let data = fs::read_to_string(path).ok()?;
    serde_json::from_str(&data).ok()
}

/// Write data as JSON to cache file.
pub fn write_cache<T: Serialize>(path: &PathBuf, data: &T) {
    if let Ok(json) = serde_json::to_string(data) {
        let _ = fs::write(path, json);
    }
}

/// Merge results from multiple sources, keeping all entries.
/// Results are sorted: exact name matches first, then by popularity/votes.
pub fn merge_results(mut results: Vec<AppEntry>, query: &str) -> Vec<AppEntry> {
    let q = query.to_lowercase();
    results.sort_by(|a, b| {
        let a_exact = a.name.to_lowercase() == q;
        let b_exact = b.name.to_lowercase() == q;
        if a_exact != b_exact {
            return b_exact.cmp(&a_exact);
        }
        // Then by popularity descending
        b.popularity
            .partial_cmp(&a.popularity)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    results
}

/// Check if a package is installed via pacman.
pub fn is_pacman_installed(name: &str) -> bool {
    std::process::Command::new("pacman")
        .args(["-Q", name])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Check if a Flatpak app is installed.
pub fn is_flatpak_installed(app_id: &str) -> bool {
    std::process::Command::new("flatpak")
        .args(["info", app_id])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Check if an AppImage exists in common locations.
pub fn is_appimage_installed(name: &str) -> bool {
    let home = std::env::var("HOME").unwrap_or_default();
    let locations = [
        format!("/opt/appimages/{}.AppImage", name),
        format!("{}/.local/bin/{}.AppImage", home, name),
        format!("/usr/local/bin/{}.AppImage", home),
    ];
    locations.iter().any(|p| std::path::Path::new(p).exists())
}

/// Check if a script-based app is installed by running `<script_id> check`.
pub fn is_script_installed(script_id: &str) -> bool {
    std::process::Command::new(script_id)
        .arg("check")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Strip HTML tags and collapse whitespace.
pub fn strip_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_tag = false;
    for ch in s.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => {
                in_tag = false;
                out.push(' ');
            }
            '\n' => out.push(' '),
            _ if !in_tag => out.push(ch),
            _ => {}
        }
    }
    let mut result = String::new();
    let mut prev_space = false;
    for ch in out.trim().chars() {
        if ch == ' ' {
            if !prev_space {
                result.push(' ');
            }
            prev_space = true;
        } else {
            result.push(ch);
            prev_space = false;
        }
    }
    result
}
