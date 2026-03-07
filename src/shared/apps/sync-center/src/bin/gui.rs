// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 smplOS Team

//! sync-center GUI - GTK4 interface for managing sync profiles

use gtk4::prelude::*;
use gtk4::{Application, ApplicationWindow, Label, Box, Orientation};

fn main() {
    let app = Application::builder()
        .application_id("org.smpl.SyncCenter")
        .build();

    app.connect_activate(build_ui);
    app.run();
}

fn build_ui(app: &Application) {
    let window = ApplicationWindow::builder()
        .application(app)
        .default_width(600)
        .default_height(400)
        .title("sync-center")
        .build();

    let vbox = Box::new(Orientation::Vertical, 5);
    let label = Label::new(Some("sync-center - Directory Synchronization Manager"));
    vbox.append(&label);

    window.set_child(Some(&vbox));
    window.present();
}
