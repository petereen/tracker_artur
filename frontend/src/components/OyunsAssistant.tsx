import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, CircleCheck, CircleX, Download, LoaderCircle, Mic, Pencil, Send, Sparkles, Square, SquarePen, X } from 'lucide-react'
import { AssistantFileAttachment, downloadAssistantAttachment, synthesizeAssistantSpeech, transcribeAssistantVoice, useAssistantChat, useConfirmAssistantAction, useRejectAssistantAction } from '../api/enterprise'
import { AiGeneratingAnimation } from './AiGeneratingAnimation'
import { BorderBeam } from './BorderBeam'

const GREETING = 'Сайн байна уу. Би өгөгдлийн сангаас хариулж, таны ажил болон даалгаврыг ойлгож тусална. Үйлдэл хийхийн өмнө заавал баталгаажуулна.'
const SUGGESTIONS = ['Миний өнөөдрийн даалгаврууд юу вэ?', 'Энэ долоо хоногт хэдэн цаг ажилласан бэ?', 'Маргааш 10 цагт сануулга үүсгэ']

type Message = { role: 'user' | 'assistant'; text: string; audioUrl?: string; action?: { type: string; payload: Record<string, any> }; sources?: { id: string | number; title: string; locator?: Record<string, any> }[]; attachments?: AssistantFileAttachment[] }

export function OyunsAssistant({ open, onClose }: { open: boolean; onClose: () => void }) {
  const assistant = useAssistantChat()
  const confirmAction = useConfirmAssistantAction()
  const rejectAction = useRejectAssistantAction()
  const recorder = useRef<MediaRecorder>()
  const stream = useRef<MediaStream>()
  const discardRecording = useRef(false)
  const textarea = useRef<HTMLTextAreaElement | null>(null)
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<number>()
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [downloadingAttachment, setDownloadingAttachment] = useState<number>()
  const [resolvedActions, setResolvedActions] = useState<Record<number, 'confirmed' | 'rejected'>>({})
  const [history, setHistory] = useState<Message[]>([{ role: 'assistant', text: GREETING }])
  const transcriptEnd = useRef<HTMLDivElement | null>(null)
  const busy = assistant.isPending || isTranscribing

  useEffect(() => {
    if (open) transcriptEnd.current?.scrollIntoView?.({ block: 'end' })
  }, [open, history, busy])
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])
  if (!open) return null

  const startNewChat = () => {
    setConversationId(undefined)
    setResolvedActions({})
    setHistory([{ role: 'assistant', text: GREETING }])
    resizeTextarea('')
    requestAnimationFrame(() => textarea.current?.focus())
  }

  const addAnswer = async (result: any) => {
    setConversationId(result.conversation_id)
    const message = result.message
    const answer: Message = { role: 'assistant', text: message.content, action: message.action, sources: message.sources, attachments: message.attachments }
    setHistory((items) => [...items, answer])
    try {
      const audioUrl = await synthesizeAssistantSpeech(message.content)
      if (audioUrl) setHistory((items) => items.map((item) => item === answer ? { ...item, audioUrl } : item))
    } catch {
      // The text answer is already available when Chimege is unavailable.
    }
  }

  const sendQuestion = async (text: string, voiceMode = false) => {
    setHistory((items) => [...items, { role: 'user', text }])
    try {
      await addAnswer(await assistant.mutateAsync({ text, conversation_id: conversationId, voice_mode: voiceMode }))
    } catch {
      setHistory((items) => [...items, { role: 'assistant', text: 'Одоогоор OYUNS хариулж чадсангүй. Түр хүлээгээд дахин оролдоно уу.' }])
    }
  }

  const submit = async (event?: React.FormEvent) => {
    event?.preventDefault()
    const text = input.trim()
    if (!text || isRecording || isTranscribing) return
    resizeTextarea('')
    await sendQuestion(text)
  }

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    void submit()
  }

  const resizeTextarea = (value: string) => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    const maxHeight = 144
    element.style.height = `${Math.min(Math.max(element.scrollHeight, 36), maxHeight)}px`
    element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden'
    setInput(value)
  }

  const stopTracks = () => {
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = undefined
  }

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setHistory((items) => [...items, { role: 'assistant', text: 'Энэ хөтөч микрофоноор асуух боломжийг дэмжихгүй байна.' }])
      return
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.current = media
      const chunks: BlobPart[] = []
      const activeRecorder = new MediaRecorder(media)
      recorder.current = activeRecorder
      activeRecorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      activeRecorder.onstop = async () => {
        stopTracks(); setIsRecording(false)
        if (discardRecording.current) { discardRecording.current = false; return }
        const recording = new Blob(chunks, { type: activeRecorder.mimeType || 'audio/webm' })
        if (!recording.size) return
        setIsTranscribing(true)
        try {
          const { transcript } = await transcribeAssistantVoice(recording)
          if (!transcript?.trim()) throw new Error('empty transcript')
          await sendQuestion(transcript.trim(), true)
        } catch {
          setHistory((items) => [...items, { role: 'assistant', text: 'Дуу хоолойг таньж чадсангүй. Дахин бичих эсвэл текстээр оруулна уу.' }])
        } finally { setIsTranscribing(false) }
      }
      activeRecorder.start()
      setIsRecording(true)
    } catch {
      stopTracks()
      setHistory((items) => [...items, { role: 'assistant', text: 'Микрофоны зөвшөөрөл хэрэгтэй байна. Хөтчийн тохиргооноос зөвшөөрөөд дахин оролдоно уу.' }])
    }
  }

  const stopRecording = (discard = false) => {
    discardRecording.current = discard
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }

  const confirmTaskAction = async (payload: Record<string, any>, index: number) => {
    try {
      const result = await confirmAction.mutateAsync(payload.action_reference || payload.token)
      if (result?.status !== 'ok') throw new Error(result?.data?.reason || 'Action unavailable')
      const created = result?.data?.created
      const updated = result?.data?.updated
      const title = created?.title || ''
      const message = created
        ? `Даалгаврыг ERP-д үүсгэлээ${title ? `: “${title}”` : ''}.`
        : updated
          ? 'Даалгаврын өөрчлөлтийг хэрэгжүүллээ.'
          : 'Үйлдэл амжилттай хэрэгжлээ.'
      setHistory((items) => [...items, { role: 'assistant', text: message }])
      setResolvedActions((items) => ({ ...items, [index]: 'confirmed' }))
    } catch (error: any) {
      setHistory((items) => [...items, { role: 'assistant', text: error?.message || 'Үйлдлийг хэрэгжүүлж чадсангүй.' }])
    }
  }

  const rejectTaskAction = async (payload: Record<string, any>, index: number) => {
    try {
      const result = await rejectAction.mutateAsync(payload.action_reference || payload.token)
      if (result?.status !== 'ok') throw new Error(result?.data?.reason || 'Ноорог цуцлах боломжгүй байна')
      setResolvedActions((items) => ({ ...items, [index]: 'rejected' }))
      setHistory((items) => [...items, { role: 'assistant', text: 'Даалгаврын ноорог цуцлагдлаа.' }])
    } catch (error: any) {
      setHistory((items) => [...items, { role: 'assistant', text: error?.message || 'Ноорог цуцлагдсангүй.' }])
    }
  }

  const editTaskAction = (payload: Record<string, any>) => {
    const title = payload.title || ''
    resizeTextarea(`Нооргийг засах${title ? `: “${title}”` : ''}. `)
    requestAnimationFrame(() => textarea.current?.focus())
  }

  const downloadAttachment = async (attachment: AssistantFileAttachment) => {
    setDownloadingAttachment(attachment.item_id)
    try {
      await downloadAssistantAttachment(attachment)
    } catch {
      setHistory((items) => [...items, { role: 'assistant', text: `“${attachment.filename}” файлыг татаж чадсангүй. Дахин оролдоно уу.` }])
    } finally {
      setDownloadingAttachment(undefined)
    }
  }

  const actionsPending = confirmAction.isPending || rejectAction.isPending

  return <div className="assistant-backdrop" onMouseDown={onClose}>
    <BorderBeam className="assistant-panel-beam" colorVariant="ocean" radius={18} size="md" strength={0.58} theme="light">
      <aside className="assistant-panel" role="dialog" aria-modal="true" aria-label="OYUNS AI агент" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <span className="assistant-avatar" aria-hidden><Sparkles size={18} /></span>
          <div className="assistant-title"><strong>OYUNS AI</strong><small>Компаний туслах</small></div>
          <div className="assistant-header-actions">
            <button type="button" onClick={startNewChat} disabled={history.length === 1 || busy} aria-label="Шинэ яриа" title="Шинэ яриа"><SquarePen size={17} /></button>
            <button type="button" onClick={onClose} aria-label="Хаах" title="Хаах"><X size={18} /></button>
          </div>
        </header>
        <div className="assistant-messages" aria-live="polite">
          {history.map((message, index) => <div key={index} className={`assistant-message ${message.role}`}>
            {message.role === 'assistant' && <span className="assistant-avatar" aria-hidden><Sparkles size={14} /></span>}
            <div className="assistant-message-body">
              <div className="assistant-bubble"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown></div>
              {message.audioUrl ? <audio className="assistant-audio" controls autoPlay src={message.audioUrl}><track kind="captions" /></audio> : null}
              {message.attachments?.length ? <div className="assistant-attachments" aria-label="Хавсаргасан файлууд">{message.attachments.map((attachment) => <button key={attachment.item_id} type="button" className="assistant-attachment" onClick={() => downloadAttachment(attachment)} disabled={downloadingAttachment === attachment.item_id}><Download size={15} />{downloadingAttachment === attachment.item_id ? 'Татаж байна…' : attachment.filename}</button>)}</div> : null}
              {message.sources?.length ? <div className="assistant-sources" aria-label="Эх сурвалж">{message.sources.map((source) => <span key={source.id} title={source.title}>{source.title}</span>)}</div> : null}
              {message.action?.type === 'task_action_preview' && <section className="assistant-draft">
                {resolvedActions[index]
                  ? <strong className={`assistant-draft-status ${resolvedActions[index]}`}>{resolvedActions[index] === 'confirmed' ? <><CircleCheck size={15} />Даалгавар үүслээ</> : <><CircleX size={15} />Ноорог цуцлагдлаа</>}</strong>
                  : <>
                    <span>Баталгаажуулах ноорог</span>
                    <strong>{message.action.payload.title || message.action.payload.task_id || 'Даалгавар'}</strong>
                    <p>{message.action.payload.action_type === 'update_task' ? 'Даалгаврын өөрчлөлт' : message.action.payload.action_type === 'delegate_task' ? 'Өөр ажилтанд оноох шинэ даалгавар' : 'Шинэ даалгавар'}</p>
                    <div className="assistant-draft-actions">
                      <button type="button" onClick={() => void confirmTaskAction(message.action!.payload, index)} disabled={actionsPending}><Check size={14} />{message.action.payload.action_type === 'update_task' ? 'Өөрчлөлт хэрэгжүүлэх' : 'ERP-д үүсгэх'}</button>
                      <button type="button" className="edit" onClick={() => editTaskAction(message.action!.payload)} disabled={actionsPending}><Pencil size={14} />Засах</button>
                      <button type="button" className="reject" onClick={() => void rejectTaskAction(message.action!.payload, index)} disabled={actionsPending}><X size={14} />Татгалзах</button>
                    </div>
                  </>}
              </section>}
            </div>
          </div>)}
          {history.length === 1 && !busy && <div className="assistant-suggestions" aria-label="Санал болгох асуултууд">{SUGGESTIONS.map((suggestion) => <button type="button" key={suggestion} onClick={() => void sendQuestion(suggestion)}>{suggestion}</button>)}</div>}
          {assistant.isPending && <AiGeneratingAnimation className="assistant-generating" />}
          <div ref={transcriptEnd} aria-hidden />
        </div>
        <div className="assistant-footer">
          {isRecording ? <div className="assistant-recording"><span />Сонсож байна… <button type="button" onClick={() => stopRecording(true)}>Болих</button></div> : null}
          {isTranscribing ? <div className="assistant-recording"><LoaderCircle className="spin" size={15} />Дуу хоолойг таньж байна…</div> : null}
          <form onSubmit={submit}>
            <textarea ref={textarea} rows={1} value={input} onChange={(event) => resizeTextarea(event.target.value)} onKeyDown={onInputKeyDown} placeholder="Асуултаа бичнэ үү…" aria-label="OYUNS AI-аас асуух" autoFocus />
            <button type="button" className={`assistant-record ${isRecording ? 'recording' : ''}`} onClick={() => isRecording ? stopRecording() : startRecording()} disabled={assistant.isPending || isTranscribing} aria-label={isRecording ? 'Бичлэг дуусгах' : 'Дуугаар асуух'}>{isTranscribing ? <LoaderCircle className="spin" size={17} /> : isRecording ? <Square size={15} /> : <Mic size={18} />}</button>
            <button disabled={assistant.isPending || isRecording || isTranscribing || !input.trim()} aria-label="Илгээх"><Send size={17} /></button>
          </form>
          <small className="assistant-hint">Enter — илгээх · Shift + Enter — шинэ мөр</small>
        </div>
      </aside>
    </BorderBeam>
  </div>
}
