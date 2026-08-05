import axios from 'axios'
import { useAuthStore } from '../store/auth'

export const api = axios.create({ baseURL: '/api', withCredentials: true })

function getToken(): string | null {
  // Сначала пробуем Zustand (работает после hydration)
  const fromStore = useAuthStore.getState().token
  if (fromStore) return fromStore
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
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/')) {
      useAuthStore.getState().logout()
    }
    return Promise.reject(err)
  },
)
