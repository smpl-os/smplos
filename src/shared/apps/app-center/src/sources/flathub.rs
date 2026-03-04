use crate::catalog::{is_flatpak_installed, strip_html, AppEntry, Source};
use serde::Deserialize;
use std::time::Duration;

/// A hit from the Flathub POST /search API.
#[derive(Deserialize)]
struct SearchHit {
    app_id: Option<String>,
    name: Option<String>,
    summary: Option<String>,
    icon: Option<String>,
    installs_last_month: Option<u64>,
}

/// Top-level response from POST /search.
#[derive(Deserialize)]
struct SearchResponse {
    hits: Vec<SearchHit>,
}

/// Flathub appstream detail (full per-app data).
#[derive(Deserialize)]
#[allow(dead_code)]
struct FlathubDetail {
    id: String,
    name: Option<String>,
    summary: Option<String>,
    description: Option<String>,
    icon: Option<String>,
    urls: Option<FlathubUrls>,
    releases: Option<Vec<FlathubRelease>>,
}

#[derive(Deserialize)]
struct FlathubUrls {
    homepage: Option<String>,
}

#[derive(Deserialize)]
struct FlathubRelease {
    version: Option<String>,
}

/// Search the full Flathub catalog via the server-side search API.
pub fn search(query: &str) -> Vec<AppEntry> {
    if query.len() < 2 {
        return Vec::new();
    }

    let body = format!(r#"{{"query":"{}"}}"#, query.replace('"', r#"\""#));

    let resp = match ureq::post("https://flathub.org/api/v2/search")
        .set("Content-Type", "application/json")
        .timeout(Duration::from_secs(8))
        .send_string(&body)
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("Flathub search failed: {}", e);
            return Vec::new();
        }
    };

    let sr: SearchResponse = match resp.into_json() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("Flathub search parse error: {}", e);
            return Vec::new();
        }
    };

    sr.hits
        .into_iter()
        .filter(|h| h.app_id.is_some())
        .take(50)
        .map(|hit| {
            let app_id = hit.app_id.unwrap_or_default();
            let installed = is_flatpak_installed(&app_id);
            AppEntry {
                name: hit.name.unwrap_or_default(),
                id: app_id,
                version: String::new(),
                description: hit.summary.unwrap_or_default(),
                source: Source::Flatpak,
                icon_url: hit.icon.unwrap_or_default(),
                icon_path: String::new(),
                homepage: String::new(),
                votes: 0,
                popularity: hit.installs_last_month.unwrap_or(0) as f64,
                installed,
            }
        })
        .collect()
}

/// Get details for a specific Flatpak app.
pub fn get_details(app_id: &str) -> Option<AppEntry> {
    let url = format!("https://flathub.org/api/v2/appstream/{}", app_id);
    let resp = ureq::get(&url)
        .timeout(Duration::from_secs(8))
        .call()
        .ok()?;

    let detail: FlathubDetail = resp.into_json().ok()?;
    let installed = is_flatpak_installed(&detail.id);
    let version = detail
        .releases
        .as_ref()
        .and_then(|r| r.first())
        .and_then(|r| r.version.clone())
        .unwrap_or_default();

    let desc_raw = detail.description.unwrap_or_default();
    let description = strip_html(&desc_raw);

    Some(AppEntry {
        name: detail.name.unwrap_or_default(),
        id: detail.id,
        version,
        description,
        source: Source::Flatpak,
        icon_url: detail.icon.unwrap_or_default(),
        icon_path: String::new(),
        homepage: detail
            .urls
            .and_then(|u| u.homepage)
            .unwrap_or_default(),
        votes: 0,
        popularity: 0.0,
        installed,
    })
}
