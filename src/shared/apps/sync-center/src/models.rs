// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! Data models for sync-center

use crate::config::{VolumeIdentifier, SyncProfile, DirectorySync};
use std::collections::HashMap;
use std::path::PathBuf;
use std::time::SystemTime;

pub use crate::config::{VolumeIdentifier, PostSyncAction};

#[derive(Debug, Clone)]
pub struct ConnectedVolume {
    pub id: String,
    pub mount_point: PathBuf,
    pub size_bytes: u64,
    pub available_bytes: u64,
    pub label: String,
}

#[derive(Debug, Clone)]
pub struct ActiveSync {
    pub profile_id: String,
    pub started_at: SystemTime,
    pub current_file: String,
    pub progress: (u64, u64), // (current, total)
    pub pid: u32,
}

#[derive(Debug, Clone)]
pub struct SyncEvent {
    pub timestamp: SystemTime,
    pub profile_id: String,
    pub profile_name: String,
    pub success: bool,
    pub message: String,
    pub duration_secs: u64,
}

pub use crate::config::SyncProfile;
pub use crate::config::DirectorySync;
