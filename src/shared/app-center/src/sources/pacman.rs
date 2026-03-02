use crate::catalog::{is_pacman_installed, AppEntry, Source};
use serde::Deserialize;
use std::time::Duration;

#[derive(Deserialize)]
struct SearchResponse {
    results: Vec<PkgResult>,
}

#[derive(Deserialize)]
struct PkgResult {
    pkgname: String,
    pkgdesc: Option<String>,
    pkgver: String,
    pkgrel: String,
    repo: String,
    url: Option<String>,
}

/// Search the official Arch Linux package repos via the packages.archlinux.org JSON API.
pub fn search(query: &str) -> Vec<AppEntry> {
    if query.len() < 2 {
        return Vec::new();
    }

    let url = format!(
        "https://archlinux.org/packages/search/json/?q={}",
        urlenc(query)
    );

    let resp = match ureq::get(&url)
        .timeout(Duration::from_secs(8))
        .call()
    {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let data: SearchResponse = match resp.into_json() {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };

    data.results
        .into_iter()
        .take(50)
        .map(|pkg| {
            let installed = is_pacman_installed(&pkg.pkgname);
            // Rank core > extra > multilib > others so common packages float up
            let popularity: f64 = match pkg.repo.as_str() {
                "core" => 1000.0,
                "extra" => 500.0,
                "multilib" => 200.0,
                _ => 100.0,
            };
            AppEntry {
                name: pkg.pkgname.clone(),
                id: pkg.pkgname,
                version: format!("{}-{}", pkg.pkgver, pkg.pkgrel),
                description: pkg.pkgdesc.unwrap_or_default(),
                source: Source::Pacman,
                icon_url: String::new(),
                icon_path: String::new(),
                homepage: pkg.url.unwrap_or_default(),
                votes: 0,
                popularity,
                installed,
            }
        })
        .collect()
}

fn urlenc(s: &str) -> String {
    s.chars()
        .flat_map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' || c == '.' {
                vec![c]
            } else {
                format!("%{:02X}", c as u32).chars().collect::<Vec<_>>()
            }
        })
        .collect()
}
