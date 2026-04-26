import axios from 'axios'
import { useAuthStore } from '../store/auth'

export const api = axios.create({ baseURL: '/api' })

function getToken(): string | null {
  // Сначала пробуем Zustand (работает после hydration)
  const fromStore = useAuthStore.getState().token
  if (fromStore) return fromStore
  // Fallback — читаем напрямую из localStorage (до hydration)
  try {
    const raw = localStorage.getItem('auth')
    if (raw) {
      const parsed = JSON.parse(raw)
      return parsed?.state?.token ?? null
    }
  } catch {
    // ignore
  }
  return null
}

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    // Logout только если запрос НЕ логин
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/')) {
      useAuthStore.getState().logout()
    }
    return Promise.reject(err)
  },
)
