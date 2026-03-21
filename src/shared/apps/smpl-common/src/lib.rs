//! smpl-common — shared initialisation code for all smplOS Slint/Winit apps.
//!
//! Every smplOS GUI app needs:
//!   1. FemtoVG renderer (OpenGL/EGL with ARGB visuals — supports transparency)
//!   2. `with_decorations(false)` — no CSD frame
//!   3. `with_name(app_id, app_id)` — sets Wayland app_id for windowrulev2
//!   4. A fixed logical size so Hyprland can float + size it via windowrule
//!
//! NEVER use renderer-software — it uses softbuffer which hardcodes
//! wl_shm::Format::Xrgb8888 on Wayland, making alpha completely ignored.
//!
//! NEVER use renderer-software — it uses softbuffer which hardcodes
//! wl_shm::Format::Xrgb8888 on Wayland, making alpha completely ignored.
//!
//! Without ALL of these, either the blur breaks, the window gets decorated,
//! or Hyprland can't target it with windowrulev2. See copilot-instructions.md.

use i_slint_backend_winit::winit::dpi::LogicalSize;
use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
use slint::PlatformError;

/// Initialise the Slint backend for a smplOS popup window.
///
/// Must be called **before** creating any Slint component.
///
/// # Arguments
/// * `app_id` – Wayland `app_id` / instance name (matches binary name).
///   Must match the `initialClass` in Hyprland `windowrulev2`.
/// * `width` – Logical width in DIPs.
/// * `height` – Logical height in DIPs.
///
/// # Example
/// ```no_run
/// smpl_common::init("start-menu", 420.0, 680.0).expect("backend init failed");
/// let ui = MainWindow::new().unwrap();
/// ui.run().unwrap();
/// ```FemtoVG renderer: uses OpenGL/EGL with ARGB visuals on Wayland,
        // so the compositor sees real alpha and can blur through it.
        // NEVER use "software" — softbuffer hardcodes XRGB on Wayland (no alpha).
        .with_renderer_name("femtovgnGL/EGL with ARGB visuals on Wayland,
        // so the compositor sees real alpha and can blur through it.
        // NEVER use "software" — softbuffer hardcodes XRGB on Wayland (no alpha).
        .with_renderer_name("femtovg")
        .with_window_attributes_hook(move |attrs| {
            attrs
                // Sets Wayland app_id so `windowrulev2 = float, initialClass:start-menu`
                // (and blur/opacity rules) can target this window specifically.
                .with_name(app_id, app_id)
                // No client-side decorations — adds an opaque frame otherwise.
                .with_decorations(false)
                // Fixed logical size. Hyprland's `windowrule = size W H` overrides
                // this at the compositor level, but we set it here too so the window
                // opens at the right size before Hyprland applies its rules.
                .with_inner_size(LogicalSize::new(width, height))
        })
        .build()?;

    slint::platform::set_platform(Box::new(backend))
        .map_err(|e| PlatformError::Other(e.to_string()))?;

    Ok(())
}
