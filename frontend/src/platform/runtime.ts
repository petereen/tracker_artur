import { Capacitor } from '@capacitor/core'

const nativeApiOrigin = (import.meta.env.VITE_NATIVE_API_ORIGIN || 'https://erp.oyuns.mn').replace(/\/$/, '')

export function getNativeApiOrigin() {
  return nativeApiOrigin
}

export const isNativePlatform = () => Capacitor.isNativePlatform()

export const nativePlatform = (): 'ios' | 'android' | null => {
  const platform = Capacitor.getPlatform()
  return platform === 'ios' || platform === 'android' ? platform : null
}

export function initializeRuntimeClass() {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('capacitor-native', isNativePlatform())
  document.documentElement.dataset.platform = Capacitor.getPlatform()
}

export function getApiBaseUrl() {
  return isNativePlatform() && !import.meta.env.DEV ? `${nativeApiOrigin}/api` : '/api'
}

export function getRealtimeUrl(path = '/v1/realtime') {
  if (typeof window === 'undefined') return ''

  if (!isNativePlatform() || import.meta.env.DEV) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/api${path}`
  }

  const endpoint = new URL(nativeApiOrigin)
  endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:'
  endpoint.pathname = `/api${path}`
  endpoint.search = ''
  endpoint.hash = ''
  return endpoint.toString()
}

export function resolvePublicAssetUrl(value: string | null | undefined) {
  if (!value || !value.startsWith('/api/') || !isNativePlatform() || import.meta.env.DEV) return value
  return `${nativeApiOrigin}${value}`
}

export function requireWebCapability(label: string) {
  if (isNativePlatform()) throw new Error(`${label} is not available in the native app yet.`)
}

export function safeStorage(storage: Storage | undefined) {
  return {
    get(key: string) {
      try {
        return storage?.getItem(key) ?? null
      } catch {
        return null
      }
    },
    set(key: string, value: string) {
      try {
        storage?.setItem(key, value)
        return true
      } catch {
        return false
      }
    },
    remove(key: string) {
      try {
        storage?.removeItem(key)
      } catch {
        // Storage can be unavailable in privacy-restricted WebViews.
      }
    },
  }
}

export const safeLocalStorage = () => safeStorage(typeof window === 'undefined' ? undefined : window.localStorage)
export const safeSessionStorage = () => safeStorage(typeof window === 'undefined' ? undefined : window.sessionStorage)
