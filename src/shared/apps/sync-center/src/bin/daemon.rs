// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center daemon - Event-driven directory synchronization to external drives

use sync_center::config::Config;
use sync_center::dbus::{DaemonState, DbusService};
use sync_center::models::{ConnectedVolume, SyncProfile};
use sync_center::volume_monitor::VolumeMonitor;

use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn};

#[tokio::main]
async fn main() -> sync_center::Result<()> {
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

    info!("sync-center daemon starting...");

    // Load config
    let config = Config::load()?;
    info!("Configuration loaded: {} profiles", config.profiles.len());

    // Initialize volume monitor
    let volume_monitor = VolumeMonitor::new(config.clone());
    info!("Volume monitor initialized");

    info!("sync-center daemon ready - D-Bus and volume monitoring to be implemented");

    // Keep daemon running
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");

    Ok(())
}
