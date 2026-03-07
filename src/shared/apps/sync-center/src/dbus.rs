// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! D-Bus interface for sync-center daemon

use zbus::interface;
use anyhow::Result;

pub struct DbusService;

impl DbusService {
    pub async fn start() -> Result<()> {
        // TODO: Implement D-Bus service
        Ok(())
    }
}

#[interface(name = "org.smpl.SyncCenter")]
impl DbusService {
    #[zbus(property)]
    fn is_active(&self) -> bool {
        // TODO: Return actual active sync status
        false
    }

    #[zbus(property)]
    fn current_profile(&self) -> String {
        // TODO: Return current profile ID
        String::new()
    }

    async fn get_profiles(&self) -> Result<String> {
        // TODO: Return profiles as JSON
        Ok(String::new())
    }

    async fn sync_now(&self, profile_id: String) -> Result<bool> {
        // TODO: Start sync for profile
        Ok(false)
    }

    async fn cancel_sync(&self) -> Result<bool> {
        // TODO: Cancel current sync
        Ok(false)
    }
}
