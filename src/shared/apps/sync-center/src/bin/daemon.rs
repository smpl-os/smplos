// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center daemon - Event-driven directory synchronization to external drives

use std::collections::HashMap;
use std::path::PathBuf;
use anyhow::Result;
use tracing::{info, warn, error};

mod config;
mod dbus;
mod models;
mod notification;
mod rsync_runner;
mod volume_monitor;

use config::Config;
use models::{SyncProfile, ConnectedVolume};
use volume_monitor::VolumeMonitor;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing_subscriber::filter::LevelFilter::INFO.into()),
        )
        .init();

    info!("sync-center daemon starting...");

    // Load configuration
    let config = Config::load()?;
    info!("Loaded {} sync profiles", config.profiles.len());

    // Initialize D-Bus
    let dbus_handle = dbus::DbusService::start().await?;
    info!("D-Bus service initialized");

    // Initialize volume monitor
    let mut volume_monitor = VolumeMonitor::new(config.clone());
    info!("Volume monitor initialized");

    // Start monitoring volumes
    volume_monitor.start().await?;

    info!("sync-center daemon ready");

    // Keep daemon running
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");

    Ok(())
}
