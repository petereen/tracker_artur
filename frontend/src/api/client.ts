import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { clearNativeRefreshToken, getNativeRefreshToken, setNativeRefreshToken } from '../platform/secure-session'
import { getApiBaseUrl, isNativePlatform } from '../platform/runtime'
import { useAuthStore } from '../store/auth'

const apiBaseUrl = getApiBaseUrl()

export const api = axios.create({ baseURL: apiBaseUrl, withCredentials: true })
// Public kiosk endpoints must not trigger the employee session refresh flow.
// A TV at /worktimeqr has no employee bearer token before pairing.
export const publicApi = axios.create({ baseURL: apiBaseUrl, withCredentials: true })
const refreshClient = axios.create({ baseURL: apiBaseUrl, withCredentials: true })
let refreshPromise: Promise<string> | null = null
let proactiveTimer: number | undefined

export async function acceptSession(data: { access_token: string; expires_in?: number; refresh_token?: string | null }) {
  const expiresIn = data.expires_in ?? 15 * 60
  if (isNativePlatform() && data.refresh_token) await setNativeRefreshToken(data.refresh_token)
  useAuthStore.getState().setSession(data.access_token, expiresIn)
  if (proactiveTimer && typeof window !== 'undefined') window.clearTimeout(proactiveTimer)
  if (typeof window !== 'undefined') {
    proactiveTimer = window.setTimeout(() => { refreshAccessToken().catch(() => undefined) }, Math.max(10_000, (expiresIn - 60) * 1000))
  }
  return data.access_token
}

async function rotateSession() {
  const refreshToken = isNativePlatform() ? await getNativeRefreshToken() : null
  const { data } = await refreshClient.post('/v1/auth/refresh', refreshToken ? { refresh_token: refreshToken } : undefined)
  return acceptSession(data)
}

export async function clearSessionCredentials() {
  if (proactiveTimer && typeof window !== 'undefined') window.clearTimeout(proactiveTimer)
  proactiveTimer = undefined
  await clearNativeRefreshToken()
}

export function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise
  const tokenBeforeLock = useAuthStore.getState().token
  const run = async () => {
    const current = useAuthStore.getState()
    if (current.token && current.token !== tokenBeforeLock && (current.expiresAt ?? 0) > Date.now() + 30_000) return current.token
    return rotateSession()
  }
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
  const operation = (locks ? locks.request('oyuns-session-refresh', async () => await run()) : run()) as Promise<string>
  const result = operation.finally(() => { refreshPromise = null })
  refreshPromise = result
  return result
}

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as (InternalAxiosRequestConfig & { _sessionRetried?: boolean }) | undefined
    const sessionEndpoint = ['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/logout', '/v1/auth/telegram'].some((path) => config?.url?.includes(path))
    if (error.response?.status !== 401 || !config || sessionEndpoint || config._sessionRetried) throw error
    config._sessionRetried = true
    try {
      config.headers.Authorization = `Bearer ${await refreshAccessToken()}`
      return api.request(config)
    } catch (refreshError) {
      await clearSessionCredentials()
      useAuthStore.getState().logout()
      throw refreshError
    }
  },
)
