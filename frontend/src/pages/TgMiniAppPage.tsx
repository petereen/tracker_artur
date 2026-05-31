import { useEffect, useMemo, useState } from 'react'
import { useMiniMe, useMiniTasks, useMiniCreateTask, useMiniUpdateTask, MiniTaskOut, TaskScope } from '../api/miniapp'

const PRIORITY_BAR: Record<number, string> = { 1: 'bg-red-500', 2: 'bg-amber-400', 3: 'bg-green-500' }

// Вертикальные «колонки» канбана (секции сверху вниз)
const COLUMNS: { key: string; label: string; icon: string; accent: string; dot: string }[] = [
  { key: 'overdue', label: 'Просрочено', icon: '🔴', accent: 'text-red-300', dot: 'bg-red-500' },
  { key: 'open', label: 'Открыто', icon: '📥', accent: 'text-sky-300', dot: 'bg-sky-500' },
  { key: 'in_progress', label: 'В работе', icon: '🔧', accent: 'text-amber-300', dot: 'bg-amber-400' },
  { key: 'done', label: 'Завершено', icon: '✅', accent: 'text-emerald-300', dot: 'bg-emerald-500' },
]

function formatDeadline(dt: string | null): string {
  if (!dt) return ''
  return new Date(dt).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function isPast(dt: string | null): boolean {
  return !!dt && new Date(dt) < new Date()
}

/** Колонка задачи: done/cancelled как есть; просроченные активные — в «Просрочено». */
function columnOf(t: MiniTaskOut): string {
  if (t.status === 'done') return 'done'
  if (t.status === 'cancelled') return 'cancelled'
  if (t.status === 'overdue' || isPast(t.deadline_at)) return 'overdue'
  return t.status // open | in_progress
}

interface CreateForm { title: string; description: string; deadline_at: string; priority: string }
const EMPTY_FORM: CreateForm = { title: '', description: '', deadline_at: '', priority: '2' }

function TaskCard({ task, onStatus, onPostpone, busy }: {
  task: MiniTaskOut
  onStatus: (id: number, status: string) => void
  onPostpone: (id: number) => void
  busy: boolean
}) {
  const overdue = task.status !== 'done' && isPast(task.deadline_at)
  const done = task.status === 'done'
  return (
    <div className="relative bg-gray-800/80 rounded-2xl pl-3 pr-3 py-2.5 mb-2 overflow-hidden">
      <div className={`absolute left-0 top-0 bottom-0 w-1.5 ${PRIORITY_BAR[task.priority] ?? 'bg-gray-500'}`} />
      <div className={`text-[14px] font-semibold leading-snug break-words ${done ? 'text-gray-400 line-through' : 'text-white'}`}>
        {task.title}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[11px]">
        {task.assignee_name && <span className="text-gray-400">👤 {task.assignee_name}</span>}
        {task.deadline_at && (
          <span className={overdue ? 'text-red-400 font-semibold' : 'text-gray-400'}>
            🕒 {formatDeadline(task.deadline_at)}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2.5">
        {done ? (
          <button disabled={busy} onClick={() => onStatus(task.id, 'in_progress')}
            className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-gray-700 text-gray-200 active:opacity-70 disabled:opacity-40">
            ↩ Вернуть
          </button>
        ) : (
          <>
            {(task.status === 'open' || task.status === 'overdue') && (
              <button disabled={busy} onClick={() => onStatus(task.id, 'in_progress')}
                className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-amber-600/80 text-white active:opacity-70 disabled:opacity-40">
                ▶ В работу
              </button>
            )}
            <button disabled={busy} onClick={() => onStatus(task.id, 'done')}
              className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-emerald-600 text-white active:opacity-70 disabled:opacity-40">
              ✓ Завершить
            </button>
            <button disabled={busy} onClick={() => onPostpone(task.id)}
              className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-gray-700 text-gray-300 active:opacity-70 disabled:opacity-40">
              ⏰ +1д
            </button>
          </>
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
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ done: true })

  useEffect(() => {
    try {
      const tg = (window as any).Telegram?.WebApp
      if (tg) { tg.ready(); tg.expand(); setInitData(tg.initData ?? '') }
      else setInitData('')
    } catch { setInitData('') }
  }, [])

  const meQuery = useMiniMe()
  const tasksQuery = useMiniTasks(scope, true)
  const createTask = useMiniCreateTask()
  const updateTask = useMiniUpdateTask()

  const tasks: MiniTaskOut[] = tasksQuery.data ?? []
  const grouped = useMemo(() => {
    const g: Record<string, MiniTaskOut[]> = {}
    for (const t of tasks) {
      const c = columnOf(t)
      if (c === 'cancelled') continue
      ;(g[c] ||= []).push(t)
    }
    return g
  }, [tasks])

  if (initData === null) {
    return <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-400 text-sm">Загрузка…</div>
  }
  if (initData === '') {
    return (
      <div className="min-h-screen bg-gray-950 flex flex-col items-center justify-center px-6 text-center">
        <div className="text-6xl mb-4">📱</div>
        <div className="text-white text-xl font-semibold mb-2">Откройте через Telegram</div>
        <div className="text-gray-400 text-sm">Это приложение работает только внутри Telegram.</div>
      </div>
    )
  }

  const me = meQuery.data
  const busy = updateTask.isPending

  const handleStatus = (id: number, status: string) => updateTask.mutate({ id, status })
  const handlePostpone = (id: number) => {
    const t = tasks.find((x) => x.id === id)
    const base = t?.deadline_at ? new Date(t.deadline_at) : new Date()
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
    setShowCreate(false); setForm(EMPTY_FORM)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white pb-24">
      <div className="bg-gray-900/95 backdrop-blur border-b border-gray-800 px-4 py-3 sticky top-0 z-10">
        <div className="text-[15px] font-semibold">Задачи</div>
        {me && <div className="text-[11px] text-gray-400">{me.name}{me.is_manager ? ' · руководитель' : ''}</div>}
        {me?.is_manager && (
          <div className="flex gap-2 mt-2 overflow-x-auto -mx-1 px-1">
            {(['mine', 'assigned', 'created', 'all'] as TaskScope[]).map((s) => {
              const labels: Record<TaskScope, string> = { mine: 'Мои', assigned: 'Назначено мной', created: 'Созданные', all: 'Все' }
              return (
                <button key={s} onClick={() => setScope(s)}
                  className={`px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap border ${scope === s ? 'bg-blue-600 text-white border-blue-600' : 'bg-gray-800 text-gray-400 border-gray-700'}`}>
                  {labels[s]}
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="px-4 pt-3">
        {meQuery.isError && (
          <div className="text-red-400 text-sm text-center py-8">Ошибка авторизации. Убедитесь, что вы зарегистрированы (или откройте через кнопку бота).</div>
        )}
        {tasksQuery.isLoading && <div className="text-gray-400 text-sm text-center py-8">Загрузка задач…</div>}
        {!tasksQuery.isLoading && !meQuery.isError && tasks.length === 0 && (
          <div className="text-gray-500 text-sm text-center py-12">Пока нет задач. Нажмите «+», чтобы создать.</div>
        )}

        {!tasksQuery.isLoading && !meQuery.isError && tasks.length > 0 && COLUMNS.map((col) => {
          const items = grouped[col.key] ?? []
          const isCollapsed = collapsed[col.key]
          return (
            <div key={col.key} className="mb-4">
              <button
                onClick={() => setCollapsed((c) => ({ ...c, [col.key]: !c[col.key] }))}
                className="w-full flex items-center gap-2 py-2 sticky top-[52px] bg-gray-950/95 backdrop-blur z-[5]"
              >
                <span className={`w-2.5 h-2.5 rounded-full ${col.dot}`} />
                <span className={`text-[13px] font-bold uppercase tracking-wide ${col.accent}`}>{col.label}</span>
                <span className="text-[11px] text-gray-500 bg-gray-800 rounded-full px-2 py-0.5">{items.length}</span>
                <span className="ml-auto text-gray-600 text-xs">{isCollapsed ? '▸' : '▾'}</span>
              </button>
              {!isCollapsed && (
                items.length === 0
                  ? <div className="text-gray-600 text-[12px] py-1 pl-4">пусто</div>
                  : items.map((t) => (
                      <TaskCard key={t.id} task={t} onStatus={handleStatus} onPostpone={handlePostpone} busy={busy} />
                    ))
              )}
            </div>
          )
        })}
      </div>

      {/* FAB */}
      <button
        onClick={() => setShowCreate(true)}
        className="fixed bottom-5 right-5 z-20 w-14 h-14 rounded-full bg-blue-600 text-white text-3xl leading-none shadow-lg shadow-blue-900/50 active:scale-95 flex items-center justify-center"
        aria-label="Новая задача"
      >+</button>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/70" onClick={() => { setShowCreate(false); setForm(EMPTY_FORM) }}>
          <div className="bg-gray-900 border-t border-gray-700 rounded-t-2xl w-full p-5 pb-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-[16px] font-semibold">Новая задача</div>
              <button onClick={() => { setShowCreate(false); setForm(EMPTY_FORM) }} className="text-gray-400 text-lg px-2">✕</button>
            </div>
            <div className="flex flex-col gap-3">
              <input
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="Название задачи *"
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
              />
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="Описание (необязательно)"
                rows={2}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500 resize-none"
              />
              <label className="text-xs text-gray-400">Дедлайн</label>
              <input
                type="datetime-local"
                value={form.deadline_at}
                onChange={(e) => setForm((f) => ({ ...f, deadline_at: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
              />
              <label className="text-xs text-gray-400">Приоритет</label>
              <select
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-white text-[14px] outline-none focus:border-blue-500"
              >
                <option value="1">🔴 Высокий</option>
                <option value="2">🟡 Средний</option>
                <option value="3">🟢 Низкий</option>
              </select>
              <button
                onClick={handleCreate}
                disabled={!form.title.trim() || createTask.isPending}
                className="w-full py-3 rounded-xl bg-blue-600 text-white font-semibold text-[15px] disabled:opacity-40 active:opacity-75 mt-1"
              >
                {createTask.isPending ? 'Создание…' : 'Создать задачу'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
