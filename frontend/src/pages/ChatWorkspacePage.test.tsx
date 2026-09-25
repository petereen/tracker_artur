import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatWorkspacePage, slashQuery } from './ChatWorkspacePage'

const mocks = vi.hoisted(() => ({ share: vi.fn(), shareQueries: [] as string[], send: vi.fn(), acknowledge: vi.fn(), createGroup: vi.fn(), openDirect: vi.fn(), confirmDraft: vi.fn(), rejectDraft: vi.fn() }))

const member = { account_id: 2, employee_id: 2, name: 'Ану', email: 'anu@example.com', avatar_url: null, is_online: true, last_seen_at: new Date().toISOString(), role: 'member' as const }
const conversation = { id: 9, public_id: 'c1', kind: 'direct' as const, title: 'Ану', avatar_urls: [], presence: 'online' as const, members: [member], member_count: 2, can_manage: false, last_message: { id: 12, body: 'Сайн байна уу?', sender_account_id: 2, sender_name: 'Ану', created_at: new Date().toISOString() }, unread_count: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
const incoming = { id: 12, conversation_id: 9, sender: member, sender_account_id: 2, client_nonce: crypto.randomUUID(), body: 'Сайн байна уу?', action: { type: 'task_action_preview' as const, payload: { action_reference: 'mcpact-test-reference', title: 'Тайлан бэлдэх', action_type: 'create_task' } }, created_at: new Date().toISOString(), is_mine: false, status: null, receipts: { total: 0, delivered: 0, read: 0 } }
const outgoing = { id: 13, conversation_id: 9, sender: { ...member, account_id: 1, name: 'Manager' }, sender_account_id: 1, client_nonce: crypto.randomUUID(), body: 'Сайн, сайн.', created_at: new Date().toISOString(), is_mine: true, status: 'read' as const, receipts: { total: 1, delivered: 1, read: 1 } }
const callHistory = { id: 14, conversation_id: 9, sender: null, sender_account_id: null, client_nonce: crypto.randomUUID(), body: null, kind: 'call' as const, call: { call_id: crypto.randomUUID(), call_type: 'audio' as const, outcome: 'completed' as const, duration_seconds: 225, direction: 'incoming' as const, caller_name: 'Ану', callee_name: 'Manager', started_at: new Date().toISOString(), ended_at: new Date().toISOString() }, created_at: new Date().toISOString(), is_mine: false, status: null, receipts: { total: 0, delivered: 0, read: 0 } }

const sharedOpen = { id: 15, conversation_id: 9, sender: member, sender_account_id: 2, client_nonce: crypto.randomUUID(), body: '✅ Даалгавар: Гэрээ шалгах', action: { type: 'shared_item' as const, payload: { kind: 'task', ref: '5', group: 'tasks', kind_label: 'Даалгавар', title: 'Гэрээ шалгах', status: 'in_progress', status_label: 'Хийгдэж буй', fields: [{ label: 'Хариуцагч', value: 'Ану' }, { label: 'Дуусах хугацаа', value: '2026-10-01 18:00' }], excerpt: 'Нийлүүлэгчийн гэрээний нөхцөл', can_open: true, target_url: '/tasks?task=5' } }, created_at: new Date().toISOString(), is_mine: false, status: null, receipts: { total: 0, delivered: 0, read: 0 } }
const sharedLocked = { ...sharedOpen, id: 16, client_nonce: crypto.randomUUID(), body: '📊 Тайлан: 9-р сарын тайлан', action: { type: 'shared_item' as const, payload: { kind: 'report', ref: '8', group: 'reports', kind_label: 'Тайлан', title: '9-р сарын тайлан', status: 'approved', status_label: 'Батлагдсан', fields: [], excerpt: null, can_open: false } } }
const shareGroups = { query: '', groups: [
  { key: 'tasks', label: 'Идэвхтэй даалгавар', items: [{ kind: 'task', ref: '5', group: 'tasks', kind_label: 'Даалгавар', title: 'Гэрээ шалгах', subtitle: 'Ану', status: 'in_progress', status_label: 'Хийгдэж буй', updated_at: null }] },
  { key: 'plans', label: 'Төлөвлөгөө', items: [] },
  { key: 'contracts', label: 'Гэрээний ноорог', items: [{ kind: 'contract', ref: 'uuid-1', group: 'contracts', kind_label: 'Гэрээ', title: 'Нийлүүлэлтийн гэрээ', subtitle: 'Гэрээ', status: 'DRAFT', status_label: 'Ноорог', updated_at: null }] },
  { key: 'reports', label: 'Тайлан', items: [] },
] }

vi.mock('../api/chatShare', () => ({
  useChatShareItems: (query: string, enabled: boolean) => { if (enabled) mocks.shareQueries.push(query); return { data: enabled ? shareGroups : undefined, isFetching: false } },
  useShareChatItem: () => ({ mutate: mocks.share, isPending: false }),
}))

vi.mock('../api/enterprise', () => ({
  useChatConversations: () => ({ data: { items: [conversation], next_cursor: null } }),
  useChatConversation: () => ({ data: conversation }),
  useChatMessages: () => ({ data: { pages: [{ items: [sharedOpen, sharedLocked, incoming, outgoing, callHistory], next_before_id: null }] }, hasNextPage: false, isLoading: false, isFetchingNextPage: false, fetchNextPage: vi.fn() }),
  useChatMessageContext: () => ({ data: undefined }),
  useSendChatMessage: () => ({ mutate: mocks.send, isPending: false }),
  useConfirmAssistantAction: () => ({ mutateAsync: mocks.confirmDraft, isPending: false }),
  useRejectAssistantAction: () => ({ mutateAsync: mocks.rejectDraft, isPending: false }),
  useAcknowledgeChat: () => ({ mutate: mocks.acknowledge }),
  useChatContacts: () => ({ data: [member] }),
  useOpenDirectConversation: () => ({ mutateAsync: mocks.openDirect, isPending: false }),
  useCreateChatGroup: () => ({ mutateAsync: mocks.createGroup, isPending: false }),
  useRenameChatGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAddChatMembers: () => ({ mutateAsync: vi.fn() }),
  useRemoveChatMember: () => ({ mutate: vi.fn() }),
  useLeaveChatGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useChatReceiptDetails: () => ({ isLoading: false, data: { message_id: 13, counts: { total: 1, delivered: 1, read: 1 }, items: [{ account: member, status: 'read', delivered_at: new Date().toISOString(), read_at: new Date().toISOString() }] } }),
  useEditChatMessage: () => ({ mutate: vi.fn() }),
  useDeleteChatMessage: () => ({ mutate: vi.fn() }),
  useReactChatMessage: () => ({ mutate: vi.fn() }),
  useStarChatMessage: () => ({ mutate: vi.fn() }),
  usePinChatMessage: () => ({ mutate: vi.fn() }),
  useForwardChatMessage: () => ({ mutate: vi.fn() }),
  useUpdateChatConversationPreferences: () => ({ mutate: vi.fn() }),
  useChatSearch: () => ({ data: { items: [] }, isFetching: false }),
  useChatThread: () => ({ data: undefined, isLoading: false }),
  uploadChatAttachment: vi.fn(),
  cancelChatUpload: vi.fn(),
  downloadChatAttachment: vi.fn(),
}))

vi.mock('../platform/runtime', () => ({
  resolvePublicAssetUrl: (value: string) => value,
  safeLocalStorage: () => ({ get: vi.fn(() => null), set: vi.fn() }),
  isNativePlatform: () => false,
}))

function renderChat() {
  return render(<MemoryRouter initialEntries={['/chat/c1']}><Routes><Route path="/chat/:conversationId?" element={<ChatWorkspacePage />} /></Routes></MemoryRouter>)
}

describe('chat workspace', () => {
  beforeEach(() => {
    mocks.send.mockClear(); mocks.share.mockClear(); mocks.shareQueries.length = 0; mocks.acknowledge.mockClear(); mocks.confirmDraft.mockReset(); mocks.rejectDraft.mockReset()
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    Element.prototype.scrollTo = vi.fn()
  })

  it('renders the conversation list, presence, thread, and auto-resizing composer', async () => {
    renderChat()
    expect(screen.getAllByText('Ану').length).toBeGreaterThan(0)
    expect(screen.getByText('Онлайн')).toBeInTheDocument()
    expect(screen.getAllByText('Сайн байна уу?').length).toBeGreaterThan(1)
    expect(screen.getByText('📞 Дуудлага дууссан • 3:45')).toBeInTheDocument()
    const composer = screen.getByRole('textbox', { name: 'Мессеж' })
    fireEvent.change(composer, { target: { value: 'Шинэ мессеж' } })
    fireEvent.keyDown(composer, { key: 'Enter' })
    expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ body: 'Шинэ мессеж' }), expect.any(Object))
    await waitFor(() => expect(mocks.acknowledge).toHaveBeenCalledWith({ message_id: 12, status: 'read' }))
  })

  it('opens per-recipient details when the sender clicks an own-message status', () => {
    renderChat()
    fireEvent.click(screen.getByRole('button', { name: /Уншсан/ }))
    expect(screen.getByRole('dialog', { name: 'Мессежийн төлөв' })).toBeInTheDocument()
    expect(screen.getByText('Уншсан ·', { exact: false })).toBeInTheDocument()
  })

  it('renders task-draft confirm, reject, and edit controls in platform chat', () => {
    renderChat()
    expect(screen.getByRole('button', { name: '✅ Баталгаажуулах' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '❌ Татгалзах' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '✏️ Засах' }))
    expect(screen.getByRole('textbox', { name: 'Мессеж' })).toHaveValue('Нооргийг засах: “Тайлан бэлдэх”. ')
  })

  it('exposes a persistent desktop conversation-pane toggle', () => {
    renderChat()
    const toggle = screen.getByRole('button', { name: 'Чатын жагсаалт нуух' })
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: 'Чатын жагсаалт нээх' })).toBeInTheDocument()
  })

  it('parses only a leading single-line slash as a share query', () => {
    expect(slashQuery('/')).toBe('')
    expect(slashQuery('/ гэрээ ')).toBe('гэрээ')
    expect(slashQuery('hello /x')).toBeNull()
    expect(slashQuery('/a\nb')).toBeNull()
  })

  it('opens a grouped slash menu, live-searches, and shares the chosen item', async () => {
    renderChat()
    const composer = screen.getByRole('textbox', { name: 'Мессеж' })
    fireEvent.change(composer, { target: { value: '/гэр' } })
    const listbox = screen.getByRole('listbox', { name: 'Хуваалцах боломжтой зүйлс' })
    expect(listbox).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Идэвхтэй даалгавар' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Гэрээний ноорог' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Төлөвлөгөө' })).not.toBeInTheDocument()
    await waitFor(() => expect(mocks.shareQueries).toContain('гэр'))
    expect(composer).toHaveAttribute('aria-activedescendant', 'chat-slash-option-0')
    fireEvent.keyDown(composer, { key: 'ArrowDown' })
    expect(screen.getByRole('option', { name: /Нийлүүлэлтийн гэрээ/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(composer, { key: 'Enter' })
    expect(mocks.share).toHaveBeenCalledWith(expect.objectContaining({ kind: 'contract', ref: 'uuid-1' }), expect.any(Object))
    expect(mocks.send).not.toHaveBeenCalled()
    expect(composer).toHaveValue('')
  })

  it('closes the slash menu on Escape and keeps the typed text', () => {
    renderChat()
    const composer = screen.getByRole('textbox', { name: 'Мессеж' })
    fireEvent.change(composer, { target: { value: '/' } })
    fireEvent.keyDown(composer, { key: 'Escape' })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(composer).toHaveValue('/')
  })

  it('renders shared items as info cards linked only when the reader has access', () => {
    renderChat()
    const link = screen.getByRole('link', { name: 'Даалгавар: Гэрээ шалгах — нээх' })
    expect(link).toHaveAttribute('href', '/tasks?task=5')
    expect(screen.getByText('Нийлүүлэгчийн гэрээний нөхцөл')).toBeInTheDocument()
    expect(screen.getByText('2026-10-01 18:00')).toBeInTheDocument()
    expect(screen.getByText('9-р сарын тайлан').closest('a')).toBeNull()
    expect(screen.getByText('Танд нээх эрх байхгүй')).toBeInTheDocument()
  })
})
