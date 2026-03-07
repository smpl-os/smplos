// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center GUI - GTK4 interface for managing sync profiles

use gtk4::prelude::*;
use gtk4::{Application, ApplicationWindow};
use adwaita::prelude::*;
use anyhow::Result;
use tracing::info;

fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing_subscriber::filter::LevelFilter::INFO.into()),
        )
        .init();

    info!("sync-center GUI starting...");

    let app = Application::builder()
        .application_id("org.smpl.SyncCenter")
        .build();

    app.connect_activate(build_ui);

    Ok(app.run())
}

fn build_ui(app: &Application) {
    // TODO: Build main window with profile list
    // For now, just show a placeholder window

    let window = ApplicationWindow::builder()
        .application(app)
        .title("Sync Center")
        .default_width(600)
        .default_height(400)
        .build();

    window.present();
}
