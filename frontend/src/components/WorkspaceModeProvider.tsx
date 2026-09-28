import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
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
  const queryClient = useQueryClient()
  const token = useAuthStore((state) => state.token)
  const accountId = useAuthStore((state) => state.actor?.id)
  // Eligibility follows the account's real grants: in the personal view the
  // effective `roles` are narrowed to member, but the toggle must remain.
  const grantedRoles = useAuthStore((state) => state.actor?.account_roles ?? state.actor?.roles ?? EMPTY_ROLES)
  const eligible = grantedRoles.some((role) => MANAGEMENT_ROLES.includes(role))
  const mode = useWorkspaceModeStore((state) => state.mode)
  const hydrated = useWorkspaceModeStore((state) => state.hydrated)
  const setStoreMode = useWorkspaceModeStore((state) => state.setMode)
  const setHydrated = useWorkspaceModeStore((state) => state.setHydrated)
  const reset = useWorkspaceModeStore((state) => state.reset)
  const preference = useWorkspaceModePreferences(Boolean(token && accountId && eligible))
  const update = useUpdateWorkspaceModePreferences()

  useEffect(() => {
    if (!token) {
      reset()
      return
    }
    // Wait for the actor before deciding; keep the remembered mode meanwhile.
    if (!accountId) return
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

  // Every API request carries the mode, so a switch must refetch all data
  // (including the actor, whose effective roles drive navigation and pages).
  const lastScopedMode = useRef<WorkspaceMode | null>(null)
  useEffect(() => {
    if (!token || !accountId || !eligible) {
      lastScopedMode.current = null
      return
    }
    if (lastScopedMode.current !== null && lastScopedMode.current !== mode) {
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[3] !== 'workspace-mode' })
    }
    lastScopedMode.current = mode
  }, [accountId, eligible, mode, queryClient, token])

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
