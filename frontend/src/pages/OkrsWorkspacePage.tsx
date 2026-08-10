import { useState } from 'react'
import { Goal, Plus, Target, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useObjectives } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'

export function OkrsWorkspacePage() {
  const objectives = useObjectives()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('quarter')
  const [period, setPeriod] = useState(() => periodFromPreset('quarter'))
  const year = new Date().getFullYear()
  const [form, setForm] = useState({ title: '', description: '', level: 'company', period_start: `${year}-01-01`, period_end: `${year}-12-31` })
  const create = useMutation({ mutationFn: () => api.post('/v1/objectives', form), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'objectives'] }); setOpen(false) } })
  const visibleObjectives = objectives.data?.filter((objective) => objective.period_end >= period.date_from && objective.period_start <= period.date_to) ?? []
  return <div><div className="view-toolbar"><div><h2>Стратегийн зорилгууд</h2><p>Компаний ажлыг хэмжигдэхүйц үр дүнтэй холбоно.</p></div><div className="toolbar-cluster"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) }} /><button className="primary-action compact" onClick={() => setOpen(true)}><Plus size={16} />Зорилго</button></div></div><div className="okr-list">{visibleObjectives.map((objective) => <article className="okr-card panel" key={objective.id}><div className="okr-icon"><Goal /></div><div className="okr-body"><div><span className="eyebrow">{objective.level} · {objective.period_start} — {objective.period_end}</span><h3>{objective.title}</h3><p>{objective.description || 'Тайлбар оруулаагүй байна.'}</p></div><div className="okr-progress"><div><span>Нийт ахиц</span><strong>{objective.status === 'completed' ? 100 : 0}%</strong></div><div className="progress-track purple"><span style={{ width: objective.status === 'completed' ? '100%' : '0%' }} /></div></div></div><span className={`status-pill ${objective.status}`}>{objective.status}</span></article>)}{!visibleObjectives.length && <div className="empty-state"><Target /><h3>Энэ хугацаанд зорилго алга</h3><p>Хугацааны шүүлтүүрээ өөрчлөх эсвэл хэмжигдэхүйц зорилго нэмнэ үү.</p></div>}</div><AnimatePresence>{open && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setOpen(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Strategic objective</span><h2>Шинэ зорилго</h2></div><button onClick={() => setOpen(false)}><X /></button></div><form className="sheet-form" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><label>Зорилгын нэр<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>Тайлбар<textarea rows={5} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><div className="form-row"><label>Эхлэх<input type="date" value={form.period_start} onChange={(event) => setForm({ ...form, period_start: event.target.value })} /></label><label>Дуусах<input type="date" value={form.period_end} onChange={(event) => setForm({ ...form, period_end: event.target.value })} /></label></div><button className="primary-action">Зорилго үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence></div>
}
