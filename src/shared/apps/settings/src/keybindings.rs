//! Keybinding editor -- re-exports from smpl-common::keybindings.
//!
//! All keybinding parsing, editing, conflict detection, and humanization
//! lives in the shared `smpl-common` crate so `webapp-center` (and future
//! apps) can reuse the same logic.

pub use smpl_common::keybindings::*;
