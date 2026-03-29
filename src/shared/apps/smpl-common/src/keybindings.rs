//! Shared keybinding editor for smplOS.
//!
//! Parses `bindings.conf` (Hyprland `bindd` format) line-by-line, preserving
//! comments, blank lines, section headers, and submap blocks for round-trip
//! write-back. Supports read, edit, add, remove, conflict detection, and
//! live-apply via `hyprctl reload`.
//!
//! Used by both `settings` (keybindings tab) and `webapp-center` (assign
//! hotkey to web apps).

use std::path::PathBuf;

// ── Data types ───────────────────────────────────────────────────────────────

/// A single parsed keybinding.
#[derive(Clone, Debug)]
pub struct Keybinding {
    /// Original bind keyword (e.g. "bindd", "bindeld", "bindrd").
    pub bind_type: String,
    /// Modifier keys as written (e.g. "SUPER SHIFT").
    pub mods: String,
    /// Key name as written (e.g. "W", "code:10", "XF86AudioMute").
    pub key: String,
    /// Human-readable description (the 3rd field in bindd).
    pub description: String,
    /// Hyprland dispatcher (e.g. "exec", "killactive", "workspace").
    pub dispatcher: String,
    /// Dispatcher arguments (e.g. "terminal", "1", "").
    pub args: String,
    /// Section this binding belongs to (parsed from comment headers).
    pub section: String,
    /// Whether this binding is inside a submap block.
    pub submap: String,
}

/// Result of a conflict check.
#[derive(Clone, Debug)]
pub struct Conflict {
    /// The binding that already uses this combo.
    pub existing: Keybinding,
    /// Index into the bindings vec.
    pub index: usize,
}

impl Keybinding {
    /// Human-friendly key combo string (e.g. "Super+Shift+W").
    pub fn combo_display(&self) -> String {
        let mods = humanize_mods(&self.mods);
        let key = humanize_key(&self.key);
        if mods.is_empty() {
            key
        } else {
            format!("{mods}+{key}")
        }
    }

    /// Normalized combo key for comparison (e.g. "SUPER W" regardless of spacing).
    fn combo_normalized(&self) -> (Vec<String>, String) {
        let mut mods: Vec<String> = self
            .mods
            .split_whitespace()
            .map(|m| m.to_uppercase())
            .collect();
        mods.sort();
        (mods, self.key.to_uppercase())
    }

    /// Serialize back to Hyprland config line.
    pub fn to_config_line(&self) -> String {
        if self.description.is_empty() {
            // Non-description bind types (bind, bindm, etc.)
            format!(
                "{} = {}, {}, {}, {}",
                self.bind_type, self.mods, self.key, self.dispatcher, self.args
            )
        } else {
            format!(
                "{} = {}, {}, {}, {}, {}",
                self.bind_type, self.mods, self.key, self.description, self.dispatcher, self.args
            )
        }
    }
}

/// One line in the config file — preserves structure for round-trip editing.
#[derive(Clone, Debug)]
enum ConfigLine {
    /// A blank line.
    Blank,
    /// A comment line (including the `#` prefix).
    Comment(String),
    /// A section header comment like `# APPLICATION LAUNCHERS`.
    SectionHeader(String),
    /// A submap directive: `submap = resize` or `submap = reset`.
    Submap(String),
    /// A parsed keybinding with its index into the `bindings` vec.
    Binding(usize),
}

/// Full parsed state of bindings.conf.
pub struct BindingsFile {
    lines: Vec<ConfigLine>,
    pub bindings: Vec<Keybinding>,
    path: PathBuf,
}

// ── Paths ────────────────────────────────────────────────────────────────────

fn bindings_conf_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    // Prefer the live Hyprland config (what Hyprland actually sources at runtime).
    // ~/.config/smplos/bindings.conf is the smplos source-of-truth template but
    // Hyprland only reads ~/.config/hypr/bindings.conf, so writing to smplos would
    // silently produce keybindings that never fire.
    let hypr = PathBuf::from(&home).join(".config/hypr/bindings.conf");
    if hypr.exists() {
        return hypr;
    }
    let smplos = PathBuf::from(&home).join(".config/smplos/bindings.conf");
    if smplos.exists() {
        return smplos;
    }
    hypr // default write target
}

// ── Parsing ──────────────────────────────────────────────────────────────────

impl BindingsFile {
    pub fn load() -> Result<Self, String> {
        let path = bindings_conf_path();
        let content = std::fs::read_to_string(&path)
            .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;
        Ok(Self::parse(&content, path))
    }

    fn parse(content: &str, path: PathBuf) -> Self {
        let mut lines = Vec::new();
        let mut bindings = Vec::new();
        let mut current_section = String::new();
        let mut current_submap = String::new();

        for raw_line in content.lines() {
            let trimmed = raw_line.trim();

            if trimmed.is_empty() {
                lines.push(ConfigLine::Blank);
                continue;
            }

            // Section header: `# ====...` followed by `# SECTION NAME`
            if trimmed.starts_with("# ===") {
                lines.push(ConfigLine::Comment(raw_line.to_string()));
                continue;
            }

            // Section name: `# WORD WORD` (all-caps line after ===)
            if trimmed.starts_with('#') {
                let text = trimmed.trim_start_matches('#').trim();
                if !text.is_empty()
                    && text
                        .chars()
                        .all(|c| c.is_uppercase() || c == ' ' || c == '(' || c == ')')
                {
                    current_section = titlecase(text);
                    lines.push(ConfigLine::SectionHeader(current_section.clone()));
                    continue;
                }
                lines.push(ConfigLine::Comment(raw_line.to_string()));
                continue;
            }

            // Submap directive
            if trimmed.starts_with("submap") && trimmed.contains('=') {
                let val = trimmed.split('=').nth(1).unwrap_or("").trim().to_string();
                if val == "reset" {
                    current_submap.clear();
                } else {
                    current_submap = val.clone();
                }
                lines.push(ConfigLine::Submap(val));
                continue;
            }

            // Binding line: starts with bind (various flavors)
            if trimmed.starts_with("bind") && trimmed.contains('=') {
                if let Some(kb) = parse_bind_line(trimmed, &current_section, &current_submap) {
                    let idx = bindings.len();
                    bindings.push(kb);
                    lines.push(ConfigLine::Binding(idx));
                    continue;
                }
            }

            // Anything else is a plain comment
            lines.push(ConfigLine::Comment(raw_line.to_string()));
        }

        Self {
            lines,
            bindings,
            path,
        }
    }

    /// Get all unique section names in order.
    pub fn sections(&self) -> Vec<String> {
        let mut seen = Vec::new();
        for b in &self.bindings {
            if !b.section.is_empty() && !seen.contains(&b.section) {
                seen.push(b.section.clone());
            }
        }
        seen
    }

    /// Serialize the entire file back to a string, preserving structure.
    pub fn serialize(&self) -> String {
        let mut out = String::new();
        for line in &self.lines {
            match line {
                ConfigLine::Blank => out.push('\n'),
                ConfigLine::Comment(s) | ConfigLine::SectionHeader(s) => {
                    out.push_str(s);
                    out.push('\n');
                }
                ConfigLine::Submap(val) => {
                    out.push_str(&format!("submap = {val}\n"));
                }
                ConfigLine::Binding(idx) => {
                    if let Some(kb) = self.bindings.get(*idx) {
                        out.push_str(&kb.to_config_line());
                        out.push('\n');
                    }
                }
            }
        }
        out
    }

    /// Write the file back and reload Hyprland config.
    pub fn save_and_reload(&self) -> Result<(), String> {
        let content = self.serialize();
        std::fs::write(&self.path, &content)
            .map_err(|e| format!("Failed to write {}: {}", self.path.display(), e))?;

        // Reload Hyprland to pick up changes
        let output = std::process::Command::new("hyprctl")
            .arg("reload")
            .output()
            .map_err(|e| format!("Failed to run hyprctl reload: {e}"))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("hyprctl reload failed: {stderr}"));
        }
        Ok(())
    }

    /// Update the key combo for binding at index.
    pub fn edit_combo(&mut self, idx: usize, mods: &str, key: &str) {
        if let Some(kb) = self.bindings.get_mut(idx) {
            kb.mods = mods.to_string();
            kb.key = key.to_string();
        }
    }

    /// Update the description for binding at index.
    pub fn edit_description(&mut self, idx: usize, desc: &str) {
        if let Some(kb) = self.bindings.get_mut(idx) {
            kb.description = desc.to_string();
        }
    }

    /// Update the dispatcher args for binding at index (for `exec` bindings).
    pub fn edit_args(&mut self, idx: usize, args: &str) {
        if let Some(kb) = self.bindings.get_mut(idx) {
            kb.args = args.to_string();
        }
    }

    /// Remove binding at index.
    pub fn remove(&mut self, idx: usize) {
        if idx >= self.bindings.len() {
            return;
        }
        self.bindings.remove(idx);

        // Remove the ConfigLine::Binding(idx) entry
        self.lines
            .retain(|line| !matches!(line, ConfigLine::Binding(i) if *i == idx));

        // Fix indices > idx
        for line in &mut self.lines {
            if let ConfigLine::Binding(ref mut i) = line {
                if *i > idx {
                    *i -= 1;
                }
            }
        }
    }

    /// Add a new binding at the end of a given section (or at EOF).
    pub fn add(&mut self, kb: Keybinding) {
        let section = kb.section.clone();
        let idx = self.bindings.len();
        self.bindings.push(kb);

        // Find the last binding in this section and insert after it
        let mut insert_pos = None;
        for (i, line) in self.lines.iter().enumerate().rev() {
            if let ConfigLine::Binding(bi) = line {
                if self.bindings[*bi].section == section {
                    insert_pos = Some(i + 1);
                    break;
                }
            }
        }

        let pos = insert_pos.unwrap_or(self.lines.len());
        self.lines.insert(pos, ConfigLine::Binding(idx));
    }

    /// Check if a key combo conflicts with any existing binding.
    /// `exclude_idx` can be used to skip a binding being edited (so it doesn't
    /// conflict with itself).
    pub fn find_conflict(
        &self,
        mods: &str,
        key: &str,
        submap: &str,
        exclude_idx: Option<usize>,
    ) -> Option<Conflict> {
        let mut check_mods: Vec<String> = mods
            .split_whitespace()
            .map(|m| m.to_uppercase())
            .collect();
        check_mods.sort();
        let check_key = key.to_uppercase();

        for (i, kb) in self.bindings.iter().enumerate() {
            if Some(i) == exclude_idx {
                continue;
            }
            // Only conflict within the same submap
            if kb.submap != submap {
                continue;
            }
            let (existing_mods, existing_key) = kb.combo_normalized();
            if existing_mods == check_mods && existing_key == check_key {
                return Some(Conflict {
                    existing: kb.clone(),
                    index: i,
                });
            }
        }
        None
    }

    /// Open the file in the user's preferred editor.
    pub fn open_in_editor(&self) {
        let editor = std::env::var("EDITOR").unwrap_or_else(|_| "nvim".to_string());
        let terminal = which_terminal();
        let _ = std::process::Command::new(&terminal)
            .args(["-e", &editor, &self.path.to_string_lossy()])
            .spawn();
    }

    pub fn path_display(&self) -> String {
        self.path.display().to_string()
    }
}

fn which_terminal() -> String {
    if let Ok(t) = std::env::var("TERMINAL") {
        return t;
    }
    for t in ["foot", "st", "alacritty", "kitty", "xterm"] {
        if std::process::Command::new("which")
            .arg(t)
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return t.to_string();
        }
    }
    "xterm".to_string()
}

// ── Bind line parser ─────────────────────────────────────────────────────────

fn parse_bind_line(line: &str, section: &str, submap: &str) -> Option<Keybinding> {
    let (bind_type, rest) = line.split_once('=')?;
    let bind_type = bind_type.trim().to_string();

    // Has description if bind_type contains 'd' (bindd, bindrd, bindeld, etc.)
    let has_desc = bind_type.contains('d') && bind_type != "bind";

    let parts: Vec<&str> = rest.splitn(if has_desc { 5 } else { 4 }, ',').collect();

    if has_desc {
        if parts.len() < 4 {
            return None;
        }
        Some(Keybinding {
            bind_type,
            mods: parts[0].trim().to_string(),
            key: parts[1].trim().to_string(),
            description: parts[2].trim().to_string(),
            dispatcher: parts[3].trim().to_string(),
            args: parts.get(4).map(|s| s.trim()).unwrap_or("").to_string(),
            section: section.to_string(),
            submap: submap.to_string(),
        })
    } else {
        if parts.len() < 3 {
            return None;
        }
        Some(Keybinding {
            bind_type,
            mods: parts[0].trim().to_string(),
            key: parts[1].trim().to_string(),
            description: String::new(),
            dispatcher: parts[2].trim().to_string(),
            args: parts.get(3).map(|s| s.trim()).unwrap_or("").to_string(),
            section: section.to_string(),
            submap: submap.to_string(),
        })
    }
}

// ── Humanization ─────────────────────────────────────────────────────────────

fn titlecase(s: &str) -> String {
    s.split_whitespace()
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                None => String::new(),
                Some(first) => {
                    format!("{}{}", first.to_uppercase(), c.as_str().to_lowercase())
                }
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn humanize_mods(mods: &str) -> String {
    if mods.is_empty() {
        return String::new();
    }
    mods.split_whitespace()
        .map(|m| match m {
            "SUPER" => "Super",
            "SHIFT" => "Shift",
            "CTRL" => "Ctrl",
            "ALT" => "Alt",
            other => other,
        })
        .collect::<Vec<_>>()
        .join("+")
}

pub fn humanize_key(key: &str) -> String {
    match key {
        "RETURN" => "Enter".into(),
        "SPACE" => "Space".into(),
        "ESCAPE" => "Esc".into(),
        "PRINT" => "Print".into(),
        "LEFT" => "Left".into(),
        "RIGHT" => "Right".into(),
        "UP" => "Up".into(),
        "DOWN" => "Down".into(),
        "BACKSPACE" | "BackSpace" => "Backspace".into(),
        "DELETE" => "Delete".into(),
        "COMMA" => ",".into(),
        "TAB" => "Tab".into(),
        "SUPER_L" | "Super_L" => "Super".into(),
        "Shift_L" | "SHIFT_L" => "Shift".into(),
        "Alt_L" | "ALT_L" => "Alt".into(),
        "Control_L" | "CTRL_L" => "Ctrl".into(),
        "code:10" => "1".into(),
        "code:11" => "2".into(),
        "code:12" => "3".into(),
        "code:13" => "4".into(),
        "code:14" => "5".into(),
        "code:15" => "6".into(),
        "code:16" => "7".into(),
        "code:17" => "8".into(),
        "code:18" => "9".into(),
        "code:19" => "0".into(),
        "code:20" => "-".into(),
        "code:21" => "=".into(),
        "XF86AudioRaiseVolume" => "Vol Up".into(),
        "XF86AudioLowerVolume" => "Vol Down".into(),
        "XF86AudioMute" => "Mute".into(),
        "XF86AudioMicMute" => "Mic Mute".into(),
        "XF86MonBrightnessUp" => "Bright Up".into(),
        "XF86MonBrightnessDown" => "Bright Down".into(),
        "XF86AudioPlay" => "Play".into(),
        "XF86AudioPause" => "Pause".into(),
        "XF86AudioNext" => "Next Track".into(),
        "XF86AudioPrev" => "Prev Track".into(),
        "mouse_down" => "Scroll Down".into(),
        "mouse_up" => "Scroll Up".into(),
        "mouse:272" => "LMB".into(),
        "mouse:273" => "RMB".into(),
        other => other.to_string(),
    }
}

/// Reverse humanization: convert display key name back to Hyprland key name.
pub fn dehumanize_key(display: &str) -> String {
    match display {
        "Enter" => "RETURN".into(),
        "Space" => "SPACE".into(),
        "Esc" => "ESCAPE".into(),
        "Print" => "PRINT".into(),
        "Left" => "LEFT".into(),
        "Right" => "RIGHT".into(),
        "Up" => "UP".into(),
        "Down" => "DOWN".into(),
        "Backspace" => "BACKSPACE".into(),
        "Delete" => "DELETE".into(),
        "Tab" => "TAB".into(),
        other => other.to_uppercase(),
    }
}

/// Map Slint key event text to Hyprland key names.
/// Slint sends single chars for printable keys, and Unicode PUA chars for
/// special keys (Key.Return = \u{f710}, etc.).
pub fn slint_key_to_hyprland(text: &str) -> String {
    // Single printable character -> uppercase
    if text.len() == 1 {
        let c = text.chars().next().unwrap();
        if c.is_alphanumeric() || c.is_ascii_punctuation() {
            return c.to_uppercase().to_string();
        }
    }

    match text {
        "\n" | "\r" => "RETURN".into(),
        " " => "SPACE".into(),
        "\t" => "TAB".into(),
        "\u{7f}" | "\u{08}" => "BACKSPACE".into(),
        "\u{1b}" => "ESCAPE".into(),
        // Slint PUA key codes
        "\u{f700}" => "UP".into(),
        "\u{f701}" => "DOWN".into(),
        "\u{f702}" => "LEFT".into(),
        "\u{f703}" => "RIGHT".into(),
        "\u{f728}" => "DELETE".into(),
        "\u{f729}" => "HOME".into(),
        "\u{f72b}" => "END".into(),
        "\u{f72c}" => "PAGEUP".into(),
        "\u{f72d}" => "PAGEDOWN".into(),
        "\u{f704}" => "F1".into(),
        "\u{f705}" => "F2".into(),
        "\u{f706}" => "F3".into(),
        "\u{f707}" => "F4".into(),
        "\u{f708}" => "F5".into(),
        "\u{f709}" => "F6".into(),
        "\u{f70a}" => "F7".into(),
        "\u{f70b}" => "F8".into(),
        "\u{f70c}" => "F9".into(),
        "\u{f70d}" => "F10".into(),
        "\u{f70e}" => "F11".into(),
        "\u{f70f}" => "F12".into(),
        _ => String::new(),
    }
}

/// Get all unique sections from a bindings list for UI filtering.
pub fn unique_sections(bindings: &[Keybinding]) -> Vec<String> {
    let mut sections = vec!["All".to_string()];
    for b in bindings {
        if !b.section.is_empty() && !sections.contains(&b.section) {
            sections.push(b.section.clone());
        }
    }
    sections
}
