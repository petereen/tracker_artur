import { defineTheme } from '@astryxdesign/core/theme'
import { neutralTheme } from '@astryxdesign/theme-neutral'

// OYUNS brand theme for Astryx. Seeds match --color-accent in index.css
// (light #2d62ec, dark #7d9dff) so Astryx components and legacy CSS share one blue,
// and --color-on-accent is derived from the same seeds.
export const oyunsTheme = defineTheme({
  name: 'oyuns',
  extends: neutralTheme,
  color: { accent: ['#2d62ec', '#7d9dff'], neutralStyle: 'cool' },
  typography: {
    body: { family: 'Montserrat', fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
    heading: { family: 'Montserrat', fallbacks: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  },
})
