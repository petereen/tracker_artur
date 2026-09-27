# Astryx Setup & Usage Guide

This project uses **Astryx v0.6.3** — Meta's production-grade React 19 component library with 164+ accessible, themeable components powered by StyleX.

## ✅ Setup Complete

- ✓ Astryx packages installed: `@astryxdesign/core`, `@astryxdesign/theme-neutral`, `@astryxdesign/cli`, `@stylexjs/stylex`
- ✓ React upgraded to v19
- ✓ Theme configured (neutral theme with CSS imports in `src/main.tsx`)
- ✓ `AGENTS.md` generated with component inventory and conventions
- ✓ Build verified (test: `npm run build`)

## Quick Start: Building UI

**Always start here for any new UI:**

```bash
npx astryx build "<your-feature-idea>"
```

Example:
```bash
npx astryx build "a task card with status badge and priority indicator"
```

This returns:
- Closest matching [page] template (if applicable)
- [block]s (reusable layout sections) you need
- [component]s to build it

Then scaffold the template:
```bash
npx astryx template <TemplateName>
```

## Component Discovery

**Before coding any component, check its props:**

```bash
npx astryx component Button
npx astryx component Card
npx astryx component Table
```

Returns: prop signature, type info, live examples.

**Browse all 164 components:**
```bash
npx astryx component --list
```

**Search for something:**
```bash
astryx search "form input"
astryx search "status indicator"
```

## Styling Rules

### ✅ DO THIS:

1. **Use component props** for all styling:
   ```jsx
   import { Button } from '@astryxdesign/core'
   
   <Button variant="primary" size="lg" disabled={false}>
     Click me
   </Button>
   ```

2. **Use Tailwind utilities backed by Astryx tokens** when a component prop doesn't exist:
   ```jsx
   <div className="bg-surface text-primary rounded-lg p-4 border border-neutral-200">
     Content
   </div>
   ```

3. **Reference available tokens** before hardcoding values:
   ```bash
   npx astryx docs tokens
   ```

### ❌ NEVER DO THIS:

- ❌ `<div>` for layout — use Astryx Layout, Stack, or specialized components
- ❌ `style={{…}}` — use className with tokens instead
- ❌ Hardcoded values: `bg-[#fff]`, `p-[13px]`, `text-[14px]`
- ❌ `@apply` or imported `.css` for component styling
- ❌ `className="text-[#333]"` — use token-backed utility (e.g. `text-primary`)

## Common Workflows

### Building a Form
```bash
npx astryx search "form"
npx astryx template FormPage
npx astryx component TextField
npx astryx component Select
npx astryx component Button
```

### Creating a List/Table
```bash
npx astryx docs layout  # Understand grid/table patterns
npx astryx template TablePage
npx astryx component Table
npx astryx component List
```

### Building a Modal/Dialog
```bash
npx astryx component Dialog
npx astryx component Modal
```

### Responsive Design
```bash
npx astryx docs layout  # Learn breakpoint conventions
```

## CLI Reference

All commands use `npx astryx`:

| Command | Purpose |
|---------|---------|
| `build "<idea>"` | **START HERE** — AI returns closest templates + blocks + components |
| `template --list` | Browse page and block recipes |
| `template <Name>` | Scaffold a page/block template |
| `component --list` | See all 164 components by category |
| `component <Name>` | Props, types, examples for a component |
| `search "<query>"` | Find component/hook/doc/template matching query |
| `docs <topic>` | Read documentation (layout, spacing, tokens, theme, motion, icons, etc.) |
| `swizzle <Name>` | Eject component source for deep customization (rare) |
| `doctor` | Verify setup health |
| `--help` | See all commands |

## Tokens & Theming

All design values (colors, spacing, typography, shadows, etc.) are **tokens**:

```bash
npx astryx docs tokens  # See all available tokens
```

In code:
```jsx
// Use token names as Tailwind utilities
<div className="bg-surface text-primary p-4 rounded-lg">
  <p className="text-sm text-secondary">Secondary text</p>
</div>

// Available token categories:
// - Colors: surface, primary, secondary, success, warning, error, neutral-*
// - Spacing: p-0 through p-12, gap-*, etc.
// - Typography: text-sm, text-base, text-lg, font-semibold, etc.
// - Shadows: shadow-sm, shadow, shadow-lg
// - Radius: rounded-none, rounded-sm, rounded-lg, rounded-full
```

## Custom Theming

The project uses **neutral theme** by default. To build a custom theme:

```bash
npx astryx theme template  # Create theme scaffold
# Edit the theme file
npx astryx theme build <file>  # Generate theme artifacts
```

Then wire it in `astryx.config.mjs`:
```javascript
export default {
  theme: './my-custom-theme.json',
};
```

## Accessibility

Astryx components are **built accessible** by default. All components follow WCAG 2.1 AA. You don't need to add `aria-*` attributes manually — they're included.

## Dark Mode

Built-in — the theme automatically respects `prefers-color-scheme`.

## Internationalization (i18n)

Astryx supports 30+ locales. See:
```bash
npx astryx docs internationalization
```

## Troubleshooting

**Components don't have styling:**
- Ensure `src/main.tsx` imports the CSS files:
  ```jsx
  import '@astryxdesign/core/reset.css'
  import '@astryxdesign/core/astryx.css'
  import '@astryxdesign/theme-neutral/theme.css'
  import { Theme } from '@astryxdesign/core'
  import { neutralTheme } from '@astryxdesign/theme-neutral/built'
  // Wrap app in <Theme theme={neutralTheme}>
  ```

**Build errors:**
```bash
npx astryx doctor  # Verify setup
npm run build      # Full rebuild
```

**Can't find a component?**
```bash
npx astryx search "<description>"
```

## Next Steps

1. Read `AGENTS.md` for AI-specific guidance (generated by CLI)
2. Run `npx astryx build "describe your first feature"` to get started
3. Use `npx astryx component <Name>` before building anything
4. Study one template: `npx astryx template <Name>`
5. Check tokens: `npx astryx docs tokens`

---

For full documentation, visit [Astryx Docs](https://astryx.atmeta.com/docs).
