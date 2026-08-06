import { create } from 'zustand'

export interface Actor {
  id: number
  email: string
  employee_id: number | null
  locale: string
  roles: string[]
  name?: string | null
  avatar_url?: string | null
}

export const EMPTY_ROLES: string[] = []

interface AuthState {
  token: string | null
  expiresAt: number | null
  actor: Actor | null
  initialized: boolean
  setToken: (token: string | null) => void
  setSession: (token: string, expiresIn: number) => void
  setActor: (actor: Actor | null) => void
  setInitialized: (initialized: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  expiresAt: null,
  actor: null,
  initialized: false,
  setToken: (token) => set({ token, expiresAt: token ? Date.now() + 14 * 60_000 : null }),
  setSession: (token, expiresIn) => set({ token, expiresAt: Date.now() + expiresIn * 1000 }),
  setActor: (actor) => set({ actor }),
  setInitialized: (initialized) => set({ initialized }),
  logout: () => set({ token: null, expiresAt: null, actor: null, initialized: true }),
}))
