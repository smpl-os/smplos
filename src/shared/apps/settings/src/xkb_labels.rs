use xkbcommon::xkb::{self, Keycode};

/// Resolved label data for a single key, ready for Slint.
pub struct KeyInfo {
    pub base: String,
    pub english: String,
    pub width: f32,
    pub is_modifier: bool,
}

/// Physical key on the keyboard: keycode + size + optional fixed label.
struct PhysicalKey {
    keycode: u32,
    width: f32,
    fixed_label: &'static str,
}

impl PhysicalKey {
    fn key(kc: u32) -> Self {
        Self { keycode: kc, width: 1.0, fixed_label: "" }
    }
    fn wide(kc: u32, w: f32) -> Self {
        Self { keycode: kc, width: w, fixed_label: "" }
    }
    fn modifier(kc: u32, w: f32, label: &'static str) -> Self {
        Self { keycode: kc, width: w, fixed_label: label }
    }
}

/// Standard ANSI keyboard layout: 5 rows, keycodes are evdev + 8.
fn physical_layout() -> [Vec<PhysicalKey>; 5] {
    [
        // Row 0: number row
        vec![
            PhysicalKey::key(49),
            PhysicalKey::key(10), PhysicalKey::key(11),
            PhysicalKey::key(12), PhysicalKey::key(13),
            PhysicalKey::key(14), PhysicalKey::key(15),
            PhysicalKey::key(16), PhysicalKey::key(17),
            PhysicalKey::key(18), PhysicalKey::key(19),
            PhysicalKey::key(20), PhysicalKey::key(21),
            PhysicalKey::modifier(22, 2.0, "Bksp"),
        ],
        // Row 1: top letter row (QWERTY)
        vec![
            PhysicalKey::modifier(23, 1.5, "Tab"),
            PhysicalKey::key(24), PhysicalKey::key(25),
            PhysicalKey::key(26), PhysicalKey::key(27),
            PhysicalKey::key(28), PhysicalKey::key(29),
            PhysicalKey::key(30), PhysicalKey::key(31),
            PhysicalKey::key(32), PhysicalKey::key(33),
            PhysicalKey::key(34), PhysicalKey::key(35),
            PhysicalKey::wide(51, 1.5),
        ],
        // Row 2: home row (ASDF)
        vec![
            PhysicalKey::modifier(66, 1.75, "Caps"),
            PhysicalKey::key(38), PhysicalKey::key(39),
            PhysicalKey::key(40), PhysicalKey::key(41),
            PhysicalKey::key(42), PhysicalKey::key(43),
            PhysicalKey::key(44), PhysicalKey::key(45),
            PhysicalKey::key(46),
            PhysicalKey::key(47), PhysicalKey::key(48),
            PhysicalKey::modifier(36, 2.25, "Enter"),
        ],
        // Row 3: bottom row (ZXCV)
        vec![
            PhysicalKey::modifier(50, 2.25, "Shift"),
            PhysicalKey::key(52), PhysicalKey::key(53),
            PhysicalKey::key(54), PhysicalKey::key(55),
            PhysicalKey::key(56), PhysicalKey::key(57),
            PhysicalKey::key(58),
            PhysicalKey::key(59), PhysicalKey::key(60),
            PhysicalKey::key(61),
            PhysicalKey::modifier(62, 2.75, "Shift"),
        ],
        // Row 4: space row
        vec![
            PhysicalKey::modifier(37, 1.25, "Ctrl"),
            PhysicalKey::modifier(133, 1.25, "Super"),
            PhysicalKey::modifier(64, 1.25, "Alt"),
            PhysicalKey::modifier(65, 6.25, ""),
            PhysicalKey::modifier(108, 1.25, "Alt"),
            PhysicalKey::modifier(134, 1.25, "Super"),
            PhysicalKey::modifier(135, 1.25, "Menu"),
            PhysicalKey::modifier(105, 1.25, "Ctrl"),
        ],
    ]
}

fn resolve_row(
    row: Vec<PhysicalKey>,
    state_base: &xkb::State,
    us_state: Option<&xkb::State>,
) -> Vec<KeyInfo> {
    row.into_iter()
        .map(|pk| {
            if !pk.fixed_label.is_empty() {
                return KeyInfo {
                    base: pk.fixed_label.to_string(),
                    english: String::new(),
                    width: pk.width,
                    is_modifier: true,
                };
            }

            let base = state_base.key_get_utf8(Keycode::new(pk.keycode));
            let base = base.chars().filter(|c| !c.is_control()).collect::<String>();

            let eng = us_state
                .map(|s| {
                    s.key_get_utf8(Keycode::new(pk.keycode))
                        .chars()
                        .filter(|c| !c.is_control())
                        .collect::<String>()
                        .to_uppercase()
                })
                .unwrap_or_default();

            let show_eng = !eng.is_empty()
                && eng != base
                && eng.to_lowercase() != base.to_lowercase();

            KeyInfo {
                base: if base.is_empty() { " ".into() } else { base },
                english: if show_eng { eng } else { String::new() },
                width: pk.width,
                is_modifier: false,
            }
        })
        .collect()
}

/// Resolve key labels for the given XKB layout and variant.
/// Returns (layout_name, row0, row1, row2, row3, row4).
pub fn resolve(layout: &str, variant: &str) -> (String, Vec<KeyInfo>, Vec<KeyInfo>, Vec<KeyInfo>, Vec<KeyInfo>, Vec<KeyInfo>) {
    let ctx = xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
    let keymap = xkb::Keymap::new_from_names(
        &ctx, "", "", layout, variant, None,
        xkb::KEYMAP_COMPILE_NO_FLAGS,
    );

    let [r0, r1, r2, r3, r4] = physical_layout();

    let us_state = if layout != "us" || !variant.is_empty() {
        xkb::Keymap::new_from_names(
            &ctx, "", "", "us", "", None,
            xkb::KEYMAP_COMPILE_NO_FLAGS,
        ).map(|km| xkb::State::new(&km))
    } else {
        None
    };

    match keymap {
        Some(km) => {
            let name = {
                let raw = km.layout_get_name(0);
                if raw.is_empty() {
                    if variant.is_empty() { layout.to_string() }
                    else { format!("{} ({})", layout, variant) }
                } else {
                    raw.to_string()
                }
            };

            let state_base = xkb::State::new(&km);

            (
                name,
                resolve_row(r0, &state_base, us_state.as_ref()),
                resolve_row(r1, &state_base, us_state.as_ref()),
                resolve_row(r2, &state_base, us_state.as_ref()),
                resolve_row(r3, &state_base, us_state.as_ref()),
                resolve_row(r4, &state_base, us_state.as_ref()),
            )
        }
        None => {
            let name = format!("Unknown layout: {}", layout);
            let fallback = |row: Vec<PhysicalKey>| -> Vec<KeyInfo> {
                row.into_iter()
                    .map(|pk| KeyInfo {
                        base: if pk.fixed_label.is_empty() { "?".into() } else { pk.fixed_label.into() },
                        english: String::new(),
                        width: pk.width,
                        is_modifier: !pk.fixed_label.is_empty(),
                    })
                    .collect()
            };
            (name, fallback(r0), fallback(r1), fallback(r2), fallback(r3), fallback(r4))
        }
    }
}
