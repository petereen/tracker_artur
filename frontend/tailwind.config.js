/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)', surface: 'var(--color-surface)', surface2: 'var(--color-surface-2)',
        surface3: 'var(--color-surface-3)', border: 'var(--color-border)', border2: 'var(--color-border-soft)',
        text: 'var(--color-text)', muted: 'var(--color-muted)', muted2: 'var(--color-muted-2)',
        accent: 'var(--color-accent)', 'accent-dim': 'var(--color-accent-soft)', green: 'var(--color-green)',
        'green-dim': 'var(--color-green-soft)', yellow: 'var(--color-amber)', 'yellow-dim': 'var(--color-amber-soft)',
        red: 'var(--color-red)', 'red-dim': 'var(--color-red-soft)', purple: 'var(--color-purple)',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      fontSize: { base: '14px' },
    },
  },
  plugins: [],
}
