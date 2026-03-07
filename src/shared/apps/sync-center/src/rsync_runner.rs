// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! rsync execution and progress tracking with pre-flight validation

use crate::error::{SyncError, Result};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::fs;

/// Metadata about available disk space
#[derive(Debug, Clone)]
pub struct DiskSpace {
    pub total: u64,
    pub available: u64,
    pub used: u64,
}

/// Executes rsync operations with progress tracking and validation
pub struct RsyncRunner;

impl RsyncRunner {
    /// Validate that rsync is installed
    pub fn check_rsync_installed() -> Result<()> {
        match Command::new("rsync").arg("--version").output() {
            Ok(output) if output.status.success() => Ok(()),
            _ => Err(SyncError::RsyncNotInstalled),
        }
    }

    /// Pre-flight checks before sync
    ///
    /// Validates:
    /// - rsync is installed
    /// - source exists and is readable
    /// - destination parent exists and is writable
    /// - sufficient disk space (with 10% buffer)
    pub fn preflight_check(
        source: &Path,
        destination: &Path,
        required_buffer_percent: u32,
    ) -> Result<()> {
        // Check rsync
        Self::check_rsync_installed()?;

        // Check source
        if !source.exists() {
            return Err(SyncError::SourceNotFound(source.to_path_buf()));
        }

        // Verify we can read source
        if fs::read_dir(source).is_err() {
            return Err(SyncError::SourceNotReadable(source.to_path_buf()));
        }

        // Check destination parent
        let dest_parent = destination.parent().unwrap_or_else(|| Path::new("/"));
        if !dest_parent.exists() {
            return Err(SyncError::DestinationParentNotFound(dest_parent.to_path_buf()));
        }

        // Check destination writability with test write
        let test_file = dest_parent.join(".sync-test-write");
        match fs::File::create(&test_file) {
            Ok(_) => {
                let _ = fs::remove_file(&test_file);
            }
            Err(_) => {
                return Err(SyncError::DestinationNotWritable(dest_parent.to_path_buf()));
            }
        }

        // Check disk space
        let source_size = Self::calculate_dir_size(source)?;
        let disk_space = Self::get_disk_space(dest_parent)?;

        let required_buffer = source_size.saturating_mul(required_buffer_percent as u64) / 100;
        let required_space = source_size.saturating_add(required_buffer);

        if disk_space.available < required_space {
            return Err(SyncError::InsufficientDiskSpace {
                drive: dest_parent.display().to_string(),
                required: (required_space + 1024 * 1024 * 1024 - 1) / (1024 * 1024 * 1024), // Round up to GB
                available: disk_space.available / (1024 * 1024 * 1024),
            });
        }

        Ok(())
    }

    /// Calculate total size of a directory recursively
    fn calculate_dir_size(path: &Path) -> Result<u64> {
        let mut total = 0u64;

        fn walk_dir(path: &Path, total: &mut u64) -> std::io::Result<()> {
            for entry in fs::read_dir(path)? {
                let entry = entry?;
                let metadata = entry.metadata()?;
                if metadata.is_file() {
                    *total = total.saturating_add(metadata.len());
                } else if metadata.is_dir() {
                    walk_dir(&entry.path(), total)?;
                }
            }
            Ok(())
        }

        walk_dir(path, &mut total).map_err(|e| SyncError::Io(e))?;
        Ok(total)
    }

    /// Get disk space information for a mount point
    #[cfg(target_os = "linux")]
    fn get_disk_space(path: &Path) -> Result<DiskSpace> {
        use nix::sys::statvfs::statvfs;

        let stat = statvfs(path).map_err(|e| {
            SyncError::VolumeInfoError(format!("Cannot get disk space: {}", e))
        })?;

        let block_size = stat.blocks_available() as u64 * stat.block_size() as u64;
        let total = stat.blocks() as u64 * stat.block_size() as u64;
        let available = block_size;
        let used = total.saturating_sub(available);

        Ok(DiskSpace {
            total,
            available,
            used,
        })
    }

    /// Sync source to destination using rsync
    ///
    /// # Arguments
    /// * `source` - Source directory path
    /// * `destination` - Destination directory path
    /// * `exclude` - List of rsync exclude patterns
    ///
    /// # Returns
    /// * `Ok(())` on success
    /// * `Err(SyncError)` on failure
    pub fn sync(
        source: &Path,
        destination: &Path,
        exclude: &[String],
    ) -> Result<()> {
        // Pre-flight checks
        Self::preflight_check(source, destination, 10)?;

        // Ensure directories exist
        fs::create_dir_all(destination).map_err(|e| {
            SyncError::Internal(format!("Cannot create destination: {}", e))
        })?;

        // Build rsync command
        let mut cmd = Command::new("rsync");
        cmd.arg("-avz") // archive, verbose, compress
            .arg("--info=progress2") // progress output
            .arg("--delete") // delete files not in source
            .arg("-L") // follow symlinks
            .arg("--timeout=300"); // 5 minute timeout per operation

        // Add exclude patterns
        for pattern in exclude {
            cmd.arg("--exclude").arg(pattern);
        }

        // Source and destination - ensure source has trailing slash
        let source_with_slash = format!("{}/", source.display());
        cmd.arg(&source_with_slash);
        cmd.arg(destination);

        // Spawn process
        let output = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| {
                if e.kind() == std::io::ErrorKind::NotFound {
                    SyncError::RsyncNotInstalled
                } else {
                    SyncError::RsyncFailed(e.to_string())
                }
            })?;

        // Wait for process
        let result = output.wait_with_output().map_err(|e| {
            SyncError::RsyncFailed(e.to_string())
        })?;

        if result.status.success() {
            Ok(())
        } else {
            let stderr = String::from_utf8_lossy(&result.stderr);
            Err(SyncError::RsyncFailed(stderr.to_string()))
        }
    }
}
