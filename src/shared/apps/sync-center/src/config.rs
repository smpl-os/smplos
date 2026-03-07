// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::collections::HashMap;

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
    pub fn load() -> anyhow::Result<Self> {
        let config_dir = dirs::config_dir()
            .expect("No config directory found")
            .join("sync-center");
        
        let config_file = config_dir.join("config.json");
        
        if !config_file.exists() {
            return Ok(Self::default());
        }
        
        let contents = std::fs::read_to_string(&config_file)?;
        let config = serde_json::from_str(&contents)?;
        
        Ok(config)
    }
    
    pub fn save(&self) -> anyhow::Result<()> {
        let config_dir = dirs::config_dir()
            .expect("No config directory found")
            .join("sync-center");
        
        std::fs::create_dir_all(&config_dir)?;
        
        let config_file = config_dir.join("config.json");
        let contents = serde_json::to_string_pretty(self)?;
        std::fs::write(&config_file, contents)?;
        
        Ok(())
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
