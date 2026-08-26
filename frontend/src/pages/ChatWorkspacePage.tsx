import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Archive, BellOff, Bookmark, Check, CheckCheck, ChevronLeft, Download, FileText, Forward, Info, Menu, MessageCircle, Mic, MoreHorizontal, Paperclip, Pause, Pencil, Pin, Play, Plus, Reply, RotateCcw, Search, Send, Square, Star, Trash2,
  UserMinus, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  cancelChatUpload, ChatAttachment, ChatConversation, ChatConversationFilter, ChatIdentity, ChatMessage, CompanyFileChatAttachment, downloadChatAttachment, downloadCompanyFileChatAttachment, uploadChatAttachment, useAcknowledgeChat, useAddChatMembers, useChatContacts,
  useChatConversation, useChatConversations, useChatMessageContext, useChatMessages, useChatReceiptDetails, useCreateChatGroup,
  useDeleteChatMessage, useEditChatMessage, useForwardChatMessage, useLeaveChatGroup, useOpenDirectConversation, usePinChatMessage, useReactChatMessage, useRemoveChatMember, useRenameChatGroup, useSendChatMessage, useStarChatMessage, useChatSearch, useChatThread, useUpdateChatConversationPreferences,
} from '../api/enterprise'
import { resolvePublicAssetUrl, safeLocalStorage } from '../platform/runtime'
import { ChatCallHeader } from '../components/ChatCallHeader'


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

function useFocusTrap<T extends HTMLElement>(active: boolean, onClose: () => void) {
  const ref = useRef<T>(null)
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    if (!active) return
    const previous = document.activeElement as HTMLElement | null
    const container = ref.current
    const focusable = () => [...(container?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]') ?? [])]
    focusable()[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) { event.preventDefault(); return }
      const first = items[0]; const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus?.() }
  }, [active])
  return ref
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

function CallHistoryMessage({ message }: { message: ChatMessage }) {
  const call = message.call
  if (!call) return null
  let label = '📞 Дуудлага дууссан'
  if (call.outcome === 'completed') label += ` • ${formatDuration(call.duration_seconds)}`
  else if (call.outcome === 'missed') label = call.direction === 'incoming' ? '📞 Аваагүй дуудлага' : '📞 Хариу өгөөгүй'
  else if (call.outcome === 'declined') label = call.direction === 'incoming' ? '📞 Татгалзсан дуудлага' : '📞 Дуудлагаас татгалзлаа'
  else if (call.outcome === 'canceled') label = '📞 Цуцалсан дуудлага'
  else label = '📞 Холболт тасарсан'
  return <article id={`chat-message-${message.id}`} className="chat-call-history"><span>{label}</span><time>{formatTimestamp(message.created_at)}</time></article>
}

function ConversationList({
  conversations, selectedId, search, filter, onFilter, onSearch, onSelect, onCreate, drawerRef,
}: {
  conversations: ChatConversation[]; selectedId?: string; search: string; onSearch: (value: string) => void;
  filter: ChatConversationFilter; onFilter: (value: ChatConversationFilter) => void;
  onSelect: (id: string) => void; onCreate: () => void; drawerRef: React.RefObject<HTMLElement>;
}) {
  return (
    <aside ref={drawerRef} className="chat-conversation-pane" aria-label="Чатын жагсаалт">
      <header className="chat-list-header">
        <div><span className="eyebrow">OYUNS</span><h2>Чат</h2></div>
        <button className="chat-icon-button primary" onClick={onCreate} aria-label="Шинэ чат"><Plus /></button>
      </header>
      <label className="chat-search"><Search /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Хэрэглэгч, бүлэг хайх…" /></label>
      <nav className="chat-list-filters" aria-label="Чатын шүүлтүүр">
        {([['all', 'Бүгд'], ['unread', 'Уншаагүй'], ['groups', 'Бүлэг'], ['direct', 'Шууд'], ['archived', 'Архив']] as Array<[ChatConversationFilter, string]>).map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => onFilter(value)} aria-pressed={filter === value}>{label}</button>)}
      </nav>
      <div className="chat-conversation-list">
        {conversations.map((conversation) => (
          <button key={conversation.public_id} className={selectedId === conversation.public_id ? 'active' : ''} onClick={() => onSelect(conversation.public_id)}>
            <span className="chat-avatar-wrap"><Avatar conversation={conversation} />{conversation.kind === 'direct' && <PresenceDot online={conversation.presence === 'online'} />}</span>
            <span className="chat-conversation-copy"><span><strong>{conversation.title}</strong>{conversation.is_pinned && <Pin size={12} fill="currentColor" />}{conversation.is_muted && <BellOff size={12} />}<time>{formatTimestamp(conversation.last_message?.created_at || conversation.updated_at)}</time></span><small>{conversation.last_message?.body || (conversation.kind === 'group' ? `${conversation.member_count} гишүүн` : 'Шинэ чат')}</small></span>
            {conversation.unread_count > 0 && <b className="chat-unread-count" aria-label={`${conversation.unread_count} уншаагүй`}>{conversation.unread_count > 99 ? '99+' : conversation.unread_count}</b>}
          </button>
        ))}
        {!conversations.length && <div className="chat-list-empty"><MessageCircle /><strong>Чат олдсонгүй</strong><span>Шинэ чат бичиж эхлэнэ үү</span></div>}
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
  const modalRef = useFocusTrap<HTMLElement>(open, onClose)
  useEffect(() => { if (!open) { setSearch(''); setTitle(''); setSelected([]); setMode('direct') } }, [open])
  if (!open) return null
  const chooseDirect = async (contact: ChatIdentity) => {
    try { onCreated(await openDirect.mutateAsync(contact.is_agent ? { agent: true } : { account_id: contact.account_id })) } catch (error: any) { toast.error(error.response?.data?.detail || 'Чат нээж чадсангүй') }
  }
  const create = async () => {
    if (!title.trim() || selected.length < 2) return
    try { onCreated(await createGroup.mutateAsync({ title: title.trim(), member_account_ids: selected })) } catch (error: any) { toast.error(error.response?.data?.detail || 'Бүлэг үүссэнгүй') }
  }
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
    <section ref={modalRef} className="chat-modal" role="dialog" aria-modal="true" aria-labelledby="new-chat-title">
      <header><div><span className="eyebrow">OYUNS CHAT</span><h2 id="new-chat-title">Шинэ чат</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
      <div className="chat-segments"><button className={mode === 'direct' ? 'active' : ''} onClick={() => setMode('direct')}>Шууд чат</button><button className={mode === 'group' ? 'active' : ''} onClick={() => setMode('group')}>Бүлэг</button></div>
      {mode === 'group' && <label className="chat-field"><span>Бүлгийн нэр</span><input value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} placeholder="Жишээ: Маркетингийн баг" /></label>}
      <label className="chat-search"><Search /><input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Хэрэглэгч хайх…" /></label>
      <div className="chat-contact-list">
        {(contacts.data ?? []).map((contact) => {
          const checked = selected.includes(contact.account_id)
          return <button key={contact.account_id} className={contact.is_agent ? 'chat-agent-contact' : ''} onClick={() => mode === 'direct' ? chooseDirect(contact) : setSelected((current) => checked ? current.filter((id) => id !== contact.account_id) : [...current, contact.account_id])}>
            <span className="chat-avatar-wrap"><Avatar identity={contact} />{contact.is_agent ? <i className="chat-agent-badge">AI</i> : <PresenceDot online={contact.is_online} />}</span><span><strong>{contact.name}</strong><small>{contact.is_agent ? 'Компанийн AI туслах' : contact.email}</small></span>{mode === 'group' && <i className={`chat-check ${checked ? 'selected' : ''}`}>{checked && <Check />}</i>}
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
  const modalRef = useFocusTrap<HTMLElement>(true, onClose)
  const memberIds = new Set(conversation.members.map((member) => member.account_id))
  const available = (contacts.data ?? []).filter((contact) => !memberIds.has(contact.account_id))
  const saveTitle = async () => { if (title.trim() && title.trim() !== conversation.title) await rename.mutateAsync(title.trim()) }
  const leaveGroup = async () => { if (!window.confirm('Энэ бүлгээс гарах уу?')) return; await leave.mutateAsync(); onLeft() }
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}><section ref={modalRef} className="chat-modal chat-manage-modal" role="dialog" aria-modal="true" aria-label="Бүлгийн тохиргоо">
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
  const modalRef = useFocusTrap<HTMLElement>(true, onClose)
  return <div className="chat-modal-backdrop" onPointerDown={(event) => { if (event.currentTarget === event.target) onClose() }}><section ref={modalRef} className="chat-modal receipt-modal" role="dialog" aria-modal="true" aria-label="Мессежийн төлөв">
    <header><div><span className="eyebrow">MESSAGE INFO</span><h2>Мессежийн төлөв</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
    {receipts.isLoading ? <p className="chat-state">Ачаалж байна…</p> : <><div className="receipt-totals"><span><CheckCheck />Уншсан<strong>{receipts.data?.counts.read ?? 0}</strong></span><span><Check />Хүрсэн<strong>{receipts.data?.counts.delivered ?? 0}</strong></span><span><Send />Нийт<strong>{receipts.data?.counts.total ?? 0}</strong></span></div><div className="receipt-list">{receipts.data?.items.map((item) => <div key={item.account.account_id}><Avatar identity={item.account} /><span><strong>{item.account.name}</strong><small>{item.status === 'read' ? `Уншсан · ${formatTimestamp(item.read_at)}` : item.status === 'delivered' ? `Хүрсэн · ${formatTimestamp(item.delivered_at)}` : 'Илгээсэн'}</small></span></div>)}</div></>}
  </section></div>
}

type PendingUpload = { localId: string; file: File; progress: number; status: 'uploading' | 'ready' | 'failed'; attachment?: ChatAttachment; controller: AbortController; error?: string }

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

const RECORDER_FORMATS = [
  // Python's mimetypes maps `.webm` to video/webm; `.weba` is the audio/webm extension.
  { mime: 'audio/webm;codecs=opus', type: 'audio/webm', extension: 'weba' },
  { mime: 'audio/ogg;codecs=opus', type: 'audio/ogg', extension: 'ogg' },
  { mime: 'audio/mp4', type: 'audio/mp4', extension: 'm4a' },
  { mime: 'audio/wav', type: 'audio/wav', extension: 'wav' },
] as const

function formatDuration(value: number) {
  if (!Number.isFinite(value) || value < 0) return '0:00'
  const seconds = Math.floor(value)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function WaveformBars({ values, progress = 0, recording = false }: { values: number[]; progress?: number; recording?: boolean }) {
  return <span className={`chat-waveform ${recording ? 'recording' : ''}`} aria-hidden>
    {values.map((value, index) => <i key={index} className={index / Math.max(values.length, 1) <= progress ? 'played' : ''} style={{ height: `${Math.max(16, Math.min(100, value * 100))}%` }} />)}
  </span>
}

function RecordingVisualizer({ stream }: { stream: MediaStream | null }) {
  const [levels, setLevels] = useState<number[]>(() => Array.from({ length: 28 }, () => 0.18))
  useEffect(() => {
    if (!stream) return
    const context = new AudioContext()
    const source = context.createMediaStreamSource(stream)
    const analyser = context.createAnalyser()
    analyser.fftSize = 64
    source.connect(analyser)
    const data = new Uint8Array(analyser.frequencyBinCount)
    let frame = 0
    const update = () => {
      analyser.getByteFrequencyData(data)
      setLevels(Array.from(data).map((value) => Math.max(0.12, value / 255)).slice(0, 28))
      frame = requestAnimationFrame(update)
    }
    update()
    return () => { cancelAnimationFrame(frame); source.disconnect(); analyser.disconnect(); void context.close() }
  }, [stream])
  return <div className="chat-recording-visualizer" role="status" aria-label="Аудио бичиж байна"><WaveformBars values={levels} recording /><span>Бичиж байна…</span></div>
}

function VoiceMessagePlayer({ conversationId, attachment }: { conversationId: string; attachment: ChatAttachment }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const waveformRef = useRef<HTMLButtonElement>(null)
  const [url, setUrl] = useState<string>()
  const [waveform, setWaveform] = useState<number[]>([])
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(attachment.duration_seconds || 0)
  const [speed, setSpeed] = useState(1)

  useEffect(() => {
    let active = true
    let objectUrl: string | undefined
    void downloadChatAttachment(conversationId, attachment).then(async (value) => {
      objectUrl = value
      if (!active) { URL.revokeObjectURL(value); return }
      setUrl(value)
      try {
        const response = await fetch(value)
        const buffer = await response.arrayBuffer()
        const context = new AudioContext()
        const decoded = await context.decodeAudioData(buffer)
        const data = decoded.getChannelData(0)
        const bars = 44
        const block = Math.max(1, Math.floor(data.length / bars))
        const samples = Array.from({ length: bars }, (_, index) => {
          let peak = 0
          for (let offset = index * block; offset < Math.min(data.length, (index + 1) * block); offset += 1) peak = Math.max(peak, Math.abs(data[offset]))
          return peak || 0.12
        })
        if (active) { setWaveform(samples); setDuration(decoded.duration) }
        await context.close()
      } catch { if (active) setWaveform(Array.from({ length: 44 }, () => 0.35)) }
    }).catch(() => undefined)
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [attachment.public_id, conversationId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const audio = audioRef.current
    if (audio) audio.playbackRate = speed
  }, [speed])

  const seek = (event: React.PointerEvent<HTMLButtonElement>) => {
    const audio = audioRef.current
    const element = waveformRef.current
    if (!audio || !element || !duration) return
    const update = (clientX: number) => {
      const bounds = element.getBoundingClientRect()
      const ratio = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width))
      audio.currentTime = ratio * duration
      setCurrent(audio.currentTime)
    }
    update(event.clientX)
    element.setPointerCapture(event.pointerId)
    const move = (moveEvent: PointerEvent) => update(moveEvent.clientX)
    const up = () => { element.removeEventListener('pointermove', move); element.removeEventListener('pointerup', up) }
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerup', up, { once: true })
  }

  const toggle = () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) void audio.play().catch(() => undefined)
    else audio.pause()
  }

  return <div className="chat-voice-player">
    <button className="chat-voice-toggle" onClick={toggle} disabled={!url} aria-label={playing ? 'Түр зогсоох' : 'Тоглуулах'}>{playing ? <Pause /> : <Play />}</button>
    <div className="chat-voice-track"><button ref={waveformRef} className="chat-waveform-button" onPointerDown={seek} aria-label="Дууны байрлал сонгох"><WaveformBars values={waveform.length ? waveform : Array.from({ length: 44 }, () => 0.2)} progress={duration ? current / duration : 0} /></button><div className="chat-voice-meta"><span>{formatDuration(current)}</span><span>{formatDuration(duration)}</span></div></div>
    <button className="chat-voice-speed" onClick={() => setSpeed((value) => value >= 2 ? 1 : value + 0.5)} aria-label={`Хурд ${speed}x`}>{speed}x</button>
    <audio ref={audioRef} src={url} preload="metadata" onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || duration)} onTimeUpdate={(event) => setCurrent(event.currentTarget.currentTime)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setCurrent(0) }} />
  </div>
}

function ChatAttachmentView({ conversationId, attachment }: { conversationId: string; attachment: ChatAttachment }) {
  const [url, setUrl] = useState<string>()
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (attachment.media_kind === 'document') return
    let active = true
    let objectUrl: string | undefined
    void downloadChatAttachment(conversationId, attachment).then((value) => { objectUrl = value; if (active) setUrl(value); else URL.revokeObjectURL(value) }).catch(() => undefined)
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [attachment.public_id, conversationId]) // eslint-disable-line react-hooks/exhaustive-deps
  const download = async () => {
    setLoading(true)
    try {
      const objectUrl = await downloadChatAttachment(conversationId, attachment)
      const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = attachment.filename; anchor.click(); URL.revokeObjectURL(objectUrl)
    } catch { toast.error('Файл татаж чадсангүй') } finally { setLoading(false) }
  }
  if (attachment.media_kind === 'image') return <button className="chat-media-image" onClick={download} aria-label={`${attachment.filename} татах`}>{url ? <img src={url} alt={attachment.filename} /> : <span>Зураг ачаалж байна…</span>}</button>
  if (attachment.media_kind === 'video') return <div className="chat-media-player">{url ? <video controls preload="metadata" src={url} /> : <span>Видео ачаалж байна…</span>}<small>{attachment.filename} · {formatBytes(attachment.size)}</small></div>
  if (attachment.media_kind === 'audio') return <div className="chat-media-player audio"><VoiceMessagePlayer conversationId={conversationId} attachment={attachment} /><small>{attachment.filename} · {formatBytes(attachment.size)}</small></div>
  return <button className="chat-document-card" onClick={download} disabled={loading}><FileText /><span><strong>{attachment.filename}</strong><small>{formatBytes(attachment.size)} · {attachment.content_type}</small></span><Download /></button>
}

function CompanyFileAttachmentView({ attachment }: { attachment: CompanyFileChatAttachment }) {
  const [loading, setLoading] = useState(false)
  const download = async () => {
    setLoading(true)
    try {
      const objectUrl = await downloadCompanyFileChatAttachment(attachment)
      const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = attachment.filename; anchor.click(); URL.revokeObjectURL(objectUrl)
    } catch { toast.error('Компанийн файл татаж чадсангүй') } finally { setLoading(false) }
  }
  return <button className="chat-document-card" onClick={download} disabled={loading}><FileText /><span><strong>{attachment.filename}</strong><small>{attachment.size ? formatBytes(attachment.size) : ''} · {attachment.content_type}</small></span><Download /></button>
}

function ChatSearchPanel({ conversationId, onClose, onOpenResult }: { conversationId?: string; onClose: () => void; onOpenResult: (conversationId: string, messageId: number) => void }) {
  const [scope, setScope] = useState<'conversation' | 'global'>(conversationId ? 'conversation' : 'global')
  const [search, setSearch] = useState('')
  const results = useChatSearch(search, scope === 'conversation' ? conversationId : undefined, search.trim().length >= 2)
  const panelRef = useFocusTrap<HTMLElement>(true, onClose)
  return <aside ref={panelRef} className="chat-side-panel chat-search-panel" role="dialog" aria-modal="true" aria-label="Мессеж хайх">
    <header><div><span className="eyebrow">SEARCH</span><h2>Мессеж хайх</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
    <div className="chat-segments"><button className={scope === 'conversation' ? 'active' : ''} disabled={!conversationId} onClick={() => setScope('conversation')}>Энэ чат</button><button className={scope === 'global' ? 'active' : ''} onClick={() => setScope('global')}>Бүх чат</button></div>
    <label className="chat-search"><Search /><input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Түүхээс хайх…" /></label>
    <div className="chat-search-results">{results.isFetching && <p>Хайж байна…</p>}{results.data?.items.map((item) => <button key={`${item.conversation.public_id}-${item.message.id}`} onClick={() => onOpenResult(item.conversation.public_id, item.message.id)}><strong>{item.conversation.title}</strong><span>{item.message.sender?.name || 'Unknown'} · {formatTimestamp(item.message.created_at)}</span><p>{item.message.body || item.message.attachments?.map((file) => file.filename).join(', ')}</p></button>)}{search.trim().length >= 2 && !results.isFetching && !results.data?.items.length && <p>Илэрц олдсонгүй.</p>}</div>
  </aside>
}

function ThreadPanel({ conversationId, rootId, onClose, onReply }: { conversationId: string; rootId: number; onClose: () => void; onReply: (message: ChatMessage) => void }) {
  const thread = useChatThread(conversationId, rootId)
  const items = thread.data ? [thread.data.root, ...thread.data.items] : []
  const panelRef = useFocusTrap<HTMLElement>(true, onClose)
  return <aside ref={panelRef} className="chat-side-panel chat-thread-panel" role="dialog" aria-modal="true" aria-label="Мессежийн thread">
    <header><div><span className="eyebrow">THREAD</span><h2>Хариултууд</h2></div><button className="chat-icon-button" onClick={onClose} aria-label="Хаах"><X /></button></header>
    <div>{thread.isLoading && <p>Ачаалж байна…</p>}{items.map((message) => <article key={message.id}><strong>{message.sender?.name}</strong><p>{message.is_deleted ? 'Энэ мессеж устгагдсан' : message.body || 'Хавсралт'}</p><small>{formatTimestamp(message.created_at)}</small></article>)}</div>
    {thread.data?.root && <button className="chat-primary-button" onClick={() => onReply(thread.data!.root)}><Reply /> Thread-д хариулах</button>}
  </aside>
}

type ChatActionMenuProps = {
  anchorRef: React.RefObject<HTMLButtonElement>
  boundsRef: React.RefObject<HTMLElement>
  onClose: () => void
  children: React.ReactNode
}

function ChatActionMenu({ anchorRef, boundsRef, onClose, children }: ChatActionMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ left: number; top: number; placement: 'above' | 'below' }>()

  useLayoutEffect(() => {
    const anchor = anchorRef.current
    const menu = menuRef.current
    if (!anchor || !menu) return

    const updatePosition = () => {
      const anchorRect = anchor.getBoundingClientRect()
      const menuRect = menu.getBoundingClientRect()
      const paneRect = boundsRef.current?.getBoundingClientRect()
      const padding = 8
      const minLeft = Math.max(padding, paneRect?.left ?? padding)
      const maxRight = Math.min(window.innerWidth - padding, paneRect?.right ?? window.innerWidth - padding)
      const minTop = Math.max(padding, paneRect?.top ?? padding)
      const maxBottom = Math.min(window.innerHeight - padding, paneRect?.bottom ?? window.innerHeight - padding)
      const availableAbove = anchorRect.top - minTop
      const placement = availableAbove >= menuRect.height + padding || anchorRect.bottom + menuRect.height + padding > maxBottom ? 'above' : 'below'
      const preferredTop = placement === 'above' ? anchorRect.top - menuRect.height - padding : anchorRect.bottom + padding
      const top = Math.max(minTop, Math.min(preferredTop, maxBottom - menuRect.height))
      const preferredLeft = anchorRect.right - menuRect.width
      const left = Math.max(minLeft, Math.min(preferredLeft, maxRight - menuRect.width))
      setPosition({ left, top, placement })
    }

    updatePosition()
    const onViewportChange = () => updatePosition()
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', onViewportChange, true)
    return () => {
      window.removeEventListener('resize', onViewportChange)
      window.removeEventListener('scroll', onViewportChange, true)
    }
  }, [anchorRef, boundsRef])

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (!menuRef.current?.contains(target) && !anchorRef.current?.contains(target)) onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [anchorRef, onClose])

  return createPortal(
    <div ref={menuRef} className="chat-popover-menu message chat-portal-menu" data-placement={position?.placement} style={position ? { left: position.left, top: position.top } : undefined}>
      {children}
    </div>,
    document.body,
  )
}

function ForwardDialog({ message, conversations, onClose, onForward }: { message: ChatMessage; conversations: ChatConversation[]; onClose: () => void; onForward: (ids: string[]) => void }) {
  const [selected, setSelected] = useState<string[]>([])
  const modalRef = useFocusTrap<HTMLElement>(true, onClose)
  return <div className="chat-modal-backdrop"><section ref={modalRef} className="chat-modal" role="dialog" aria-modal="true" aria-label="Мессеж дамжуулах"><header><div><span className="eyebrow">FORWARD</span><h2>Мессеж дамжуулах</h2></div><button className="chat-icon-button" onClick={onClose}><X /></button></header><div className="chat-contact-list">{conversations.map((conversation) => <button key={conversation.public_id} onClick={() => setSelected((items) => items.includes(conversation.public_id) ? items.filter((id) => id !== conversation.public_id) : items.length < 10 ? [...items, conversation.public_id] : items)}><Avatar conversation={conversation} /><span><strong>{conversation.title}</strong><small>{conversation.kind === 'group' ? `${conversation.member_count} гишүүн` : 'Шууд чат'}</small></span><i className={`chat-check ${selected.includes(conversation.public_id) ? 'selected' : ''}`}>{selected.includes(conversation.public_id) && <Check />}</i></button>)}</div><footer><span>{selected.length} сонгосон</span><button className="chat-primary-button" disabled={!selected.length} onClick={() => onForward(selected)}><Forward /> Дамжуулах</button></footer></section></div>
}

export function ChatWorkspacePage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const mobile = useMobileLayout()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<ChatConversationFilter>('all')
  const [collapsed, setCollapsed] = useState(() => safeLocalStorage().get('oyuns-chat-sidebar-collapsed') === '1')
  const [drawerOpen, setDrawerOpen] = useState(() => !conversationId)
  const [createOpen, setCreateOpen] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [conversationMenuOpen, setConversationMenuOpen] = useState(false)
  const [receiptMessageId, setReceiptMessageId] = useState<number>()
  const [searchOpen, setSearchOpen] = useState(false)
  const [threadRootId, setThreadRootId] = useState<number>()
  const [actionMessageId, setActionMessageId] = useState<number>()
  const [replyingTo, setReplyingTo] = useState<ChatMessage>()
  const [forwardMessage, setForwardMessage] = useState<ChatMessage>()
  const [uploads, setUploads] = useState<PendingUpload[]>([])
  const [recording, setRecording] = useState(false)
  const [recordingStream, setRecordingStream] = useState<MediaStream | null>(null)
  const [draft, setDraft] = useState('')
  const drawerRef = useRef<HTMLElement>(null)
  const paneShellRef = useRef<HTMLDivElement>(null)
  const drawerTriggerRef = useRef<HTMLButtonElement>(null)
  const threadPaneRef = useRef<HTMLElement>(null)
  const actionButtonRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MediaRecorder>()
  const recordingStreamRef = useRef<MediaStream | null>(null)
  const recordingTimerRef = useRef<number>()
  const uploadsRef = useRef<PendingUpload[]>([])
  const lastAckRef = useRef('')
  const highlightId = Number(searchParams.get('message')) || undefined
  const conversationList = useChatConversations(search, filter)
  const allConversations = useChatConversations('', 'all')
  const conversation = useChatConversation(conversationId)
  const messages = useChatMessages(conversationId)
  const context = useChatMessageContext(conversationId, highlightId)
  const send = useSendChatMessage(conversationId)
  const acknowledge = useAcknowledgeChat(conversationId)
  const edit = useEditChatMessage(conversationId)
  const remove = useDeleteChatMessage(conversationId)
  const react = useReactChatMessage(conversationId)
  const star = useStarChatMessage(conversationId)
  const pinMessage = usePinChatMessage(conversationId)
  const forward = useForwardChatMessage(conversationId)
  const preferences = useUpdateChatConversationPreferences(conversationId)
  const orderedMessages = useMemo(() => context.data?.items?.length ? context.data.items : [...(messages.data?.pages ?? [])].reverse().flatMap((page) => page.items), [context.data?.items, messages.data?.pages])

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
    if (highlightId) document.getElementById(`chat-message-${highlightId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    else logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
    const latest = [...orderedMessages].reverse().find((message) => message.kind !== 'call' && message.id > 0 && !message.is_mine)
    if (!latest || !conversationId || document.visibilityState !== 'visible') return
    const key = `${conversationId}:${latest.id}:read`
    if (lastAckRef.current === key) return
    lastAckRef.current = key
    acknowledge.mutate({ message_id: latest.id, status: 'read' })
  }, [conversationId, highlightId, orderedMessages]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { uploadsRef.current = uploads }, [uploads])
  useEffect(() => {
    setUploads([])
    return () => {
      uploadsRef.current.forEach((item) => {
        item.controller.abort()
        if (conversationId && item.attachment) void cancelChatUpload(conversationId, item.attachment.public_id)
      })
      if (recordingTimerRef.current) window.clearTimeout(recordingTimerRef.current)
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop())
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop())
      recordingStreamRef.current = null
      setRecordingStream(null)
    }
  }, [conversationId])

  const selectConversation = (id: string) => { navigate(`/chat/${id}`); if (mobile) setDrawerOpen(false) }
  const beginUpload = (localId: string, file: File, controller: AbortController) => {
    if (!conversationId) return
    void uploadChatAttachment(conversationId, file, (progress) => setUploads((items) => items.map((item) => item.localId === localId ? { ...item, progress } : item)), controller.signal)
      .then((attachment) => setUploads((items) => items.map((item) => item.localId === localId ? { ...item, status: 'ready', progress: 100, attachment, error: undefined } : item)))
      .catch((error) => { if (!controller.signal.aborted) setUploads((items) => items.map((item) => item.localId === localId ? { ...item, status: 'failed', error: error.response?.data?.detail || 'Upload failed' } : item)) })
  }
  const queueFiles = (files: File[]) => {
    if (!conversationId) return
    const available = Math.max(0, 10 - uploads.length)
    let totalBytes = uploads.reduce((total, item) => total + item.file.size, 0)
    files.slice(0, available).forEach((file) => {
      if (file.size > 25 * 1024 * 1024) { toast.error(`${file.name}: 25 MB-аас их байна`); return }
      if (totalBytes + file.size > 100 * 1024 * 1024) { toast.error('Нэг мессежийн хавсралт нийт 100 MB-аас их байж болохгүй'); return }
      totalBytes += file.size
      const controller = new AbortController()
      const localId = crypto.randomUUID()
      const pending: PendingUpload = { localId, file, progress: 0, status: 'uploading', controller }
      setUploads((items) => [...items, pending])
      beginUpload(localId, file, controller)
    })
  }
  const retryUpload = (item: PendingUpload) => {
    const controller = new AbortController()
    setUploads((items) => items.map((candidate) => candidate.localId === item.localId ? { ...candidate, controller, status: 'uploading', progress: 0, error: undefined } : candidate))
    beginUpload(item.localId, item.file, controller)
  }
  const discardUpload = (item: PendingUpload) => {
    item.controller.abort()
    if (conversationId && item.attachment) void cancelChatUpload(conversationId, item.attachment.public_id)
    setUploads((items) => items.filter((candidate) => candidate.localId !== item.localId))
  }
  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') { toast.error('Энэ төхөөрөмж аудио бичлэг дэмжихгүй байна'); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = []
      const selected = RECORDER_FORMATS.find(({ mime }) => MediaRecorder.isTypeSupported(mime)) || RECORDER_FORMATS.find(({ type }) => MediaRecorder.isTypeSupported(type))
      if (!selected) { stream.getTracks().forEach((track) => track.stop()); toast.error('Дэмжигдсэн аудио формат олдсонгүй'); return }
      const recorder = new MediaRecorder(stream, { mimeType: selected.mime })
      recorderRef.current = recorder
      recordingStreamRef.current = stream
      setRecordingStream(stream)
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        recordingStreamRef.current = null
        setRecordingStream(null)
        setRecording(false)
        if (recordingTimerRef.current) window.clearTimeout(recordingTimerRef.current)
        if (chunks.length) {
          const blob = new Blob(chunks, { type: selected.type })
          queueFiles([new File([blob], `voice-note-${Date.now()}.${selected.extension}`, { type: selected.type })])
        }
      }
      recorder.start()
      setRecording(true)
      recordingTimerRef.current = window.setTimeout(() => recorder.state === 'recording' && recorder.stop(), 5 * 60_000)
    } catch { toast.error('Микрофоны зөвшөөрөл шаардлагатай') }
  }
  const stopRecording = () => recorderRef.current?.state === 'recording' && recorderRef.current.stop()
  const submit = (body: string | null = draft, nonce: string = crypto.randomUUID()) => {
    const text = body?.trim() || null
    const readyUploads = uploads.filter((item) => item.status === 'ready' && item.attachment)
    if ((!text && !readyUploads.length) || uploads.some((item) => item.status !== 'ready') || send.isPending) return
    if (body === draft) setDraft('')
    send.mutate({ body: text, client_nonce: nonce, upload_ids: readyUploads.map((item) => item.attachment!.public_id), reply_to_message_id: replyingTo?.id }, { onSuccess: () => { setUploads([]); setReplyingTo(undefined) } })
  }
  const onComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!mobile && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() }
  }
  const sidebarVisible = mobile ? drawerOpen : !collapsed
  useEffect(() => { paneShellRef.current?.toggleAttribute('inert', !sidebarVisible) }, [sidebarVisible])

  const editMessage = (message: ChatMessage) => {
    const body = window.prompt('Мессеж засах', message.body || '')
    if (body?.trim() && body.trim() !== message.body) edit.mutate({ messageId: message.id, body: body.trim() })
    setActionMessageId(undefined)
  }
  const forwardTo = (ids: string[]) => {
    if (!forwardMessage) return
    forward.mutate({ messageId: forwardMessage.id, destinations: ids.map((conversation_public_id) => ({ conversation_public_id, client_nonce: crypto.randomUUID() })) }, { onSuccess: () => { toast.success('Мессеж дамжууллаа'); setForwardMessage(undefined) } })
  }

  return <div className={`chat-workspace ${collapsed && !mobile ? 'sidebar-collapsed' : ''}`}>
    {mobile && drawerOpen && <button className="chat-drawer-scrim" onClick={() => setDrawerOpen(false)} aria-label="Чатын жагсаалт хаах" />}
    <div ref={paneShellRef} className={`chat-pane-shell ${sidebarVisible ? 'open' : ''}`} aria-hidden={!sidebarVisible}>
      <ConversationList drawerRef={drawerRef} conversations={conversationList.data?.items ?? []} selectedId={conversationId} search={search} filter={filter} onFilter={setFilter} onSearch={setSearch} onSelect={selectConversation} onCreate={() => setCreateOpen(true)} />
    </div>
    <section ref={threadPaneRef} className="chat-thread-pane">
      {conversationId && conversation.data ? <>
        <header className="chat-thread-header">
          <button ref={drawerTriggerRef} className="chat-icon-button" onClick={() => mobile ? setDrawerOpen(true) : setCollapsed((value) => !value)} aria-label={sidebarVisible ? 'Чатын жагсаалт нуух' : 'Чатын жагсаалт нээх'}>{mobile || collapsed ? <Menu /> : <ChevronLeft />}</button>
          <Avatar conversation={conversation.data} />
          <div><strong>{conversation.data.title}</strong><small>{conversation.data.kind === 'direct' ? (conversation.data.presence === 'online' ? 'Онлайн' : 'Идэвхгүй') : `${conversation.data.member_count} гишүүн`}</small></div>
          <ChatCallHeader conversation={conversation.data} />
          <button className="chat-icon-button" onClick={() => setSearchOpen(true)} aria-label="Мессеж хайх"><Search /></button>
          <div className="chat-header-menu-wrap"><button className="chat-icon-button" onClick={() => setConversationMenuOpen((value) => !value)} aria-label="Чатын тохиргоо"><MoreHorizontal /></button>{conversationMenuOpen && <div className="chat-popover-menu">
            <button onClick={() => preferences.mutate({ pinned: !conversation.data!.is_pinned }, { onSuccess: () => setConversationMenuOpen(false) })}><Pin />{conversation.data.is_pinned ? 'Чат салгах' : 'Чат тогтоох'}</button>
            <button onClick={() => preferences.mutate({ archived: !conversation.data!.is_archived }, { onSuccess: () => { setConversationMenuOpen(false); if (!conversation.data!.is_archived) navigate('/chat') } })}><Archive />{conversation.data.is_archived ? 'Архиваас гаргах' : 'Архивлах'}</button>
            {conversation.data.is_muted ? <button onClick={() => preferences.mutate({ mute_for: 'off' }, { onSuccess: () => setConversationMenuOpen(false) })}><BellOff />Дууг нээх</button> : <><button onClick={() => preferences.mutate({ mute_for: '1h' }, { onSuccess: () => setConversationMenuOpen(false) })}><BellOff />1 цаг дуугүй</button><button onClick={() => preferences.mutate({ mute_for: '8h' }, { onSuccess: () => setConversationMenuOpen(false) })}><BellOff />8 цаг дуугүй</button><button onClick={() => preferences.mutate({ mute_for: '1w' }, { onSuccess: () => setConversationMenuOpen(false) })}><BellOff />1 долоо хоног дуугүй</button><button onClick={() => preferences.mutate({ mute_for: 'forever' }, { onSuccess: () => setConversationMenuOpen(false) })}><BellOff />Үргэлж дуугүй</button></>}
            {conversation.data.kind === 'group' && <button onClick={() => { setManageOpen(true); setConversationMenuOpen(false) }}><Info />Бүлгийн тохиргоо</button>}
          </div>}</div>
        </header>
        <div ref={logRef} className="chat-message-log" role="log" aria-live="polite" aria-label={`${conversation.data.title} мессежүүд`}>
          {messages.hasNextPage && <button className="chat-load-older" onClick={() => messages.fetchNextPage()} disabled={messages.isFetchingNextPage}>{messages.isFetchingNextPage ? 'Ачаалж байна…' : 'Өмнөх мессежүүд'}</button>}
          {!orderedMessages.length && !messages.isLoading && <div className="chat-thread-empty"><MessageCircle /><strong>Чат бичиж харилцан яриагаа эхлүүлээрэй</strong><span>Энд илгээсэн мессежүүд зөвхөн оролцогчдод харагдана.</span></div>}
          {orderedMessages.map((message) => message.kind === 'call' ? <CallHistoryMessage key={`${message.id}-${message.client_nonce}`} message={message} /> : <article id={message.id > 0 ? `chat-message-${message.id}` : undefined} key={`${message.id}-${message.client_nonce}`} className={`chat-message ${message.is_mine ? 'mine' : 'theirs'} ${message.status === 'failed' ? 'send-failed' : ''} ${highlightId === message.id ? 'highlighted' : ''}`} onContextMenu={(event) => { if (message.id > 0 && !message.is_deleted) { event.preventDefault(); setActionMessageId(message.id) } }}>
            {!message.is_mine && <Avatar identity={message.sender} />}
            <div className="chat-message-content"><div className="chat-bubble">{!message.is_mine && conversation.data.kind === 'group' && <strong>{message.sender?.name}</strong>}{message.forwarded_sender_name && <small className="chat-forwarded"><Forward /> {message.forwarded_sender_name}-с дамжуулсан</small>}{message.reply_preview && <button className="chat-reply-preview" onClick={() => setThreadRootId(message.thread_root_message_id || message.reply_preview!.id)}><strong>{message.reply_preview.sender_name}</strong><span>{message.reply_preview.is_deleted ? 'Устгасан мессеж' : message.reply_preview.body || 'Хавсралт'}</span></button>}{message.is_deleted ? <p className="chat-deleted-message">Энэ мессеж устгагдсан</p> : <>{message.body && <p>{message.body}</p>}{message.attachments?.length ? <div className="chat-attachments">{message.attachments.map((attachment) => <ChatAttachmentView key={attachment.public_id} conversationId={conversationId} attachment={attachment} />)}</div> : null}{message.company_file_attachments?.length ? <div className="chat-attachments">{message.company_file_attachments.map((attachment) => <CompanyFileAttachmentView key={attachment.item_id} attachment={attachment} />)}</div> : null}</>} </div>
              {!!message.reactions?.length && <div className="chat-reaction-row">{message.reactions.map((reaction) => <button key={reaction.emoji} className={reaction.reacted ? 'active' : ''} onClick={() => react.mutate({ messageId: message.id, emoji: reaction.emoji, remove: reaction.reacted })}>{reaction.emoji} <span>{reaction.count}</span></button>)}</div>}
              <footer><time>{formatTimestamp(message.created_at)}{message.edited_at ? ' · зассан' : ''}</time>{message.is_pinned && <Pin size={11} fill="currentColor" />}{message.is_starred && <Star size={11} fill="currentColor" />}{message.thread_reply_count > 0 && <button onClick={() => setThreadRootId(message.thread_root_message_id || message.id)}>{message.thread_reply_count} хариулт</button>}{message.is_mine && <button disabled={message.id < 1} onClick={() => message.id > 0 && setReceiptMessageId(message.id)}><ReceiptLabel message={message} /></button>}{message.status === 'failed' && message.body && <button className="chat-retry" onClick={() => submit(message.body, message.client_nonce)}>Дахин илгээх</button>}</footer>
              {message.id > 0 && !message.is_deleted && <div className="chat-message-actions"><button ref={(element) => { actionButtonRefs.current[message.id] = element }} onClick={() => setActionMessageId(actionMessageId === message.id ? undefined : message.id)} aria-label="Мессежийн үйлдэл"><MoreHorizontal /></button>{actionMessageId === message.id && <ChatActionMenu anchorRef={{ current: actionButtonRefs.current[message.id] }} boundsRef={threadPaneRef} onClose={() => setActionMessageId(undefined)}><div className="chat-quick-reactions">{['👍', '❤️', '😂', '🎉', '😮', '😢'].map((emoji) => <button key={emoji} onClick={() => react.mutate({ messageId: message.id, emoji, remove: message.reactions?.some((item) => item.emoji === emoji && item.reacted) })}>{emoji}</button>)}</div><button onClick={() => { setReplyingTo(message); setActionMessageId(undefined); textareaRef.current?.focus() }}><Reply />Хариулах</button>{message.thread_root_message_id == null && <button onClick={() => { setThreadRootId(message.id); setActionMessageId(undefined) }}><MessageCircle />Thread нээх</button>}{message.capabilities?.can_edit && <button onClick={() => editMessage(message)}><Pencil />Засах</button>}<button onClick={() => { setForwardMessage(message); setActionMessageId(undefined) }}><Forward />Дамжуулах</button><button onClick={() => pinMessage.mutate({ messageId: message.id, pinned: !message.is_pinned }, { onSuccess: () => setActionMessageId(undefined) })}><Pin />{message.is_pinned ? 'Салгах' : 'Тогтоох'}</button><button onClick={() => star.mutate({ messageId: message.id, starred: !message.is_starred }, { onSuccess: () => setActionMessageId(undefined) })}><Star />{message.is_starred ? 'Star болиулах' : 'Star'}</button><button onClick={() => { setReceiptMessageId(message.id); setActionMessageId(undefined) }}><Info />Мэдээлэл</button><button className="danger" onClick={() => remove.mutate({ messageId: message.id, scope: 'self' }, { onSuccess: () => setActionMessageId(undefined) })}><Trash2 />Өөрөөс устгах</button>{message.capabilities?.can_delete_everyone && <button className="danger" onClick={() => window.confirm('Бүх хүнээс устгах уу?') && remove.mutate({ messageId: message.id, scope: 'everyone' }, { onSuccess: () => setActionMessageId(undefined) })}><Trash2 />Бүгдээс устгах</button>}</ChatActionMenu>}</div>}
            </div>
          </article>)}
        </div>
        <footer className="chat-composer-shell">{recording && <RecordingVisualizer stream={recordingStream} />}{replyingTo && <div className="chat-composer-reply"><Reply /><span><strong>{replyingTo.sender?.name}</strong>{replyingTo.body || 'Хавсралт'}</span><button onClick={() => setReplyingTo(undefined)} aria-label="Хариултыг болих"><X /></button></div>}{uploads.length > 0 && <div className="chat-upload-queue">{uploads.map((item) => <div key={item.localId} className={item.status}><Paperclip /><span><strong>{item.file.name}</strong><small>{item.status === 'failed' ? item.error : item.status === 'ready' ? 'Бэлэн' : `${item.progress}%`}</small>{item.status === 'uploading' && <i style={{ width: `${item.progress}%` }} />}</span>{item.status === 'failed' && <button onClick={() => retryUpload(item)} aria-label={`${item.file.name} дахин upload хийх`}><RotateCcw /></button>}<button onClick={() => discardUpload(item)} aria-label={`${item.file.name} хасах`}><X /></button></div>)}</div>}<div className="chat-composer"><input ref={fileInputRef} type="file" hidden multiple accept="image/*,video/mp4,video/webm,video/quicktime,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.md" onChange={(event) => { queueFiles(Array.from(event.target.files ?? [])); event.currentTarget.value = '' }} /><button className="chat-composer-tool" onClick={() => fileInputRef.current?.click()} disabled={uploads.length >= 10} aria-label="Файл хавсаргах"><Paperclip /></button><textarea ref={textareaRef} rows={1} maxLength={4000} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onComposerKeyDown} placeholder="Мессеж бичих…" aria-label="Мессеж" /><button className={`chat-composer-tool ${recording ? 'recording' : ''}`} onClick={recording ? stopRecording : startRecording} aria-label={recording ? 'Бичлэг дуусгах' : 'Аудио бичих'}>{recording ? <Square /> : <Mic />}</button><button className="chat-send-button" onClick={() => submit()} disabled={(!draft.trim() && !uploads.some((item) => item.status === 'ready')) || uploads.some((item) => item.status !== 'ready') || send.isPending} aria-label="Илгээх"><Send /></button></div></footer>
      </> : <div className="chat-no-selection"><div><MessageCircle /><h2>OYUNS Chat</h2><p>Хамтран ажиллагсадтайгаа шууд эсвэл бүлгээр аюулгүй харилцана уу.</p><button className="chat-primary-button" onClick={() => mobile ? setDrawerOpen(true) : setCreateOpen(true)}>{mobile ? 'Чат сонгох' : 'Шинэ чат'}</button></div></div>}
    </section>
    {searchOpen && <ChatSearchPanel conversationId={conversationId} onClose={() => setSearchOpen(false)} onOpenResult={(id, messageId) => { setSearchOpen(false); navigate(`/chat/${id}?message=${messageId}`) }} />}
    {threadRootId && conversationId && <ThreadPanel conversationId={conversationId} rootId={threadRootId} onClose={() => setThreadRootId(undefined)} onReply={(message) => { setReplyingTo(message); setThreadRootId(undefined); textareaRef.current?.focus() }} />}
    <NewChatDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(created) => { setCreateOpen(false); selectConversation(created.public_id) }} />
    {manageOpen && conversation.data && <GroupManager conversation={conversation.data} onClose={() => setManageOpen(false)} onLeft={() => { setManageOpen(false); navigate('/chat'); setDrawerOpen(true) }} />}
    {receiptMessageId && conversationId && <ReceiptDialog conversationId={conversationId} messageId={receiptMessageId} onClose={() => setReceiptMessageId(undefined)} />}
    {forwardMessage && <ForwardDialog message={forwardMessage} conversations={(allConversations.data?.items ?? []).filter((item) => item.public_id !== conversationId)} onClose={() => setForwardMessage(undefined)} onForward={forwardTo} />}
  </div>
}
