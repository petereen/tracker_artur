import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, BriefcaseBusiness, CalendarDays, CircleDollarSign, Plus, X } from 'lucide-react'
import { useCreateProject, useProjects } from '../api/enterprise'

const EMPTY = { code: '', name: '', description: '', status: 'active', budget_minutes: '', budget_amount: '', currency: 'MNT', default_billable: false }

export function ProjectsWorkspacePage() {
  const projects = useProjects()
  const createProject = useCreateProject()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    await createProject.mutateAsync({ ...form, budget_minutes: form.budget_minutes ? Number(form.budget_minutes) : null, budget_amount: form.budget_amount ? Number(form.budget_amount) : null })
    setOpen(false); setForm(EMPTY)
  }
  return (
    <div>
      <div className="view-toolbar"><div><h2>Төслийн портфолио</h2><p>Төсөв, хугацаа, баг болон гүйцэтгэлийг нэг дор.</p></div><button className="primary-action compact" onClick={() => setOpen(true)}><Plus size={16} />Шинэ төсөл</button></div>
      <div className="project-grid">
        {(projects.data ?? []).map((project) => (
          <article className="project-card" key={project.id}>
            <div className="project-card-top"><span className="project-code">{project.code}</span><span className={`status-pill ${project.status}`}>{project.status}</span></div>
            <h3>{project.name}</h3><p>{project.description || 'Төслийн тайлбар оруулаагүй байна.'}</p>
            <div className="project-stat"><CalendarDays size={16} /><span>Хугацаа</span><strong>{project.ends_on || 'Тодорхойгүй'}</strong></div>
            <div className="project-stat"><CircleDollarSign size={16} /><span>Төсөв</span><strong>{project.budget_amount ? `${project.budget_amount.toLocaleString()} ${project.currency}` : '—'}</strong></div>
            <div className="project-progress"><span style={{ width: `${Math.min(100, project.status === 'completed' ? 100 : project.status === 'active' ? 48 : 12)}%` }} /></div>
            <a href={`/tasks?project=${project.id}`}>Даалгавар харах <ArrowUpRight size={15} /></a>
          </article>
        ))}
        {!projects.isLoading && !projects.data?.length && <div className="empty-state"><BriefcaseBusiness /><h3>Эхний төслөө үүсгэнэ үү</h3><p>Даалгавар, цаг, төсөв, багийн ачааллыг төслөөр нэгтгэнэ.</p><button className="primary-action compact" onClick={() => setOpen(true)}><Plus size={16} />Төсөл үүсгэх</button></div>}
      </div>
      <AnimatePresence>{open && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setOpen(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">New project</span><h2>Шинэ төсөл</h2></div><button onClick={() => setOpen(false)}><X /></button></div><form className="sheet-form" onSubmit={submit}><label>Код<input value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value.toUpperCase() })} required /></label><label>Нэр<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Тайлбар<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={4} /></label><div className="form-row"><label>Цагийн төсөв<input type="number" min="0" value={form.budget_minutes} onChange={(event) => setForm({ ...form, budget_minutes: event.target.value })} /></label><label>Мөнгөн төсөв<input type="number" min="0" value={form.budget_amount} onChange={(event) => setForm({ ...form, budget_amount: event.target.value })} /></label></div><label className="checkbox-label"><input type="checkbox" checked={form.default_billable} onChange={(event) => setForm({ ...form, default_billable: event.target.checked })} />Төслийн цагийг анхдагчаар billable болгох</label><button className="primary-action" disabled={createProject.isPending}>Төсөл үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence>
    </div>
  )
}
