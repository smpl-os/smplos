// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center GUI - Slint interface for managing sync profiles

use sync_center::config::Config;
use std::process::{Command, Stdio};
use std::path::PathBuf;
use std::env;

slint::include_modules!();

fn start_daemon() -> Result<(), Box<dyn std::error::Error>> {
    // Get the path to the daemon binary (should be in same directory as GUI)
    let mut daemon_path = env::current_exe()?;
    daemon_path.pop(); // Remove current binary name
    daemon_path.push("sync-center-daemon");
    
    if !daemon_path.exists() {
        eprintln!("Warning: sync-center-daemon not found at {:?}", daemon_path);
        return Err("Daemon binary not found".into());
    }
    
    // Spawn daemon as detached background process
    Command::new(daemon_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    
    println!("Daemon started successfully");
    Ok(())
}

fn is_daemon_running() -> bool {
    // Try to connect to D-Bus service to check if daemon is running
    // TODO: Implement proper D-Bus check
    // For now, just check if process exists
    Command::new("pgrep")
        .arg("-f")
        .arg("sync-center-daemon")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Set up winit backend with transparency
    let backend = i_slint_backend_winit::Backend::builder()
        .with_renderer_name("femtovg")
        .with_window_attributes_hook(|attrs| {
            use i_slint_backend_winit::winit::dpi::LogicalSize;
            use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
            attrs
                .with_name("sync-center", "sync-center")
                .with_decorations(false)
                .with_inner_size(LogicalSize::new(800.0_f64, 600.0))
        })
        .build()?;
    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| slint::PlatformError::Other(e.to_string()))?;

    // Create main window
    let main_window = MainWindow::new()?;

    // Check if daemon is running, if not start it
    let daemon_running = is_daemon_running();
    if !daemon_running {
        if let Err(e) = start_daemon() {
            eprintln!("Failed to start daemon: {}", e);
        }
        // Give daemon time to start
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    main_window.set_daemon_running(is_daemon_running());

    // Load configuration and populate profiles
    let config = Config::load().unwrap_or_default();
    // TODO: Convert Config profiles to Slint SyncProfile structs
    // let profiles: Vec<SyncProfile> = config.profiles.iter().map(...).collect();
    // main_window.set_profiles(...);

    // Set up callbacks
    main_window.on_add_profile({
        let window = main_window.as_weak();
        move || {
            // Show profile dialog
            println!("Add profile clicked - TODO: show ProfileDialog");
            
            // TODO: After user fills dialog and clicks Start:
            // 1. Save profile to config
            // 2. Ensure daemon is running
            // 3. Notify daemon via D-Bus to reload config
            // 4. Refresh profile list
        }
    });

    main_window.on_edit_profile({
        let window = main_window.as_weak();
        move |idx| {
            println!("Edit profile {} clicked", idx);
            // TODO: Load profile data, show dialog, save changes
        }
    });

    main_window.on_sync_profile({
        let window = main_window.as_weak();
        move |idx| {
            println!("Sync profile {} clicked", idx);
            // TODO: Call D-Bus sync_now(profile_id)
        }
    });

    main_window.on_toggle_profile({
        let window = main_window.as_weak();
        move |idx| {
            println!("Toggle profile {} clicked", idx);
            // TODO: Update config, notify daemon
        }
    });

    main_window.on_refresh({
        let window = main_window.as_weak();
        move || {
            println!("Refresh clicked");
            // TODO: Query D-Bus for state, reload profiles
        }
    });

    main_window.run()?;
    Ok(())
}
