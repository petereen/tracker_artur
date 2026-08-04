import { useMemo, useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { CompanyPlanItem, PlanHorizon, PlanSuggestion, useCompanyPlan, useCreateCompanyPlanItem, usePlanSuggestions, useReorderCompanyPlan } from '../api/hooks'
import { ReportDetailModal } from '../components/ReportDetailModal'

const HORIZONS: { id: PlanHorizon; label: string; color: 'purple' | 'blue' | 'green' }[] = [
  { id: 'long_term', label: 'Урт хугацааны', color: 'purple' },
  { id: 'mid_term', label: 'Дунд хугацааны', color: 'blue' },
  { id: 'short_term', label: 'Богино хугацааны', color: 'green' },
]

function currentMonth() { return new Date().toISOString().slice(0, 7) }
function monthDate(value: string) { return `${value}-01` }

export function PlansPage() {
  const [tab, setTab] = useState<'suggestions' | 'company'>('suggestions')
  const [month, setMonth] = useState(currentMonth)
  const [editingSuggestion, setEditingSuggestion] = useState<PlanSuggestion | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [draggedId, setDraggedId] = useState<number | null>(null)
  const suggestions = usePlanSuggestions(monthDate(month))
  const companyPlan = useCompanyPlan(monthDate(month))
  const reorder = useReorderCompanyPlan()
  const columns = useMemo(() => HORIZONS.reduce((result, horizon) => ({ ...result, [horizon.id]: (companyPlan.data || []).filter((item) => item.horizon === horizon.id).sort((a, b) => a.position - b.position) }), {} as Record<PlanHorizon, CompanyPlanItem[]>), [companyPlan.data])

  const moveItem = (target: PlanHorizon, targetIndex?: number) => {
    if (draggedId === null || !companyPlan.data) return
    const allColumns = HORIZONS.reduce((result, horizon) => ({ ...result, [horizon.id]: [...columns[horizon.id]] }), {} as Record<PlanHorizon, CompanyPlanItem[]>)
    let moved: CompanyPlanItem | undefined
    for (const horizon of HORIZONS) {
      const index = allColumns[horizon.id].findIndex((item) => item.id === draggedId)
      if (index >= 0) moved = allColumns[horizon.id].splice(index, 1)[0]
    }
    if (!moved) return
    const index = targetIndex === undefined ? allColumns[target].length : targetIndex
    allColumns[target].splice(index, 0, moved)
    reorder.mutate({ plan_month: monthDate(month), columns: HORIZONS.reduce((result, horizon) => ({ ...result, [horizon.id]: allColumns[horizon.id].map((item) => item.id) }), {} as Record<PlanHorizon, number[]>) })
    setDraggedId(null)
  }

  return <div>
    <PageHeader title="Төлөвлөгөө" sub={`${month} сарын компанийн төлөвлөгөө`} />
    <div className="flex flex-wrap gap-3 items-center mb-4">
      <div className="flex gap-1 bg-surface2 rounded-lg p-1"><button onClick={() => setTab('suggestions')} className={`px-3 py-1.5 rounded text-xs border-none cursor-pointer ${tab === 'suggestions' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Санал, санаа</button><button onClick={() => setTab('company')} className={`px-3 py-1.5 rounded text-xs border-none cursor-pointer ${tab === 'company' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Компанийн төлөвлөгөө</button></div>
      <input type="month" value={month} onChange={(event) => setMonth(event.target.value)} className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-[13px] outline-none" />
    </div>
    {tab === 'suggestions' && <SuggestionsPanel suggestions={suggestions.data || []} loading={suggestions.isLoading} onApprove={setEditingSuggestion} onOpenReport={setDetailId} />}
    {tab === 'company' && <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      {HORIZONS.map((horizon) => <div key={horizon.id} onDragOver={(event) => event.preventDefault()} onDrop={() => moveItem(horizon.id)} className="bg-surface2 border border-border rounded-xl min-h-[360px] p-3">
        <div className="flex justify-between items-center mb-3"><Badge color={horizon.color}>{horizon.label}</Badge><span className="text-xs text-muted">{columns[horizon.id].length}</span></div>
        <div className="space-y-2">{columns[horizon.id].map((item, index) => <div key={item.id} draggable onDragStart={() => setDraggedId(item.id)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.stopPropagation(); moveItem(horizon.id, index) }} className="bg-surface border border-border rounded-lg p-3 cursor-grab active:cursor-grabbing">
          <div className="text-sm font-medium whitespace-pre-wrap">{item.title}</div>{item.content && <div className="text-xs text-muted whitespace-pre-wrap mt-2 line-clamp-3">{item.content}</div>}<div className="text-[11px] text-muted mt-3">{item.source_employee_name || 'Эх сурвалжгүй'}</div>
        </div>)}</div>
        {!columns[horizon.id].length && <div className="text-center text-xs text-muted py-12">Энд төлөвлөгөө чирж оруулна уу</div>}
      </div>)}
    </div>}
    {editingSuggestion && <ApprovePlanModal suggestion={editingSuggestion} month={monthDate(month)} onClose={() => setEditingSuggestion(null)} />}
    {detailId !== null && <ReportDetailModal reportId={detailId} onClose={() => setDetailId(null)} />}
  </div>
}

function SuggestionsPanel({ suggestions, loading, onApprove, onOpenReport }: { suggestions: PlanSuggestion[]; loading: boolean; onApprove: (suggestion: PlanSuggestion) => void; onOpenReport: (id: number) => void }) {
  return <Card className="admin-table-card !p-0 overflow-hidden"><div className="divide-y divide-border2">
    {suggestions.map((suggestion) => <div key={suggestion.id} className="p-5 flex flex-col gap-3"><div className="flex justify-between gap-4"><div><div className="font-medium">{suggestion.employee_name}</div><div className="text-xs text-muted mt-1">{suggestion.period_date} · {suggestion.company_plan_item_count} төлөвлөгөөний зүйл үүссэн</div></div><div className="flex gap-2"><Btn onClick={() => onOpenReport(suggestion.id)}>Бүтэн тайлан</Btn><Btn variant="primary" onClick={() => onApprove(suggestion)}>Төлөвлөгөөнд оруулах</Btn></div></div><div className="text-sm text-muted whitespace-pre-wrap leading-6 line-clamp-4">{suggestion.text || 'Текст байхгүй'}</div></div>)}
    {!loading && !suggestions.length && <div className="p-10 text-center text-muted">Энэ сарын ажилтны санал байхгүй</div>}
  </div></Card>
}

function ApprovePlanModal({ suggestion, month, onClose }: { suggestion: PlanSuggestion; month: string; onClose: () => void }) {
  const create = useCreateCompanyPlanItem()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState(suggestion.text || '')
  const [horizon, setHorizon] = useState<PlanHorizon>('short_term')
  const submit = async () => { if (!title.trim()) return; await create.mutateAsync({ source_report_id: suggestion.id, title: title.trim(), content, plan_month: month, horizon }); onClose() }
  return <Modal title="Компанийн төлөвлөгөөнд оруулах" onClose={onClose} className="max-w-2xl"><div className="flex flex-col gap-4"><div className="text-sm text-muted">Эх сурвалж: {suggestion.employee_name}</div><Input label="Төлөвлөгөөний зүйл" value={title} onChange={setTitle} placeholder="Хийх ажлын тодорхой гарчиг" fullWidth /><div className="flex flex-col gap-1.5"><label className="text-xs text-muted font-medium">Дэлгэрэнгүй</label><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={6} className="bg-surface2 border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-accent" /></div><Select label="Хугацааны түвшин" value={horizon} onChange={(value) => setHorizon(value as PlanHorizon)} options={HORIZONS.map((item) => ({ value: item.id, label: item.label }))} fullWidth /><div className="flex justify-end gap-2"><Btn onClick={onClose}>Цуцлах</Btn><Btn variant="primary" size="lg" onClick={submit} disabled={!title.trim() || create.isPending}>Баталж оруулах</Btn></div></div></Modal>
}
