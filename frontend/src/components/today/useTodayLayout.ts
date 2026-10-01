import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  todayLayoutQueryKey,
  useSaveTodayLayoutPreferences,
  useTodayLayoutPreferences,
  type TodayLayoutPreferences,
  type TodayWidgetState,
} from '../../api/today'
import { safeLocalStorage } from '../../platform/runtime'
import { useAuthStore } from '../../store/auth'

const SAVE_DELAY_MS = 700
const storageKey = (accountId: number | null | undefined) => `oyuns.today-layout:${accountId ?? 'anonymous'}`

function readCache(accountId: number | null | undefined): TodayLayoutPreferences | null {
  const raw = safeLocalStorage().get(storageKey(accountId))
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && (parsed.widgets === null || Array.isArray(parsed.widgets)) ? parsed : null
  } catch {
    return null
  }
}

/**
 * The canvas layout of the signed-in account. It renders from the local
 * cache immediately, adopts the server copy when that one is newer (another
 * device), and saves edits to both — the server write is debounced so a drag
 * or a burst of typing in a notes widget becomes a single request.
 */
export function useTodayLayout(defaultWidgets: () => TodayWidgetState[]) {
  const accountId = useAuthStore((state) => state.actor?.id)
  const queryClient = useQueryClient()
  const server = useTodayLayoutPreferences(accountId != null)
  const save = useSaveTodayLayoutPreferences()
  const [local, setLocal] = useState<TodayLayoutPreferences | null>(() => readCache(accountId))
  const pending = useRef<TodayLayoutPreferences | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const saveRef = useRef(save.mutate)
  saveRef.current = save.mutate

  useEffect(() => { setLocal(readCache(accountId)) }, [accountId])

  const flush = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    const next = pending.current
    pending.current = null
    if (!next) return
    saveRef.current(next, { onSuccess: (data) => queryClient.setQueryData(todayLayoutQueryKey, data) })
  }, [queryClient])

  const persist = useCallback((next: TodayLayoutPreferences) => {
    setLocal(next)
    safeLocalStorage().set(storageKey(accountId), JSON.stringify(next))
    pending.current = next
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(flush, SAVE_DELAY_MS)
  }, [accountId, flush])

  // Reconcile with the server copy: whichever was edited last wins.
  const serverData = server.data
  useEffect(() => {
    if (!serverData) return
    const localUpdated = local?.updated_at ?? 0
    const serverUpdated = serverData.updated_at ?? 0
    if (serverUpdated > localUpdated) {
      setLocal(serverData)
      safeLocalStorage().set(storageKey(accountId), JSON.stringify(serverData))
    } else if (local && localUpdated > serverUpdated && !pending.current) {
      // Edited while offline (or the save failed): push the newer local copy.
      pending.current = local
      flush()
    }
    // Only react to new server data, not to every local edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverData])

  // Never lose the last edit when leaving the page.
  useEffect(() => {
    window.addEventListener('pagehide', flush)
    return () => { window.removeEventListener('pagehide', flush); flush() }
  }, [flush])

  const widgets = useMemo(() => local?.widgets ?? defaultWidgets(), [defaultWidgets, local?.widgets])
  const setWidgets = useCallback((next: TodayWidgetState[]) => persist({ widgets: next, updated_at: Date.now() }), [persist])
  const resetToDefault = useCallback(() => persist({ widgets: null, updated_at: Date.now() }), [persist])

  return {
    widgets,
    isCustomized: Boolean(local?.widgets),
    isLoading: !local && server.isLoading,
    setWidgets,
    resetToDefault,
  }
}
