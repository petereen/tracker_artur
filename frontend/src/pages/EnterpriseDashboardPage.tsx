import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowUpRight, BriefcaseBusiness, CheckCircle2, Coffee, House, Laptop2, Pause, Play } from 'lucide-react'
import { useClock, useClockAction, useEnterpriseSummary, useEnterpriseTasks, useStartCheckin, useSubmitCheckin, useTodayAgenda, useTodayCheckin } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

function formatDuration(seconds: number) {
  seconds = Math.max(0, Math.floor(seconds))
  return [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60].map((value) => String(value).padStart(2, '0')).join(':')
}

function formatLocalTime(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: timezone }).format(new Date(value))
  } catch {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }
}

export function EnterpriseDashboardPage() {
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('week')
  const [period, setPeriod] = useState(() => periodFromPreset('week'))
  const summary = useEnterpriseSummary(period)
  const employeeId = useAuthStore((state) => state.actor?.employee_id)
  const clock = useClock(employeeId != null)
  const action = useClockAction()
  const todayCheckin = useTodayCheckin()
  const startCheckin = useStartCheckin()
  const submitCheckin = useSubmitCheckin()
  const [checkinOpen, setCheckinOpen] = useState(false)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const today = new Date().toISOString().slice(0, 10)
  const todayTasks = useEnterpriseTasks(undefined, { date_from: today, date_to: today })
  const agenda = useTodayAgenda()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const isSupervisor = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const [, tick] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => tick((value) => value + 1), 1000); return () => clearInterval(timer) }, [])
  const active = clock.data?.active
  const working = active?.entry_type === 'work'
  const onBreak = active?.entry_type === 'break'
  const todayEntries = clock.data?.today_entries ?? []
  const todayWorkSeconds = todayEntries.reduce((total, entry) => {
    if (entry.entry_type !== 'work') return total
    return total + Math.max(0, ((entry.ended_at ? new Date(entry.ended_at).getTime() : Date.now()) - new Date(entry.started_at).getTime()) / 1000)
  }, 0)

  const cards = [
    { label: 'Идэвхтэй төсөл', value: summary.data?.active_projects ?? '—', icon: BriefcaseBusiness, tone: 'blue' },
    { label: 'Дууссан даалгавар', value: summary.data?.completed_tasks ?? '—', icon: CheckCircle2, tone: 'green' },
    { label: 'Гүйцэтгэл', value: summary.data ? `${summary.data.completion_rate}%` : '—', icon: ArrowUpRight, tone: 'purple' },
    { label: 'Ажилласан цаг', value: summary.data ? `${Math.round(summary.data.worked_minutes / 60 * 10) / 10}ц` : '—', icon: Coffee, tone: 'amber' },
  ]

  const openCheckin = async () => {
    if (todayCheckin.data?.checkin?.status === 'submitted') return
    if (!todayCheckin.data?.checkin && todayCheckin.data?.template?.id) await startCheckin.mutateAsync(todayCheckin.data.template.id)
    setCheckinOpen(true)
  }
  const saveCheckin = async (event: React.FormEvent) => {
    event.preventDefault()
    const current = todayCheckin.data?.checkin || await startCheckin.mutateAsync(todayCheckin.data.template.id)
    const questions = todayCheckin.data?.template?.questions ?? []
    await submitCheckin.mutateAsync({ id: current.id, answers: questions.map((question: any) => question.answer_type === 'integer' || question.answer_type === 'decimal' ? { question_id: question.id, value_numeric: Number(answers[question.id]) } : { question_id: question.id, value_text: answers[question.id] }) })
    setCheckinOpen(false)
  }

  return (
    <div className="dashboard-grid">
      <div className="dashboard-period"><div><span className="eyebrow">{isSupervisor ? 'Байгууллагын тойм' : 'Хувийн тойм'}</span><h2>{isSupervisor ? 'Нийт гүйцэтгэлийн үзүүлэлт' : 'Таны гүйцэтгэлийн үзүүлэлт'}</h2></div><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) }} /></div>
      <section className="clock-panel panel">
        <div className="panel-heading"><div><span className="eyebrow">Punch clock</span><h2>Өнөөдрийн ажлын цаг</h2></div><span className={`live-indicator ${active ? 'online' : ''}`}>{active ? 'LIVE' : 'OFF'}</span></div>
        <div className="clock-summary"><div className="clock-time" aria-live="polite">{formatDuration(todayWorkSeconds)}</div>
        <p>{working ? `${active?.mode === 'remote' ? 'Remote' : 'Оффис'} горимоор ажиллаж байна.` : onBreak ? 'Завсарлагын хугацаа ажилласан цагт орохгүй.' : 'Telegram болон вэбийн цагийн төлөв үргэлж ижил байна.'}</p>
        <div className="clock-details" aria-label="Өнөөдрийн цагийн дэлгэрэнгүй">
          {todayEntries.map((entry) => {
            const seconds = Math.max(0, ((entry.ended_at ? new Date(entry.ended_at).getTime() : Date.now()) - new Date(entry.started_at).getTime()) / 1000)
            return <div key={entry.id}>{entry.entry_type === 'break' ? 'Завсарлага' : entry.mode === 'remote' ? 'Remote' : 'Оффис'}: {formatLocalTime(entry.started_at, clock.data?.timezone ?? 'Asia/Ulaanbaatar')}–{entry.ended_at ? formatLocalTime(entry.ended_at, clock.data?.timezone ?? 'Asia/Ulaanbaatar') : 'одоо'} ({formatDuration(seconds)})</div>
          })}
        </div>
        </div>
        <div className="clock-actions">
          {!active && <><button className="clock-button office" onClick={() => action.mutate({ action: 'start', mode: 'in_person' })}><House />Оффис эхлэх</button><button className="clock-button remote" onClick={() => action.mutate({ action: 'start', mode: 'remote' })}><Laptop2 />Remote эхлэх</button></>}
          {working && <><button className="clock-button break" onClick={() => action.mutate({ action: 'break' })}><Coffee />Завсарлага</button><button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button></>}
          {onBreak && <><button className="clock-button office" onClick={() => action.mutate({ action: 'resume' })}><Play />Үргэлжлүүлэх</button><button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button></>}
        </div>
      </section>
      <section className="daily-focus panel"><span className="eyebrow">Өнөөдрийн төвлөрөл</span><h2>Хамгийн чухал ажлаа тодорхой болго.</h2>{todayCheckin.data?.template?.questions?.slice(0, 2).map((question: any, index: number) => <div className="focus-question" key={question.id}><span>{index + 1}</span><div><strong>{question.prompt?.mn || question.prompt?.en}</strong><p>{question.is_required ? 'Заавал хариулна' : 'Сонголттой'}</p></div></div>)}{!todayCheckin.data?.template && <p>Check-in асуулт тохируулаагүй байна.</p>}<button className="secondary-action" onClick={openCheckin} disabled={!todayCheckin.data?.template || todayCheckin.data?.checkin?.status === 'submitted'}>{todayCheckin.data?.checkin?.status === 'submitted' ? 'Өнөөдрийн check-in бөглөгдсөн' : 'Өдрийн check-in бөглөх'}</button>{checkinOpen && <form className="checkin-form" onSubmit={saveCheckin}>{todayCheckin.data.template.questions.map((question: any) => <label key={question.id}><strong>{question.prompt?.mn || question.prompt?.en}</strong>{question.choices?.length ? <select required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}><option value="">Сонгох</option>{question.choices.map((choice: any) => <option key={String(choice)}>{String(choice)}</option>)}</select> : <textarea required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })} />}</label>)}<div><button type="button" className="secondary-action compact" onClick={() => setCheckinOpen(false)}>Цуцлах</button><button className="primary-action compact" disabled={submitCheckin.isPending}>Хадгалах</button></div></form>}</section>
      <section className="metrics-grid" aria-label="Гүйцэтгэлийн үзүүлэлт">{cards.map(({ label, value, icon: Icon, tone }, index) => <motion.article className={`metric-card ${tone}`} key={label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .04, type: 'spring', bounce: 0, duration: .35 }}><Icon /><span>{label}</span><strong>{value}</strong></motion.article>)}</section>
      <section className="panel productivity-panel"><div className="panel-heading"><div><span className="eyebrow">Өнөөдрийн ажил</span><h2>Хийх даалгаврууд</h2></div></div>{todayTasks.data?.length ? todayTasks.data.slice(0, 6).filter((task) => !isSupervisor || task.assignee_ids.includes(employeeId ?? -1)).map((task) => <div className="progress-row" key={task.id}><div><span>{task.primary_owner_name || 'Хариуцагчгүй'}</span><strong>{task.title}</strong></div><span>{task.deadline_at ? new Date(task.deadline_at).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit' }) : 'Хугацаагүй'}</span></div>) : <p>Өнөөдөр төлөвлөсөн даалгавар алга.</p>}<aside className="today-mini-calendar"><strong>{new Date().toLocaleDateString('mn-MN', { month: 'long', year: 'numeric' })}</strong><div>{Array.from({ length: 7 }, (_, index) => { const day = new Date(); day.setDate(day.getDate() + index); const count = (agenda.data?.tasks ?? []).filter((task: any) => (task.start_at || task.deadline_at)?.slice(0, 10) === day.toISOString().slice(0, 10)).length + (agenda.data?.entries ?? []).filter((item: any) => item.starts_at?.slice(0, 10) === day.toISOString().slice(0, 10)).length; return <span key={index} className={index === 0 ? 'today' : ''}>{day.getDate()}<i>{count || ''}</i></span> })}</div><small>Дараагийн 7 өдрийн үйл явдал</small></aside></section>
    </div>
  )
}
