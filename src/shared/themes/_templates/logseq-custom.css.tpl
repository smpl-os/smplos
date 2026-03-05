/* smplOS theme — auto-generated, do not edit manually */

:root {
  --ls-primary-background-color: {{ background }} !important;
  --ls-secondary-background-color: {{ bg_light }} !important;
  --ls-tertiary-background-color: {{ bg_lighter }} !important;
  --ls-quaternary-background-color: {{ bg_lighter }} !important;

  --ls-primary-text-color: {{ foreground }} !important;
  --ls-secondary-text-color: {{ muted }} !important;

  --ls-link-text-color: {{ accent }} !important;
  --ls-link-text-hover-color: {{ accent_bright }} !important;
  --ls-active-primary-color: {{ accent }} !important;
  --ls-active-secondary-color: {{ accent }} !important;

  --ls-border-color: {{ surface }} !important;
  --ls-secondary-border-color: {{ bg_lighter }} !important;

  --ls-selection-background-color: {{ selection_background }} !important;
  --ls-block-highlight-color: {{ bg_light }} !important;
  --ls-page-properties-background-color: {{ bg_light }} !important;
  --ls-block-properties-background-color: {{ bg_light }} !important;
  --ls-table-tr-even-background-color: {{ bg_light }} !important;
  --ls-page-inline-code-bg-color: {{ bg_light }} !important;

  --ls-focus-ring-color: {{ accent }} !important;
  --ls-a-chosen-bg: {{ bg_light }} !important;
  --ls-page-checkbox-color: {{ accent }} !important;
  --ls-page-checkbox-border-color: {{ muted }} !important;

  --ls-guideline-color: {{ surface }} !important;
  --ls-block-bullet-color: {{ muted }} !important;

  --ls-scrollbar-foreground-color: {{ bg_lighter }} !important;
  --ls-scrollbar-background-color: {{ background }} !important;

  --ls-head-text-color: {{ foreground }} !important;
  --ls-icon-color: {{ muted }} !important;

  --color-level-1: {{ background }} !important;
  --color-level-2: {{ bg_light }} !important;
  --color-level-3: {{ bg_lighter }} !important;

  --ls-highlight-color-gray: {{ bg_lighter }} !important;
  --ls-highlight-color-red: {{ danger }} !important;
  --ls-highlight-color-green: {{ success }} !important;
  --ls-highlight-color-blue: {{ accent }} !important;
  --ls-highlight-color-yellow: {{ warning }} !important;
  --ls-highlight-color-purple: {{ accent_alt }} !important;
  --ls-highlight-color-pink: {{ accent_alt }} !important;

  --ls-cloze-text-color: {{ accent }} !important;
}

/* Override code mirror / code block backgrounds */
.CodeMirror,
.cm-s-solarized,
.extensions__code .code-editor {
  background-color: {{ bg_light }} !important;
  color: {{ foreground }} !important;
}
