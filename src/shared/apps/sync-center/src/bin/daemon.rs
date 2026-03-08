// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center daemon — serves D-Bus interface and runs rsync on behalf of the GUI.

use sync_center::config::Config;
use sync_center::dbus::{DaemonState, DbusService};

use tracing::info;

#[tokio::main]
async fn main() -> sync_center::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing_subscriber::filter::LevelFilter::INFO.into()),
        )
        .init();

    info!("sync-center daemon starting...");

    let config = Config::load().unwrap_or_default();
    info!("Loaded {} sync profiles", config.profiles.len());

    let state = DaemonState::new(config);

    // This runs forever, serving the D-Bus interface.
    DbusService::start(state)
        .await
        .map_err(|e| sync_center::SyncError::Internal(e.to_string()))?;

    Ok(())
}
