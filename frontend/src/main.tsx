import { StrictMode, useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { Theme } from '@astryxdesign/core'
import '@astryxdesign/core/reset.css'
import '@astryxdesign/core/astryx.css'
import App from './App'
import { oyunsTheme } from './theme/oyunsTheme'
import { useColorThemeStore } from './store/colorTheme'
import { initializeRuntimeClass } from './platform/runtime'
import { NativeBootBoundary } from './platform/updater'
import { installNativeTelegramAuth } from './platform/telegram-auth'
import { startTelemetry } from './platform/telemetry'
import './index.css'
import './workspace-features.css'
import './i18n'

initializeRuntimeClass()
void installNativeTelegramAuth()
startTelemetry()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function ThemedRoot({ children }: { children: ReactNode }) {
  const mode = useColorThemeStore((state) => state.theme)
  useEffect(() => {
    // Browser chrome (Android address bar, installed-app status bar) follows the app theme.
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', mode === 'dark' ? '#0b172a' : '#f4f6fa')
  }, [mode])
  return <Theme theme={oyunsTheme} mode={mode}>{children}</Theme>
}

const PHONE_QUERY = '(max-width: 800px)'

function AppToaster() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches)
  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY)
    const onChange = () => setPhone(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return <Toaster
    position={phone ? 'top-center' : 'top-right'}
    containerStyle={phone ? { top: 'calc(10px + env(safe-area-inset-top))' } : undefined}
    toastOptions={{ style: { background: '#161B22', color: '#E6EDF3', border: '1px solid #30363D', ...(phone ? { borderRadius: '14px', maxWidth: 'calc(100vw - 24px)' } : {}) } }}
  />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemedRoot>
      <QueryClientProvider client={queryClient}>
        <NativeBootBoundary><App /></NativeBootBoundary>
        <AppToaster />
      </QueryClientProvider>
    </ThemedRoot>
  </StrictMode>,
)
