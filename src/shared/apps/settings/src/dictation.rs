use crate::debug_log;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};

// ── Language + Model data ────────────────────────────────────────────────────

pub struct Language {
    pub name: &'static str,
    pub code: &'static str,
}

/// All Whisper-supported languages + English default + auto-detect.
pub static LANGUAGES: &[Language] = &[
    Language { name: "English (recommended)", code: "en" },
    Language { name: "Auto-detect (all languages)", code: "auto" },
    Language { name: "Afrikaans", code: "af" },
    Language { name: "Albanian", code: "sq" },
    Language { name: "Amharic", code: "am" },
    Language { name: "Arabic", code: "ar" },
    Language { name: "Armenian", code: "hy" },
    Language { name: "Assamese", code: "as" },
    Language { name: "Azerbaijani", code: "az" },
    Language { name: "Bashkir", code: "ba" },
    Language { name: "Basque", code: "eu" },
    Language { name: "Belarusian", code: "be" },
    Language { name: "Bengali", code: "bn" },
    Language { name: "Bosnian", code: "bs" },
    Language { name: "Breton", code: "br" },
    Language { name: "Bulgarian", code: "bg" },
    Language { name: "Cantonese", code: "yue" },
    Language { name: "Catalan", code: "ca" },
    Language { name: "Chinese", code: "zh" },
    Language { name: "Croatian", code: "hr" },
    Language { name: "Czech", code: "cs" },
    Language { name: "Danish", code: "da" },
    Language { name: "Dutch", code: "nl" },
    Language { name: "Estonian", code: "et" },
    Language { name: "Faroese", code: "fo" },
    Language { name: "Finnish", code: "fi" },
    Language { name: "French", code: "fr" },
    Language { name: "Galician", code: "gl" },
    Language { name: "Georgian", code: "ka" },
    Language { name: "German", code: "de" },
    Language { name: "Greek", code: "el" },
    Language { name: "Gujarati", code: "gu" },
    Language { name: "Haitian Creole", code: "ht" },
    Language { name: "Hausa", code: "ha" },
    Language { name: "Hawaiian", code: "haw" },
    Language { name: "Hebrew", code: "he" },
    Language { name: "Hindi", code: "hi" },
    Language { name: "Hungarian", code: "hu" },
    Language { name: "Icelandic", code: "is" },
    Language { name: "Indonesian", code: "id" },
    Language { name: "Italian", code: "it" },
    Language { name: "Japanese", code: "ja" },
    Language { name: "Javanese", code: "jw" },
    Language { name: "Kannada", code: "kn" },
    Language { name: "Kazakh", code: "kk" },
    Language { name: "Khmer", code: "km" },
    Language { name: "Korean", code: "ko" },
    Language { name: "Lao", code: "lo" },
    Language { name: "Latin", code: "la" },
    Language { name: "Latvian", code: "lv" },
    Language { name: "Lingala", code: "ln" },
    Language { name: "Lithuanian", code: "lt" },
    Language { name: "Luxembourgish", code: "lb" },
    Language { name: "Macedonian", code: "mk" },
    Language { name: "Malagasy", code: "mg" },
    Language { name: "Malay", code: "ms" },
    Language { name: "Malayalam", code: "ml" },
    Language { name: "Maltese", code: "mt" },
    Language { name: "Maori", code: "mi" },
    Language { name: "Marathi", code: "mr" },
    Language { name: "Mongolian", code: "mn" },
    Language { name: "Myanmar", code: "my" },
    Language { name: "Nepali", code: "ne" },
    Language { name: "Norwegian", code: "no" },
    Language { name: "Nynorsk", code: "nn" },
    Language { name: "Occitan", code: "oc" },
    Language { name: "Pashto", code: "ps" },
    Language { name: "Persian", code: "fa" },
    Language { name: "Polish", code: "pl" },
    Language { name: "Portuguese", code: "pt" },
    Language { name: "Punjabi", code: "pa" },
    Language { name: "Romanian", code: "ro" },
    Language { name: "Russian", code: "ru" },
    Language { name: "Sanskrit", code: "sa" },
    Language { name: "Serbian", code: "sr" },
    Language { name: "Shona", code: "sn" },
    Language { name: "Sindhi", code: "sd" },
    Language { name: "Sinhala", code: "si" },
    Language { name: "Slovak", code: "sk" },
    Language { name: "Slovenian", code: "sl" },
    Language { name: "Somali", code: "so" },
    Language { name: "Spanish", code: "es" },
    Language { name: "Sundanese", code: "su" },
    Language { name: "Swahili", code: "sw" },
    Language { name: "Swedish", code: "sv" },
    Language { name: "Tagalog", code: "tl" },
    Language { name: "Tajik", code: "tg" },
    Language { name: "Tamil", code: "ta" },
    Language { name: "Tatar", code: "tt" },
    Language { name: "Telugu", code: "te" },
    Language { name: "Thai", code: "th" },
    Language { name: "Tibetan", code: "bo" },
    Language { name: "Turkish", code: "tr" },
    Language { name: "Turkmen", code: "tk" },
    Language { name: "Ukrainian", code: "uk" },
    Language { name: "Urdu", code: "ur" },
    Language { name: "Uzbek", code: "uz" },
    Language { name: "Vietnamese", code: "vi" },
    Language { name: "Welsh", code: "cy" },
    Language { name: "Yiddish", code: "yi" },
    Language { name: "Yoruba", code: "yo" },
];

pub struct WhisperModel {
    pub id: &'static str,
    pub label: &'static str,
    pub size: &'static str,
    pub note: &'static str,
    pub english_only: bool,
}

pub static MODELS: &[WhisperModel] = &[
    WhisperModel { id: "base.en",         label: "Base (English)", size: "~150 MB", note: "Fastest, English only",     english_only: true  },
    WhisperModel { id: "base",            label: "Base",           size: "~150 MB", note: "Fast, 99 languages",        english_only: false },
    WhisperModel { id: "small",           label: "Small",          size: "~500 MB", note: "Good balance",              english_only: false },
    WhisperModel { id: "medium",          label: "Medium",         size: "~1.5 GB", note: "Higher accuracy, slower",   english_only: false },
    WhisperModel { id: "large-v3-turbo",  label: "Large Turbo",    size: "~3 GB",   note: "Best quality, needs 6GB+ RAM", english_only: false },
];

pub fn find_language_idx(code: &str) -> Option<usize> {
    LANGUAGES.iter().position(|l| l.code == code)
}

pub fn find_model_idx(id: &str) -> Option<usize> {
    MODELS.iter().position(|m| m.id == id)
}

fn language_name(code: &str) -> &str {
    LANGUAGES.iter()
        .find(|l| l.code == code)
        .map(|l| l.name)
        .unwrap_or(code)
}

pub fn language_display(cfg: &DictationConfig) -> slint::SharedString {
    if cfg.also_english {
        format!("{} + English", language_name(&cfg.primary_code)).into()
    } else {
        language_name(&cfg.primary_code).into()
    }
}

pub fn model_display(model_id: &str) -> slint::SharedString {
    MODELS.iter()
        .find(|m| m.id == model_id)
        .map(|m| m.label)
        .unwrap_or(model_id)
        .into()
}

pub fn is_model_english_only(model_idx: usize) -> bool {
    MODELS.get(model_idx).map(|m| m.english_only).unwrap_or(false)
}

static INSTALL_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

pub fn is_install_running() -> bool {
    INSTALL_IN_PROGRESS.load(Ordering::Relaxed)
}

fn set_install_running(v: bool) {
    INSTALL_IN_PROGRESS.store(v, Ordering::Relaxed);
}

// ── Config read/write ────────────────────────────────────────────────────────

pub struct DictationConfig {
    pub primary_code: String,
    pub also_english: bool,
    pub model: String,
}

fn home_dir() -> Option<String> {
    let h = std::env::var("HOME").ok()?;
    if h.is_empty() { None } else { Some(h) }
}

fn config_path() -> Option<String> {
    Some(format!("{}/.config/voxtype/config.toml", home_dir()?))
}

pub fn config_exists() -> bool {
    config_path()
        .map(|p| std::path::Path::new(&p).exists())
        .unwrap_or(false)
}

pub fn is_installed() -> bool {
    Command::new("which")
        .arg("voxtype")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

pub fn read_config() -> Option<DictationConfig> {
    let path = config_path()?;
    let content = std::fs::read_to_string(&path).ok()?;

    let mut language = String::from("auto");
    let mut model = String::from("base");
    let mut in_whisper = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            in_whisper = trimmed == "[whisper]";
            continue;
        }
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }

        if in_whisper {
            if let Some(rest) = trimmed.strip_prefix("model") {
                if let Some((_, val)) = rest.split_once('=') {
                    let val = val.trim().trim_matches('"');
                    if !val.is_empty() {
                        model = val.to_string();
                    }
                }
            }
            if let Some(rest) = trimmed.strip_prefix("language") {
                if let Some((_, val)) = rest.split_once('=') {
                    let raw = val.trim();
                    if raw.starts_with('[') {
                        let inner = raw
                            .trim_start_matches('[')
                            .trim_end_matches(']')
                            .split(',')
                            .map(|s| s.trim().trim_matches('"').to_string())
                            .filter(|s| !s.is_empty())
                            .collect::<Vec<_>>()
                            .join(", ");
                        if !inner.is_empty() {
                            language = inner;
                        }
                    } else {
                        let v = raw.trim_matches('"').to_string();
                        if !v.is_empty() {
                            language = v;
                        }
                    }
                }
            }
        }
    }

    let codes: Vec<&str> = language.split(',').map(|s| s.trim()).collect();
    let (primary_code, also_english) = if codes.len() > 1 {
        let non_en: Vec<&&str> = codes.iter().filter(|c| **c != "en").collect();
        let primary = non_en.first().map(|c| c.to_string()).unwrap_or_else(|| "en".to_string());
        (primary, codes.contains(&"en"))
    } else {
        (codes[0].to_string(), false)
    };

    debug_log!("[settings] dictation config: primary={}, also_en={}, model={}",
        primary_code, also_english, model);

    Some(DictationConfig { primary_code, also_english, model })
}

pub fn is_service_running() -> bool {
    Command::new("systemctl")
        .args(["--user", "is-active", "--quiet", "voxtype"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

// ── Setup actions ────────────────────────────────────────────────────────────

pub fn write_config(lang_code: &str, model_id: &str, also_english: bool) -> bool {
    let dir = match home_dir() {
        Some(h) => format!("{}/.config/voxtype", h),
        None => {
            eprintln!("[settings] cannot write config: HOME not set");
            return false;
        }
    };
    if let Err(e) = std::fs::create_dir_all(&dir) {
        eprintln!("[settings] cannot create config dir: {}", e);
        return false;
    }

    let lang_line = if lang_code == "en" || lang_code == "auto" {
        format!("language = \"{}\"", lang_code)
    } else if also_english {
        format!("language = [\"en\", \"{}\"]", lang_code)
    } else {
        format!("language = \"{}\"", lang_code)
    };

    let config = format!(
        "# Voxtype configuration for smplOS\n\
         # Docs: https://github.com/peteonrails/voxtype\n\
         \n\
         # Use compositor keybindings (SUPER+CTRL+X) instead of built-in hotkey\n\
         [hotkey]\n\
         enabled = false\n\
         \n\
         state_file = \"auto\"\n\
         \n\
         [whisper]\n\
         model = \"{model_id}\"\n\
         {lang_line}\n\
         \n\
         [output]\n\
         mode = \"type\"\n\
         fallback_to_clipboard = true\n\
         append_text = \" \"\n\
         \n\
         [output.notification]\n\
         on_transcription = true\n\
         \n\
         [audio]\n\
         device = \"auto\"\n\
         sample_rate = 16000\n\
         max_duration_secs = 60\n\
         \n\
         [audio.feedback]\n\
         enabled = true\n\
         theme = \"default\"\n"
    );

    let path = format!("{}/config.toml", dir);
    match std::fs::write(&path, &config) {
        Ok(_) => {
            debug_log!("[settings] wrote config to {}", path);
            true
        }
        Err(e) => {
            eprintln!("[settings] failed to write config: {}", e);
            false
        }
    }
}

// ── Progress tracking ────────────────────────────────────────────────────────

fn progress_file_path() -> String {
    let run_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    format!("{}/settings-install-progress", run_dir)
}

pub fn read_progress() -> (f32, String) {
    let path = progress_file_path();
    match std::fs::read_to_string(&path) {
        Ok(content) => {
            let trimmed = content.trim();
            if trimmed.is_empty() {
                return (0.0, String::new());
            }
            if let Some((pct_str, msg)) = trimmed.split_once('|') {
                let pct: f32 = pct_str.parse().unwrap_or(0.0);
                (pct.clamp(0.0, 100.0) / 100.0, msg.to_string())
            } else {
                (0.0, trimmed.to_string())
            }
        }
        Err(_) => (0.0, String::new()),
    }
}

pub fn clear_progress() {
    let _ = std::fs::remove_file(progress_file_path());
    set_install_running(false);
}

fn clear_progress_file_only() {
    let _ = std::fs::remove_file(progress_file_path());
}

pub fn cleanup_stale_progress() {
    let path = progress_file_path();
    if std::path::Path::new(&path).exists() {
        debug_log!("[settings] removing stale progress file");
        let _ = std::fs::remove_file(&path);
    }
    set_install_running(false);
}

pub fn launch_install() -> bool {
    if INSTALL_IN_PROGRESS.swap(true, Ordering::SeqCst) {
        debug_log!("[settings] install already in progress, ignoring");
        return false;
    }
    debug_log!("[settings] launching install in terminal");
    clear_progress_file_only();
    let script = concat!(
        "PROG=\"${XDG_RUNTIME_DIR:-/tmp}/settings-install-progress\"\n",
        "cleanup() { echo \"0|Error: Interrupted\" > \"$PROG\"; exit 1; }\n",
        "trap cleanup INT TERM\n",
        "echo ''\n",
        "echo '  Installing dictation packages...'\n",
        "echo '  You may be prompted for your password once.'\n",
        "echo ''\n",
        "sudo -v || { echo '0|Error: Authentication failed' > \"$PROG\"; exit 1; }\n",
        "while sudo -vn 2>/dev/null; do sleep 50; done &\n",
        "SUDO_KEEPALIVE=$!\n",
        "trap 'kill $SUDO_KEEPALIVE 2>/dev/null; cleanup' INT TERM\n",
        "echo '5|Installing packages...' > \"$PROG\"\n",
        "\n",
        "install_pkg() {\n",
        "    local pkg=\"$1\"\n",
        "    if command -v paru &>/dev/null && paru --version &>/dev/null 2>&1; then\n",
        "        echo \"  Using paru for $pkg...\"\n",
        "        paru -S --needed --noconfirm \"$pkg\" 2>&1 && return 0\n",
        "    fi\n",
        "    if command -v yay &>/dev/null && yay --version &>/dev/null 2>&1; then\n",
        "        echo \"  Using yay for $pkg...\"\n",
        "        yay -S --needed --noconfirm \"$pkg\" 2>&1 && return 0\n",
        "    fi\n",
        "    if pacman -Si \"$pkg\" &>/dev/null; then\n",
        "        echo \"  Using pacman for $pkg...\"\n",
        "        sudo pacman -S --needed --noconfirm \"$pkg\" 2>&1 && return 0\n",
        "    fi\n",
        "    echo \"  Building $pkg from AUR manually...\"\n",
        "    local tmp\n",
        "    tmp=$(mktemp -d)\n",
        "    if git clone --depth 1 \"https://aur.archlinux.org/${pkg}.git\" \"$tmp\" 2>/dev/null; then\n",
        "        (cd \"$tmp\" && makepkg -si --noconfirm 2>&1)\n",
        "        local rc=$?\n",
        "        rm -rf \"$tmp\"\n",
        "        return $rc\n",
        "    fi\n",
        "    rm -rf \"$tmp\"\n",
        "    return 1\n",
        "}\n",
        "\n",
        "echo '10|Installing wtype...' > \"$PROG\"\n",
        "if ! install_pkg wtype; then\n",
        "    echo '0|Error: Could not install wtype' > \"$PROG\"\n",
        "    echo ''\n",
        "    echo '  ERROR: Could not install wtype.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "echo '20|Installing voxtype...' > \"$PROG\"\n",
        "if ! install_pkg voxtype-bin; then\n",
        "    echo '0|Error: Could not install voxtype-bin' > \"$PROG\"\n",
        "    echo ''\n",
        "    echo '  ERROR: Could not install voxtype-bin.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "if ! command -v voxtype &>/dev/null; then\n",
        "    echo '0|Error: voxtype not found after install' > \"$PROG\"\n",
        "    echo ''\n",
        "    echo '  ERROR: voxtype command not found after install.'\n",
        "    echo '  The package may have failed to build.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "echo '40|Downloading AI model...' > \"$PROG\"\n",
        "echo ''\n",
        "echo '  Downloading AI model (this may take a few minutes)...'\n",
        "if ! voxtype setup --download --no-post-install 2>&1; then\n",
        "    echo '0|Error: Model download failed' > \"$PROG\"\n",
        "    echo ''\n",
        "    echo '  ERROR: Model download failed.'\n",
        "    echo '  Check your internet connection and try again.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "echo '85|Setting up service...' > \"$PROG\"\n",
        "echo ''\n",
        "echo '  Setting up systemd service...'\n",
        "voxtype setup systemd 2>/dev/null || true\n",
        "systemctl --user enable voxtype 2>/dev/null || true\n",
        "systemctl --user restart voxtype 2>/dev/null || true\n",
        "echo '100|Done! Dictation is ready.' > \"$PROG\"\n",
        "kill $SUDO_KEEPALIVE 2>/dev/null\n",
        "echo ''\n",
        "echo '  Done! Dictation is ready.'\n",
        "echo '  Press SUPER+CTRL+X to start/stop speaking.'\n",
        "echo ''\n",
        "echo '  You can close this window now.'\n",
        "read -r\n",
    );
    match Command::new("terminal")
        .args(["-e", "bash", "-c", script])
        .spawn()
    {
        Ok(_) => true,
        Err(e) => {
            eprintln!("[settings] failed to spawn terminal: {}", e);
            set_install_running(false);
            let path = progress_file_path();
            let _ = std::fs::write(&path, "0|Error: Could not open terminal");
            false
        }
    }
}

pub fn launch_model_download() -> bool {
    if INSTALL_IN_PROGRESS.swap(true, Ordering::SeqCst) {
        debug_log!("[settings] install already in progress, ignoring");
        return false;
    }
    debug_log!("[settings] launching model download in terminal");
    clear_progress_file_only();
    let script = concat!(
        "PROG=\"${XDG_RUNTIME_DIR:-/tmp}/settings-install-progress\"\n",
        "cleanup() { echo \"0|Error: Interrupted\" > \"$PROG\"; exit 1; }\n",
        "trap cleanup INT TERM\n",
        "echo '10|Downloading AI model...' > \"$PROG\"\n",
        "echo ''\n",
        "echo '  Downloading AI model...'\n",
        "if ! command -v voxtype &>/dev/null; then\n",
        "    echo '0|Error: voxtype not found' > \"$PROG\"\n",
        "    echo '  ERROR: voxtype is not installed.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "if ! voxtype setup --download --no-post-install 2>&1; then\n",
        "    echo '0|Error: Model download failed' > \"$PROG\"\n",
        "    echo ''\n",
        "    echo '  ERROR: Model download failed.'\n",
        "    echo '  Check your internet connection and try again.'\n",
        "    echo '  Press Enter to close.'; read -r; exit 1\n",
        "fi\n",
        "echo '80|Restarting service...' > \"$PROG\"\n",
        "echo ''\n",
        "echo '  Restarting dictation service...'\n",
        "systemctl --user enable voxtype 2>/dev/null || true\n",
        "systemctl --user restart voxtype 2>/dev/null || true\n",
        "echo '100|Done! Model updated.' > \"$PROG\"\n",
        "echo ''\n",
        "echo '  Done! You can close this window.'\n",
        "read -r\n",
    );
    match Command::new("terminal")
        .args(["-e", "bash", "-c", script])
        .spawn()
    {
        Ok(_) => true,
        Err(e) => {
            eprintln!("[settings] failed to spawn terminal: {}", e);
            set_install_running(false);
            let path = progress_file_path();
            let _ = std::fs::write(&path, "0|Error: Could not open terminal");
            false
        }
    }
}

pub fn open_config() {
    let cfg = match config_path() {
        Some(p) => p,
        None => return,
    };
    if !std::path::Path::new(&cfg).exists() {
        write_config("en", "base", false);
    }
    let editor = if Command::new("which").arg("nvim")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .output()
        .map(|o| o.status.success()).unwrap_or(false)
    { "nvim" } else { "nano" };
    debug_log!("[settings] opening config with {}", editor);
    let _ = Command::new("terminal").args(["-e", editor, &cfg]).spawn();
}

pub fn restart_service() {
    debug_log!("[settings] restarting voxtype service");
    let _ = Command::new("systemctl")
        .args(["--user", "enable", "voxtype"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .output();
    let _ = Command::new("systemctl")
        .args(["--user", "restart", "voxtype"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .output();
}
