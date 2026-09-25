import { InfiniteData, keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ChatMessage, ChatMessagePage, ChatShareGroup, ChatShareKind } from './enterprise'

export interface ChatShareItem {
  kind: ChatShareKind
  ref: string
  group: ChatShareGroup
  kind_label: string
  title: string
  subtitle: string | null
  status: string | null
  status_label: string | null
  updated_at: string | null
}

export interface ChatShareItemGroups {
  query: string
  groups: Array<{ key: ChatShareGroup; label: string; items: ChatShareItem[] }>
}

/** Slash-menu source: role-scoped items the current account may share. */
export function useChatShareItems(query: string, enabled: boolean) {
  return useQuery<ChatShareItemGroups>({
    queryKey: ['v1', 'chat', 'share-items', query],
    queryFn: ({ signal }) => api.get('/v1/chat/share-items', { params: { q: query }, signal }).then((response) => response.data),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

export function useShareChatItem(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation<ChatMessage, any, { kind: ChatShareKind; ref: string; client_nonce: string }>({
    mutationFn: (input) => api.post(`/v1/chat/conversations/${publicId}/share`, input).then((response) => response.data),
    onSuccess: (message) => {
      const key = ['v1', 'chat', 'messages', publicId]
      queryClient.setQueryData<InfiniteData<ChatMessagePage>>(key, (current) => current
        ? { ...current, pages: current.pages.map((page, index) => index === 0 ? { ...page, items: [...page.items.filter((item) => item.client_nonce !== message.client_nonce), message] } : page) }
        : current)
      queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversations'] })
    },
  })
}
