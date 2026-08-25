import { create } from 'zustand'
import type { WorkspaceMode } from '../api/enterprise'

interface WorkspaceModeState {
  mode: WorkspaceMode
  hydrated: boolean
  setMode: (mode: WorkspaceMode) => void
  setHydrated: (hydrated: boolean) => void
  reset: () => void
}

export const useWorkspaceModeStore = create<WorkspaceModeState>((set) => ({
  mode: 'manager',
  hydrated: false,
  setMode: (mode) => set({ mode }),
  setHydrated: (hydrated) => set({ hydrated }),
  reset: () => set({ mode: 'manager', hydrated: false }),
}))
