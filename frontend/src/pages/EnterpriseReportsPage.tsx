import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, FileCheck2, MessageSquareWarning, RotateCcw, Save, Send, X } from 'lucide-react'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { useEnterpriseReports, useReportDetail, useReportReview, useSaveReportDraft } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'

export function EnterpriseReportsPage() {
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | 'custom'>('month')
  const [period, setPeriod] = useState(() => periodFromPreset('month'))
  const [selectedId, setSelectedId] = useState<number>()
  const reports = useEnterpriseReports(undefined, period)
  const detail = useReportDetail(selectedId)
  const saveDraft = useSaveReportDraft()
  const review = useReportReview()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canReview = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const isAdmin = roles.includes('admin')
  const selected = reports.data?.find((report) => report.id === selectedId)
  const [draft, setDraft] = useState({ title: '', markdown: '' })

  useEffect(() => {
    if (!detail.data) return
    setDraft({ title: detail.data.title ?? '', markdown: detail.data.revisions?.[0]?.markdown ?? '' })
  }, [detail.data])

  const editable = Boolean(selected && !canReview && ['awaiting', 'draft', 'editing', 'revision_requested'].includes(selected.status))
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
    <div className="view-toolbar"><div><h2>{canReview ? 'Багийн тайлан' : 'Миний тайлан'}</h2><p>{canReview ? 'Ажилтны илгээсэн тайланг хянаж, засвар хүсэх эсвэл батална.' : 'Ноорог хадгалж, бэлэн болсон үед нэг удаа илгээнэ.'}</p></div><div className="toolbar-cluster"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) }} /><div className="report-summary"><span><strong>{reports.data?.filter((report) => report.status === 'submitted').length ?? 0}</strong> хүлээгдэж буй</span><span><strong>{reports.data?.filter((report) => report.status === 'approved').length ?? 0}</strong> батлагдсан</span></div></div></div>
    <section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header>{reports.data?.map((report) => <article key={report.id}><button className="report-main" onClick={() => setSelectedId(report.id)}><div className="report-icon"><FileCheck2 /></div><div><strong>{canReview ? report.employee_name : (report.title || 'Миний тайлан')}</strong><span>{report.report_type.replaceAll('_', ' ')}</span></div></button><time>{report.period_date}</time><span className={`status-pill ${report.status}`}>{report.status}</span><div className="row-actions"><button onClick={() => setSelectedId(report.id)}>Нээх</button>{canReview && report.status === 'submitted' && <><button onClick={() => review.mutate({ id: report.id, action: 'request-revision' })}><MessageSquareWarning />Засвар</button><button className="approve" onClick={() => review.mutate({ id: report.id, action: 'approve' })}><Check />Батлах</button></>}{isAdmin && ['submitted', 'approved'].includes(report.status) && <button onClick={() => review.mutate({ id: report.id, action: 'reopen' })}><RotateCcw />Буцаах</button>}</div></article>)}</section>
    <AnimatePresence>{selectedId && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setSelectedId(undefined)}><motion.aside className="detail-sheet report-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Report #{selectedId}</span><h2>{selected?.employee_name}</h2></div><button onClick={() => setSelectedId(undefined)} aria-label="Хаах"><X /></button></div>{detail.isLoading ? <p>Ачаалж байна…</p> : <><div className="task-detail-meta"><span>{selected?.report_type}</span><span>{selected?.period_date}</span><span>{selected?.status}</span><span>v{detail.data?.version}</span></div><form className="sheet-form" onSubmit={(event) => { event.preventDefault(); save() }}><label>Гарчиг<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} disabled={!editable} /></label><label>Тайлан (Markdown)<textarea rows={16} value={draft.markdown} onChange={(event) => setDraft({ ...draft, markdown: event.target.value })} disabled={!editable} /></label>{editable && <div className="report-editor-actions"><button className="secondary-action" disabled={!draft.markdown.trim() || saveDraft.isPending}><Save size={16} />Ноорог хадгалах</button><button type="button" className="primary-action" disabled={!draft.markdown.trim() || saveDraft.isPending || review.isPending} onClick={async () => { await save(); await act('submit') }}><Send size={16} />Илгээх</button></div>}</form>{canReview && selected?.status === 'submitted' && <div className="report-review-actions"><button onClick={() => act('request-revision')}><MessageSquareWarning />Засвар хүсэх</button><button className="approve" onClick={() => act('approve')}><Check />Батлах</button></div>}{isAdmin && selected && ['submitted', 'approved'].includes(selected.status) && <button className="secondary-action" onClick={() => act('reopen')}><RotateCcw size={16} />Засварт буцаах</button>}<section className="revision-history"><h3>Хувилбарын түүх</h3>{detail.data?.revisions?.map((revision: any) => <article key={revision.id}><span>{new Date(revision.created_at).toLocaleString('mn-MN')}</span><strong>{revision.status}</strong><p>{revision.markdown}</p></article>)}</section></>}</motion.aside></motion.div>}</AnimatePresence>
  </div>
}
