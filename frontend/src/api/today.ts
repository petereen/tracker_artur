import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface TodayWidgetState {
  id: string
  type: string
  x: number
  y: number
  w: number
  h: number
  settings: Record<string, unknown>
}

export interface TodayLayoutPreferences {
  /** null = never customised; the client renders its default canvas. */
  widgets: TodayWidgetState[] | null
  /** Client clock (ms) of the last edit — the newer copy wins between devices. */
  updated_at: number | null
}

export const todayLayoutQueryKey = ['v1', 'auth', 'preferences', 'today-layout'] as const

export function useTodayLayoutPreferences(enabled = true) {
  return useQuery<TodayLayoutPreferences>({
    queryKey: todayLayoutQueryKey,
    queryFn: () => api.get('/v1/auth/preferences/today-layout').then((response) => response.data),
    enabled,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
}

export function useSaveTodayLayoutPreferences() {
  return useMutation({
    mutationFn: (input: TodayLayoutPreferences) =>
      api.put('/v1/auth/preferences/today-layout', input).then((response) => response.data as TodayLayoutPreferences),
  })
}

/**
 * News & announcements feed: published posts, written on `/announcements`
 * (see `api/announcements.ts`). A backend without the endpoint yields an
 * empty feed instead of an error.
 */
export interface Announcement {
  id: number | string
  title: string
  summary?: string | null
  /** Markdown body. */
  body?: string | null
  cover_url?: string | null
  image_urls?: string[]
  author_name?: string | null
  category?: string | null
  is_pinned?: boolean
  published_at: string
}

export function useAnnouncements(limit = 30) {
  return useQuery<Announcement[]>({
    queryKey: ['v1', 'announcements', limit],
    queryFn: async ({ signal }) => {
      try {
        const response = await api.get('/v1/announcements', { signal, params: { limit } })
        const data = response.data
        return Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : []
      } catch (error: any) {
        if ([404, 405].includes(error?.response?.status)) return []
        throw error
      }
    },
    staleTime: 5 * 60_000,
    retry: 1,
  })
}
