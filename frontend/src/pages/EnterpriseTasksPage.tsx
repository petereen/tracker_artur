import { useMemo, useState } from 'react'
import { DndContext, DragEndEvent, KeyboardSensor, PointerSensor, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { AnimatePresence, motion } from 'motion/react'
import ReactMarkdown from 'react-markdown'
import { CalendarDays, CheckCircle2, Circle, Clock3, GripVertical, LayoutGrid, List, Plus, Rows3, Save, X } from 'lucide-react'
import { EnterpriseTask, useCreateEnterpriseTask, useEnterpriseTasks, useProjects, useUpdateEnterpriseTask, WorkflowStatus } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'

const COLUMNS: { key: WorkflowStatus; label: string; tone: string }[] = [
  { key: 'backlog', label: 'Backlog', tone: 'slate' }, { key: 'to_do', label: 'Хийх', tone: 'blue' },
  { key: 'in_progress', label: 'Хийгдэж буй', tone: 'amber' }, { key: 'review', label: 'Хяналт', tone: 'purple' },
  { key: 'done', label: 'Дууссан', tone: 'green' },
]

function SortableTask({ task, onOpen }: { task: EnterpriseTask; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: task.id, data: { status: task.workflow_status } })
  return <article ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={`kanban-card ${isDragging ? 'dragging' : ''}`} onClick={onOpen}><button className="drag-handle" {...attributes} {...listeners} onClick={(event) => event.stopPropagation()} aria-label={`${task.title} зөөх`}><GripVertical size={15} /></button><div className="task-priority" data-priority={task.priority} /><h3>{task.title}</h3>{task.description && <p>{task.description}</p>}<footer>{task.deadline_at ? <span className={task.is_overdue ? 'overdue' : ''}><CalendarDays size={13} />{new Date(task.deadline_at).toLocaleDateString('mn-MN')}</span> : <span><Clock3 size={13} />Хугацаагүй</span>}{task.estimate_minutes ? <strong>{Math.round(task.estimate_minutes / 60 * 10) / 10}ц</strong> : null}</footer></article>
}

function BoardColumn({ column, tasks, onOpen }: { column: typeof COLUMNS[number]; tasks: EnterpriseTask[]; onOpen: (task: EnterpriseTask) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: `column-${column.key}`, data: { status: column.key } })
  return <section className="kanban-column"><header><span className={`column-dot ${column.tone}`} />{column.label}<b>{tasks.length}</b></header><SortableContext items={tasks.map((task) => task.id)} strategy={verticalListSortingStrategy}><div ref={setNodeRef} className={`kanban-dropzone ${isOver ? 'over' : ''}`}>{tasks.map((task) => <SortableTask key={task.id} task={task} onOpen={() => onOpen(task)} />)}{!tasks.length && <div className="column-empty">Энд даалгавар зөөнө үү</div>}</div></SortableContext></section>
}

export function EnterpriseTasksPage() {
  const params = new URLSearchParams(location.search)
  const projectId = params.get('project') ? Number(params.get('project')) : undefined
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('month')
  const [period, setPeriod] = useState(() => periodFromPreset('month'))
  const tasks = useEnterpriseTasks(projectId, period)
  const projects = useProjects()
  const updateTask = useUpdateEnterpriseTask()
  const createTask = useCreateEnterpriseTask()
  const [view, setView] = useState<'board' | 'list' | 'timeline' | 'calendar'>('board')
  const [selected, setSelected] = useState<EnterpriseTask | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ title: '', description: '', project_id: projectId ? String(projectId) : '', workflow_status: 'to_do', start_at: '', deadline_at: '', estimate_minutes: '' })
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }))
  const grouped = useMemo(() => Object.fromEntries(COLUMNS.map((column) => [column.key, (tasks.data ?? []).filter((task) => task.workflow_status === column.key)])) as Record<WorkflowStatus, EnterpriseTask[]>, [tasks.data])
  const timeline = useMemo(() => {
    const from = new Date(`${period.date_from}T00:00:00`).getTime()
    const to = new Date(`${period.date_to}T23:59:59`).getTime()
    const span = Math.max(to - from, 1)
    return (tasks.data ?? []).map((task) => {
      const deadline = task.deadline_at ? new Date(task.deadline_at).getTime() : null
      const start = task.start_at ? new Date(task.start_at).getTime() : deadline ? deadline - (task.estimate_minutes ?? 60) * 60_000 : null
      const end = deadline ?? (start ? start + (task.estimate_minutes ?? 60) * 60_000 : null)
      return { task, start, left: start === null ? null : Math.max(0, Math.min(100, (start - from) * 100 / span)), width: start === null || end === null ? 0 : Math.max(1.5, Math.min(100, (end - start) * 100 / span)) }
    })
  }, [period, tasks.data])
  const calendarDays = useMemo(() => {
    const days: Date[] = []
    const cursor = new Date(`${period.date_from}T12:00:00`)
    const end = new Date(`${period.date_to}T12:00:00`)
    while (cursor <= end && days.length < 93) { days.push(new Date(cursor)); cursor.setDate(cursor.getDate() + 1) }
    return days
  }, [period])
  const dragEnd = ({ active, over }: DragEndEvent) => {
    if (!over) return
    const task = tasks.data?.find((item) => item.id === active.id)
    const overTask = tasks.data?.find((item) => item.id === over.id)
    const status = (over.data.current?.status || overTask?.workflow_status) as WorkflowStatus | undefined
    if (task && status && status !== task.workflow_status) updateTask.mutate({ id: task.id, version: task.version, workflow_status: status })
  }
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    await createTask.mutateAsync({ title: form.title, description: form.description || null, project_id: form.project_id ? Number(form.project_id) : null, workflow_status: form.workflow_status, start_at: form.start_at ? new Date(form.start_at).toISOString() : null, deadline_at: form.deadline_at ? new Date(form.deadline_at).toISOString() : null, estimate_minutes: form.estimate_minutes ? Number(form.estimate_minutes) : null })
    setCreating(false); setForm({ title: '', description: '', project_id: projectId ? String(projectId) : '', workflow_status: 'to_do', start_at: '', deadline_at: '', estimate_minutes: '' })
  }
  const saveSelected = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selected) return
    const data = new FormData(event.currentTarget)
    await updateTask.mutateAsync({ id: selected.id, version: selected.version, title: String(data.get('title')), description: String(data.get('description') || ''), start_at: data.get('start_at') ? new Date(String(data.get('start_at'))).toISOString() : null, deadline_at: data.get('deadline_at') ? new Date(String(data.get('deadline_at'))).toISOString() : null, estimate_minutes: data.get('estimate_minutes') ? Number(data.get('estimate_minutes')) : null })
    setSelected(null)
  }
  return <div className="task-workspace"><div className="view-toolbar"><div><h2>Ажлын урсгал</h2><p>{projectId ? projects.data?.find((project) => project.id === projectId)?.name : 'Таны харах эрхтэй даалгаврууд'}</p></div><div className="toolbar-cluster"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) }} /><div className="segmented-control" aria-label="Харагдац"><button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}><LayoutGrid size={15} />Самбар</button><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}><List size={15} />Жагсаалт</button><button className={view === 'timeline' ? 'active' : ''} onClick={() => setView('timeline')}><Rows3 size={15} />Timeline</button><button className={view === 'calendar' ? 'active' : ''} onClick={() => setView('calendar')}><CalendarDays size={15} />Календарь</button></div><button className="primary-action compact" onClick={() => setCreating(true)}><Plus size={16} />Даалгавар</button></div></div>
    {view === 'board' && <DndContext sensors={sensors} onDragEnd={dragEnd}><div className="kanban-board">{COLUMNS.map((column) => <BoardColumn key={column.key} column={column} tasks={grouped[column.key] || []} onOpen={setSelected} />)}</div></DndContext>}
    {view === 'list' && <div className="task-list panel">{(tasks.data ?? []).map((task) => <button key={task.id} onClick={() => setSelected(task)}><span>{task.workflow_status === 'done' ? <CheckCircle2 /> : <Circle />}</span><strong>{task.title}</strong><small>{COLUMNS.find((column) => column.key === task.workflow_status)?.label}</small><time>{task.deadline_at ? new Date(task.deadline_at).toLocaleDateString('mn-MN') : '—'}</time></button>)}</div>}
    {view === 'timeline' && <div className="timeline-view panel"><div className="timeline-axis"><span>{period.date_from}</span><span>25%</span><span>50%</span><span>{period.date_to}</span></div>{timeline.map(({ task, left, width }) => <button key={task.id} onClick={() => setSelected(task)}><strong>{task.title}</strong>{left === null ? <em>Хуваарьгүй</em> : <span className={task.is_overdue ? 'overdue' : ''} style={{ left: `calc(205px + (100% - 220px) * ${left / 100})`, width: `max(8px, calc((100% - 220px) * ${width / 100}))` }} />}</button>)}</div>}
    {view === 'calendar' && <div className="task-calendar panel">{calendarDays.map((day) => { const key = day.toISOString().slice(0, 10); const dayTasks = (tasks.data ?? []).filter((task) => task.deadline_at?.slice(0, 10) === key); return <section key={key} className={key === new Date().toISOString().slice(0, 10) ? 'today' : ''}><header><strong>{day.getDate()}</strong><span>{day.toLocaleDateString('mn-MN', { weekday: 'short' })}</span></header>{dayTasks.map((task) => <button key={task.id} onClick={() => setSelected(task)}>{task.title}</button>)}</section> })}</div>}
    <AnimatePresence>{(selected || creating) && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => { setSelected(null); setCreating(false) }}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}>{selected ? <><div className="sheet-header"><div><span className="eyebrow">Task #{selected.id}</span><h2>{selected.title}</h2></div><button onClick={() => setSelected(null)}><X /></button></div><div className="task-detail-meta"><span>{COLUMNS.find((column) => column.key === selected.workflow_status)?.label}</span><span>Priority {selected.priority}</span><span>v{selected.version}</span></div><form className="sheet-form" onSubmit={saveSelected}><label>Гарчиг<input name="title" defaultValue={selected.title} required /></label><label>Тайлбар (Markdown)<textarea name="description" rows={7} defaultValue={selected.description ?? ''} /></label><div className="form-row"><label>Эхлэх<input name="start_at" type="datetime-local" defaultValue={selected.start_at?.slice(0, 16) ?? ''} /></label><label>Дуусах<input name="deadline_at" type="datetime-local" defaultValue={selected.deadline_at?.slice(0, 16) ?? ''} /></label></div><label>Тооцоолсон минут<input name="estimate_minutes" type="number" min="0" defaultValue={selected.estimate_minutes ?? ''} /></label><button className="primary-action" disabled={updateTask.isPending}><Save size={16} />Хадгалах</button></form><div className="markdown-content"><ReactMarkdown>{selected.description || '_Тайлбар оруулаагүй байна._'}</ReactMarkdown></div></> : <><div className="sheet-header"><div><span className="eyebrow">Quick create</span><h2>Шинэ даалгавар</h2></div><button onClick={() => setCreating(false)}><X /></button></div><form className="sheet-form" onSubmit={submit}><label>Гарчиг<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} autoFocus required /></label><label>Тайлбар (Markdown)<textarea rows={6} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Төсөл<select value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}><option value="">Төсөлгүй</option>{projects.data?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><div className="form-row"><label>Эхлэх<input type="datetime-local" value={form.start_at} onChange={(event) => setForm({ ...form, start_at: event.target.value })} /></label><label>Дуусах<input type="datetime-local" value={form.deadline_at} onChange={(event) => setForm({ ...form, deadline_at: event.target.value })} /></label></div><label>Тооцоолсон минут<input type="number" min="0" value={form.estimate_minutes} onChange={(event) => setForm({ ...form, estimate_minutes: event.target.value })} /></label><button className="primary-action" disabled={createTask.isPending}>Үүсгэх</button></form></>}</motion.aside></motion.div>}</AnimatePresence></div>
}
