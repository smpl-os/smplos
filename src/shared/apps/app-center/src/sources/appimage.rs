use crate::catalog::{
    cache_dir, cache_is_fresh, is_appimage_installed, read_cache, strip_html, write_cache,
    AppEntry, Source,
};
use serde::{Deserialize, Serialize};
use std::time::Duration;

const CATALOG_MAX_AGE: Duration = Duration::from_secs(86400 * 3); // 3 days

/// Minimal AppImage catalog entry parsed from the appimage.github.io data.
#[derive(Clone, Debug, Serialize, Deserialize)]
struct AppImageEntry {
    name: String,
    description: String,
    categories: Vec<String>,
    authors: Vec<String>,
    license: String,
    links: Vec<String>,
    icons: Vec<String>,
}

/// Search the locally cached AppImage catalog.
pub fn search(query: &str) -> Vec<AppEntry> {
    if query.len() < 2 {
        return Vec::new();
    }

    let catalog = load_catalog();
    let q = query.to_lowercase();

    catalog
        .into_iter()
        .filter(|app| {
            app.name.to_lowercase().contains(&q)
                || app.description.to_lowercase().contains(&q)
        })
        .take(50)
        .map(|app| {
            let installed = is_appimage_installed(&app.name);
            let icon_url = app.icons.first().cloned().unwrap_or_default();
            let homepage = app.links.first().cloned().unwrap_or_default();
            AppEntry {
                name: app.name.clone(),
                id: app.name,
                version: String::new(),
                description: strip_html(&app.description),
                source: Source::AppImage,
                icon_url,
                icon_path: String::new(),
                homepage,
                votes: 0,
                popularity: 0.0,
                installed,
            }
        })
        .collect()
}

/// Load the AppImage catalog, refreshing from network if stale.
fn load_catalog() -> Vec<AppImageEntry> {
    let cache_path = cache_dir().join("appimage-catalog.json");

    if cache_is_fresh(&cache_path, CATALOG_MAX_AGE) {
        if let Some(cached) = read_cache::<Vec<AppImageEntry>>(&cache_path) {
            return cached;
        }
    }

    match download_catalog() {
        Some(apps) => {
            write_cache(&cache_path, &apps);
            apps
        }
        None => read_cache::<Vec<AppImageEntry>>(&cache_path).unwrap_or_default(),
    }
}

/// Download the AppImage catalog from the GitHub-hosted feed.
fn download_catalog() -> Option<Vec<AppImageEntry>> {
    // The feed.json contains items with basic metadata
    let url = "https://appimage.github.io/feed.json";
    let resp = ureq::get(url)
        .timeout(Duration::from_secs(15))
        .call()
        .ok()?;

    let body: serde_json::Value = resp.into_json().ok()?;

    let items = body.get("items")?.as_array()?;

    let apps: Vec<AppImageEntry> = items
        .iter()
        .filter_map(|item| {
            let name = item.get("name")?.as_str()?.to_string();
            if name.is_empty() {
                return None;
            }
            let description = strip_html(
                item.get("description")
                    .and_then(|v| v.as_str())
                    .unwrap_or(""),
            );
            let categories = item
                .get("categories")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            let authors = item
                .get("authors")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| {
                            v.get("name")
                                .and_then(|n| n.as_str())
                                .map(String::from)
                        })
                        .collect()
                })
                .unwrap_or_default();
            let license = item
                .get("license")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let links = item
                .get("links")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.get("url").and_then(|u| u.as_str()).map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            let icons = item
                .get("icons")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();

            Some(AppImageEntry {
                name,
                description,
                categories,
                authors,
                license,
                links,
                icons,
            })
        })
        .collect();

    if apps.is_empty() {
        None
    } else {
        Some(apps)
    }
}
