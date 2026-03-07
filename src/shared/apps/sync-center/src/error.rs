use thiserror::Error;
use std::path::PathBuf;

/// Comprehensive error type for sync-center operations
#[derive(Error, Debug)]
pub enum SyncError {
    // Pre-flight checks
    #[error("rsync is not installed. Install with: sudo pacman -S rsync")]
    RsyncNotInstalled,

    #[error("source path does not exist: {0}")]
    SourceNotFound(PathBuf),

    #[error("source path is not readable (permission denied): {0}")]
    SourceNotReadable(PathBuf),

    #[error("destination parent directory does not exist: {0}")]
    DestinationParentNotFound(PathBuf),

    #[error("destination is not writable (permission denied): {0}")]
    DestinationNotWritable(PathBuf),

    #[error("destination is on a read-only filesystem: {0}")]
    DestinationReadOnly(PathBuf),

    #[error("insufficient disk space on {drive}: need {required} GB, have {available} GB")]
    InsufficientDiskSpace {
        drive: String,
        required: u64,
        available: u64,
    },

    #[error("insufficient inode space on {drive}")]
    InsufficientInodes { drive: String },

    #[error("USB drive disconnected before sync could start: {volume}")]
    VolumeDisconnected { volume: String },

    // Runtime errors
    #[error("rsync command failed: {0}")]
    RsyncFailed(String),

    #[error("rsync timeout after {seconds}s")]
    RsyncTimeout { seconds: u64 },

    #[error("USB drive disconnected during sync")]
    VolumeDisconnectedDuringSyncSync,

    #[error("merge conflict detected in file: {path}")]
    MergeConflict { path: PathBuf },

    #[error("disk full during sync (consumed {consumed_mb} MB)")]
    DiskFull { consumed_mb: u64 },

    #[error("config file corrupted: {reason}")]
    ConfigCorrupted { reason: String },

    #[error("config file not found at {0}, creating default")]
    ConfigNotFound(PathBuf),

    #[error("invalid profile ID: {0}")]
    InvalidProfileId(String),

    #[error("profile not found: {0}")]
    ProfileNotFound(String),

    #[error("another sync is already running for profile: {0}")]
    SyncAlreadyRunning(String),

    #[error("failed to acquire sync lock: {reason}")]
    LockAcquisitionFailed { reason: String },

    // D-Bus and IPC errors
    #[error("D-Bus error: {0}")]
    DbusError(String),

    #[error("daemon not responding, may not be running")]
    DaemonNotResponding,

    // Notification errors
    #[error("failed to send notification: {0}")]
    NotificationFailed(String),

    // Volume monitoring errors
    #[error("GIO error: {0}")]
    GioError(String),

    #[error("failed to get volume information for {0}")]
    VolumeInfoError(String),

    // IO errors
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    // Serialization errors
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    // Generic errors
    #[error("sync cancelled by user")]
    Cancelled,

    #[error("internal error: {0}")]
    Internal(String),
}

/// Result type for sync-center operations
pub type Result<T> = std::result::Result<T, SyncError>;

/// Severity level for errors (for UI/notification purposes)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorSeverity {
    /// User action required (e.g., install rsync)
    Critical,
    /// Sync failed but can be retried
    High,
    /// Some files skipped but sync completed
    Warning,
    /// Informational
    Info,
}

impl SyncError {
    /// Get the severity level of this error
    pub fn severity(&self) -> ErrorSeverity {
        match self {
            // Critical: must fix before sync can proceed
            SyncError::RsyncNotInstalled
            | SyncError::SourceNotFound(_)
            | SyncError::SourceNotReadable(_)
            | SyncError::DestinationParentNotFound(_)
            | SyncError::DestinationNotWritable(_)
            | SyncError::DestinationReadOnly(_)
            | SyncError::InsufficientDiskSpace { .. }
            | SyncError::InsufficientInodes { .. }
            | SyncError::VolumeDisconnected { .. }
            | SyncError::ConfigCorrupted { .. } => ErrorSeverity::Critical,

            // High: sync failed but might be retryable
            SyncError::RsyncFailed(_)
            | SyncError::RsyncTimeout { .. }
            | SyncError::VolumeDisconnectedDuringSyncSync
            | SyncError::DiskFull { .. }
            | SyncError::SyncAlreadyRunning(_)
            | SyncError::LockAcquisitionFailed { .. }
            | SyncError::DbusError(_)
            | SyncError::Io(_) => ErrorSeverity::High,

            // Warning: some issues but sync may have partially succeeded
            SyncError::MergeConflict { .. } => ErrorSeverity::Warning,

            // Info: non-fatal issues
            SyncError::ConfigNotFound(_)
            | SyncError::DaemonNotResponding
            | SyncError::NotificationFailed(_)
            | SyncError::GioError(_)
            | SyncError::VolumeInfoError(_)
            | SyncError::InvalidProfileId(_)
            | SyncError::ProfileNotFound(_)
            | SyncError::Json(_)
            | SyncError::Cancelled
            | SyncError::Internal(_) => ErrorSeverity::Info,
        }
    }

    /// Get human-friendly message for notifications
    pub fn user_message(&self) -> String {
        match self {
            SyncError::RsyncNotInstalled => {
                "rsync is not installed.\n\nInstall with: sudo pacman -S rsync".to_string()
            }
            SyncError::SourceNotFound(p) => {
                format!("Source folder not found:\n{}", p.display())
            }
            SyncError::SourceNotReadable(p) => {
                format!("Cannot read source folder (permission denied):\n{}", p.display())
            }
            SyncError::DestinationNotWritable(p) => {
                format!("Cannot write to destination (permission denied):\n{}", p.display())
            }
            SyncError::DestinationReadOnly(p) => {
                format!("Destination is read-only:\n{}", p.display())
            }
            SyncError::InsufficientDiskSpace {
                drive,
                required,
                available,
            } => {
                format!(
                    "Insufficient disk space on {}:\nNeed: {} GB\nAvailable: {} GB",
                    drive, required, available
                )
            }
            SyncError::VolumeDisconnected { volume } => {
                format!("USB drive disconnected: {}", volume)
            }
            SyncError::RsyncFailed(msg) => {
                format!("Sync failed:\n{}", msg)
            }
            SyncError::RsyncTimeout { seconds } => {
                format!("Sync timed out after {}s", seconds)
            }
            SyncError::VolumeDisconnectedDuringSyncSync => {
                "USB drive was disconnected during sync".to_string()
            }
            SyncError::MergeConflict { path } => {
                format!(
                    "Merge conflict in:\n{}\n\nResolve manually and remove .CONFLICT suffix",
                    path.display()
                )
            }
            SyncError::DiskFull { consumed_mb } => {
                format!("Destination disk full ({} MB written)", consumed_mb)
            }
            SyncError::SyncAlreadyRunning(profile) => {
                format!("Another sync is running for profile: {}", profile)
            }
            SyncError::ConfigCorrupted { reason } => {
                format!("Configuration is corrupted:\n{}\n\nReverting to defaults.", reason)
            }
            _ => self.to_string(),
        }
    }
}

/// Conflict information for tracking merge conflicts
#[derive(Debug, Clone)]
pub struct ConflictInfo {
    pub file_path: PathBuf,
    pub conflict_type: ConflictType,
    pub source_size: u64,
    pub dest_size: u64,
    pub source_mtime: i64,
    pub dest_mtime: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConflictType {
    /// Text file with conflict markers added
    TextConflict,
    /// Binary file, skipped
    BinaryConflict,
    /// Directory conflict
    DirectoryConflict,
}

impl ConflictType {
    pub fn as_str(&self) -> &'static str {
        match self {
            ConflictType::TextConflict => "text",
            ConflictType::BinaryConflict => "binary",
            ConflictType::DirectoryConflict => "directory",
        }
    }
}
