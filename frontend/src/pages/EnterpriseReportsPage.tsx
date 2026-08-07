import { useEffect, useState, useTransition } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, FileCheck2, MessageSquareWarning, Plus, RotateCcw, Save, Send, X } from 'lucide-react'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { useCreateReport, useEnterpriseReports, useReportDetail, useReportReview, useSaveReportDraft } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'
import { QueryRegion, Skeleton, TableSkeleton } from '../components/Loading'

export function EnterpriseReportsPage() {
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('month')
  const [period, setPeriod] = useState(() => periodFromPreset('month'))
  const [selectedId, setSelectedId] = useState<number>()
  const reports = useEnterpriseReports(undefined, period)
  const detail = useReportDetail(selectedId)
  const saveDraft = useSaveReportDraft()
  const review = useReportReview()
  const createReport = useCreateReport()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canReview = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const isAdmin = roles.includes('admin')
  const selected = reports.data?.find((report) => report.id === selectedId)
  const [draft, setDraft] = useState({ title: '', markdown: '' })
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState<{ report_type: 'daily' | 'monthly'; period_date: string }>({ report_type: 'daily', period_date: new Date().toISOString().slice(0, 10) })
  const [, startTransition] = useTransition()

  useEffect(() => {
    if (!detail.data) return
    setDraft({ title: detail.data.title ?? '', markdown: detail.data.revisions?.[0]?.markdown ?? '' })
  }, [detail.data])

  const editable = Boolean(selected && !canReview && selected.report_type !== 'next_month_plan' && selected.status !== 'approved')
  const save = async () => {
    if (!detail.data) return
    const result = await saveDraft.mutateAsync({ id: detail.data.id, version: detail.data.version, title: draft.title, markdown: draft.markdown })
    setDraft({ title: result.title ?? '', markdown: result.markdown })
  }
  const act = async (action: 'approve' | 'request-revision' | 'submit' | 'reopen') => {
    if (!selectedId) return
    await review.mutateAsync({ id: selectedId, action })
    setSelectedId(undefined)
  }

  return <div>
    <div className="view-toolbar"><div><h2>{canReview ? 'Багийн тайлан' : 'Миний тайлан'}</h2><p>{canReview ? 'Зөвхөн сарын тайлан баталгаажуулалт шаарддаг.' : 'Өдрийн ба сарын тайланг нэг удаа илгээгээд, сарын тайлан батлагдахаас өмнө засах боломжтой.'}</p></div><div className="toolbar-cluster report-toolbar"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => startTransition(() => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) })} /><div className="report-actions">{!canReview && <button className="primary-action compact" onClick={() => setCreating(true)}><Plus size={16} />Тайлан үүсгэх</button>}<div className="report-summary"><span><strong>{reports.data?.filter((report) => report.report_type === 'monthly' && report.status === 'submitted').length ?? 0}</strong> хүлээгдэж буй</span><span><strong>{reports.data?.filter((report) => report.status === 'approved').length ?? 0}</strong> батлагдсан</span></div></div></div></div>
    <QueryRegion pending={reports.isLoading || reports.isFetching} skeleton={<section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header><TableSkeleton rows={6} /></section>}><section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header>{reports.data?.filter((report) => report.report_type !== 'next_month_plan').map((report) => <article key={report.id}><button className="report-main" onClick={() => setSelectedId(report.id)}><div className="report-icon"><FileCheck2 /></div><div><strong>{canReview ? report.employee_name : (report.title || 'Миний тайлан')}</strong><span>{report.report_type.replaceAll('_', ' ')}</span></div></button><time>{report.period_date}</time><span className={`status-pill ${report.status}`}>{report.status}</span><div className="row-actions"><button onClick={() => setSelectedId(report.id)}>Нээх</button>{canReview && report.report_type === 'monthly' && report.status === 'submitted' && <><button onClick={() => review.mutate({ id: report.id, action: 'request-revision' })}><MessageSquareWarning />Засвар</button><button className="approve" onClick={() => review.mutate({ id: report.id, action: 'approve' })}><Check />Батлах</button></>}{isAdmin && report.report_type === 'monthly' && ['submitted', 'approved'].includes(report.status) && <button onClick={() => review.mutate({ id: report.id, action: 'reopen' })}><RotateCcw />Буцаах</button>}</div></article>)}</section></QueryRegion>
    <AnimatePresence>{selectedId && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setSelectedId(undefined)}><motion.aside className="detail-sheet report-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Report #{selectedId}</span><h2>{selected?.employee_name}</h2></div><button onClick={() => setSelectedId(undefined)} aria-label="Хаах"><X /></button></div><QueryRegion pending={detail.isLoading || detail.isFetching} skeleton={<Skeleton variant="sheet" count={6} />}><><div className="task-detail-meta"><span>{selected?.report_type}</span><span>{selected?.period_date}</span><span>{selected?.status}</span><span>v{detail.data?.version}</span></div><form className="sheet-form" onSubmit={(event) => { event.preventDefault(); save() }}><label>Гарчиг<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} disabled={!editable} /></label><label>Тайлан (Markdown)<textarea rows={16} value={draft.markdown} onChange={(event) => setDraft({ ...draft, markdown: event.target.value })} disabled={!editable} /></label>{editable && <div className="report-editor-actions"><button className="secondary-action" disabled={!draft.markdown.trim() || saveDraft.isPending}><Save size={16} />Хадгалах</button>{selected?.status !== 'submitted' && <button type="button" className="primary-action" disabled={!draft.markdown.trim() || saveDraft.isPending || review.isPending} onClick={async () => { await save(); await act('submit') }}><Send size={16} />Илгээх</button>}</div>}</form>{canReview && selected?.report_type === 'monthly' && selected.status === 'submitted' && <div className="report-review-actions"><button onClick={() => act('request-revision')}><MessageSquareWarning />Засвар хүсэх</button><button className="approve" onClick={() => act('approve')}><Check />Батлах</button></div>}{isAdmin && selected?.report_type === 'monthly' && ['submitted', 'approved'].includes(selected.status) && <button className="secondary-action" onClick={() => act('reopen')}><RotateCcw size={16} />Засварт буцаах</button>}<section className="revision-history"><h3>Хувилбарын түүх</h3>{detail.data?.revisions?.map((revision: any) => <article key={revision.id}><span>{new Date(revision.created_at).toLocaleString('mn-MN')}</span><strong>{revision.status}</strong><p>{revision.markdown}</p></article>)}</section></></QueryRegion></motion.aside></motion.div>}</AnimatePresence>
    <AnimatePresence>{creating && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCreating(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">New report</span><h2>Тайлан үүсгэх</h2></div><button onClick={() => setCreating(false)} aria-label="Хаах"><X /></button></div><form className="sheet-form" onSubmit={async (event) => { event.preventDefault(); const result = await createReport.mutateAsync(createForm); setCreating(false); setSelectedId(result.id) }}><label>Тайлангийн төрөл<select value={createForm.report_type} onChange={(event) => setCreateForm({ ...createForm, report_type: event.target.value as typeof createForm.report_type })}><option value="daily">Өдрийн тайлан</option><option value="monthly">Сарын тайлан</option></select></label><label>Хугацаа<input type="date" required value={createForm.period_date} onChange={(event) => setCreateForm({ ...createForm, period_date: event.target.value })} /></label><button className="primary-action" disabled={createReport.isPending}>Үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence>
  </div>
}
