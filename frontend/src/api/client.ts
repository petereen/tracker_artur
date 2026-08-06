import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '../store/auth'

export const api = axios.create({ baseURL: '/api', withCredentials: true })
const refreshClient = axios.create({ baseURL: '/api', withCredentials: true })
let refreshPromise: Promise<string> | null = null
let proactiveTimer: number | undefined

export function acceptSession(data: { access_token: string; expires_in?: number }) {
  const expiresIn = data.expires_in ?? 15 * 60
  useAuthStore.getState().setSession(data.access_token, expiresIn)
  if (proactiveTimer) window.clearTimeout(proactiveTimer)
  proactiveTimer = window.setTimeout(() => { refreshAccessToken().catch(() => undefined) }, Math.max(10_000, (expiresIn - 60) * 1000))
  return data.access_token
}

async function rotateSession() {
  const { data } = await refreshClient.post('/v1/auth/refresh')
  return acceptSession(data)
}

export function refreshAccessToken(): Promise<string> {
  if (refreshPromise) return refreshPromise
  const tokenBeforeLock = useAuthStore.getState().token
  const run = async () => {
    const current = useAuthStore.getState()
    if (current.token && current.token !== tokenBeforeLock && (current.expiresAt ?? 0) > Date.now() + 30_000) return current.token
    return rotateSession()
  }
  const locks = navigator.locks
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
    const sessionEndpoint = ['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/logout', '/v1/auth/telegram', '/v1/auth/telegram-widget'].some((path) => config?.url?.includes(path))
    if (error.response?.status !== 401 || !config || sessionEndpoint || config._sessionRetried) throw error
    config._sessionRetried = true
    try {
      config.headers.Authorization = `Bearer ${await refreshAccessToken()}`
      return api.request(config)
    } catch (refreshError) {
      useAuthStore.getState().logout()
      throw refreshError
    }
  },
)
