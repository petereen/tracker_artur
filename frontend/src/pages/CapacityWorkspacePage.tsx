import { useState } from 'react'
import { AlertTriangle, CalendarOff, Users2 } from 'lucide-react'
import { useCapacity } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'

export function CapacityWorkspacePage() {
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('week')
  const [period, setPeriod] = useState(() => periodFromPreset('week'))
  const capacity = useCapacity(period)
  return <div><div className="view-toolbar"><div><h2>Багийн багтаамж</h2><p>Төлөвлөсөн ажлыг сонгосон хугацааны боломжит цагтай харьцуулна.</p></div><div className="toolbar-cluster"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) }} /><div className="legend"><span><i className="safe" />Хэвийн</span><span><i className="near" />Анхаарах</span><span><i className="over" />Хэтэрсэн</span></div></div></div><section className="capacity-table panel"><header><span>Ажилтан</span><span>Боломжит</span><span>Төлөвлөсөн</span><span>Ачаалал</span></header>{capacity.data?.map((row) => <article key={row.employee_id}><div className="person-cell"><div className="avatar">{row.name[0]}</div><strong>{row.name}</strong></div><span>{Math.round(row.available_minutes / 60)}ц</span><span>{Math.round(row.planned_minutes / 60)}ц</span><div className="capacity-cell"><div className={`capacity-bar ${row.warning || 'safe'}`}><span style={{ width: `${Math.min(100, row.utilization_percent)}%` }} /></div><strong>{row.utilization_percent}%</strong>{row.warning === 'over' && <AlertTriangle size={15} />}</div></article>)}</section><div className="capacity-insights"><article className="panel"><Users2 /><div><strong>Багийн тэнцвэр</strong><p>90%-иас дээш ачаалалтай ажилтныг эрт илрүүлнэ.</p></div></article><article className="panel"><CalendarOff /><div><strong>Чөлөөний давхцал</strong><p>Батлагдсан чөлөө боломжит цагаас автоматаар хасагдана.</p></div></article></div></div>
}
