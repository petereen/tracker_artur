/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0D1117',
        surface: '#161B22',
        surface2: '#1C2128',
        surface3: '#21262D',
        border: '#30363D',
        border2: '#21262D',
        text: '#E6EDF3',
        muted: '#7D8590',
        muted2: '#484F58',
        accent: '#388BFD',
        'accent-dim': '#1C3A6B',
        green: '#3FB950',
        'green-dim': '#1A3A23',
        yellow: '#D29922',
        'yellow-dim': '#3A2E0F',
        red: '#F85149',
        'red-dim': '#3A1515',
        purple: '#BC8CFF',
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      fontSize: { base: '14px' },
    },
  },
  plugins: [],
}
