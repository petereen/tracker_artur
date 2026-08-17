import { useEffect, useRef, useState, useTransition } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Download, FileCheck2, Paperclip, Plus, RotateCcw, Save, Send, Trash2, X } from 'lucide-react'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { downloadAttachment, useAddReportComment, useAttachments, useCreateReport, useDeleteAttachment, useEnterpriseReports, useReportDetail, useReportReview, useResolveReportComment, useSaveReportDraft, useUploadAttachment } from '../api/enterprise'
import { PeriodPreset, periodFromPreset, TimePeriodFilter } from '../components/TimePeriodFilter'
import { QueryRegion, Skeleton, TableSkeleton } from '../components/Loading'
import { DropdownSelect } from '../components/DropdownSelect'

function ReportReviewWorkspace({ reportId, detail, canReview }: { reportId: number; detail: any; canReview: boolean }) {
  const revisions = detail?.revisions ?? []; const [leftId, setLeftId] = useState<number>(); const [rightId, setRightId] = useState<number>(); const [comment, setComment] = useState(''); const [progress, setProgress] = useState(0); const selectionRef = useRef<HTMLTextAreaElement>(null)
  const addComment = useAddReportComment(); const resolve = useResolveReportComment(); const files = useAttachments('report', reportId); const upload = useUploadAttachment(); const remove = useDeleteAttachment()
  useEffect(() => { setRightId(revisions[0]?.id); setLeftId(revisions[1]?.id ?? revisions[0]?.id) }, [reportId, revisions.length])
  const left = revisions.find((item: any) => item.id === leftId); const right = revisions.find((item: any) => item.id === rightId)
  const submitComment = () => { if (!comment.trim() || !right) return; const field = selectionRef.current; const start = field?.selectionStart ?? 0; const end = field?.selectionEnd ?? start; addComment.mutate({ reportId, revision_id: right.id, text: comment.trim(), range_metadata: end > start ? { start, end, quote: right.markdown.slice(start, end) } : undefined }); setComment('') }
  return <section className="report-collaboration"><h3>Хувилбар харьцуулах</h3><div className="revision-selectors"><DropdownSelect ariaLabel="Зүүн хувилбар" value={String(leftId ?? '')} onChange={(value) => setLeftId(Number(value))} options={revisions.map((item: any) => ({ value: String(item.id), label: `#${item.id} · ${item.status}` }))} /><DropdownSelect ariaLabel="Баруун хувилбар" value={String(rightId ?? '')} onChange={(value) => setRightId(Number(value))} options={revisions.map((item: any) => ({ value: String(item.id), label: `#${item.id} · ${item.status}` }))} /></div><div className="revision-compare"><article><ReactMarkdown remarkPlugins={[remarkGfm]}>{left?.markdown ?? ''}</ReactMarkdown></article><article><ReactMarkdown remarkPlugins={[remarkGfm]}>{right?.markdown ?? ''}</ReactMarkdown></article></div>
    {canReview && right && <div className="inline-review"><label>Сэтгэгдэл холбох текстээ доороос сонгоно уу<textarea ref={selectionRef} readOnly value={right.markdown} rows={8} /></label><div className="inline-compose"><input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Засварын тайлбар" /><button type="button" onClick={submitComment}>Нэмэх</button></div></div>}
    <div className="report-comments">{detail?.comments?.map((item: any) => <article className={item.is_resolved ? 'resolved' : ''} key={item.id}>{item.range_metadata?.quote && <blockquote>{item.range_metadata.quote}</blockquote>}<p>{item.text}</p><button type="button" onClick={() => resolve.mutate({ reportId, id: item.id, is_resolved: !item.is_resolved })}>{item.is_resolved ? 'Дахин нээх' : 'Шийдсэн'}</button></article>)}</div>
    <div className="report-files"><label className="file-upload"><Paperclip size={15} />Хавсралт<input type="file" onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate({ objectType: 'report', objectId: reportId, file, onProgress: setProgress }) }} /></label>{upload.isPending && <progress value={progress} max="100" />}{files.data?.map((file) => <article key={file.id}><span>{file.filename} · {file.scan_status}</span><button type="button" onClick={() => downloadAttachment(file.id, file.filename)}><Download size={14} /></button><button type="button" onClick={() => remove.mutate({ id: file.id, objectType: 'report', objectId: reportId })}><Trash2 size={14} /></button></article>)}</div>
  </section>
}

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
  const act = async (action: 'approve' | 'submit' | 'reopen') => {
    if (!selectedId) return
    await review.mutateAsync({ id: selectedId, action })
    setSelectedId(undefined)
  }

  return <div>
    <div className="workspace-toolbar reports-toolbar"><div className="toolbar-cluster report-toolbar"><TimePeriodFilter preset={periodPreset} period={period} onChange={(nextPreset, nextPeriod) => startTransition(() => { setPeriodPreset(nextPreset); setPeriod(nextPeriod) })} /><div className="report-summary"><span><strong>{reports.data?.filter((report) => report.report_type === 'monthly' && report.status === 'submitted').length ?? 0}</strong> хүлээгдэж буй</span><span><strong>{reports.data?.filter((report) => report.status === 'approved').length ?? 0}</strong> батлагдсан</span></div>{!canReview && <button className="primary-action compact" onClick={() => setCreating(true)}><Plus size={16} />Тайлан үүсгэх</button>}</div></div>
    <QueryRegion pending={reports.isLoading || reports.isFetching} skeleton={<section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header><TableSkeleton rows={6} /></section>}><section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header>{reports.data?.filter((report) => report.report_type !== 'next_month_plan').map((report) => <article key={report.id}><button className="report-main" onClick={() => setSelectedId(report.id)}><div className="report-icon"><FileCheck2 /></div><div><strong>{canReview ? report.employee_name : (report.title || 'Миний тайлан')}</strong><span>{report.report_type.replaceAll('_', ' ')}</span></div></button><time>{report.period_date}</time><span className={`status-pill ${report.status}`}>{report.status}</span><div className="row-actions"><button onClick={() => setSelectedId(report.id)}>Нээх</button>{canReview && report.report_type === 'monthly' && report.status === 'submitted' && <button className="approve" onClick={() => review.mutate({ id: report.id, action: 'approve' })}><Check />Батлах</button>}</div></article>)}</section></QueryRegion>
    <AnimatePresence>{selectedId && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setSelectedId(undefined)}><motion.aside className="detail-sheet report-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Report #{selectedId}</span><h2>{selected?.employee_name}</h2></div><button onClick={() => setSelectedId(undefined)} aria-label="Хаах"><X /></button></div><QueryRegion pending={detail.isLoading || detail.isFetching} skeleton={<Skeleton variant="sheet" count={6} />}><><div className="task-detail-meta"><span>{selected?.report_type}</span><span>{selected?.period_date}</span><span>{selected?.status}</span><span>v{detail.data?.version}</span></div><form className="sheet-form" onSubmit={(event) => { event.preventDefault(); save() }}><label>Гарчиг<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} disabled={!editable} /></label><label>Тайлан (Markdown)<textarea rows={16} value={draft.markdown} onChange={(event) => setDraft({ ...draft, markdown: event.target.value })} disabled={!editable} /></label>{editable && <div className="report-editor-actions"><button className="secondary-action" disabled={!draft.markdown.trim() || saveDraft.isPending}><Save size={16} />Хадгалах</button>{selected?.status !== 'submitted' && <button type="button" className="primary-action" disabled={!draft.markdown.trim() || saveDraft.isPending || review.isPending} onClick={async () => { await save(); await act('submit') }}><Send size={16} />Илгээх</button>}</div>}</form>{canReview && selected?.report_type === 'monthly' && selected.status === 'submitted' && <div className="report-review-actions"><button className="approve" onClick={() => act('approve')}><Check />Батлах</button></div>}{isAdmin && selected?.report_type === 'monthly' && ['submitted', 'approved'].includes(selected.status) && <button className="secondary-action" onClick={() => act('reopen')}><RotateCcw size={16} />Засварт буцаах</button>}<ReportReviewWorkspace reportId={selectedId} detail={detail.data} canReview={canReview} /></></QueryRegion></motion.aside></motion.div>}</AnimatePresence>
    <AnimatePresence>{creating && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCreating(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">New report</span><h2>Тайлан үүсгэх</h2></div><button onClick={() => setCreating(false)} aria-label="Хаах"><X /></button></div><form className="sheet-form" onSubmit={async (event) => { event.preventDefault(); const result = await createReport.mutateAsync(createForm); setCreating(false); setSelectedId(result.id) }}><label>Тайлангийн төрөл<select value={createForm.report_type} onChange={(event) => setCreateForm({ ...createForm, report_type: event.target.value as typeof createForm.report_type })}><option value="daily">Өдрийн тайлан</option><option value="monthly">Сарын тайлан</option></select></label><label>Хугацаа<input type="date" required value={createForm.period_date} onChange={(event) => setCreateForm({ ...createForm, period_date: event.target.value })} /></label><button className="primary-action" disabled={createReport.isPending}>Үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence>
  </div>
}
