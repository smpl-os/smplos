// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! rsync execution and progress tracking

use anyhow::Result;
use std::path::PathBuf;

pub struct RsyncRunner;

impl RsyncRunner {
    pub fn new() -> Self {
        Self
    }

    pub async fn sync(
        source: &str,
        destination: &str,
        exclude: &[String],
    ) -> Result<()> {
        // TODO: Execute rsync with progress tracking
        Ok(())
    }
}
