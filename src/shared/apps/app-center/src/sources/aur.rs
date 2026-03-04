use crate::catalog::{is_pacman_installed, AppEntry, Source};
use serde::Deserialize;

/// AUR RPC v5 response.
#[derive(Deserialize)]
struct AurResponse {
    results: Vec<AurPackage>,
}

#[derive(Deserialize)]
struct AurPackage {
    #[serde(rename = "Name")]
    name: String,
    #[serde(rename = "Version")]
    version: String,
    #[serde(rename = "Description")]
    description: Option<String>,
    #[serde(rename = "URL")]
    url: Option<String>,
    #[serde(rename = "NumVotes")]
    num_votes: Option<i64>,
    #[serde(rename = "Popularity")]
    popularity: Option<f64>,
}

/// Search the AUR RPC API. Returns up to 50 results.
pub fn search(query: &str) -> Vec<AppEntry> {
    if query.len() < 2 {
        return Vec::new();
    }

    let url = format!(
        "https://aur.archlinux.org/rpc/v5/search/{}?by=name-desc",
        urlenc(query)
    );

    let resp = match ureq::get(&url).timeout(std::time::Duration::from_secs(5)).call() {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let body: AurResponse = match resp.into_json() {
        Ok(b) => b,
        Err(_) => return Vec::new(),
    };

    body.results
        .into_iter()
        .take(50)
        .map(|pkg| {
            let installed = is_pacman_installed(&pkg.name);
            AppEntry {
                name: pkg.name.clone(),
                id: pkg.name,
                version: pkg.version,
                description: pkg.description.unwrap_or_default(),
                source: Source::Aur,
                icon_url: String::new(),
                icon_path: String::new(),
                homepage: pkg.url.unwrap_or_default(),
                votes: pkg.num_votes.unwrap_or(0),
                popularity: pkg.popularity.unwrap_or(0.0),
                installed,
            }
        })
        .collect()
}

/// Minimal URL encoding for the search query.
fn urlenc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'-' | b'_' | b'.' => {
                out.push(b as char);
            }
            b' ' => out.push('+'),
            _ => {
                out.push('%');
                out.push_str(&format!("{:02X}", b));
            }
        }
    }
    out
}
