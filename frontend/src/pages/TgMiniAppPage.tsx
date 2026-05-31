import { useEffect, useState } from 'react'
import { useMiniMe, useMiniTasks, useMiniCreateTask, useMiniUpdateTask, MiniTaskOut, TaskScope } from '../api/miniapp'

const PRIORITY_DOT: Record<number, string> = { 1: 'bg-red-500', 2: 'bg-yellow-400', 3: 'bg-green-500' }
const PRIORITY_LABELS: Record<number, string> = { 1: '🔴 Высокий', 2: '🟡 Средний', 3: '🟢 Низкий' }

const STATUS_LABELS: Record<string, string> = {
  open: 'Открыто',
  in_progress: 'В работе',
  done: 'Выполнено',
  overdue: 'Просрочено',
  cancelled: 'Отменено',
}

const STATUS_BG: Record<string, string> = {
  open: 'bg-blue-900/40 border-blue-700',
  in_progress: 'bg-yellow-900/30 border-yellow-700',
  done: 'bg-green-900/30 border-green-700',
  overdue: 'bg-red-900/30 border-red-700',
  cancelled: 'bg-gray-800 border-gray-600',
}

function formatDeadline(dt: string | null): string {
  if (!dt) return ''
  const d = new Date(dt)
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function isOverdue(task: MiniTaskOut): boolean {
  if (!task.deadline_at) return false
  if (task.status === 'done' || task.status === 'cancelled') return false
  return new Date(task.deadline_at) < new Date()
}

function tgTheme() {
  try {
    const tg = (window as any).Telegram?.WebApp
    return tg?.colorScheme ?? 'dark'
  } catch { return 'dark' }
}

interface CreateForm {
  title: string
  description: string
  deadline_at: string
  priority: string
}
const EMPTY_FORM: CreateForm = { title: '', description: '', deadline_at: '', priority: '2' }

function MiniTaskCard({ task, onDone, onPostpone }: {
  task: MiniTaskOut
  onDone: (id: number) => void
  onPostpone: (id: number) => void
}) {
  const overdue = isOverdue(task)
  return (
    <div className={`border rounded-xl p-3 mb-2.5 ${STATUS_BG[task.status] ?? 'bg-gray-800 border-gray-600'}`}>
      <div className="flex items-start gap-2 mb-1.5">
        <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${PRIORITY_DOT[task.priority]}`} />
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-semibold text-white leading-snug break-words">{task.title}</div>
        </div>
      </div>

      {task.assignee_name && (
        <div className="text-xs text-gray-400 mb-1 truncate">Исп: {task.assignee_name}</div>
      )}

      <div className="flex items-center justify-between mt-1">
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] text-gray-400">{STATUS_LABELS[task.status] ?? task.status}</span>
          {task.deadline_at && (
            <span className={`text-[11px] ${overdue ? 'text-red-400 font-semibold' : 'text-gray-500'}`}>
              {overdue ? '⚠ ' : ''}Срок: {formatDeadline(task.deadline_at)}
            </span>
          )}
        </div>

        {(task.status !== 'done' && task.status !== 'cancelled') && (
          <div className="flex gap-1.5 flex-shrink-0 ml-2">
            <button
              onClick={() => onDone(task.id)}
              className="px-2.5 py-1 rounded-lg text-xs font-medium bg-green-800 text-green-200 border border-green-700 active:opacity-70"
            >
              ✓ Готово
            </button>
            <button
              onClick={() => onPostpone(task.id)}
              className="px-2.5 py-1 rounded-lg text-xs font-medium bg-gray-700 text-gray-300 border border-gray-600 active:opacity-70"
            >
              +1д
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function TgMiniAppPage() {
  const [initData, setInitData] = useState<string | null>(null)
  const [scope, setScope] = useState<TaskScope>('mine')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM)

  useEffect(() => {
    try {
      const tg = (window as any).Telegram?.WebApp
      if (tg) {
        tg.ready()
        tg.expand()
        setInitData(tg.initData ?? '')
      } else {
        setInitData('')
      }
    } catch {
      setInitData('')
    }
  }, [])

  const meQuery = useMiniMe()
  const tasksQuery = useMiniTasks(scope)
  const createTask = useMiniCreateTask()
  const updateTask = useMiniUpdateTask()

  // initData not yet resolved
  if (initData === null) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Загрузка...</div>
      </div>
    )
  }

  // Not opened in Telegram
  if (initData === '') {
    return (
      <div className="min-h-screen bg-gray-900 flex flex-col items-center justify-center px-6 text-center">
        <div className="text-6xl mb-4">📱</div>
        <div className="text-white text-xl font-semibold mb-2">Откройте через Telegram</div>
        <div className="text-gray-400 text-sm">Это приложение работает только внутри Telegram Mini App.</div>
      </div>
    )
  }

  const me = meQuery.data
  const tasks: MiniTaskOut[] = tasksQuery.data ?? []

  const handleDone = (id: number) => updateTask.mutate({ id, status: 'done' })

  const handlePostpone = (id: number) => {
    const task = tasks.find((t) => t.id === id)
    const base = task?.deadline_at ? new Date(task.deadline_at) : new Date()
    base.setDate(base.getDate() + 1)
    updateTask.mutate({ id, deadline_at: base.toISOString() })
  }

  const handleCreate = async () => {
    if (!form.title.trim()) return
    await createTask.mutateAsync({
      title: form.title.trim(),
      description: form.description || undefined,
      deadline_at: form.deadline_at || undefined,
      priority: Number(form.priority) as 1 | 2 | 3,
    })
    setShowCreate(false)
    setForm(EMPTY_FORM)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between sticky top-0 z-10">
        <div>
          <div className="text-[15px] font-semibold">Мои задачи</div>
          {me && <div className="text-[11px] text-gray-400">{me.name}</div>}
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-medium active:opacity-75"
        >
          + Задача
        </button>
      </div>

      {/* Scope filter — only for managers */}
      {me?.is_manager && (
        <div className="flex gap-2 px-4 py-3 overflow-x-auto">
          {(['mine', 'assigned', 'created', 'all'] as TaskScope[]).map((s) => {
            const labels: Record<TaskScope, string> = { mine: 'Мои', assigned: 'Назначено мной', created: 'Созданные мной', all: 'Все' }
            return (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap border transition-colors ${scope === s ? 'bg-blue-600 text-white border-blue-600' : 'bg-gray-800 text-gray-400 border-gray-700'}`}
              >
                {labels[s]}
              </button>
            )
          })}
        </div>
      )}

      {/* Task list */}
      <div className="px-4 pb-6 pt-2">
        {meQuery.isError && (
          <div className="text-red-400 text-sm text-center py-8">
            Ошибка авторизации. Убедитесь, что вы зарегистрированы в системе.
          </div>
        )}
        {tasksQuery.isLoading && (
          <div className="text-gray-400 text-sm text-center py-8">Загрузка задач...</div>
        )}
        {!tasksQuery.isLoading && tasks.length === 0 && (
          <div className="text-gray-500 text-sm text-center py-12">Нет задач</div>
        )}
        {tasks.map((task) => (
          <MiniTaskCard
            key={task.id}
            task={task}
            onDone={handleDone}
            onPostpone={handlePostpone}
          />
        ))}
      </div>

      {/* Create Task bottom sheet */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/70" onClick={() => { setShowCreate(false); setForm(EMPTY_FORM) }}>
          <div
            className="bg-gray-900 border-t border-gray-700 rounded-t-2xl w-full p-5 pb-8"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="text-[16px] font-semibold">Новая задача</div>
              <button
                onClick={() => { setShowCreate(false); setForm(EMPTY_FORM) }}
                className="text-gray-400 text-lg px-2"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col gap-3">
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Название *</label>
                <input
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder="Название задачи"
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400 mb-1 block">Описание</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Детали..."
                  rows={2}
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500 resize-none"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400 mb-1 block">Дедлайн</label>
                <input
                  type="datetime-local"
                  value={form.deadline_at}
                  onChange={(e) => setForm((f) => ({ ...f, deadline_at: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="text-xs text-gray-400 mb-1 block">Приоритет</label>
                <select
                  value={form.priority}
                  onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
                >
                  <option value="1">🔴 Высокий</option>
                  <option value="2">🟡 Средний</option>
                  <option value="3">🟢 Низкий</option>
                </select>
              </div>

              <button
                onClick={handleCreate}
                disabled={!form.title.trim() || createTask.isPending}
                className="w-full py-3 rounded-xl bg-blue-600 text-white font-semibold text-[15px] disabled:opacity-40 active:opacity-75 mt-1"
              >
                {createTask.isPending ? 'Создание...' : 'Создать задачу'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
