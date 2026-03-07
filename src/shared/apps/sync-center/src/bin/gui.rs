// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center GUI - Slint interface for managing sync profiles

use sync_center::config::Config;

slint::include_modules!();

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

    // TODO: Load configuration and populate profiles
    // let config = Config::load().unwrap_or_default();
    // let profiles: Vec<SyncProfile> = config.profiles.iter().map(|p| {
    //     SyncProfile {
    //         id: p.id.clone().into(),
    //         name: p.name.clone().into(),
    //         ...
    //     }
    // }).collect();
    // main_window.set_profiles(profiles.as_slice().into());

    // Set up callbacks
    main_window.on_add_profile({
        let window = main_window.as_weak();
        move || {
            // TODO: Open add profile dialog
            println!("Add profile clicked");
        }
    });

    main_window.on_edit_profile({
        let window = main_window.as_weak();
        move |idx| {
            // TODO: Open edit profile dialog
            println!("Edit profile {} clicked", idx);
        }
    });

    main_window.on_sync_profile({
        let window = main_window.as_weak();
        move |idx| {
            // TODO: Trigger sync via D-Bus
            println!("Sync profile {} clicked", idx);
        }
    });

    main_window.on_toggle_profile({
        let window = main_window.as_weak();
        move |idx| {
            // TODO: Toggle profile enabled state
            println!("Toggle profile {} clicked", idx);
        }
    });

    main_window.on_refresh({
        let window = main_window.as_weak();
        move || {
            // TODO: Refresh profiles and volume list
            println!("Refresh clicked");
        }
    });

    // Set daemon status
    // TODO: Check if daemon is running via D-Bus
    main_window.set_daemon_running(false);

    main_window.run()?;
    Ok(())
}
