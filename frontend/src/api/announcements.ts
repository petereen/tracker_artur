import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Announcement } from './today'

export type AnnouncementStatus = 'draft' | 'published' | 'archived'

/** A post as its authors see it: every status, plus what the caller may do. */
export interface ManagedAnnouncement extends Omit<Announcement, 'id' | 'published_at'> {
  id: number
  status: AnnouncementStatus
  published_at: string | null
  author_account_id: number | null
  created_at: string
  updated_at: string
  can_edit: boolean
}

export interface AnnouncementInput {
  title: string
  summary: string | null
  body: string
  cover_url: string | null
  image_urls: string[]
  category: string | null
  is_pinned: boolean
  status: AnnouncementStatus
}

export const ANNOUNCEMENT_AUTHOR_ROLES = ['admin', 'manager', 'team_lead']
/** Roles that edit, pin and delete posts written by somebody else. */
export const ANNOUNCEMENT_EDITOR_ROLES = ['admin', 'manager']
export const ANNOUNCEMENT_LIMITS = { title: 200, summary: 500, body: 20_000, category: 60, images: 12, imageBytes: 8 * 1024 * 1024 }
export const ANNOUNCEMENT_IMAGE_TYPES = 'image/png,image/jpeg,image/webp'

// The feed (`useAnnouncements`) lives under the same prefix, so one invalidation refreshes both.
const announcementsKey = ['v1', 'announcements'] as const

export function announcementErrorText(error: unknown, fallback: string) {
  const detail = (error as any)?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg
  if (typeof detail?.message === 'string') return detail.message
  return fallback
}

export function useManagedAnnouncements() {
  return useQuery<ManagedAnnouncement[]>({
    queryKey: [...announcementsKey, 'manage'],
    queryFn: ({ signal }) => api.get('/v1/announcements/manage', { signal }).then((response) => response.data),
  })
}

export function useSaveAnnouncement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id?: number; input: Partial<AnnouncementInput> }) =>
      (id ? api.patch(`/v1/announcements/${id}`, input) : api.post('/v1/announcements', input)).then((response) => response.data as ManagedAnnouncement),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: announcementsKey }),
  })
}

export function useDeleteAnnouncement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/v1/announcements/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: announcementsKey }),
  })
}

export async function uploadAnnouncementImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const response = await api.post('/v1/announcements/images', form)
  return response.data.url as string
}
