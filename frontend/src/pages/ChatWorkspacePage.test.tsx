import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatWorkspacePage } from './ChatWorkspacePage'

const mocks = vi.hoisted(() => ({ send: vi.fn(), acknowledge: vi.fn(), createGroup: vi.fn(), openDirect: vi.fn() }))

const member = { account_id: 2, employee_id: 2, name: 'Ану', email: 'anu@example.com', avatar_url: null, is_online: true, last_seen_at: new Date().toISOString(), role: 'member' as const }
const conversation = { id: 9, public_id: 'c1', kind: 'direct' as const, title: 'Ану', avatar_urls: [], presence: 'online' as const, members: [member], member_count: 2, can_manage: false, last_message: { id: 12, body: 'Сайн байна уу?', sender_account_id: 2, sender_name: 'Ану', created_at: new Date().toISOString() }, unread_count: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
const incoming = { id: 12, conversation_id: 9, sender: member, sender_account_id: 2, client_nonce: crypto.randomUUID(), body: 'Сайн байна уу?', created_at: new Date().toISOString(), is_mine: false, status: null, receipts: { total: 0, delivered: 0, read: 0 } }
const outgoing = { id: 13, conversation_id: 9, sender: { ...member, account_id: 1, name: 'Manager' }, sender_account_id: 1, client_nonce: crypto.randomUUID(), body: 'Сайн, сайн.', created_at: new Date().toISOString(), is_mine: true, status: 'read' as const, receipts: { total: 1, delivered: 1, read: 1 } }

vi.mock('../api/enterprise', () => ({
  useChatConversations: () => ({ data: { items: [conversation], next_cursor: null } }),
  useChatConversation: () => ({ data: conversation }),
  useChatMessages: () => ({ data: { pages: [{ items: [incoming, outgoing], next_before_id: null }] }, hasNextPage: false, isLoading: false, isFetchingNextPage: false, fetchNextPage: vi.fn() }),
  useSendChatMessage: () => ({ mutate: mocks.send, isPending: false }),
  useAcknowledgeChat: () => ({ mutate: mocks.acknowledge }),
  useChatContacts: () => ({ data: [member] }),
  useOpenDirectConversation: () => ({ mutateAsync: mocks.openDirect, isPending: false }),
  useCreateChatGroup: () => ({ mutateAsync: mocks.createGroup, isPending: false }),
  useRenameChatGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAddChatMembers: () => ({ mutateAsync: vi.fn() }),
  useRemoveChatMember: () => ({ mutate: vi.fn() }),
  useLeaveChatGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useChatReceiptDetails: () => ({ isLoading: false, data: { message_id: 13, counts: { total: 1, delivered: 1, read: 1 }, items: [{ account: member, status: 'read', delivered_at: new Date().toISOString(), read_at: new Date().toISOString() }] } }),
}))

vi.mock('../platform/runtime', () => ({
  resolvePublicAssetUrl: (value: string) => value,
  safeLocalStorage: () => ({ get: vi.fn(() => null), set: vi.fn() }),
}))

function renderChat() {
  return render(<MemoryRouter initialEntries={['/chat/c1']}><Routes><Route path="/chat/:conversationId?" element={<ChatWorkspacePage />} /></Routes></MemoryRouter>)
}

describe('chat workspace', () => {
  beforeEach(() => {
    mocks.send.mockClear(); mocks.acknowledge.mockClear()
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    Element.prototype.scrollTo = vi.fn()
  })

  it('renders the conversation list, presence, thread, and auto-resizing composer', async () => {
    renderChat()
    expect(screen.getAllByText('Ану').length).toBeGreaterThan(0)
    expect(screen.getByText('Онлайн')).toBeInTheDocument()
    expect(screen.getAllByText('Сайн байна уу?').length).toBeGreaterThan(1)
    const composer = screen.getByRole('textbox', { name: 'Мессеж' })
    fireEvent.change(composer, { target: { value: 'Шинэ мессеж' } })
    fireEvent.keyDown(composer, { key: 'Enter' })
    expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ body: 'Шинэ мессеж' }))
    await waitFor(() => expect(mocks.acknowledge).toHaveBeenCalledWith({ message_id: 12, status: 'read' }))
  })

  it('opens per-recipient details when the sender clicks an own-message status', () => {
    renderChat()
    fireEvent.click(screen.getByRole('button', { name: /Уншсан/ }))
    expect(screen.getByRole('dialog', { name: 'Мессежийн төлөв' })).toBeInTheDocument()
    expect(screen.getByText('Уншсан ·', { exact: false })).toBeInTheDocument()
  })

  it('exposes a persistent desktop conversation-pane toggle', () => {
    renderChat()
    const toggle = screen.getByRole('button', { name: 'Чатын жагсаалт нуух' })
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: 'Чатын жагсаалт нээх' })).toBeInTheDocument()
  })
})
