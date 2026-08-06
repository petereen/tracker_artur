import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, BriefcaseBusiness, CalendarDays, Plus, Users2, X } from 'lucide-react'
import { useCreateProject, useProjects, useWorkerDirectory } from '../api/enterprise'

const EMPTY = { code: '', name: '', description: '', status: 'active', manager_id: '', member_ids: [] as number[], starts_on: '', ends_on: '', budget_minutes: '', budget_amount: '', currency: 'MNT' }

export function ProjectsWorkspacePage() {
  const projects = useProjects()
  const workers = useWorkerDirectory()
  const createProject = useCreateProject()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      await createProject.mutateAsync({ ...form, manager_id: form.manager_id ? Number(form.manager_id) : null, member_ids: form.member_ids, starts_on: form.starts_on || null, ends_on: form.ends_on || null, budget_minutes: form.budget_minutes ? Number(form.budget_minutes) : null, budget_amount: form.budget_amount ? Number(form.budget_amount) : null })
      setForm(EMPTY); setOpen(false)
    } catch { /* mutation hook shows the server error */ }
  }
  const toggleMember = (id: number) => setForm({ ...form, member_ids: form.member_ids.includes(id) ? form.member_ids.filter((value) => value !== id) : [...form.member_ids, id] })
  return <div className="projects-workspace">
    <div className="view-toolbar"><div><h2>Төслийн портфолио</h2><p>Хариуцагч, баг, хугацаа болон төсвийг нэг дор удирдана.</p></div><button className="primary-action" onClick={() => setOpen(true)}><Plus size={17} />Шинэ төсөл</button></div>
    <div className="project-grid">{projects.data?.map((project) => <article className="project-card panel" key={project.id}><div className="project-card-top"><div className="project-icon"><BriefcaseBusiness /></div><span className={`status-pill ${project.status}`}>{project.status}</span></div><span className="eyebrow">{project.code}</span><h3>{project.name}</h3><p>{project.description || 'Тайлбаргүй'}</p><div className="project-stats"><div className="project-stat"><CalendarDays size={16} /><span>Хугацаа</span><strong>{project.ends_on || 'Тодорхойгүй'}</strong></div><div className="project-stat"><Users2 size={16} /><span>Хариуцагч</span><strong>{project.manager_name || 'Томилоогүй'}</strong></div></div><footer><span>{project.member_ids?.length || 0} гишүүн</span><a href={`/tasks?project=${project.id}`}>Нээх <ArrowUpRight size={14} /></a></footer></article>)}</div>
    <AnimatePresence>{open && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setOpen(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">New project</span><h2>Шинэ төсөл</h2></div><button onClick={() => setOpen(false)}><X /></button></div><form className="sheet-form" onSubmit={submit}><label>Код<input value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value.toUpperCase() })} required /></label><label>Нэр<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><label>Тайлбар<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} /></label><label>Хариуцагч<select value={form.manager_id} onChange={(event) => setForm({ ...form, manager_id: event.target.value })}><option value="">Томилоогүй</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label><fieldset className="member-picker"><legend>Төслийн гишүүд</legend>{workers.data?.map((worker) => <label key={worker.id}><input type="checkbox" checked={form.member_ids.includes(worker.id)} onChange={() => toggleMember(worker.id)} />{worker.name}</label>)}</fieldset><div className="form-row"><label>Эхлэх огноо<input type="date" value={form.starts_on} onChange={(event) => setForm({ ...form, starts_on: event.target.value })} /></label><label>Дуусах огноо<input type="date" value={form.ends_on} onChange={(event) => setForm({ ...form, ends_on: event.target.value })} /></label></div><div className="form-row"><label>Цагийн төсөв<input type="number" min="0" value={form.budget_minutes} onChange={(event) => setForm({ ...form, budget_minutes: event.target.value })} /></label><label>Мөнгөн төсөв<input type="number" min="0" value={form.budget_amount} onChange={(event) => setForm({ ...form, budget_amount: event.target.value })} /></label></div><button className="primary-action" disabled={createProject.isPending}>Төсөл үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence>
  </div>
}
