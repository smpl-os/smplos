// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! USB volume detection and mount-point resolution shared by the GUI and daemon.

use crate::config::{SyncProfile, VolumeIdentifier};
use std::fs;
use std::path::PathBuf;

/// Unescape the octal-encoded fields in `/proc/self/mounts` (kernel format).
fn unescape_mount_field(field: &str) -> String {
    field
        .replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
}

/// Return the device path (e.g. `/dev/sdb1`) for a given mount point, or `None`.
pub fn device_for_mount_path(mount_path: &str) -> Option<String> {
    let mounts = fs::read_to_string("/proc/self/mounts").ok()?;
    for line in mounts.lines() {
        let mut parts = line.split_whitespace();
        let device = parts.next()?;
        let mounted_at = parts.next()?;
        if unescape_mount_field(mounted_at) == mount_path {
            return Some(device.to_string());
        }
    }
    None
}

/// Return the filesystem UUID for a block device path, or `None`.
pub fn uuid_for_device(device: &str) -> Option<String> {
    let canonical_device = fs::canonicalize(device).ok()?;
    let entries = fs::read_dir("/dev/disk/by-uuid").ok()?;
    for entry in entries.flatten() {
        let uuid_name = entry.file_name().into_string().ok()?;
        if let Ok(target) = fs::canonicalize(entry.path()) {
            if target == canonical_device {
                return Some(uuid_name);
            }
        }
    }
    None
}

/// Resolve the full absolute destination path for a profile's first sync rule,
/// searching under `/run/media/$USER/`.
///
/// Returns `None` if the volume is not currently mounted.
pub fn resolve_destination(profile: &SyncProfile) -> Option<PathBuf> {
    let user = std::env::var("USER").unwrap_or_default();
    let base = PathBuf::from(format!("/run/media/{}", user));

    let sync = profile.syncs.first()?;
    let dest_relative = &sync.destination;

    match &profile.identifier {
        VolumeIdentifier::Label { value } => {
            let mount = base.join(value);
            if mount.is_dir() {
                Some(mount.join(dest_relative))
            } else {
                None
            }
        }
        VolumeIdentifier::UUID { value } => {
            if let Ok(entries) = fs::read_dir(&base) {
                for entry in entries.flatten() {
                    if !entry.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                        continue;
                    }
                    let mount = entry.path().to_string_lossy().to_string();
                    if let Some(uuid) = device_for_mount_path(&mount)
                        .and_then(|dev| uuid_for_device(&dev))
                    {
                        if &uuid == value {
                            return Some(entry.path().join(dest_relative));
                        }
                    }
                }
            }
            None
        }
        VolumeIdentifier::Marker { path } => {
            if let Ok(entries) = fs::read_dir(&base) {
                for entry in entries.flatten() {
                    if !entry.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                        continue;
                    }
                    let marker = entry.path().join(path.trim_start_matches('/'));
                    if marker.exists() {
                        return Some(entry.path().join(dest_relative));
                    }
                }
            }
            None
        }
    }
}
