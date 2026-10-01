import { defineTheme } from '@astryxdesign/core/theme'
import { neutralTheme } from '@astryxdesign/theme-neutral'

// OYUNS brand theme for Astryx. Seeds match --color-accent in index.css
// (light #2d62ec, dark #7d9dff) so Astryx components and legacy CSS share one blue,
// and --color-on-accent is derived from the same seeds.
export const oyunsTheme = defineTheme({
  name: 'oyuns',
  extends: neutralTheme,
  color: { accent: ['#2d62ec', '#7d9dff'], neutralStyle: 'cool' },
  // Surfaces and text match the legacy palette in index.css (--color-bg / --color-surface /
  // --color-surface-2 / --color-text / --color-muted), so Astryx cards and legacy panels sit on
  // the same navy in dark mode instead of neutral near-black.
  tokens: {
    '--color-background-body': ['#f4f6fa', '#0b172a'],
    '--color-background-surface': ['#ffffff', '#111e31'],
    '--color-background-card': ['#ffffff', '#111e31'],
    '--color-background-popover': ['#ffffff', '#15243a'],
    '--color-text-primary': ['#231f20', '#f2f5fa'],
    '--color-text-secondary': ['#667085', '#aab6c7'],
  },
  typography: {
    body: { family: 'Montserrat', fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
    heading: { family: 'Montserrat', fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  },
})
