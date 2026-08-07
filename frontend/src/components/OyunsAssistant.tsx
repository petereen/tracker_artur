import { useState } from 'react'
import { Bot, Check, Send, Sparkles, X } from 'lucide-react'
import { useAssistantChat, useCreateEnterpriseTask } from '../api/enterprise'

type Message = { role: 'user' | 'assistant'; text: string; action?: { type: string; payload: Record<string, any> }; sources?: { id: number; title: string }[] }

export function OyunsAssistant({ open, onClose }: { open: boolean; onClose: () => void }) {
  const assistant = useAssistantChat()
  const createTask = useCreateEnterpriseTask()
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<number>()
  const [history, setHistory] = useState<Message[]>([{ role: 'assistant', text: 'Сайн байна уу. Би компаний мэдлэгээс хариулж, таны ажил болон даалгаврыг ойлгож тусална. Үйлдэл хийхийн өмнө заавал баталгаажуулна.' }])
  if (!open) return null

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = input.trim()
    if (!text) return
    setHistory((items) => [...items, { role: 'user', text }]); setInput('')
    try {
      const result = await assistant.mutateAsync({ text, conversation_id: conversationId })
      setConversationId(result.conversation_id)
      const message = result.message
      setHistory((items) => [...items, { role: 'assistant', text: message.content, action: message.action, sources: message.sources }])
    } catch {
      setHistory((items) => [...items, { role: 'assistant', text: 'Одоогоор OYUNS хариулж чадсангүй. Түр хүлээгээд дахин оролдоно уу.' }])
    }
  }
  const confirmTask = async (payload: Record<string, any>) => {
    await createTask.mutateAsync({ title: payload.title, description: payload.description ?? null, deadline_at: payload.deadline_at ?? null, priority: payload.priority ?? 2, workflow_status: 'to_do' })
    setHistory((items) => [...items, { role: 'assistant', text: 'Даалгаврыг ERP-д үүсгэлээ.' }])
  }

  return <div className="assistant-backdrop" onMouseDown={onClose}><aside className="assistant-panel" role="dialog" aria-modal="true" aria-label="OYUNS AI туслах" onMouseDown={(event) => event.stopPropagation()}><header><div><span><Sparkles size={15} /> OYUNS AI</span><strong>Компанийн туслах</strong></div><button onClick={onClose} aria-label="Хаах"><X /></button></header><div className="assistant-messages" aria-live="polite">{history.map((message, index) => <div key={index} className={`assistant-message ${message.role}`}><span>{message.role === 'assistant' ? <Bot size={15} /> : 'Та'}</span><p>{message.text}</p>{message.sources?.length ? <small>{message.sources.map((source) => source.title).join(' · ')}</small> : null}{message.action?.type === 'task_draft' && <section className="assistant-draft"><span>Баталгаажуулах ноорог</span><strong>{message.action.payload.title}</strong><button onClick={() => confirmTask(message.action!.payload)} disabled={createTask.isPending}><Check size={15} />ERP-д үүсгэх</button></section>}</div>)}</div><form onSubmit={submit}><textarea rows={2} value={input} onChange={(event) => setInput(event.target.value)} placeholder="Компанийн журам, миний ажил, эсвэл даалгаврын талаар асуу…" autoFocus /><button disabled={assistant.isPending || !input.trim()} aria-label="Илгээх"><Send size={17} /></button></form><small>OYUNS компанийн мэдлэг болон таны эрхтэй мэдээллийг ашиглана.</small></aside></div>
}
