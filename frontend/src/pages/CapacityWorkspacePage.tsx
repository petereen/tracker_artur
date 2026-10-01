import { useTranslation } from 'react-i18next'
import { useState, useTransition } from 'react'
import { AlertTriangle, CalendarOff, Users2 } from 'lucide-react'
import { useCapacity } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'
import { QueryRegion, TableSkeleton, toQueryRegionState } from '../components/Loading'

export function CapacityWorkspacePage() {
  const { t } = useTranslation()
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('week')
  const [period, setPeriod] = useState(() => periodFromPreset('week'))
  const capacity = useCapacity(period)
  const [, startTransition] = useTransition()
  return <div><div className="view-toolbar"><div><h2>{t('projects.capacity.title')}</h2><p>{t('projects.capacity.subtitle')}</p></div><div className="toolbar-cluster"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => startTransition(() => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) })} /><div className="legend"><span><i className="safe" />{t('projects.capacity.normal')}</span><span><i className="near" />{t('projects.capacity.warning')}</span><span><i className="over" />{t('projects.capacity.over')}</span></div></div></div><QueryRegion state={toQueryRegionState(capacity)} empty={Boolean(capacity.data && capacity.data.length === 0)} emptyFallback={<p className="query-region-state">{t('projects.capacity.empty')}</p>} skeleton={<section className="capacity-table panel"><header><span>{t('projects.capacity.employee')}</span><span>{t('projects.capacity.available')}</span><span>{t('projects.capacity.planned')}</span><span>{t('projects.capacity.load')}</span></header><TableSkeleton rows={6} /></section>}><section className="capacity-table panel"><header><span>{t('projects.capacity.employee')}</span><span>{t('projects.capacity.available')}</span><span>{t('projects.capacity.planned')}</span><span>{t('projects.capacity.load')}</span></header>{capacity.data?.map((row) => <article key={row.employee_id}><div className="person-cell"><div className="avatar">{row.name[0]}</div><strong>{row.name}</strong></div><span>{Math.round(row.available_minutes / 60)}{t('worktime.unit.hour')}</span><span>{Math.round(row.planned_minutes / 60)}{t('worktime.unit.hour')}</span><div className="capacity-cell"><div className={`capacity-bar ${row.warning || 'safe'}`}><span style={{ width: `${Math.min(100, row.utilization_percent)}%` }} /></div><strong>{row.utilization_percent}%</strong>{row.warning === 'over' && <AlertTriangle size={15} />}</div></article>)}</section></QueryRegion><div className="capacity-insights"><article className="panel"><Users2 /><div><strong>{t('projects.capacity.balanceTitle')}</strong><p>{t('projects.capacity.balanceBody')}</p></div></article><article className="panel"><CalendarOff /><div><strong>{t('projects.capacity.leaveTitle')}</strong><p>{t('projects.capacity.leaveBody')}</p></div></article></div></div>
}
