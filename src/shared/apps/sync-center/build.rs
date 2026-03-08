use std::fs;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let counter_path = manifest_dir.join(".build-patch");

    let current_patch = fs::read_to_string(&counter_path)
        .ok()
        .and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(0);

    let next_patch = current_patch.saturating_add(1);
    let _ = fs::write(&counter_path, format!("{}\n", next_patch));

    let pkg_version = std::env::var("CARGO_PKG_VERSION").unwrap_or_else(|_| "0.1.0".to_string());
    let mut parts = pkg_version.split('.');
    let major = parts.next().unwrap_or("0");
    let minor = parts.next().unwrap_or("1");
    let computed_version = format!("{}.{}.{}", major, minor, next_patch);

    println!("cargo:rustc-env=SYNC_CENTER_VERSION={}", computed_version);

    slint_build::compile("ui/main.slint").unwrap();
}
