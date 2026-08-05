import { useState } from 'react'
import { Bot, Check, Send, Sparkles, X } from 'lucide-react'
import { useAssistantDraft, useCreateEnterpriseTask } from '../api/enterprise'

interface Draft { kind: 'task' | 'report'; title: string; description?: string; markdown?: string }

export function OyunsAssistant({ open, onClose }: { open: boolean; onClose: () => void }) {
  const assistant = useAssistantDraft()
  const createTask = useCreateEnterpriseTask()
  const [input, setInput] = useState('')
  const [kind, setKind] = useState<'task' | 'report'>('task')
  const [draft, setDraft] = useState<Draft>()
  const [history, setHistory] = useState<{ role: 'user' | 'assistant'; text: string }[]>([
    { role: 'assistant', text: 'Сайн байна уу. Би даалгавар эсвэл тайлангийн ноорог бэлдэж, таны зөвшөөрлөөр ERP-д үйлдэл хийж чадна.' },
  ])
  if (!open) return null

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = input.trim()
    if (!text) return
    setHistory((items) => [...items, { role: 'user', text }])
    setInput('')
    try {
      const result = await assistant.mutateAsync({ text, kind })
      setDraft({ kind, ...result.draft })
      setHistory((items) => [...items, { role: 'assistant', text: kind === 'task' ? `“${result.draft.title}” даалгаврын ноорог бэлэн. Үүсгэхээс өмнө шалгана уу.` : 'Тайлангийн ноорог бэлэн. Доорх агуулгыг тайландаа ашиглаж болно.' }])
    } catch {
      setHistory((items) => [...items, { role: 'assistant', text: 'Одоогоор ноорог үүсгэж чадсангүй. Та үндсэн хэсгүүдээс үйлдлээ үргэлжлүүлж болно.' }])
    }
  }

  const confirmTask = async () => {
    if (!draft || draft.kind !== 'task') return
    await createTask.mutateAsync({ title: draft.title, description: draft.description ?? null, workflow_status: 'to_do' })
    setHistory((items) => [...items, { role: 'assistant', text: 'Даалгаврыг таны нэр дээр үүсгэлээ.' }])
    setDraft(undefined)
  }

  return <div className="assistant-backdrop" onMouseDown={onClose}><aside className="assistant-panel" role="dialog" aria-modal="true" aria-label="OYUNS AI туслах" onMouseDown={(event) => event.stopPropagation()}><header><div><span><Sparkles size={15} /> OYUNS AI</span><strong>ERP туслах</strong></div><button onClick={onClose} aria-label="Хаах"><X /></button></header><div className="assistant-mode"><button className={kind === 'task' ? 'active' : ''} onClick={() => setKind('task')}>Даалгавар</button><button className={kind === 'report' ? 'active' : ''} onClick={() => setKind('report')}>Тайлан</button></div><div className="assistant-messages" aria-live="polite">{history.map((message, index) => <div key={index} className={`assistant-message ${message.role}`}><span>{message.role === 'assistant' ? <Bot size={15} /> : 'Та'}</span><p>{message.text}</p></div>)}{draft && <section className="assistant-draft"><span>Баталгаажуулах ноорог</span><strong>{draft.title}</strong><p>{draft.description ?? draft.markdown}</p>{draft.kind === 'task' && <button onClick={confirmTask} disabled={createTask.isPending}><Check size={15} />ERP-д үүсгэх</button>}</section>}</div><form onSubmit={submit}><textarea rows={2} value={input} onChange={(event) => setInput(event.target.value)} placeholder={kind === 'task' ? 'Жишээ: Баасан гарагт тайлан шалгах даалгавар үүсгэ' : 'Энэ долоо хоногийн ажлын тайлангийн ноорог…'} autoFocus /><button disabled={assistant.isPending || !input.trim()} aria-label="Илгээх"><Send size={17} /></button></form><small>Өөрчлөлт хийхийн өмнө OYUNS үргэлж баталгаажуулна.</small></aside></div>
}
