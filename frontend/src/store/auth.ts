import { create } from 'zustand'

export interface Actor {
  id: number
  email: string
  employee_id: number | null
  locale: string
  roles: string[]
}

interface AuthState {
  token: string | null
  actor: Actor | null
  initialized: boolean
  setToken: (token: string | null) => void
  setActor: (actor: Actor | null) => void
  setInitialized: (initialized: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  actor: null,
  initialized: false,
  setToken: (token) => set({ token }),
  setActor: (actor) => set({ actor }),
  setInitialized: (initialized) => set({ initialized }),
  logout: () => set({ token: null, actor: null, initialized: true }),
}))
