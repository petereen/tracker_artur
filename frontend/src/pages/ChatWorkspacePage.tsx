import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Check, CheckCheck, ChevronLeft, Info, Menu, MessageCircle, MoreHorizontal, Plus, Search, Send,
  UserMinus, Users, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  ChatConversation, ChatIdentity, ChatMessage, useAcknowledgeChat, useAddChatMembers, useChatContacts,
  useChatConversation, useChatConversations, useChatMessages, useChatReceiptDetails, useCreateChatGroup,
  useLeaveChatGroup, useOpenDirectConversation, useRemoveChatMember, useRenameChatGroup, useSendChatMessage,
} from '../api/enterprise'
import { resolvePublicAssetUrl, safeLocalStorage } from '../platform/runtime'


function useMobileLayout() {
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 800px)').matches)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 800px)')
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return mobile
}

function formatTimestamp(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit' })
  return date.toLocaleDateString('mn-MN', { month: 'short', day: 'numeric' })
}

function Avatar({ identity, conversation, size = 'normal' }: { identity?: ChatIdentity | null; conversation?: ChatConversation; size?: 'normal' | 'large' }) {
  const urls = conversation?.avatar_urls ?? (identity?.avatar_url ? [identity.avatar_url] : [])
  const label = conversation?.title ?? identity?.name ?? '?'
  return (
    <span className={`chat-avatar ${size === 'large' ? 'large' : ''} ${urls.length > 1 ? 'stacked' : ''}`} aria-hidden>
      {urls.length ? urls.slice(0, 3).map((url, index) => <img key={`${url}-${index}`} src={resolvePublicAssetUrl(url) || undefined} alt="" />) : label.slice(0, 2).toUpperCase()}
    </span>
  )
}

function PresenceDot({ online }: { online: boolean }) {
  return <i className={`chat-presence ${online ? 'online' : 'offline'}`} title={online ? 'Онлайн' : 'Идэвхгүй'} aria-label={online ? 'Онлайн' : 'Идэвхгүй'} />
}

function ReceiptLabel({ message }: { message: ChatMessage }) {
  if (!message.is_mine || !message.status) return null
  if (message.status === 'sending') return <span>Илгээж байна…</span>
  if (message.status === 'failed') return <span className="failed">Илгээгдсэнгүй</span>
  if (message.receipts.total > 1) {
    return <span><CheckCheck size={12} /> Уншсан {message.receipts.read}/{message.receipts.total} · Хүрсэн {message.receipts.delivered}/{message.receipts.total}</span>
  }
  if (message.status === 'read') return <span className="read"><CheckCheck size={12} /> Уншсан</span>
  if (message.status === 'delivered') return <span><CheckCheck size={12} /> Хүрсэн</span>
  return <span><Check size={12} /> Илгээсэн</span>
}

function ConversationList({
  conversations, selectedId, search, onSearch, onSelect, onCreate, drawerRef,
}: {
  conversations: ChatConversation[]; selectedId?: string; search: string; onSearch: (value: string) => void;
  onSelect: (id: string) => void; onCreate: () => void; drawerRef: React.RefObject<HTMLElement>;
}) {
  return (
    <aside ref={drawerRef} className="chat-conversation-pane" aria-label="Чатын жагсаалт">
      <header className="chat-list-header">
        <div><span className="eyebrow">OYUNS</span><h2>Чат</h2></div>
        <button className="chat-icon-button primary" onClick={onCreate} aria-label="Шинэ чат"><Plus /></button>
      </header>
      <label className="chat-search"><Search /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Хэрэглэгч, бүлэг хайх…" /></label>
      <div className="chat-conversation-list">
        {conversations.map((conversation) => (
          <button key={conversation.public_id} className={selectedId === conversation.public_id ? 'active' : ''} onClick={() => onSelect(conversation.public_id)}>
            <span className="chat-avatar-wrap"><Avatar conversation={conversation} />{conversation.kind === 'direct' && <PresenceDot online={conversation.presence === 'online'} />}</span>
            <span className="chat-conversation-copy"><span><strong>{conversation.title}</strong><time>{formatTimestamp(conversation.last_message?.created_at || conversation.updated_at)}</time></span><small>{conversation.last_message?.body || (conversation.kind === 'group' ? `${conversation.member_count} гишүүн` : 'Шинэ харилцан яриа')}</small></span>
            {conversation.unread_count > 0 && <b className="chat-unread-count" aria-label={`${conversation.unread_count} уншаагүй`}>{conversation.unread_count > 99 ? '99+' : conversation.unread_count}</b>}
          </button>
        ))}
        {!conversations.length && <div className="chat-list-empty"><MessageCircle /><strong>Чат олдсонгүй</strong><span>Шинэ чат үүсгэж эхлээрэй.</span></div>}
      </div>
    </aside>
  )
}

function NewChatDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (conversation: ChatConversation) => void }) {
  const [mode, setMode] = useState<'direct' | 'group'>('direct')
  const [search, setSearch] = useState('')
  const [title, setTitle] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const contacts = useChatContacts(search, open)
  const openDirect = useOpenDirectConversation()
  const createGroup = useCreateChatGroup()
  useEffect(() => { if (!open) { setSearch(''); setTitle(''); setSelected([]); setMode('direct') } }, [open])
  if (!open) return null
  const chooseDirect = async (accountId: number) => {
    try { onCreated(await openDirect.mutateAsync({ account_id: accountId })) } catch (error: any) { toast.error(error.response?.data?.detail || 'Чат нээж чадсангүй') }
  }
  const create = async () => {
    if (!title.trim() || selected.length < 2) return
    try { onCreated(await createGroup.mutateAsync({ title: title.trim(), member_account_ids: selected })) } catch (error: any) { toast.error(error.response?.data?.detail || 'Бүлэг үүссэнгүй') }
  }
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
    <section className="chat-modal" role="dialog" aria-modal="true" aria-labelledby="new-chat-title">
      <header><div><span className="eyebrow">OYUNS CHAT</span><h2 id="new-chat-title">Шинэ чат</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
      <div className="chat-segments"><button className={mode === 'direct' ? 'active' : ''} onClick={() => setMode('direct')}>Шууд чат</button><button className={mode === 'group' ? 'active' : ''} onClick={() => setMode('group')}>Бүлэг</button></div>
      {mode === 'group' && <label className="chat-field"><span>Бүлгийн нэр</span><input value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} placeholder="Жишээ: Маркетингийн баг" /></label>}
      <label className="chat-search"><Search /><input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Хэрэглэгч хайх…" /></label>
      <div className="chat-contact-list">
        {(contacts.data ?? []).map((contact) => {
          const checked = selected.includes(contact.account_id)
          return <button key={contact.account_id} onClick={() => mode === 'direct' ? chooseDirect(contact.account_id) : setSelected((current) => checked ? current.filter((id) => id !== contact.account_id) : [...current, contact.account_id])}>
            <span className="chat-avatar-wrap"><Avatar identity={contact} /><PresenceDot online={contact.is_online} /></span><span><strong>{contact.name}</strong><small>{contact.email}</small></span>{mode === 'group' && <i className={`chat-check ${checked ? 'selected' : ''}`}>{checked && <Check />}</i>}
          </button>
        })}
      </div>
      {mode === 'group' && <footer><span>{selected.length} сонгосон · хамгийн багадаа 2</span><button className="chat-primary-button" disabled={!title.trim() || selected.length < 2 || createGroup.isPending} onClick={create}>Бүлэг үүсгэх</button></footer>}
    </section>
  </div>
}

function GroupManager({ conversation, onClose, onLeft }: { conversation: ChatConversation; onClose: () => void; onLeft: () => void }) {
  const [title, setTitle] = useState(conversation.title)
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const contacts = useChatContacts(search, adding)
  const rename = useRenameChatGroup(conversation.public_id)
  const add = useAddChatMembers(conversation.public_id)
  const remove = useRemoveChatMember(conversation.public_id)
  const leave = useLeaveChatGroup(conversation.public_id)
  const memberIds = new Set(conversation.members.map((member) => member.account_id))
  const available = (contacts.data ?? []).filter((contact) => !memberIds.has(contact.account_id))
  const saveTitle = async () => { if (title.trim() && title.trim() !== conversation.title) await rename.mutateAsync(title.trim()) }
  const leaveGroup = async () => { if (!window.confirm('Энэ бүлгээс гарах уу?')) return; await leave.mutateAsync(); onLeft() }
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}><section className="chat-modal chat-manage-modal" role="dialog" aria-modal="true" aria-label="Бүлгийн тохиргоо">
    <header><div><span className="eyebrow">GROUP CHAT</span><h2>Бүлгийн тохиргоо</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
    {conversation.can_manage && <div className="chat-manage-title"><label className="chat-field"><span>Бүлгийн нэр</span><input value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} /></label><button className="chat-secondary-button" onClick={saveTitle} disabled={!title.trim() || rename.isPending}>Хадгалах</button></div>}
    <div className="chat-member-heading"><strong>{conversation.member_count} гишүүн</strong>{conversation.can_manage && <button className="chat-secondary-button" onClick={() => setAdding((value) => !value)}><Plus /> Гишүүн нэмэх</button>}</div>
    {adding && <><label className="chat-search"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Нэмэх хүн хайх…" /></label><div className="chat-contact-list compact">{available.map((contact) => <button key={contact.account_id} onClick={() => add.mutateAsync([contact.account_id])}><Avatar identity={contact} /><span><strong>{contact.name}</strong><small>{contact.email}</small></span><Plus /></button>)}</div></>}
    <div className="chat-member-list">{conversation.members.map((member) => <div key={member.account_id}><span className="chat-avatar-wrap"><Avatar identity={member} /><PresenceDot online={member.is_online} /></span><span><strong>{member.name}</strong><small>{member.role === 'owner' ? 'Эзэмшигч' : member.email}</small></span>{conversation.can_manage && member.role !== 'owner' && <button className="chat-icon-button danger" onClick={() => remove.mutate(member.account_id)} aria-label={`${member.name}-г хасах`}><UserMinus /></button>}</div>)}</div>
    <footer><button className="chat-danger-button" onClick={leaveGroup} disabled={leave.isPending}>Бүлгээс гарах</button></footer>
  </section></div>
}

function ReceiptDialog({ conversationId, messageId, onClose }: { conversationId: string; messageId: number; onClose: () => void }) {
  const receipts = useChatReceiptDetails(conversationId, messageId)
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}><section className="chat-modal receipt-modal" role="dialog" aria-modal="true" aria-label="Мессежийн төлөв">
    <header><div><span className="eyebrow">MESSAGE INFO</span><h2>Мессежийн төлөв</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
    {receipts.isLoading ? <p className="chat-state">Ачаалж байна…</p> : <><div className="receipt-totals"><span><CheckCheck />Уншсан<strong>{receipts.data?.counts.read ?? 0}</strong></span><span><Check />Хүрсэн<strong>{receipts.data?.counts.delivered ?? 0}</strong></span><span><Send />Нийт<strong>{receipts.data?.counts.total ?? 0}</strong></span></div><div className="receipt-list">{receipts.data?.items.map((item) => <div key={item.account.account_id}><Avatar identity={item.account} /><span><strong>{item.account.name}</strong><small>{item.status === 'read' ? `Уншсан · ${formatTimestamp(item.read_at)}` : item.status === 'delivered' ? `Хүрсэн · ${formatTimestamp(item.delivered_at)}` : 'Илгээсэн'}</small></span></div>)}</div></>}
  </section></div>
}

export function ChatWorkspacePage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const mobile = useMobileLayout()
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState(() => safeLocalStorage().get('oyuns-chat-sidebar-collapsed') === '1')
  const [drawerOpen, setDrawerOpen] = useState(() => !conversationId)
  const [createOpen, setCreateOpen] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [receiptMessageId, setReceiptMessageId] = useState<number>()
  const [draft, setDraft] = useState('')
  const drawerRef = useRef<HTMLElement>(null)
  const paneShellRef = useRef<HTMLDivElement>(null)
  const drawerTriggerRef = useRef<HTMLButtonElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const lastAckRef = useRef('')
  const conversationList = useChatConversations(search)
  const conversation = useChatConversation(conversationId)
  const messages = useChatMessages(conversationId)
  const send = useSendChatMessage(conversationId)
  const acknowledge = useAcknowledgeChat(conversationId)
  const orderedMessages = useMemo(() => [...(messages.data?.pages ?? [])].reverse().flatMap((page) => page.items), [messages.data?.pages])

  useEffect(() => { safeLocalStorage().set('oyuns-chat-sidebar-collapsed', collapsed ? '1' : '0') }, [collapsed])
  useEffect(() => { if (!conversationId && mobile) setDrawerOpen(true) }, [conversationId, mobile])
  useEffect(() => {
    if (!mobile || !drawerOpen) return
    const previous = document.activeElement as HTMLElement | null
    const drawer = drawerRef.current
    drawer?.querySelector<HTMLInputElement>('input')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setDrawerOpen(false); return }
      if (event.key !== 'Tab' || !drawer) return
      const focusable = [...drawer.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href]')]
      if (!focusable.length) return
      const first = focusable[0]; const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); (drawerTriggerRef.current || previous)?.focus?.() }
  }, [drawerOpen, mobile])
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`
  }, [draft])
  useEffect(() => {
    if (!orderedMessages.length) return
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
    const latest = [...orderedMessages].reverse().find((message) => message.id > 0 && !message.is_mine)
    if (!latest || !conversationId || document.visibilityState !== 'visible') return
    const key = `${conversationId}:${latest.id}:read`
    if (lastAckRef.current === key) return
    lastAckRef.current = key
    acknowledge.mutate({ message_id: latest.id, status: 'read' })
  }, [conversationId, orderedMessages]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectConversation = (id: string) => { navigate(`/chat/${id}`); if (mobile) setDrawerOpen(false) }
  const submit = (body = draft, nonce: string = crypto.randomUUID()) => {
    if (!body.trim() || send.isPending) return
    if (body === draft) setDraft('')
    send.mutate({ body: body.trim(), client_nonce: nonce })
  }
  const onComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!mobile && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() }
  }
  const sidebarVisible = mobile ? drawerOpen : !collapsed
  useEffect(() => { paneShellRef.current?.toggleAttribute('inert', !sidebarVisible) }, [sidebarVisible])

  return <div className={`chat-workspace ${collapsed && !mobile ? 'sidebar-collapsed' : ''}`}>
    {mobile && drawerOpen && <button className="chat-drawer-scrim" onClick={() => setDrawerOpen(false)} aria-label="Чатын жагсаалт хаах" />}
    <div ref={paneShellRef} className={`chat-pane-shell ${sidebarVisible ? 'open' : ''}`} aria-hidden={!sidebarVisible}>
      <ConversationList drawerRef={drawerRef} conversations={conversationList.data?.items ?? []} selectedId={conversationId} search={search} onSearch={setSearch} onSelect={selectConversation} onCreate={() => setCreateOpen(true)} />
    </div>
    <section className="chat-thread-pane">
      {conversationId && conversation.data ? <>
        <header className="chat-thread-header">
          <button ref={drawerTriggerRef} className="chat-icon-button" onClick={() => mobile ? setDrawerOpen(true) : setCollapsed((value) => !value)} aria-label={sidebarVisible ? 'Чатын жагсаалт нуух' : 'Чатын жагсаалт нээх'}>{mobile || collapsed ? <Menu /> : <ChevronLeft />}</button>
          <Avatar conversation={conversation.data} />
          <div><strong>{conversation.data.title}</strong><small>{conversation.data.kind === 'direct' ? (conversation.data.presence === 'online' ? 'Онлайн' : 'Идэвхгүй') : `${conversation.data.member_count} гишүүн`}</small></div>
          {conversation.data.kind === 'group' && <button className="chat-icon-button" onClick={() => setManageOpen(true)} aria-label="Бүлгийн тохиргоо"><MoreHorizontal /></button>}
        </header>
        <div ref={logRef} className="chat-message-log" role="log" aria-live="polite" aria-label={`${conversation.data.title} мессежүүд`}>
          {messages.hasNextPage && <button className="chat-load-older" onClick={() => messages.fetchNextPage()} disabled={messages.isFetchingNextPage}>{messages.isFetchingNextPage ? 'Ачаалж байна…' : 'Өмнөх мессежүүд'}</button>}
          {!orderedMessages.length && !messages.isLoading && <div className="chat-thread-empty"><MessageCircle /><strong>Харилцан яриагаа эхлүүлнэ үү</strong><span>Энд илгээсэн мессежүүд зөвхөн оролцогчдод харагдана.</span></div>}
          {orderedMessages.map((message) => <article key={`${message.id}-${message.client_nonce}`} className={`chat-message ${message.is_mine ? 'mine' : 'theirs'} ${message.status === 'failed' ? 'send-failed' : ''}`}>
            {!message.is_mine && <Avatar identity={message.sender} />}
            <div><div className="chat-bubble">{!message.is_mine && conversation.data.kind === 'group' && <strong>{message.sender?.name}</strong>}<p>{message.body}</p></div><footer><time>{formatTimestamp(message.created_at)}</time>{message.is_mine && <button disabled={message.id < 1} onClick={() => message.id > 0 && setReceiptMessageId(message.id)}><ReceiptLabel message={message} /></button>}{message.status === 'failed' && <button className="chat-retry" onClick={() => submit(message.body, message.client_nonce)}>Дахин илгээх</button>}</footer></div>
          </article>)}
        </div>
        <footer className="chat-composer"><textarea ref={textareaRef} rows={1} maxLength={4000} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onComposerKeyDown} placeholder="Мессеж бичих…" aria-label="Мессеж" /><button className="chat-send-button" onClick={() => submit()} disabled={!draft.trim() || send.isPending} aria-label="Илгээх"><Send /></button></footer>
      </> : <div className="chat-no-selection"><div><MessageCircle /><h2>OYUNS Chat</h2><p>Хамтран ажиллагсадтайгаа шууд эсвэл бүлгээр аюулгүй харилцана уу.</p><button className="chat-primary-button" onClick={() => mobile ? setDrawerOpen(true) : setCreateOpen(true)}>{mobile ? 'Чат сонгох' : 'Шинэ чат'}</button></div></div>}
    </section>
    <NewChatDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(created) => { setCreateOpen(false); selectConversation(created.public_id) }} />
    {manageOpen && conversation.data && <GroupManager conversation={conversation.data} onClose={() => setManageOpen(false)} onLeft={() => { setManageOpen(false); navigate('/chat'); setDrawerOpen(true) }} />}
    {receiptMessageId && conversationId && <ReceiptDialog conversationId={conversationId} messageId={receiptMessageId} onClose={() => setReceiptMessageId(undefined)} />}
  </div>
}
