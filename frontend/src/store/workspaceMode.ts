import { create } from 'zustand'
import type { WorkspaceMode } from '../api/enterprise'

const STORAGE_KEY = 'oyuns-workspace-mode'

// The last chosen mode is remembered per browser so the very first requests
// after a reload already use the right scope instead of flashing the
// company-wide view before the saved preference loads.
function readStoredMode(): WorkspaceMode {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === 'member' ? 'member' : 'manager'
  } catch {
    return 'manager'
  }
}

function writeStoredMode(mode: WorkspaceMode | null) {
  try {
    if (typeof window === 'undefined') return
    if (mode) window.localStorage.setItem(STORAGE_KEY, mode)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage can be unavailable (private mode); the server preference still applies.
  }
}

interface WorkspaceModeState {
  mode: WorkspaceMode
  hydrated: boolean
  setMode: (mode: WorkspaceMode) => void
  setHydrated: (hydrated: boolean) => void
  reset: () => void
}

export const useWorkspaceModeStore = create<WorkspaceModeState>((set) => ({
  mode: readStoredMode(),
  hydrated: false,
  setMode: (mode) => { writeStoredMode(mode); set({ mode }) },
  setHydrated: (hydrated) => set({ hydrated }),
  reset: () => { writeStoredMode(null); set({ mode: 'manager', hydrated: false }) },
}))

/** Header value sent with every API request; the server narrows scope for "member". */
export function workspaceModeHeader(): WorkspaceMode {
  return useWorkspaceModeStore.getState().mode
}
