import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowUpRight, BriefcaseBusiness, CheckCircle2, Coffee, House, Laptop2, Pause, Play, TimerReset } from 'lucide-react'
import { useClock, useClockAction, useEnterpriseSummary } from '../api/enterprise'

function elapsed(startedAt?: string) {
  if (!startedAt) return '00:00:00'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000))
  return [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60].map((value) => String(value).padStart(2, '0')).join(':')
}

export function EnterpriseDashboardPage() {
  const summary = useEnterpriseSummary()
  const clock = useClock()
  const action = useClockAction()
  const [, tick] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => tick((value) => value + 1), 1000); return () => clearInterval(timer) }, [])
  const active = clock.data?.active
  const working = active?.entry_type === 'work'
  const onBreak = active?.entry_type === 'break'

  const cards = [
    { label: 'Идэвхтэй төсөл', value: summary.data?.active_projects ?? '—', icon: BriefcaseBusiness, tone: 'blue' },
    { label: 'Дууссан даалгавар', value: summary.data?.completed_tasks ?? '—', icon: CheckCircle2, tone: 'green' },
    { label: 'Гүйцэтгэл', value: summary.data ? `${summary.data.completion_rate}%` : '—', icon: ArrowUpRight, tone: 'purple' },
    { label: 'Billable харьцаа', value: summary.data ? `${summary.data.billable_ratio}%` : '—', icon: TimerReset, tone: 'amber' },
  ]

  return (
    <div className="dashboard-grid">
      <section className="clock-panel panel">
        <div className="panel-heading"><div><span className="eyebrow">Punch clock</span><h2>{working ? 'Ажиллаж байна' : onBreak ? 'Завсарлага' : 'Өдрөө эхлүүлэх үү?'}</h2></div><span className={`live-indicator ${active ? 'online' : ''}`}>{active ? 'LIVE' : 'OFF'}</span></div>
        <div className="clock-time" aria-live="polite">{elapsed(active?.started_at)}</div>
        <p>{working ? `${active?.mode === 'remote' ? 'Remote' : 'Оффис'} горимоор ажиллаж байна.` : onBreak ? 'Завсарлагын хугацаа ажилласан цагт орохгүй.' : 'Telegram болон вэбийн цагийн төлөв үргэлж ижил байна.'}</p>
        <div className="clock-actions">
          {!active && <><button className="clock-button office" onClick={() => action.mutate({ action: 'start', mode: 'in_person' })}><House />Оффис эхлэх</button><button className="clock-button remote" onClick={() => action.mutate({ action: 'start', mode: 'remote' })}><Laptop2 />Remote эхлэх</button></>}
          {working && <><button className="clock-button break" onClick={() => action.mutate({ action: 'break' })}><Coffee />Завсарлага</button><button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button></>}
          {onBreak && <><button className="clock-button office" onClick={() => action.mutate({ action: 'resume' })}><Play />Үргэлжлүүлэх</button><button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button></>}
        </div>
      </section>
      <section className="daily-focus panel"><span className="eyebrow">Өнөөдрийн төвлөрөл</span><h2>Хамгийн чухал ажлаа тодорхой болго.</h2><div className="focus-question"><span>1</span><div><strong>Таны эхний 3 зорилт юу вэ?</strong><p>Богино, үйлдэлд чиглэсэн байдлаар бичнэ үү.</p></div></div><div className="focus-question"><span>2</span><div><strong>Саад болж байгаа зүйл бий юу?</strong><p>Удирдлагад эрт харагдвал хурдан шийдэгдэнэ.</p></div></div><button className="secondary-action">Өдрийн check-in бөглөх</button></section>
      <section className="metrics-grid" aria-label="Гүйцэтгэлийн үзүүлэлт">{cards.map(({ label, value, icon: Icon, tone }, index) => <motion.article className={`metric-card ${tone}`} key={label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .04, type: 'spring', bounce: 0, duration: .35 }}><Icon /><span>{label}</span><strong>{value}</strong></motion.article>)}</section>
      <section className="panel productivity-panel"><div className="panel-heading"><div><span className="eyebrow">Хувийн бүтээмж</span><h2>Ажилласан цагийн зураглал</h2></div></div><div className="progress-row"><div><span>Нийт ажилласан</span><strong>{Math.round((summary.data?.worked_minutes ?? 0) / 60)} цаг</strong></div><div className="progress-track"><span style={{ width: `${Math.min(100, (summary.data?.worked_minutes ?? 0) / 24)}%` }} /></div></div><div className="progress-row"><div><span>Billable ажил</span><strong>{Math.round((summary.data?.billable_minutes ?? 0) / 60)} цаг</strong></div><div className="progress-track green"><span style={{ width: `${summary.data?.billable_ratio ?? 0}%` }} /></div></div></section>
    </div>
  )
}
