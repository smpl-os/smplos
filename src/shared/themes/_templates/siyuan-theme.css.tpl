/* smplOS SiYuan theme — auto-generated, do not edit manually */
/* Overrides SiYuan's default daylight/midnight variables with smplOS palette */

:root {
    /* ── Primary / accent colors ────────────────────────────────────── */
    --b3-theme-primary: {{ accent }};
    --b3-theme-primary-light: rgba({{ accent_rgb }}, 0.54);
    --b3-theme-primary-lighter: rgba({{ accent_rgb }}, 0.38);
    --b3-theme-primary-lightest: rgba({{ accent_rgb }}, 0.12);
    --b3-theme-secondary: {{ accent_alt }};

    /* ── Backgrounds / surfaces ─────────────────────────────────────── */
    --b3-theme-background: {{ background }};
    --b3-theme-background-light: {{ bg_light }};
    --b3-theme-surface: {{ surface }};
    --b3-theme-surface-light: rgba({{ surface_rgb }}, 0.86);
    --b3-theme-surface-lighter: {{ bg_lighter }};

    /* ── Semantic status colors ─────────────────────────────────────── */
    --b3-theme-error: {{ danger }};
    --b3-theme-success: {{ success }};

    /* ── Text on coloured backgrounds ──────────────────────────────── */
    --b3-theme-on-primary: #fff;
    --b3-theme-on-secondary: #fff;
    --b3-theme-on-background: {{ foreground }};
    --b3-theme-on-surface: {{ fg_dim }};
    --b3-theme-on-surface-light: {{ fg_alt }};
    --b3-theme-on-error: #fff;

    /* ── Toolbar ────────────────────────────────────────────────────── */
    --b3-toolbar-background: {{ surface }};
    --b3-toolbar-blur-background: {{ surface }};
    --b3-toolbar-color: {{ fg_dim }};
    --b3-toolbar-hover: {{ bg_light }};

    /* ── Borders ────────────────────────────────────────────────────── */
    --b3-border-color: {{ bg_lighter }};

    /* ── Scrollbar ──────────────────────────────────────────────────── */
    --b3-scroll-color: rgba({{ muted_rgb }}, 0.4);

    /* ── List hover ─────────────────────────────────────────────────── */
    --b3-list-hover: rgba({{ accent_rgb }}, 0.08);
    --b3-list-icon-hover: rgba({{ fg_dim_rgb }}, 0.1);

    /* ── Menu ───────────────────────────────────────────────────────── */
    --b3-menu-background: {{ surface }};

    /* ── Tooltips ───────────────────────────────────────────────────── */
    --b3-tooltips-background: {{ background }};
    --b3-tooltips-color: {{ foreground }};
    --b3-tooltips-second-color: {{ fg_dim }};
    --b3-tooltips-shadow: 0 2px 8px rgba({{ background_rgb }}, 0.3);

    /* ── Empty / placeholder text ──────────────────────────────────── */
    --b3-empty-color: {{ fg_dim }};

    /* ── Mask / overlay ────────────────────────────────────────────── */
    --b3-mask-background: rgba({{ background_rgb }}, 0.5);

    /* ── Cards (flashcards, spaced-rep) ─────────────────────────────── */
    --b3-card-error-color: {{ danger_bright }};
    --b3-card-error-background: rgba({{ danger_rgb }}, 0.15);
    --b3-card-warning-color: {{ warning_bright }};
    --b3-card-warning-background: rgba({{ warning_rgb }}, 0.15);
    --b3-card-info-color: {{ info_bright }};
    --b3-card-info-background: rgba({{ info_rgb }}, 0.15);
    --b3-card-success-color: {{ success_bright }};
    --b3-card-success-background: rgba({{ success_rgb }}, 0.15);

    /* ── Shadows ────────────────────────────────────────────────────── */
    --b3-point-shadow: 0 0 1px 0 rgba({{ background_rgb }}, 0.2),
                       0 0 2px 0 rgba({{ background_rgb }}, 0.3);
    --b3-dialog-shadow: 0 8px 24px rgba({{ background_rgb }}, 0.4);

    /* ── Highlight / find-in-page ───────────────────────────────────── */
    --b3-highlight-background: rgba({{ warning_rgb }}, 0.40);
    --b3-highlight-current-background: rgba({{ warning_rgb }}, 0.65);
    --b3-highlight-color: {{ foreground }};

    /* ── Select dropdown ───────────────────────────────────────────── */
    --b3-select-background:
        url("data:image/svg+xml;utf8,<svg fill='{{ fg_dim }}' height='24' viewBox='0 0 24 24' width='24' xmlns='http://www.w3.org/2000/svg'><path d='M7 10l5 5 5-5z'/><path d='M0 0h24v24H0z' fill='none'/></svg>")
        no-repeat right 2px center {{ background }};

    /* ── Switch toggle ─────────────────────────────────────────────── */
    --b3-switch-background: {{ bg_lighter }};
    --b3-switch-border: {{ fg_alt }};
    --b3-switch-hover: rgba({{ fg_dim_rgb }}, 0.06);
    --b3-switch-checked: #fff;
    --b3-switch-checked-background: {{ accent }};
    --b3-switch-checked-hover: rgba({{ accent_rgb }}, 0.18);
    --b3-switch-checked-hover2: rgba({{ accent_rgb }}, 0.06);

    /* ── Protyle editor — code blocks ──────────────────────────────── */
    --b3-protyle-code-background: {{ bg_light }};

    /* ── Protyle editor — inline element colors ────────────────────── */
    --b3-protyle-inline-strong-color: inherit;
    --b3-protyle-inline-em-color: inherit;
    --b3-protyle-inline-u-color: inherit;
    --b3-protyle-inline-s-color: inherit;
    --b3-protyle-inline-link-color: {{ accent }};
    --b3-protyle-inline-mark-background: rgba({{ warning_rgb }}, 0.40);
    --b3-protyle-inline-mark-color: {{ foreground }};
    --b3-protyle-inline-tag-color: {{ fg_dim }};
    --b3-protyle-inline-blockref-color: {{ accent_alt }};
    --b3-protyle-inline-fileref-color: {{ success }};

    /* ── Callout blocks ────────────────────────────────────────────── */
    --b3-callout-note: {{ accent }};
    --b3-callout-tip: {{ success }};
    --b3-callout-caution: {{ danger }};
    --b3-callout-important: {{ accent_alt }};
    --b3-callout-warning: {{ warning }};

    /* ── Table ──────────────────────────────────────────────────────── */
    --b3-table-even-background: rgba({{ foreground_rgb }}, 0.03);

    /* ── Database / attribute view ─────────────────────────────────── */
    --b3-av-gallery-shadow: rgba({{ background_rgb }}, 0.06) 0 2px 4px 0,
                            {{ bg_lighter }} 0 0 0 1px;

    /* ── Embed / blockquote / parent ───────────────────────────────── */
    --b3-embed-background: transparent;
    --b3-bq-background: transparent;
    --b3-parent-background: {{ background }};
}
