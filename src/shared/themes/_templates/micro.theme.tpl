# smplOS micro colorscheme — auto-generated from colors.toml
# Managed by generate-theme-configs.sh — do not edit by hand

# ── Base ─────────────────────────────────────────────────────────────────────
color-link default "{{ foreground }},{{ background }}"
color-link background "{{ background }},{{ background }}"

# ── UI chrome ────────────────────────────────────────────────────────────────
color-link line-number "{{ fg_alt }},{{ background }}"
color-link current-line-number "{{ accent }},{{ background }}"
color-link statusline "{{ background }},{{ accent }}"
color-link tabbar "{{ fg_alt }},{{ bg_light }}"
color-link indent-char "{{ muted }},"
color-link scrollbar "{{ muted }},"

# ── Selection & search ───────────────────────────────────────────────────────
color-link selection "{{ selection_foreground }},{{ selection_background }}"

# ── Gutter / diff ────────────────────────────────────────────────────────────
color-link gutter-error "{{ danger }},"
color-link gutter-warning "{{ warning }},"
color-link diff-added "{{ success }},"
color-link diff-modified "{{ warning }},"
color-link diff-deleted "{{ danger }},"

# ── Syntax ───────────────────────────────────────────────────────────────────
color-link comment "{{ fg_alt }}"
color-link todo "{{ warning }},bold"

color-link keyword "{{ danger }}"
color-link keyword.control "{{ accent_alt }}"
color-link keyword.operator "{{ foreground }}"

color-link type "{{ success }}"
color-link type.keyword "{{ success }}"

color-link constant "{{ accent_bright }}"
color-link constant.string "{{ success }}"
color-link constant.number "{{ warning }}"
color-link constant.bool "{{ accent_alt }}"
color-link constant.character "{{ success }}"

color-link identifier "{{ accent }}"

color-link function "{{ accent }}"

color-link statement "{{ danger }}"
color-link preproc "{{ accent }}"
color-link special "{{ warning }}"
color-link underlined "{{ info }}"
color-link error "{{ danger }},bold"
