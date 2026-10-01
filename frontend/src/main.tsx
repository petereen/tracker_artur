import { StrictMode, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { Theme } from '@astryxdesign/core'
import '@astryxdesign/core/reset.css'
import '@astryxdesign/core/astryx.css'
import App from './App'
import { oyunsTheme } from './theme/oyunsTheme'
import { applyDocumentBranding, tenantTheme } from './theme/tenantBranding'
import { useTenantBranding } from './api/tenancy'
import { useColorThemeStore } from './store/colorTheme'
import { initializeRuntimeClass } from './platform/runtime'
import { NativeBootBoundary } from './platform/updater'
import { installNativeTelegramAuth } from './platform/telegram-auth'
import { startTelemetry } from './platform/telemetry'
import './index.css'
import './workspace-features.css'
import './unified-controls.css'
import './i18n'

initializeRuntimeClass()
void installNativeTelegramAuth()
startTelemetry()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

const DEFAULT_TITLE = typeof document !== 'undefined' ? document.title : 'OYUNS ERP'

function ThemedRoot({ children }: { children: ReactNode }) {
  const mode = useColorThemeStore((state) => state.theme)
  // Tenant branding (name, favicon, brand colours) resolved from the host or
  // the signed-in session; the OYUNS theme is the fallback.
  const branding = useTenantBranding()
  const primary = branding.data?.primary_color
  const theme = useMemo(() => (primary ? tenantTheme(primary) : oyunsTheme), [primary])
  useEffect(() => {
    // Browser chrome (Android address bar, installed-app status bar) follows the app theme.
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', mode === 'dark' ? '#0b172a' : '#f4f6fa')
  }, [mode])
  useEffect(() => {
    if (branding.data) applyDocumentBranding(branding.data, DEFAULT_TITLE)
  }, [branding.data])
  return <Theme theme={theme} mode={mode}>{children}</Theme>
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
    toastOptions={{ style: { background: 'var(--color-text)', color: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius)', ...(phone ? { maxWidth: 'calc(100vw - var(--space-6))' } : {}) } }}
  />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemedRoot>
        <NativeBootBoundary><App /></NativeBootBoundary>
        <AppToaster />
      </ThemedRoot>
    </QueryClientProvider>
  </StrictMode>,
)
