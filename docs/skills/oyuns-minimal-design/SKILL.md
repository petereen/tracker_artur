---
name: oyuns-minimal-design
description: Build, refactor, or audit tracker_artur frontend UI with a restrained, typography-led OYUNS visual system. Use for React/Vite pages, components, forms, dashboards, navigation, and responsive polish; do not apply to backend-only work.
---

# OYUNS minimal product design

Use this skill when changing the frontend in `tracker_artur`. It adapts the supplied Codex minimal-design brief to the product that actually exists here: an OYUNS enterprise workspace with dense operational screens, Mongolian-first copy, light/dark themes, and an established token system.

The goal is calm, exact, useful UI. Let structure, type, spacing, and content carry the hierarchy. Keep decoration subordinate to the task. Do not copy the source brief's literal black-only palette, Open Sans typography, or editorial-photography assumptions.

## Before editing

Inspect the target page and its nearest shared primitives before adding CSS. In particular, check:

- `frontend/src/index.css` for the current light and dark token values and shared layout rules.
- `frontend/src/components/ui.tsx` and `frontend/src/components/EnterpriseShell.tsx` for reusable controls, surfaces, navigation, and responsive behavior.
- Existing page tests, i18n keys, and neighboring screens for interaction and copy conventions.

Prefer an existing component or token over a new local pattern. Keep unrelated visual systems untouched, especially when a screen already has a deliberate workflow-specific treatment.

## OYUNS tokens

The source of truth is `frontend/src/index.css`. Use these semantic variables rather than copying hex values into component styles:

| Role | Current token/value | Use |
| --- | --- | --- |
| Page background | `--color-bg` / `#f4f6fa` | App canvas in the light theme |
| Default surface | `--color-surface` / `#ffffff` | Forms, panels, dialogs, and content surfaces |
| Subtle surface | `--color-surface-2` / `#f8f9fc` | Quiet controls and secondary grouping |
| Raised/strong surface | `--color-surface-3` / `#eef1f6` | Dense secondary regions; use sparingly |
| Text | `--color-text` / `#231f20` | Primary text and dark OYUNS actions |
| Muted text | `--color-muted` / `#667085` | Metadata and supporting copy; keep contrast adequate |
| Accent | `--color-accent` / `#2d62ec` | Primary actions, active states, links, and focus |
| Accent tint | `--color-accent-soft` / `#eaf0ff` | Accent state backgrounds, never decoration by default |
| Success | `--color-green` / `#00c885` | Completed, valid, or successful state |
| Warning | `--color-amber` / `#b06d12` | Review, pending, or caution state |
| Danger | `--color-red` / `#ff3b57` | Errors and destructive state |
| Secondary category | `--color-purple` / `#7951c9` | Existing category semantics only |

Dark mode has a separate token block in the same file. Never hardcode light-theme values into new UI, and never use pure `#000000` as a generic text or surface shortcut. White is a valid surface and inverse foreground; it is not a replacement for the OYUNS palette.

Use `--color-border` and `--color-border-soft` for separation. Use the existing shadow tokens only where overlay depth genuinely needs it; do not add new shadow recipes. If a brand gradient already belongs to a purposeful OYUNS surface or assistant treatment, preserve it, but do not introduce gradients as generic decoration.

## Visual direction

### Structure before decoration

- Treat the page as the canvas. Use the existing background and generous, intentional whitespace instead of stacking ornamental cards.
- Establish hierarchy through heading size, weight, line height, alignment, content order, and spacing before using color or icons.
- Reduce unnecessary containers. Group related content with spacing and dividers; use a surface only when it improves scanning, interaction, or responsive behavior.
- Use dark inverse surfaces (`--color-text` or the established deep-dark token) for a small number of high-emphasis moments, not as a black-card default.
- Use imagery or illustrations only when they convey product content. Do not add decorative artwork to fill an empty state in the enterprise UI.

### Typography

Use Montserrat through `--font-brand`; this repo's brand typeface replaces the source brief's Open Sans. Keep the existing product density and use a restrained scale:

- `12px`: captions, metadata, timestamps, compact helper text.
- `14px`: labels, navigation, secondary UI, compact body copy.
- `16px`: primary body copy, comfortable inputs, important actions.
- `20px`: card or section titles.
- `24px`: page subheadings and dialog titles.
- `32px`: major page titles only when the available space and content justify it.

Use weight 400 for body text, 500–600 for labels and controls, and 700 for page titles. Avoid ultra-light text and avoid making every label bold. Let headings wrap deliberately; do not compress important Mongolian labels to force a single line.

Use a monospace face only for code, IDs, timestamps, or technical values when the surrounding product already supports that convention. It is not an ornamental contrast.

### Spacing and shape

Use the existing 4px rhythm (`--space-1` through `--space-8`). Prefer 4, 8, 12, 16, 24, and 32px over one-off values. Use spacing to show grouping, sequence, priority, and section boundaries.

Use the OYUNS control radius and existing component conventions rather than forcing every element into a capsule. Pill geometry is appropriate for primary/secondary buttons, search, filters, tabs, segmented controls, tags, and compact toggles. Keep textareas, drawers, tables, and dense data panels comfortably shaped with their established radius.

## Component rules

### Buttons and links

- Primary actions use `--color-accent` with a readable white foreground.
- Dark actions may use `--color-text` with white text when the hierarchy calls for a quieter, heavier action.
- Secondary actions use a light/transparent surface with an accent or existing border; do not invent a new neutral.
- Destructive actions use `--color-red` only when the action is actually destructive or has failed.
- Preserve width while loading and expose disabled state without making the label unreadable.
- Provide hover, active, and `:focus-visible` states. A state must not be communicated by color alone.
- Name actions specifically: “Save changes,” “Create report,” “View details,” “Delete employee.” Avoid “Submit,” “Click here,” “Go,” and “Are you sure?” when a direct label is possible.

Links should be typographic and distinguishable by more than color, normally through underline or clear context. Do not reintroduce browser-default blue when it conflicts with the OYUNS tokens.

### Forms and search

- Keep labels visible; placeholder text is an example, not a label.
- Use existing surface, border, radius, and font tokens. Inputs should be comfortable to scan and touch.
- Make required fields, errors, help text, and validation state explicit in both markup and copy.
- Associate errors with controls using `aria-describedby`/`aria-invalid` where appropriate.
- Search should have a specific Mongolian or English placeholder matching the current page, a visible focus state, keyboard-safe clear/submit behavior, and navigable suggestions when present.
- Use a larger radius for multiline fields and long-form editors instead of a tall pill.

### Navigation, tabs, and tables

- Keep navigation labels short, stable, and bilingual where the surrounding product is bilingual.
- Active navigation and selected tabs must have a non-color cue such as fill, weight, underline, border, or position.
- Preserve the responsive desktop/mobile navigation model already used by `EnterpriseShell`.
- Tabs and segmented controls should expose the expected keyboard behavior and selected state.
- Tables should stay white/light and typographic: strong header hierarchy, readable row height, minimal dividers, aligned numbers, and horizontal overflow on narrow screens.
- Use semantic colors in tables only for meaningful status; do not turn every category into a colored badge.

### Cards, dialogs, alerts, and empty states

- Prefer a typographic group or divider over a card whose only purpose is decoration.
- Avoid adding shadows, glassmorphism, blur, tinted panels, or layered neutral backgrounds. For drawers and dialogs, use the existing elevation token only when separation from the page requires it.
- Use black/dark inverse cards sparingly for a selected state, an important summary, or a decisive call to action.
- Dialogs must have a clear title, constrained content, pill-compatible actions, focus trapping, Escape handling where safe, and focus restoration.
- Alerts must include text and recovery guidance. Pair semantic color with an icon, label, border, or heading; never rely on color alone.
- Empty states should say what is absent and offer one clear next step. Do not add decorative illustration solely to make an empty screen feel full.

## Accessibility and motion

Treat accessibility as part of the sparse visual system, not a later audit:

- Meet WCAG 2.2 AA contrast with the actual theme surface and semantic color.
- Give every interactive element a clear `:focus-visible` treatment using the accent or another high-contrast token; it must remain visible on light and dark surfaces.
- Use semantic HTML before ARIA. Keep keyboard order aligned with visual order.
- Make touch targets comfortable, especially icon-only controls in tables and mobile toolbars; add an accessible name and tooltip/context where needed.
- Do not use color as the only signal for selected, success, warning, danger, disabled, or error states.
- Respect `prefers-reduced-motion`. Motion should clarify a state, not decorate an otherwise static screen. Keep ordinary transitions around 100–160ms, popovers around 120–200ms, and dialogs around 160–240ms unless an existing component establishes a different contract.
- Preserve the repo's existing mobile safe-area and responsive behavior.

## Product language

The product is Mongolian-first. Reuse existing i18n keys and terminology instead of embedding new English-only strings in components. Keep copy brief, specific, calm, and action-oriented. Use plain verbs and tell the user what happened and what to do next. Keep the same action name across the flow: a button labeled “Нийтлэх” should produce a message that uses the same term.

For functional UI, avoid sales-heavy taglines, repeated explanations, vague empty states, and labels that describe implementation rather than user intent. Preserve the existing bilingual pattern when a screen already uses one.

## Implementation and review loop

1. Identify the screen's primary job and the existing token/component patterns that support it.
2. Make the smallest coherent visual change; share styles instead of adding local one-off rules.
3. Check light mode, dark mode, mobile width, long Mongolian labels, keyboard focus, empty/loading/error states, and touch targets.
4. Keep the change scoped to the requested surface. Do not flatten purposeful workflow differences into a single generic card system.
5. Run the focused frontend test(s) for the touched component and `npm run build` when feasible. If validation is environment-blocked, report the exact command and blocker.

Before shipping, ask:

- Does the OYUNS palette come from existing semantic tokens?
- Is hierarchy understandable without extra color, shadows, gradients, or illustration?
- Are pills used for the right interactive controls rather than indiscriminately?
- Are selected, focus, error, loading, disabled, and success states obvious without color alone?
- Does the UI remain readable and operable in dark mode and at mobile widths?
- Are labels specific and consistent with the Mongolian-first product vocabulary?
