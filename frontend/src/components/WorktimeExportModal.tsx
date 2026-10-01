import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, FileSpreadsheet, FileText, LoaderCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { Modal } from './ui'
import { downloadWorktimeReport, useWorktimeReportOptions, useWorktimeReportPreview, type WorktimeReportQuery } from '../api/enterprise'
import i18n from '../i18n'

export type WorktimePreset = 'month' | 'five_to_fifteen' | 'fifteen_to_five' | 'custom'

function dateValue(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

function monthDate(now: Date, monthOffset: number, day: number) {
  return new Date(now.getFullYear(), now.getMonth() + monthOffset, day)
}

export function presetRange(preset: WorktimePreset, now = new Date()): { from: string; to: string } {
  if (preset === 'month') {
    return { from: dateValue(monthDate(now, 0, 1)), to: dateValue(monthDate(now, 1, 0)) }
  }
  if (preset === 'five_to_fifteen') {
    const offset = now.getDate() < 5 ? -1 : 0
    return { from: dateValue(monthDate(now, offset, 5)), to: dateValue(monthDate(now, offset, 15)) }
  }
  if (preset === 'fifteen_to_five') {
    const offset = now.getDate() >= 15 ? 0 : -1
    return { from: dateValue(monthDate(now, offset, 15)), to: dateValue(monthDate(now, offset + 1, 5)) }
  }
  return { from: dateValue(now), to: dateValue(now) }
}

function formatHours(minutes: number | null | undefined) {
  if (minutes == null) return '—'
  return `${(minutes / 60).toFixed(2)}${i18n.t('worktime.unit.hour')}`
}

function formatClock(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

export function WorktimeExportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])
  const initial = presetRange('month')
  const [preset, setPreset] = useState<WorktimePreset>('month')
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const [department, setDepartment] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [format, setFormat] = useState<'csv' | 'xlsx'>('csv')
  const [page, setPage] = useState(1)
  const [downloading, setDownloading] = useState(false)
  const options = useWorktimeReportOptions()
  const validRange = Boolean(from && to && from <= to)
  const query = useMemo<WorktimeReportQuery>(() => ({
    from,
    to,
    ...(department ? { department } : {}),
    ...(workerId ? { worker_id: Number(workerId) } : {}),
    page,
    page_size: 50,
  }), [department, from, page, to, workerId])
  const preview = useWorktimeReportPreview(query, validRange)
  const availableWorkers = useMemo(() => (options.data?.workers ?? []).filter((worker) => !department || worker.department === department), [department, options.data?.workers])
  const pageCount = preview.data ? Math.max(1, Math.ceil(preview.data.total / preview.data.page_size)) : 1

  const applyPreset = (value: WorktimePreset) => {
    setPreset(value)
    if (value !== 'custom') {
      const range = presetRange(value)
      setFrom(range.from)
      setTo(range.to)
    }
    setPage(1)
  }

  const editDate = (setter: (value: string) => void, value: string) => {
    setPreset('custom')
    setter(value)
    setPage(1)
  }

  const chooseDepartment = (value: string) => {
    setDepartment(value)
    if (workerId && !(options.data?.workers ?? []).some((worker) => worker.id === Number(workerId) && worker.department === value)) setWorkerId('')
    setPage(1)
  }

  const download = async () => {
    if (!validRange || downloading) return
    setDownloading(true)
    try {
      await downloadWorktimeReport({ ...query, page: undefined, page_size: undefined }, format)
      toast.success(t('worktime.export.done'))
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || error?.message || t('worktime.export.failed'))
    } finally {
      setDownloading(false)
    }
  }

  return <Modal title={t('worktime.export.title')} onClose={onClose} className="worktime-export-modal">
    <div className="worktime-export-config">
      <label><span>{t('worktime.export.preset')}</span><select value={preset} onChange={(event) => applyPreset(event.target.value as WorktimePreset)}><option value="month">{t('worktime.export.thisMonth')}</option><option value="five_to_fifteen">{t('worktime.export.range5to15')}</option><option value="fifteen_to_five">{t('worktime.export.range15to5')}</option><option value="custom">{t('worktime.export.custom')}</option></select></label>
      <label><span>{t('worktime.export.from')}</span><input type="date" value={from} onChange={(event) => editDate(setFrom, event.target.value)} /></label>
      <label><span>{t('worktime.export.to')}</span><input type="date" value={to} onChange={(event) => editDate(setTo, event.target.value)} /></label>
      <label><span>{t('worktime.export.department')}</span><select value={department} onChange={(event) => chooseDepartment(event.target.value)}><option value="">{t('worktime.export.allDepartments')}</option>{options.data?.departments.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label><span>{t('worktime.export.worker')}</span><select value={workerId} onChange={(event) => { setWorkerId(event.target.value); setPage(1) }}><option value="">{t('worktime.export.allWorkers')}</option>{availableWorkers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>
      <fieldset><legend>{t('worktime.export.format')}</legend><div className="worktime-format-options"><label className={format === 'csv' ? 'selected' : ''}><input type="radio" name="worktime-format" checked={format === 'csv'} onChange={() => setFormat('csv')} /><FileText size={15} />CSV</label><label className={format === 'xlsx' ? 'selected' : ''}><input type="radio" name="worktime-format" checked={format === 'xlsx'} onChange={() => setFormat('xlsx')} /><FileSpreadsheet size={15} />{t('worktime.export.excel')}</label></div></fieldset>
    </div>
    {!validRange && <p className="worktime-export-error" role="alert">{t('worktime.export.rangeInvalid')}</p>}
    {validRange && <>
      <section className="worktime-export-summary" aria-label={t('worktime.export.summary')}>
        <article><span>{t('worktime.export.totalHours')}</span><strong>{formatHours(preview.data?.summary.total_minutes)}</strong></article>
        <article><span>{t('worktime.export.avgPerWorker')}</span><strong>{formatHours(preview.data?.summary.average_minutes_per_worker)}</strong></article>
        <article><span>{t('worktime.export.avgPerDay')}</span><strong>{formatHours(preview.data?.summary.average_daily_minutes_per_worker)}</strong></article>
        <article><span>{t('worktime.export.avgPerWeek')}</span><strong>{formatHours(preview.data?.summary.average_weekly_minutes_per_worker)}</strong></article>
        <article><span>{t('worktime.export.activeWorkers')}</span><strong>{preview.data?.summary.active_worker_count ?? '—'}</strong></article>
      </section>
      <div className="worktime-export-table-wrap">
        {preview.isLoading && <p className="worktime-export-state"><LoaderCircle className="spin" size={18} />{t('worktime.export.previewLoading')}</p>}
        {preview.isError && <p className="worktime-export-state error" role="alert">{t('worktime.export.previewFailed')}</p>}
        {!preview.isLoading && !preview.isError && preview.data?.items.length === 0 && <p className="worktime-export-state">{t('worktime.export.empty')}</p>}
        {!!preview.data?.items.length && <table><thead><tr><th>{t('worktime.export.worker')}</th><th>{t('worktime.export.department')}</th><th>{t('worktime.export.date')}</th><th>{t('worktime.export.clockIn')}</th><th>{t('worktime.export.clockOut')}</th><th>{t('worktime.export.shiftHours')}</th></tr></thead><tbody>{preview.data.items.map((row) => <tr key={`${row.worker_id}-${row.date}-${row.clock_in}`}><td><strong>{row.worker_name}</strong><small>#{row.worker_id}</small></td><td>{row.department || '—'}</td><td>{row.date}</td><td>{formatClock(row.clock_in)}</td><td>{row.status === 'in_progress' ? 'In progress' : formatClock(row.clock_out)}</td><td>{formatHours(row.total_minutes)}</td></tr>)}</tbody></table>}
      </div>
      {preview.data && preview.data.total > 0 && <div className="worktime-export-pagination"><span>{t('worktime.export.rowsPage', { total: preview.data.total, page, pages: pageCount })}</span><div><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}><ChevronLeft size={15} />{t('worktime.export.prev')}</button><button type="button" onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={page >= pageCount}>{t('worktime.export.next')}<ChevronRight size={15} /></button></div></div>}
    </>}
    <footer className="worktime-export-footer"><button type="button" className="secondary-action" onClick={onClose}>{t('worktime.export.cancel')}</button><button type="button" className="primary-action" onClick={() => void download()} disabled={!validRange || downloading}><Download size={16} />{downloading ? t('worktime.export.preparing') : 'Download Report'}</button></footer>
  </Modal>
}
