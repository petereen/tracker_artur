import { useRef, useState } from 'react'
import { Bot, Check, LoaderCircle, Mic, Send, Sparkles, Square, Volume2, X } from 'lucide-react'
import { synthesizeAssistantSpeech, transcribeAssistantVoice, useAssistantChat, useCreateEnterpriseTask } from '../api/enterprise'

type Message = { role: 'user' | 'assistant'; text: string; audioUrl?: string; action?: { type: string; payload: Record<string, any> }; sources?: { id: number; title: string }[] }

export function OyunsAssistant({ open, onClose }: { open: boolean; onClose: () => void }) {
  const assistant = useAssistantChat()
  const createTask = useCreateEnterpriseTask()
  const recorder = useRef<MediaRecorder>()
  const stream = useRef<MediaStream>()
  const discardRecording = useRef(false)
  const textarea = useRef<HTMLTextAreaElement | null>(null)
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<number>()
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [history, setHistory] = useState<Message[]>([{ role: 'assistant', text: 'Сайн байна уу. Би өгөгдлийн сангаас хариулж, таны ажил болон даалгаврыг ойлгож тусална. Үйлдэл хийхийн өмнө заавал баталгаажуулна.' }])
  if (!open) return null

  const addAnswer = async (result: any) => {
    setConversationId(result.conversation_id)
    const message = result.message
    const answer: Message = { role: 'assistant', text: message.content, action: message.action, sources: message.sources }
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

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = input.trim()
    if (!text || isRecording || isTranscribing) return
    resizeTextarea('')
    await sendQuestion(text)
  }

  const resizeTextarea = (value: string) => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    const maxHeight = 144
    element.style.height = `${Math.min(Math.max(element.scrollHeight, 38), maxHeight)}px`
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

  const confirmTask = async (payload: Record<string, any>) => {
    await createTask.mutateAsync({ title: payload.title, description: payload.description ?? null, deadline_at: payload.deadline_at ?? null, priority: payload.priority ?? 2, workflow_status: 'to_do' })
    setHistory((items) => [...items, { role: 'assistant', text: 'Даалгаврыг ERP-д үүсгэлээ.' }])
  }

  return <div className="assistant-backdrop" onMouseDown={onClose}><aside className="assistant-panel" role="dialog" aria-modal="true" aria-label="OYUNS AI агент" onMouseDown={(event) => event.stopPropagation()}><header><div><span><Sparkles size={15} /> OYUNS AI</span><strong>Компаний туслах</strong></div><button onClick={onClose} aria-label="Хаах"><X /></button></header><div className="assistant-messages" aria-live="polite">{history.map((message, index) => <div key={index} className={`assistant-message ${message.role}`}><span>{message.role === 'assistant' ? <Bot size={15} /> : 'Та'}</span><p>{message.text}</p>{message.audioUrl ? <audio className="assistant-audio" controls autoPlay src={message.audioUrl}><track kind="captions" /></audio> : null}{message.sources?.length ? <small>{message.sources.map((source) => source.title).join(' · ')}</small> : null}{message.action?.type === 'task_draft' && <section className="assistant-draft"><span>Баталгаажуулах ноорог</span><strong>{message.action.payload.title}</strong><button onClick={() => confirmTask(message.action!.payload)} disabled={createTask.isPending}><Check size={15} />ERP-д үүсгэх</button></section>}</div>)}</div><form onSubmit={submit}><textarea ref={textarea} rows={1} value={input} onChange={(event) => resizeTextarea(event.target.value)} placeholder="Компаний журам, миний ажил, эсвэл даалгаврын талаар асуу…" autoFocus /><button type="button" className={`assistant-record ${isRecording ? 'recording' : ''}`} onClick={() => isRecording ? stopRecording() : startRecording()} disabled={assistant.isPending || isTranscribing} aria-label={isRecording ? 'Бичлэг дуусгах' : 'Дуугаар асуух'}>{isTranscribing ? <LoaderCircle className="spin" size={17} /> : isRecording ? <Square size={15} /> : <Mic size={18} />}</button><button disabled={assistant.isPending || isRecording || isTranscribing || !input.trim()} aria-label="Илгээх"><Send size={17} /></button></form>{isRecording ? <div className="assistant-recording"><span />Сонсож байна… <button onClick={() => stopRecording(true)}>Болих</button></div> : null}{isTranscribing ? <div className="assistant-recording"><LoaderCircle className="spin" size={15} />Дуу хоолойг таньж байна…</div> : null}</aside></div>
}
