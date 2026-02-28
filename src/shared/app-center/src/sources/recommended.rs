use crate::catalog::{is_script_installed, AppEntry, Source};

/// Curated list of recommended apps with guided setup scripts.
pub fn get_recommended() -> Vec<AppEntry> {
    let mut entries = vec![
        AppEntry {
            name: "Zen Kernel".into(),
            id: "zen-kernel-setup".into(),
            version: String::new(),
            description: "Switch to the Zen kernel for a snappier desktop. Lower input latency, smoother multitasking, and better I/O scheduling. Your LTS kernel stays as a GRUB fallback. Requires internet.".into(),
            source: Source::Script,
            icon_url: String::new(),
            icon_path: "\u{26A1}".into(),
            homepage: "https://github.com/zen-kernel/zen-kernel".into(),
            votes: 0,
            popularity: 0.0,
            installed: false,
        },
    ];

    for entry in &mut entries {
        entry.installed = is_script_installed(&entry.id);
    }

    entries
}
