import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import App from './App'
import { initializeRuntimeClass } from './platform/runtime'
import { NativeBootBoundary } from './platform/updater'
import { installNativeTelegramAuth } from './platform/telegram-auth'
import { startTelemetry } from './platform/telemetry'
import './index.css'
import './i18n'

initializeRuntimeClass()
void installNativeTelegramAuth()
startTelemetry()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <NativeBootBoundary><App /></NativeBootBoundary>
      <Toaster position="top-right" toastOptions={{ style: { background: '#161B22', color: '#E6EDF3', border: '1px solid #30363D' } }} />
    </QueryClientProvider>
  </StrictMode>,
)
