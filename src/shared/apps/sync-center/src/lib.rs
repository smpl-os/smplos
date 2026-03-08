// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

pub mod config;
pub mod conflict;
pub mod dbus;
pub mod error;
pub mod models;
pub mod mounts;
pub mod notification;
pub mod rsync_runner;
pub mod volume_monitor;

// Re-export commonly used types
pub use error::{SyncError, Result, ErrorSeverity, ConflictInfo, ConflictType};
