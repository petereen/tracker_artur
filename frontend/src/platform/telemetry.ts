type SentryModule = typeof import('@sentry/react')

let sentry: SentryModule | null = null
let loading: Promise<SentryModule | null> | null = null
const pendingTags = new Map<string, string>()

function scheduleIdle(callback: () => void) {
  const idle = (window as Window & { requestIdleCallback?: (cb: () => void, options?: { timeout: number }) => number }).requestIdleCallback
  if (idle) {
    idle(callback, { timeout: 2_000 })
  } else {
    window.setTimeout(callback, 1_000)
  }
}

function loadTelemetryModule() {
  if (!import.meta.env.VITE_SENTRY_DSN) return Promise.resolve(null)
  if (!loading) loading = import('@sentry/react').then((module) => { sentry = module; return module }).catch(() => null)
  return loading
}

export function startTelemetry() {
  if (!import.meta.env.VITE_SENTRY_DSN || loading) return
  scheduleIdle(() => {
    loading = import('@sentry/react').then((module) => {
      sentry = module
      module.init({
        dsn: import.meta.env.VITE_SENTRY_DSN,
        environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? 'production',
        tracesSampleRate: 0.1,
        integrations: [module.browserTracingIntegration()],
      })
      pendingTags.forEach((value, key) => module.setTag(key, value))
      pendingTags.clear()
      return module
    }).catch(() => null)
  })
}

export function addTelemetryBreadcrumb(input: { category: string; message: string; level?: 'debug' | 'info' | 'warning' | 'error' }) {
  void loadTelemetryModule().then((module) => module?.addBreadcrumb(input))
}

export function captureTelemetryException(error: unknown, context?: Record<string, unknown>) {
  void loadTelemetryModule().then((module) => module?.captureException(error, context ? ({ contexts: context } as any) : undefined))
}

export function setTelemetryTag(key: string, value: string) {
  if (sentry) sentry.setTag(key, value)
  else pendingTags.set(key, value)
}
