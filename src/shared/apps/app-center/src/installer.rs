use crate::catalog::Source;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;

/// A running process with streaming output and interactive input.
pub struct StreamingProcess {
    child: Child,
    output_rx: mpsc::Receiver<String>,
    stdin: Option<ChildStdin>,
}

/// Result for operations that complete instantly (no streaming needed).
pub struct ImmediateResult {
    pub success: bool,
    pub message: String,
}

/// Either a live streaming process or an instant result.
pub enum SpawnResult {
    Streaming(StreamingProcess),
    Immediate(ImmediateResult),
}

impl StreamingProcess {
    /// Drain all available output lines without blocking.
    pub fn poll_output(&self) -> Vec<String> {
        let mut lines = Vec::new();
        while let Ok(line) = self.output_rx.try_recv() {
            lines.push(line);
        }
        lines
    }

    /// Send a line of text to the process stdin.
    pub fn send_input(&mut self, text: &str) {
        if let Some(ref mut stdin) = self.stdin {
            let _ = writeln!(stdin, "{}", text);
            let _ = stdin.flush();
        }
    }

    /// Check if the process exited. Returns None if still running.
    pub fn try_wait(&mut self) -> Option<bool> {
        match self.child.try_wait() {
            Ok(Some(status)) => Some(status.success()),
            _ => None,
        }
    }

    /// Kill the process and all its children.
    pub fn kill(&mut self) {
        // Drop stdin first to unblock any reads
        self.stdin.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Strip ANSI escape sequences for clean display.
fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            if chars.peek() == Some(&'[') {
                chars.next();
                for c in chars.by_ref() {
                    if c.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
        } else if c != '\r' {
            out.push(c);
        }
    }
    out
}

fn spawn_process(cmd: &str, args: &[&str]) -> Result<StreamingProcess, String> {
    let mut child = Command::new(cmd)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Could not run {}: {}", cmd, e))?;

    let stdin = child.stdin.take();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let (tx, rx) = mpsc::channel::<String>();

    if let Some(out) = stdout {
        let tx = tx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines().flatten() {
                let _ = tx.send(strip_ansi(&line));
            }
        });
    }

    if let Some(err) = stderr {
        let tx = tx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().flatten() {
                let _ = tx.send(strip_ansi(&line));
            }
        });
    }

    Ok(StreamingProcess {
        child,
        output_rx: rx,
        stdin,
    })
}

/// Install an official-repo package. Falls back to pkexec pacman if paru is broken.
fn spawn_pacman_install(id: &str) -> SpawnResult {
    let (cmd, args): (&str, Vec<&str>) = if paru_works() {
        ("paru", vec!["-S", "--noconfirm", id])
    } else {
        ("pkexec", vec!["pacman", "-S", "--noconfirm", id])
    };
    match spawn_process(cmd, &args) {
        Ok(p) => SpawnResult::Streaming(p),
        Err(e) => SpawnResult::Immediate(ImmediateResult { success: false, message: e }),
    }
}

/// Install an AUR package. Auto-heals paru if libalpm bumped it, then installs.
fn spawn_aur_install(id: &str) -> SpawnResult {
    // Inline heal + install so the user sees a single streaming log
    let script = format!(
        "set -euo pipefail\n\
         if ! paru --version &>/dev/null 2>&1; then\n\
           echo '── Healing paru (system update changed libalpm) ──'\n\
           heal-paru || {{ echo 'ERROR: paru heal failed'; exit 1; }}\n\
         fi\n\
         paru -S --noconfirm '{}'\n",
        id.replace('\'', "'\\''")
    );
    match spawn_process("bash", &["-c", &script]) {
        Ok(p) => SpawnResult::Streaming(p),
        Err(e) => SpawnResult::Immediate(ImmediateResult { success: false, message: e }),
    }
}

/// Remove a package. Falls back to pkexec pacman if paru is broken.
fn spawn_pacman_remove(id: &str) -> SpawnResult {
    let (cmd, args): (&str, Vec<&str>) = if paru_works() {
        ("paru", vec!["-Rns", "--noconfirm", id])
    } else {
        ("pkexec", vec!["pacman", "-R", "--noconfirm", id])
    };
    match spawn_process(cmd, &args) {
        Ok(p) => SpawnResult::Streaming(p),
        Err(e) => SpawnResult::Immediate(ImmediateResult { success: false, message: e }),
    }
}

/// Spawn an install process with streaming output.
pub fn spawn_install(source: &Source, id: &str) -> SpawnResult {
    match source {
        Source::Aur => spawn_aur_install(id),
        Source::Pacman => spawn_pacman_install(id),
        Source::Flatpak => {
            if !which_exists("flatpak") {
                return SpawnResult::Immediate(ImmediateResult {
                    success: false,
                    message: "flatpak is not installed. Run: sudo pacman -S flatpak".into(),
                });
            }
            let _ = Command::new("flatpak")
                .args([
                    "remote-add", "--if-not-exists", "--user", "flathub",
                    "https://dl.flathub.org/repo/flathub.flatpakrepo",
                ])
                .output();
            match spawn_process("flatpak", &["install", "-y", "--user", "flathub", id]) {
                Ok(p) => SpawnResult::Streaming(p),
                Err(e) => SpawnResult::Immediate(ImmediateResult {
                    success: false,
                    message: e,
                }),
            }
        }
        Source::Script => match spawn_process(id, &["install"]) {
            Ok(p) => SpawnResult::Streaming(p),
            Err(e) => SpawnResult::Immediate(ImmediateResult {
                success: false,
                message: e,
            }),
        },
        Source::AppImage => SpawnResult::Immediate(ImmediateResult {
            success: false,
            message: format!(
                "Visit appimage.github.io to download {}.AppImage, then place it in ~/.local/bin/",
                id
            ),
        }),
    }
}

/// Spawn an uninstall process with streaming output.
pub fn spawn_uninstall(source: &Source, id: &str, name: &str) -> SpawnResult {
    match source {
        Source::Aur | Source::Pacman => spawn_pacman_remove(id),
        Source::Flatpak => {
            match spawn_process("flatpak", &["uninstall", "-y", "--user", id]) {
                Ok(p) => SpawnResult::Streaming(p),
                Err(e) => SpawnResult::Immediate(ImmediateResult {
                    success: false,
                    message: e,
                }),
            }
        }
        Source::AppImage => {
            let home = std::env::var("HOME").unwrap_or_default();
            for path in &[
                format!("/opt/appimages/{}.AppImage", name),
                format!("{}/.local/bin/{}.AppImage", home, name),
            ] {
                let _ = std::fs::remove_file(path);
            }
            let desktop = format!(
                "{}/.local/share/applications/{}-appimage.desktop",
                home,
                name.to_lowercase()
            );
            let _ = std::fs::remove_file(&desktop);
            SpawnResult::Immediate(ImmediateResult {
                success: true,
                message: format!("Removed {}", name),
            })
        }
        Source::Script => match spawn_process(id, &["uninstall"]) {
            Ok(p) => SpawnResult::Streaming(p),
            Err(e) => SpawnResult::Immediate(ImmediateResult {
                success: false,
                message: e,
            }),
        },
    }
}

fn which_exists(name: &str) -> bool {
    Command::new("which")
        .arg(name)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Check that paru exists AND can actually run (libalpm ABI match).
fn paru_works() -> bool {
    Command::new("paru")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}
