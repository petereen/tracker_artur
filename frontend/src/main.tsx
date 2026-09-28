import { StrictMode, type ReactNode } from 'react'
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
  return <Theme theme={oyunsTheme} mode={mode}>{children}</Theme>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemedRoot>
      <QueryClientProvider client={queryClient}>
        <NativeBootBoundary><App /></NativeBootBoundary>
        <Toaster position="top-right" toastOptions={{ style: { background: '#161B22', color: '#E6EDF3', border: '1px solid #30363D' } }} />
      </QueryClientProvider>
    </ThemedRoot>
  </StrictMode>,
)
