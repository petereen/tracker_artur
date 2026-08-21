/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string
  readonly VITE_SENTRY_ENVIRONMENT?: string
  readonly VITE_NATIVE_API_ORIGIN?: string
  readonly VITE_OTA_CHANNEL?: 'staging' | 'production'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
