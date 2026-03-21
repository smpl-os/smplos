// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! Desktop notifications via libnotify

use anyhow::Result;

pub struct Notifier;

impl Default for Notifier {
    fn default() -> Self {
        Self
    }
}

impl Notifier {
    pub fn new() -> Self {
        Self
    }

    pub fn show_sync_started(_profile_name: &str) -> Result<()> {
        // TODO: Show notification
        Ok(())
    }

    pub fn show_sync_progress(_profile_name: &str, _current: u64, _total: u64) -> Result<()> {
        // TODO: Update notification with progress
        Ok(())
    }

    pub fn show_sync_completed(_profile_name: &str, _success: bool) -> Result<()> {
        // TODO: Show completion notification
        Ok(())
    }
}
