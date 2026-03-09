// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! Merge conflict detection and resolution

use crate::error::{ConflictInfo, ConflictType, Result, SyncError};
use std::fs;
use std::io::{Read, Write};
use std::path::Path;

/// Detects if a file is likely a text file based on extension
fn is_likely_text_file(path: &Path) -> bool {
    let text_extensions = [
        "md", "txt", "rs", "json", "yaml", "yml", "toml", "csv", "sh", "bash", "html",
        "css", "js", "ts", "py", "java", "c", "h", "cpp", "hpp", "go", "rb", "php",
        "xml", "sql", "lua", "vim", "conf", "log",
    ];

    if let Some(ext) = path.extension() {
        if let Some(ext_str) = ext.to_str() {
            return text_extensions.contains(&ext_str);
        }
    }

    false
}

/// Detects if two files have conflicting content
fn files_conflict(source: &Path, dest: &Path) -> Result<bool> {
    let source_meta = fs::metadata(source).map_err(|e| SyncError::Io(e))?;
    let dest_meta = fs::metadata(dest).map_err(|e| SyncError::Io(e))?;

    // If sizes are different, they definitely conflict
    if source_meta.len() != dest_meta.len() {
        return Ok(true);
    }

    // For small files, compare content
    if source_meta.len() < 1024 * 1024 {
        // 1 MB threshold
        let mut source_buf = Vec::new();
        let mut dest_buf = Vec::new();

        fs::File::open(source)?.read_to_end(&mut source_buf)?;
        fs::File::open(dest)?.read_to_end(&mut dest_buf)?;

        Ok(source_buf != dest_buf)
    } else {
        // For large files, trust modification time
        Ok(source_meta.modified()? != dest_meta.modified()?)
    }
}

/// Resolves a conflict by adding git-style conflict markers for text files
fn resolve_text_conflict(source: &Path, dest: &Path, profile_id: &str) -> Result<()> {
    // Read both files
    let mut source_content = String::new();
    fs::File::open(source)?.read_to_string(&mut source_content)?;

    let mut dest_content = String::new();
    fs::File::open(dest)?.read_to_string(&mut dest_content)?;

    // Create conflict marker content
    let conflict_marker = format!(
        "<<<<<<< source (from sync profile: {})\n{}\n=======\n{}\n>>>>>>> dest\n",
        profile_id, source_content, dest_content
    );

    // Write conflict file
    let mut conflict_file = dest.to_path_buf();
    conflict_file.set_extension(format!("{}.CONFLICT", dest.extension().and_then(|e| e.to_str()).unwrap_or("txt")));

    fs::File::create(&conflict_file)?.write_all(conflict_marker.as_bytes())?;

    // Backup originals
    let source_backup = dest.with_extension(format!("{}.source", dest.extension().and_then(|e| e.to_str()).unwrap_or("txt")));
    let dest_backup = dest.with_extension(format!("{}.dest", dest.extension().and_then(|e| e.to_str()).unwrap_or("txt")));

    fs::copy(source, &source_backup)?;
    fs::copy(dest, &dest_backup)?;

    Ok(())
}

/// Handles a binary file conflict by skipping it
fn skip_binary_conflict(_path: &Path, _reason: &str) -> Result<()> {
    // Just log it - the file won't be touched during sync
    // Logging happens in the caller
    Ok(())
}

/// Detect and handle conflicts before rsync
///
/// Returns a list of conflicts found (if bidirectional sync is enabled)
pub fn detect_conflicts(
    source: &Path,
    dest: &Path,
    profile_id: &str,
) -> Result<Vec<ConflictInfo>> {
    let mut conflicts = Vec::new();

    // Only check if both source and dest exist
    if !dest.exists() {
        return Ok(conflicts);
    }

    fn walk_conflicts(
        source_dir: &Path,
        dest_dir: &Path,
        profile_id: &str,
        conflicts: &mut Vec<ConflictInfo>,
    ) -> Result<()> {
        for entry in fs::read_dir(source_dir)? {
            let entry = entry?;
            let path = entry.path();
            let relative = path.strip_prefix(source_dir).unwrap();
            let dest_path = dest_dir.join(relative);

            if dest_path.exists() {
                // File exists in both places
                if path.is_file() && dest_path.is_file() {
                    if files_conflict(&path, &dest_path)? {
                        let source_meta = fs::metadata(&path)?;
                        let dest_meta = fs::metadata(&dest_path)?;

                        let conflict_type = if is_likely_text_file(&path) {
                            ConflictType::TextConflict
                        } else {
                            ConflictType::BinaryConflict
                        };

                        conflicts.push(ConflictInfo {
                            file_path: relative.to_path_buf(),
                            conflict_type,
                            source_size: source_meta.len(),
                            dest_size: dest_meta.len(),
                            source_mtime: source_meta
                                .modified()?
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_secs() as i64,
                            dest_mtime: dest_meta
                                .modified()?
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_secs() as i64,
                        });
                    }
                } else if path.is_dir() && dest_path.is_dir() {
                    // Recurse into subdirectories
                    walk_conflicts(&path, &dest_path, profile_id, conflicts)?;
                }
            }
        }

        Ok(())
    }

    walk_conflicts(source, dest, profile_id, &mut conflicts)?;
    Ok(conflicts)
}

/// Resolve detected conflicts
pub fn resolve_conflicts(conflicts: &[ConflictInfo], source_base: &Path, dest_base: &Path) -> Result<()> {
    for conflict in conflicts {
        let source_path = source_base.join(&conflict.file_path);
        let dest_path = dest_base.join(&conflict.file_path);

        match conflict.conflict_type {
            ConflictType::TextConflict => {
                resolve_text_conflict(&source_path, &dest_path, "user-profile")?;
            }
            ConflictType::BinaryConflict => {
                skip_binary_conflict(&dest_path, "binary file conflict")?;
            }
            ConflictType::DirectoryConflict => {
                // Directories don't conflict in the same way, skip
            }
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_text_file_detection() {
        assert!(is_likely_text_file(Path::new("file.md")));
        assert!(is_likely_text_file(Path::new("script.rs")));
        assert!(!is_likely_text_file(Path::new("image.png")));
        assert!(!is_likely_text_file(Path::new("binary.so")));
    }
}
