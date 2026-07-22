import { useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useTasks, useCreateTask, useUpdateTask, useEmployees, TaskOut } from '../api/hooks'

const STATUS_COLUMNS = [
  { key: 'open',        label: 'Нээлттэй',           color: '#388BFD' },
  { key: 'in_progress', label: 'Хийгдэж байгаа',      color: '#D29922' },
  { key: 'done',        label: 'Дууссан',             color: '#3FB950' },
  { key: 'overdue',     label: 'Хугацаа хэтэрсэн',    color: '#F85149' },
] as const

type StatusKey = typeof STATUS_COLUMNS[number]['key']

const PRIORITY_COLORS: Record<number, string> = { 1: '#F85149', 2: '#D29922', 3: '#3FB950' }
const PRIORITY_LABELS: Record<number, string> = { 1: '🔴 Өндөр', 2: '🟡 Дунд', 3: '🟢 Бага' }

const STATUS_OPTIONS = [
  { value: 'open',        label: 'Нээлттэй' },
  { value: 'in_progress', label: 'Хийгдэж байгаа' },
  { value: 'done',        label: 'Дууссан' },
  { value: 'overdue',     label: 'Хугацаа хэтэрсэн' },
  { value: 'cancelled',   label: 'Цуцлагдсан' },
]

function formatDeadline(dt: string | null): string {
  if (!dt) return '—'
  const d = new Date(dt)
  return d.toLocaleString('mn-MN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function isOverdue(task: TaskOut): boolean {
  if (!task.deadline_at) return false
  if (task.status === 'done' || task.status === 'cancelled') return false
  return new Date(task.deadline_at) < new Date()
}

function TaskCard({ task, onStatusChange }: { task: TaskOut; onStatusChange: (id: number, status: string) => void }) {
  const overdue = isOverdue(task)
  return (
    <div className="bg-surface2 border border-border rounded-xl p-3.5 mb-2 hover:border-accent transition-colors">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold leading-snug break-words">{task.title}</div>
        </div>
        <div className="w-2 h-2 rounded-full flex-shrink-0 mt-1" style={{ background: PRIORITY_COLORS[task.priority] }} title={PRIORITY_LABELS[task.priority]} />
      </div>

      {task.assignee_name && (
        <div className="text-xs text-muted mb-1.5 truncate">
          <span className="text-muted2">Гүйц:</span> {task.assignee_name}
        </div>
      )}

      {task.deadline_at && (
        <div className={`text-xs mb-2 ${overdue ? 'text-red font-semibold' : 'text-muted'}`}>
          {overdue ? '⚠ ' : ''}Хугацаа: {formatDeadline(task.deadline_at)}
        </div>
      )}

      <div className="mt-2">
        <select
          value={task.status}
          onChange={(e) => onStatusChange(task.id, e.target.value)}
          className="w-full bg-surface3 border border-border rounded-lg px-2 py-1 text-xs text-text outline-none focus:border-accent cursor-pointer"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
    </div>
  )
}

interface CreateForm {
  title: string
  description: string
  assignee_id: string
  deadline_at: string
  priority: string
}

const EMPTY_FORM: CreateForm = {
  title: '',
  description: '',
  assignee_id: '',
  deadline_at: '',
  priority: '2',
}

export function TasksPage() {
  const { data: employees = [] } = useEmployees()
  const [filterAssignee, setFilterAssignee] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM)

  const tasksQuery = useTasks()
  const createTask = useCreateTask()
  const updateTask = useUpdateTask()

  const allTasks: TaskOut[] = tasksQuery.data ?? []

  const filtered = filterAssignee
    ? allTasks.filter((t) => String(t.assignee_id) === filterAssignee)
    : allTasks

  const columnTasks = (status: string) => filtered.filter((t) => t.status === status)

  const handleStatusChange = (id: number, status: string) => {
    updateTask.mutate({ id, status })
  }

  const handleCreate = async () => {
    if (!form.title.trim()) return
    await createTask.mutateAsync({
      title: form.title.trim(),
      description: form.description || undefined,
      assignee_id: form.assignee_id ? Number(form.assignee_id) : undefined,
      deadline_at: form.deadline_at || undefined,
      priority: Number(form.priority) as 1 | 2 | 3,
    })
    setShowModal(false)
    setForm(EMPTY_FORM)
  }

  const employeeOptions = [
    { value: '', label: 'Бүх гүйцэтгэгч' },
    ...employees.map((e: any) => ({ value: String(e.id), label: e.name })),
  ]

  const assigneeFormOptions = [
    { value: '', label: 'Гүйцэтгэгчгүй' },
    ...employees.map((e: any) => ({ value: String(e.id), label: e.name })),
  ]

  const priorityOptions = [
    { value: '1', label: '🔴 Өндөр' },
    { value: '2', label: '🟡 Дунд' },
    { value: '3', label: '🟢 Бага' },
  ]

  return (
    <div>
      <PageHeader title="Даалгаврууд" sub="Канбан самбар">
        <Select
          value={filterAssignee}
          onChange={setFilterAssignee}
          options={employeeOptions}
        />
        <Btn variant="primary" onClick={() => setShowModal(true)}>+ Шинэ даалгавар</Btn>
      </PageHeader>

      {tasksQuery.isLoading && (
        <div className="text-muted text-sm py-8 text-center">Ачаалж байна...</div>
      )}

      {!tasksQuery.isLoading && (
        <div className="grid grid-cols-4 gap-4">
          {STATUS_COLUMNS.map((col) => {
            const tasks = columnTasks(col.key)
            return (
              <div key={col.key} className="flex flex-col">
                <div className="flex items-center gap-2 mb-3 px-1">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: col.color }} />
                  <span className="text-[13px] font-semibold">{col.label}</span>
                  <span className="ml-auto text-xs text-muted bg-surface3 px-1.5 py-0.5 rounded-full">{tasks.length}</span>
                </div>
                <div className="flex-1 bg-surface rounded-xl border border-border p-2.5 min-h-[120px]">
                  {tasks.length === 0 ? (
                    <div className="text-xs text-muted2 text-center py-4">Даалгавар алга</div>
                  ) : (
                    tasks.map((task) => (
                      <TaskCard key={task.id} task={task} onStatusChange={handleStatusChange} />
                    ))
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showModal && (
        <Modal title="Шинэ даалгавар" onClose={() => { setShowModal(false); setForm(EMPTY_FORM) }}>
          <div className="flex flex-col gap-3.5">
            <Input
              label="Гарчиг *"
              value={form.title}
              onChange={(v) => setForm((f) => ({ ...f, title: v }))}
              placeholder="Даалгаврын гарчиг"
              fullWidth
            />
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted font-medium">Тайлбар</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="Нэмэлт дэлгэрэнгүй..."
                rows={3}
                className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors resize-none text-[13px]"
              />
            </div>
            <Select
              label="Гүйцэтгэгч"
              value={form.assignee_id}
              onChange={(v) => setForm((f) => ({ ...f, assignee_id: v }))}
              options={assigneeFormOptions}
              fullWidth
            />
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted font-medium">Хугацаа</label>
              <input
                type="datetime-local"
                value={form.deadline_at}
                onChange={(e) => setForm((f) => ({ ...f, deadline_at: e.target.value }))}
                className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors"
              />
            </div>
            <Select
              label="Тэргүүлэх зэрэг"
              value={form.priority}
              onChange={(v) => setForm((f) => ({ ...f, priority: v }))}
              options={priorityOptions}
              fullWidth
            />
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={() => { setShowModal(false); setForm(EMPTY_FORM) }}>Цуцлах</Btn>
              <Btn
                variant="primary"
                onClick={handleCreate}
                disabled={!form.title.trim() || createTask.isPending}
              >
                Үүсгэх
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
