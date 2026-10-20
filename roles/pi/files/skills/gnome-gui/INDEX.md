# GNOME Agent Library — Index

> Start at [SKILL.md](SKILL.md), the router. This index catalogs content
> shipped in this skill directory.

## Core References

- [COMPONENT-LIBRARY.md](COMPONENT-LIBRARY.md) — 42-widget catalog with
  Blueprint/XML examples
- [INTENT-MAP.md](INTENT-MAP.md) — intent-to-pattern lookup with implementation
  examples

## Workflow Skills

| Skill | What it teaches |
|-------|-----------------|
| [quick-start](skills/quick-start/SKILL.md) | Minimal compliant GNOME app from scratch |
| [language-quickstart](skills/language-quickstart/SKILL.md) | Build setup for Python, Rust, C, Vala, and GJS |
| [hig-audit](skills/hig-audit/SKILL.md) | 12-category HIG compliance audit and fix loop |
| [flatpak-packaging](skills/flatpak-packaging/SKILL.md) | Flatpak manifest, sandbox permissions, and Flathub submission |
| [github-actions-ci](skills/github-actions-ci/SKILL.md) | CI, Flatpak release automation, and Xvfb GUI smoke tests |

## Pattern Skills

| Skill | What it teaches |
|-------|-----------------|
| [preferences-dialog](skills/preferences-dialog/SKILL.md) | Preferences dialog, Ctrl+comma, and GSettings |
| [gsettings-backend](skills/gsettings-backend/SKILL.md) | GSettings schema, binding, and window state |
| [delete-with-undo](skills/delete-with-undo/SKILL.md) | Destructive actions and undo toasts |
| [view-switcher](skills/view-switcher/SKILL.md) | Flat page switching with 3–5 tabs |
| [tabbed-documents](skills/tabbed-documents/SKILL.md) | AdwTabView multi-document support |
| [sidebar-navigation](skills/sidebar-navigation/SKILL.md) | OverlaySplitView and NavigationSplitView |
| [adaptive-layout](skills/adaptive-layout/SKILL.md) | Breakpoints and responsive design |
| [header-bar](skills/header-bar/SKILL.md) | Header bar layout, buttons, and tooltips |
| [empty-state](skills/empty-state/SKILL.md) | Loading spinners, empty states, and StatusPages |
| [toast-feedback](skills/toast-feedback/SKILL.md) | Toasts, undo buttons, and banners |
| [search-pattern](skills/search-pattern/SKILL.md) | SearchBar, live filtering, and no-results state |
| [radio-group](skills/radio-group/SKILL.md) | CheckButton radio groups in preferences |
| [wizard-assistant](skills/wizard-assistant/SKILL.md) | Sequential setup flow and navigation |
| [carousel-tour](skills/carousel-tour/SKILL.md) | AdwCarousel onboarding with navigation dots |
| [shortcuts-window](skills/shortcuts-window/SKILL.md) | Shortcuts help window and standard accelerators |
| [about-dialog](skills/about-dialog/SKILL.md) | AdwAboutDialog and AppStream metadata |
| [accessibility](skills/accessibility/SKILL.md) | Labels, roles, keyboard navigation, and Orca testing |

## Components

The [components/](components/) directory contains 36 reference files covering
the widget catalog in [COMPONENT-LIBRARY.md](COMPONENT-LIBRARY.md).

## Design Tokens

| File | Contents |
|------|----------|
| [tokens/spacing.md](tokens/spacing.md) | Margin, padding, and spacing scale |
| [tokens/sizing.md](tokens/sizing.md) | Window sizing, sidebar widths, and breakpoints |
| [tokens/typography.md](tokens/typography.md) | Font classes and capitalization rules |
| [tokens/style-classes.md](tokens/style-classes.md) | CSS classes and compound patterns |
| [tokens/icons.md](tokens/icons.md) | Symbolic icon reference by category |

## Reference

- [reference/app-architecture.md](reference/app-architecture.md) — window
  structure, navigation choice, adaptive strategy, and project layout
- [reference/app-templates.md](reference/app-templates.md) and
  [reference/layout-recipes.md](reference/layout-recipes.md) — skeleton widget
  trees
- [reference/anti-patterns.md](reference/anti-patterns.md) — anti-patterns and
  build checklist
- [reference/hig/](reference/hig/) — 47 mirrored GNOME HIG pages
- [reference/icons.md](reference/icons.md) — Adwaita symbolic icon catalog
