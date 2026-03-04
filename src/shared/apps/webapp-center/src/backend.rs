use std::path::{Path, PathBuf};
use std::process::Command;
use url::Url;

#[derive(Clone, Debug)]
pub struct WebApp {
    pub name: String,
    pub slug: String,
    pub url: String,
    pub secure: bool,
    pub clear_on_exit: bool,
    pub vpn_iface: String,
    pub vpn_required: bool,
    pub icon: String,
    pub desktop_file: PathBuf,
}

fn apps_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(format!("{home}/.local/share/applications"))
}

fn profiles_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(format!("{home}/.local/share/webapps"))
}

fn icons_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(format!("{home}/.local/share/icons/hicolor/256x256/apps"))
}

/// Scan all .desktop files created by launch-webapp.
pub fn scan_webapps() -> Vec<WebApp> {
    let dir = apps_dir();
    let mut apps = Vec::new();

    let Ok(entries) = std::fs::read_dir(&dir) else {
        return apps;
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map_or(true, |e| e != "desktop") {
            continue;
        }
        let Ok(content) = std::fs::read_to_string(&path) else {
            continue;
        };

        let exec_line = content
            .lines()
            .find(|l| l.starts_with("Exec="))
            .map(|l| &l[5..])
            .unwrap_or("");

        if !exec_line.contains("launch-webapp") {
            continue;
        }

        let name = content
            .lines()
            .find(|l| l.starts_with("Name="))
            .map(|l| l[5..].to_string())
            .unwrap_or_default();

        let icon = content
            .lines()
            .find(|l| l.starts_with("Icon="))
            .map(|l| l[5..].to_string())
            .unwrap_or_default();

        // Parse exec line for flags
        let slug = parse_exec_flag(exec_line, "--name").unwrap_or_else(|| {
            path.file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default()
        });

        let url = extract_url(exec_line).unwrap_or_default();
        let secure = exec_line.contains("--secure");
        let clear_on_exit = exec_line.contains("--clear-on-exit");
        let vpn_iface = parse_exec_flag(exec_line, "--vpn-interface").unwrap_or_default();
        let vpn_required = exec_line.contains("--vpn-required");

        apps.push(WebApp {
            name,
            slug,
            url,
            secure,
            clear_on_exit,
            vpn_iface,
            vpn_required,
            icon,
            desktop_file: path,
        });
    }

    apps.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    apps
}

/// Parse a flag value from an Exec= line, handling both quoted and unquoted forms.
fn parse_exec_flag(exec: &str, flag: &str) -> Option<String> {
    let idx = exec.find(flag)?;
    let after = &exec[idx + flag.len()..].trim_start();

    if after.starts_with('"') {
        // Quoted value
        let inner = &after[1..];
        let end = inner.find('"')?;
        Some(inner[..end].to_string())
    } else {
        // Unquoted — take until next whitespace
        let val = after.split_whitespace().next()?;
        Some(val.trim_matches('"').to_string())
    }
}

/// Extract the URL (last argument, typically starts with http).
fn extract_url(exec: &str) -> Option<String> {
    // The URL is the last argument on the exec line
    // It may be quoted: "https://..."
    let trimmed = exec.trim();
    if trimmed.ends_with('"') {
        // Find matching opening quote
        let inner = &trimmed[..trimmed.len() - 1];
        if let Some(start) = inner.rfind('"') {
            return Some(inner[start + 1..].to_string());
        }
    }
    // Unquoted: last whitespace-separated token
    trimmed.split_whitespace().last().map(|s| s.trim_matches('"').to_string())
}

/// Delete a webapp: remove .desktop file, profile dir, and icons.
pub fn delete_webapp(app: &WebApp) {
    let _ = std::fs::remove_file(&app.desktop_file);
    let profile = profiles_dir().join(&app.slug);
    if profile.exists() {
        let _ = std::fs::remove_dir_all(&profile);
    }
    let icons = icons_dir();
    let _ = std::fs::remove_file(icons.join(format!("webapp-{}.png", app.slug)));
    let _ = std::fs::remove_file(icons.join(format!("webapp-{}.svg", app.slug)));
    refresh_cache();
}

/// Delete all webapps.
pub fn delete_all_webapps(apps: &[WebApp]) {
    for app in apps {
        let _ = std::fs::remove_file(&app.desktop_file);
        let profile = profiles_dir().join(&app.slug);
        if profile.exists() {
            let _ = std::fs::remove_dir_all(&profile);
        }
        let icons = icons_dir();
        let _ = std::fs::remove_file(icons.join(format!("webapp-{}.png", app.slug)));
        let _ = std::fs::remove_file(icons.join(format!("webapp-{}.svg", app.slug)));
    }
    refresh_cache();
}

/// Create or update a webapp .desktop file.
pub fn save_webapp(
    name: &str,
    url: &str,
    secure: bool,
    clear_on_exit: bool,
    vpn_iface: &str,
    vpn_required: bool,
) -> Result<String, String> {
    if name.trim().is_empty() {
        return Err("Name cannot be empty".into());
    }
    if url.trim().is_empty() {
        return Err("URL cannot be empty".into());
    }

    let mut url = url.to_string();
    if !url.starts_with("http") {
        url = format!("https://{url}");
    }

    // Validate URL format
    let parsed = Url::parse(&url).map_err(|_| "Invalid URL format. Use a full website URL like https://example.com")?;
    if (parsed.scheme() != "http" && parsed.scheme() != "https") || parsed.host_str().is_none() {
        return Err("Invalid URL format. Use http:// or https:// and a valid domain".into());
    }
    let host = parsed.host_str().unwrap_or_default();
    let host_is_ip = host.parse::<std::net::IpAddr>().is_ok();
    let host_is_valid_domain = host.contains('.') || host.eq_ignore_ascii_case("localhost") || host_is_ip;
    if !host_is_valid_domain {
        return Err("Invalid URL host. Use a real domain (example.com), localhost, or an IP address".into());
    }

    let apps_dir = apps_dir();
    let icons_dir = icons_dir();
    let _ = std::fs::create_dir_all(&apps_dir);
    let _ = std::fs::create_dir_all(&icons_dir);

    // Sanitize name for slug
    let name_ascii = transliterate(name);
    let safe_name = name_ascii
        .to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { '-' })
        .collect::<String>();
    let safe_name = safe_name.trim_matches('-').to_string();
    let safe_name = collapse_dashes(&safe_name);
    let safe_name = if safe_name.is_empty() {
        format!("webapp-{}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0))
    } else {
        safe_name
    };

    // Try to fetch favicon
    let domain = url
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()
        .unwrap_or("");

    let icon_file = icons_dir.join(format!("webapp-{safe_name}.png"));
    let icon_name = fetch_favicon(domain, &icon_file);

    // Build Exec line
    let mut exec = String::from("launch-webapp");
    if secure {
        exec.push_str(" \"--secure\"");
    }
    if clear_on_exit {
        exec.push_str(" \"--clear-on-exit\"");
    }
    if !vpn_iface.is_empty() {
        exec.push_str(&format!(" \"--vpn-interface\" \"{vpn_iface}\""));
        if vpn_required {
            exec.push_str(" \"--vpn-required\"");
        }
    }
    exec.push_str(&format!(" \"--name\" \"{safe_name}\" \"{url}\""));

    let desktop_path = apps_dir.join(format!("{safe_name}.desktop"));
    let desktop_content = format!(
        "[Desktop Entry]\n\
         Version=1.0\n\
         Type=Application\n\
         Name={name}\n\
         Comment=Web app for {url}\n\
         Exec={exec}\n\
         Icon={icon_name}\n\
         StartupWMClass=brave-{safe_name}\n\
         Terminal=false\n\
         Categories=Network;WebBrowser;\n"
    );

    std::fs::write(&desktop_path, &desktop_content)
        .map_err(|e| format!("Failed to write .desktop file: {e}"))?;

    // chmod +x
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&desktop_path, std::fs::Permissions::from_mode(0o755));
    }

    refresh_cache();
    Ok(safe_name)
}

fn transliterate(s: &str) -> String {
    // Simple ASCII transliteration — just strip non-ASCII
    s.chars()
        .map(|c| if c.is_ascii() { c } else { '-' })
        .collect()
}

fn collapse_dashes(s: &str) -> String {
    let mut result = String::new();
    let mut prev_dash = false;
    for c in s.chars() {
        if c == '-' {
            if !prev_dash {
                result.push('-');
            }
            prev_dash = true;
        } else {
            result.push(c);
            prev_dash = false;
        }
    }
    result
}

fn fetch_favicon(domain: &str, icon_file: &Path) -> String {
    let favicon_url = format!("https://www.google.com/s2/favicons?domain={domain}&sz=256");
    let result = Command::new("curl")
        .args(["-sL", "--max-time", "5", &favicon_url, "-o"])
        .arg(icon_file)
        .output();

    if let Ok(output) = result {
        if output.status.success() && icon_file.exists() && std::fs::metadata(icon_file).map(|m| m.len() > 0).unwrap_or(false) {
            // Extract icon name (without extension) for .desktop Icon= field
            return icon_file
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "applications-internet".into());
        }
    }
    let _ = std::fs::remove_file(icon_file);
    "applications-internet".into()
}

/// Detect VPN interfaces on the system.
pub fn list_vpn_interfaces() -> Vec<String> {
    let output = Command::new("ip")
        .args(["-o", "link", "show"])
        .output();

    let Ok(output) = output else { return Vec::new() };
    let stdout = String::from_utf8_lossy(&output.stdout);

    stdout
        .lines()
        .filter_map(|line| {
            let iface = line.split(':').nth(1)?.trim().split('@').next()?.trim().to_string();
            let patterns = ["tun", "tap", "wg", "ppp", "nordlynx", "tailscale0", "mullvad", "proton", "zt"];
            if patterns.iter().any(|p| iface.starts_with(p)) {
                Some(iface)
            } else {
                None
            }
        })
        .collect()
}

fn refresh_cache() {
    let apps_dir = apps_dir();
    let _ = Command::new("update-desktop-database")
        .arg(&apps_dir)
        .output();

    let _ = Command::new("rebuild-app-cache").output();
}
