use super::backend::DisplayBackend;
use super::monitor::{Monitor, MonitorConfig, MonitorMode};

/// A demo backend with fake monitors for UI testing on any display server.
pub struct DemoBackend;

impl DemoBackend {
    pub fn new() -> Self {
        Self
    }
}

impl DisplayBackend for DemoBackend {
    fn query_monitors(&self) -> Result<Vec<Monitor>, String> {
        Ok(vec![
            Monitor {
                id: 0,
                name: "DP-1".into(),
                description: "Demo 27\" 4K Monitor".into(),
                width: 3840,
                height: 2160,
                refresh_rate: 144.0,
                x: 0,
                y: 0,
                scale: 1.5,
                transform: 0,
                enabled: true,
                dpms: true,
                focused: true,
                available_modes: vec![
                    MonitorMode { width: 3840, height: 2160, refresh_rate: 144.0 },
                    MonitorMode { width: 3840, height: 2160, refresh_rate: 60.0 },
                    MonitorMode { width: 2560, height: 1440, refresh_rate: 165.0 },
                    MonitorMode { width: 2560, height: 1440, refresh_rate: 60.0 },
                    MonitorMode { width: 1920, height: 1080, refresh_rate: 60.0 },
                ],
            },
            Monitor {
                id: 1,
                name: "HDMI-A-1".into(),
                description: "Demo 24\" 1080p Monitor".into(),
                width: 1920,
                height: 1080,
                refresh_rate: 60.0,
                x: 3840,
                y: 0,
                scale: 1.0,
                transform: 0,
                enabled: true,
                dpms: true,
                focused: false,
                available_modes: vec![
                    MonitorMode { width: 1920, height: 1080, refresh_rate: 144.0 },
                    MonitorMode { width: 1920, height: 1080, refresh_rate: 60.0 },
                    MonitorMode { width: 1280, height: 720, refresh_rate: 60.0 },
                ],
            },
            Monitor {
                id: 2,
                name: "eDP-1".into(),
                description: "Demo 14\" Laptop Display".into(),
                width: 2880,
                height: 1800,
                refresh_rate: 120.0,
                x: 0,
                y: 2160,
                scale: 2.0,
                transform: 0,
                enabled: true,
                dpms: true,
                focused: false,
                available_modes: vec![
                    MonitorMode { width: 2880, height: 1800, refresh_rate: 120.0 },
                    MonitorMode { width: 2880, height: 1800, refresh_rate: 60.0 },
                    MonitorMode { width: 1920, height: 1200, refresh_rate: 60.0 },
                ],
            },
        ])
    }

    fn apply(&self, configs: &[MonitorConfig]) -> Result<(), String> {
        eprintln!("[demo] Would apply:");
        for c in configs {
            eprintln!("  {}", c.to_hyprland_line());
        }
        Ok(())
    }

    fn persist(&self, configs: &[MonitorConfig]) -> Result<String, String> {
        eprintln!("[demo] Would persist {} monitor config(s)", configs.len());
        Ok("(demo mode - not saved)".into())
    }

    fn set_primary(&self, monitor_name: &str) -> Result<(), String> {
        eprintln!("[demo] Would set primary: {monitor_name}");
        Ok(())
    }

    fn identify(&self, monitors: &[Monitor]) -> Result<(), String> {
        eprintln!("[demo] Identifying {} monitors:", monitors.len());
        for (i, m) in monitors.iter().enumerate() {
            eprintln!("  [{}] {} - {}x{}", i + 1, m.name, m.width, m.height);
        }
        Ok(())
    }

    fn name(&self) -> &'static str {
        "Demo"
    }
}
