// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

use crate::error::{Result, SyncError};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub version: String,
    pub general: GeneralConfig,
    pub profiles: Vec<SyncProfile>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GeneralConfig {
    pub auto_start: bool,
    pub show_notifications: bool,
    pub log_level: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncProfile {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub identifier: VolumeIdentifier,
    pub syncs: Vec<DirectorySync>,
    pub post_sync_action: PostSyncAction,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum VolumeIdentifier {
    #[serde(rename = "label")]
    Label { value: String },

    #[serde(rename = "uuid")]
    UUID { value: String },

    #[serde(rename = "marker")]
    Marker { path: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DirectorySync {
    pub source: String,
    pub destination: String,
    pub bidirectional: bool,
    pub delete_missing: bool,
    pub exclude: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PostSyncAction {
    Notify,
    Eject,
    None,
}

impl Config {
    /// Load config from ~/.config/sync-center/config.json
    ///
    /// Returns default config if file doesn't exist.
    /// Returns error if file is corrupted.
    pub fn load() -> Result<Self> {
        let config_dir = Self::config_dir();
        let config_file = config_dir.join("config.json");

        if !config_file.exists() {
            return Ok(Self::default());
        }

        let contents = std::fs::read_to_string(&config_file).map_err(|e| {
            SyncError::Internal(format!("Cannot read config file: {}", e))
        })?;

        serde_json::from_str(&contents).map_err(|e| {
            SyncError::ConfigCorrupted {
                reason: e.to_string(),
            }
        })
    }

    /// Save config to ~/.config/sync-center/config.json
    pub fn save(&self) -> Result<()> {
        let config_dir = Self::config_dir();
        std::fs::create_dir_all(&config_dir).map_err(|e| {
            SyncError::Internal(format!("Cannot create config directory: {}", e))
        })?;

        let config_file = config_dir.join("config.json");
        let contents = serde_json::to_string_pretty(self).map_err(|e| {
            SyncError::Internal(format!("Cannot serialize config: {}", e))
        })?;

        std::fs::write(&config_file, contents).map_err(|e| {
            SyncError::Internal(format!("Cannot write config file: {}", e))
        })?;

        Ok(())
    }

    /// Get config directory path
    pub fn config_dir() -> PathBuf {
        dirs::config_dir()
            .expect("No config directory found")
            .join("sync-center")
    }

    /// Get log directory path
    pub fn log_dir() -> PathBuf {
        dirs::data_dir()
            .expect("No data directory found")
            .join("sync-center")
    }

    /// Get log file path
    pub fn log_file() -> PathBuf {
        Self::log_dir().join("sync-center.log")
    }

    /// Get conflicts log file path
    pub fn conflicts_log_file() -> PathBuf {
        Self::log_dir().join("conflicts.log")
    }

    /// Validate that all profile sources and destinations exist
    pub fn validate(&self) -> Result<()> {
        for profile in &self.profiles {
            for sync in &profile.syncs {
                let source = Path::new(&sync.source);
                if !source.exists() {
                    return Err(SyncError::SourceNotFound(source.to_path_buf()));
                }

                let dest_parent = Path::new(&sync.destination)
                    .parent()
                    .unwrap_or_else(|| Path::new("/"));
                if !dest_parent.exists() {
                    return Err(SyncError::DestinationParentNotFound(
                        dest_parent.to_path_buf(),
                    ));
                }
            }
        }

        Ok(())
    }

    /// Find a profile by ID
    pub fn get_profile(&self, profile_id: &str) -> Option<&SyncProfile> {
        self.profiles.iter().find(|p| p.id == profile_id)
    }

    /// Find a profile by volume identifier
    pub fn get_profile_for_volume(&self, identifier: &VolumeIdentifier) -> Option<&SyncProfile> {
        self.profiles
            .iter()
            .find(|p| p.enabled && matches_identifier(&p.identifier, identifier))
    }
}

/// Check if two volume identifiers match
fn matches_identifier(a: &VolumeIdentifier, b: &VolumeIdentifier) -> bool {
    match (a, b) {
        (
            VolumeIdentifier::Label { value: v1 },
            VolumeIdentifier::Label { value: v2 },
        ) => v1 == v2,
        (
            VolumeIdentifier::UUID { value: v1 },
            VolumeIdentifier::UUID { value: v2 },
        ) => v1 == v2,
        (
            VolumeIdentifier::Marker { path: p1 },
            VolumeIdentifier::Marker { path: p2 },
        ) => p1 == p2,
        _ => false,
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            version: "1.0".to_string(),
            general: GeneralConfig {
                auto_start: true,
                show_notifications: true,
                log_level: "info".to_string(),
            },
            profiles: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_serialization() {
        let config = Config::default();
        let json = serde_json::to_string_pretty(&config).unwrap();
        let deserialized: Config = serde_json::from_str(&json).unwrap();
        assert_eq!(config.version, deserialized.version);
    }

    #[test]
    fn test_volume_identifier_matching() {
        let label1 = VolumeIdentifier::Label {
            value: "Photos".to_string(),
        };
        let label2 = VolumeIdentifier::Label {
            value: "Photos".to_string(),
        };
        assert!(matches_identifier(&label1, &label2));

        let uuid1 = VolumeIdentifier::UUID {
            value: "ABC123".to_string(),
        };
        let uuid2 = VolumeIdentifier::UUID {
            value: "ABC123".to_string(),
        };
        assert!(matches_identifier(&uuid1, &uuid2));

        assert!(!matches_identifier(&label1, &uuid1));
    }
}
