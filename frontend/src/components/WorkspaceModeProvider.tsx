import { createContext, useCallback, useContext, useEffect, useMemo } from 'react'
import { useWorkspaceModePreferences, useUpdateWorkspaceModePreferences, type WorkspaceMode } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { useWorkspaceModeStore } from '../store/workspaceMode'

const MANAGEMENT_ROLES = ['admin', 'manager', 'team_lead']

interface WorkspaceModeContextValue {
  mode: WorkspaceMode
  isManagerMode: boolean
  isEligible: boolean
  isLoading: boolean
  isSaving: boolean
  setMode: (mode: WorkspaceMode) => Promise<void>
}

const WorkspaceModeContext = createContext<WorkspaceModeContextValue | null>(null)

export function WorkspaceModeProvider({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token)
  const accountId = useAuthStore((state) => state.actor?.id)
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const eligible = roles.some((role) => MANAGEMENT_ROLES.includes(role))
  const mode = useWorkspaceModeStore((state) => state.mode)
  const hydrated = useWorkspaceModeStore((state) => state.hydrated)
  const setStoreMode = useWorkspaceModeStore((state) => state.setMode)
  const setHydrated = useWorkspaceModeStore((state) => state.setHydrated)
  const reset = useWorkspaceModeStore((state) => state.reset)
  const preference = useWorkspaceModePreferences(Boolean(token && accountId && eligible))
  const update = useUpdateWorkspaceModePreferences()

  useEffect(() => {
    if (!token || !accountId) {
      reset()
      return
    }
    if (!eligible) {
      setStoreMode('member')
      setHydrated(true)
      return
    }
    if (preference.data) {
      setStoreMode(preference.data.mode)
      setHydrated(true)
    } else if (preference.isError) {
      setStoreMode('manager')
      setHydrated(true)
    }
  }, [accountId, eligible, preference.data, preference.isError, reset, setHydrated, setStoreMode, token])

  const setMode = useCallback(async (next: WorkspaceMode) => {
    if (!eligible || next === mode || update.isPending) return
    const previous = mode
    setStoreMode(next)
    try {
      await update.mutateAsync({ mode: next })
    } catch {
      setStoreMode(previous)
    }
  }, [eligible, mode, setStoreMode, update])

  const value = useMemo<WorkspaceModeContextValue>(() => ({
    mode: eligible ? mode : 'member',
    isManagerMode: eligible && mode === 'manager',
    isEligible: eligible,
    isLoading: eligible && (!hydrated || preference.isLoading),
    isSaving: update.isPending,
    setMode,
  }), [eligible, hydrated, mode, preference.isLoading, setMode, update.isPending])

  return <WorkspaceModeContext.Provider value={value}>{children}</WorkspaceModeContext.Provider>
}

export function useWorkspaceMode() {
  const value = useContext(WorkspaceModeContext)
  return value ?? {
    mode: 'member' as WorkspaceMode,
    isManagerMode: false,
    isEligible: false,
    isLoading: false,
    isSaving: false,
    setMode: async () => undefined,
  }
}
