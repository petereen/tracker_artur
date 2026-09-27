import { create } from 'zustand'
import { safeLocalStorage } from '../platform/runtime'

export type ColorTheme = 'light' | 'dark'

const STORAGE_KEY = 'oyuns-theme'

interface ColorThemeState {
  theme: ColorTheme
  setTheme: (theme: ColorTheme | ((current: ColorTheme) => ColorTheme)) => void
}

// Single source for light/dark: <Theme mode> in main.tsx writes data-theme on <html>
// from this value (Astryx removes data-theme when mode is left at 'system').
export const useColorThemeStore = create<ColorThemeState>((set, get) => ({
  theme: safeLocalStorage().get(STORAGE_KEY) === 'dark' ? 'dark' : 'light',
  setTheme: (next) => {
    const theme = typeof next === 'function' ? next(get().theme) : next
    safeLocalStorage().set(STORAGE_KEY, theme)
    set({ theme })
  },
}))
