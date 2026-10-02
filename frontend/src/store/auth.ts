import { create } from 'zustand'

export interface Actor {
  id: number
  email: string
  employee_id: number | null
  locale: string
  /** Roles effective for the current workspace mode (narrowed in the personal view). */
  roles: string[]
  /** Roles actually granted to the account, independent of the workspace mode. */
  account_roles?: string[] | null
  workspace_mode?: 'member' | 'manager' | null
  name?: string | null
  avatar_url?: string | null
  /** What the session owes before the API opens up (tenant-enforced 2FA). */
  two_factor?: { required: boolean; enrolled: boolean; verified: boolean } | null
}

export const EMPTY_ROLES: string[] = []

interface AuthState {
  token: string | null
  expiresAt: number | null
  actor: Actor | null
  sessionVersion: number
  initialized: boolean
  setToken: (token: string | null) => void
  setSession: (token: string, expiresIn: number) => void
  setRefreshedSession: (token: string, expiresIn: number) => void
  setActor: (actor: Actor | null) => void
  setInitialized: (initialized: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  expiresAt: null,
  actor: null,
  sessionVersion: 0,
  initialized: false,
  setToken: (token) => set({ token, expiresAt: token ? Date.now() + 14 * 60_000 : null }),
  setSession: (token, expiresIn) => set((state) => ({ token, expiresAt: Date.now() + expiresIn * 1000, actor: null, sessionVersion: state.sessionVersion + 1 })),
  setRefreshedSession: (token, expiresIn) => set({ token, expiresAt: Date.now() + expiresIn * 1000 }),
  setActor: (actor) => set({ actor }),
  setInitialized: (initialized) => set({ initialized }),
  logout: () => set({ token: null, expiresAt: null, actor: null, initialized: true }),
}))
