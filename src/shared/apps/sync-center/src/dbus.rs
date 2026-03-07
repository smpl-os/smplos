// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! D-Bus interface for sync-center daemon

use crate::models::{ActiveSync};
use serde_json::json;
use std::sync::Arc;
use tokio::sync::RwLock;
use zbus::dbus_interface;

/// Daemon state exposed via D-Bus
#[derive(Clone)]
pub struct DaemonState {
    /// Currently active sync (if any)
    pub active_sync: Arc<RwLock<Option<ActiveSync>>>,
    /// Last error message (if any)
    pub last_error: Arc<RwLock<Option<String>>>,
}

pub struct DbusService {
    state: DaemonState,
}

impl DbusService {
    pub fn new(state: DaemonState) -> Self {
        Self { state }
    }

    pub async fn start(state: DaemonState) -> Result<(), Box<dyn std::error::Error>> {
        let service = DbusService::new(state);

        let _connection = zbus::ConnectionBuilder::session()?
            .name("org.smpl.SyncCenter")?
            .serve_at("/org/smpl/SyncCenter", service)?
            .build()
            .await?;

        // Keep the connection alive
        std::future::pending().await
    }
}

#[dbus_interface(name = "org.smpl.SyncCenter")]
impl DbusService {
    /// Whether a sync is currently running
    #[dbus_interface(property)]
    async fn is_active(&self) -> bool {
        self.state.active_sync.read().await.is_some()
    }

    /// Currently syncing profile ID
    #[dbus_interface(property)]
    async fn current_profile(&self) -> String {
        if let Some(sync) = self.state.active_sync.read().await.as_ref() {
            sync.profile_id.clone()
        } else {
            String::new()
        }
    }

    /// Get all configured profiles as JSON
    async fn get_profiles(&self) -> zbus::fdo::Result<String> {
        // TODO: Load from config
        Ok(json!([]).to_string())
    }

    /// Start sync for a specific profile
    async fn sync_now(&self, profile_id: String) -> zbus::fdo::Result<bool> {
        // Check if already syncing
        if self.state.active_sync.read().await.is_some() {
            return Err(zbus::fdo::Error::Failed(
                "Another sync is already running".to_string(),
            ));
        }

        // TODO: Trigger sync
        Ok(true)
    }

    /// Cancel the currently running sync
    async fn cancel_sync(&self) -> zbus::fdo::Result<bool> {
        if self.state.active_sync.read().await.is_none() {
            return Err(zbus::fdo::Error::Failed(
                "No sync currently running".to_string(),
            ));
        }

        // TODO: Send cancellation signal to rsync child process
        self.state.active_sync.write().await.take();
        Ok(true)
    }
}
