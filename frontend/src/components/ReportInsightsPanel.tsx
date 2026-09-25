import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import toast from 'react-hot-toast'
import { Bot, ChevronLeft, ChevronRight, Copy, Download, FileArchive, FileText, Send, Sparkles, X } from 'lucide-react'
import { DropdownSelect } from './DropdownSelect'
import { AiGeneratingAnimation } from './AiGeneratingAnimation'
import {
  downloadReportExport, ReportExportParams, ReportGroupBy, ReportScope, ReportSummaryResult, ReportType, saveBlob,
  useReportExportPreview, useReportInsightScope, useReportSummary,
} from '../api/reportInsights'

export type InsightPeriodPreset = 'week' | 'month' | 'quarter' | 'year' | 'custom'
type Tab = 'download' | 'summary' | 'chat'
type ChatTurn = { role: 'user' | 'assistant'; content: string; degraded?: boolean }

const PRESETS: Array<{ key: InsightPeriodPreset; label: string }> = [
  { key: 'week', label: 'Долоо хоног' },
  { key: 'month', label: 'Сар' },
  { key: 'quarter', label: 'Улирал' },
  { key: 'year', label: 'Жил' },
  { key: 'custom', label: 'Сонгох' },
]
const REPORT_TYPES: Array<{ key: ReportType; label: string }> = [
  { key: 'daily', label: 'Өдрийн' },
  { key: 'monthly', label: 'Сарын' },
  { key: 'next_month_plan', label: 'Дараа сарын төлөвлөгөө' },
]
const PROMPT_CHIPS = [
  'Энэ хугацааны ашиг, орлогын талаар тайланд юу дурдагдсан бэ?',
  'Зардлын гол эх үүсвэр ба бууруулах боломж юу вэ?',
  'ROI-г тооцох боломжтой өгөгдөл байна уу? Байгаа бол тооцоол.',
  'KPI гүйцэтгэлээр хамгийн сайн ба сул ажилтнууд хэн бэ?',
  'Бизнест хамгийн түрүүнд анхаарах 3 зүйл юу вэ?',
  'Эрсдэл, саад бэрхшээлүүдийг нэгтгэ.',
]

const pad = (value: number) => String(value).padStart(2, '0')
const isoDate = (value: Date) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`

/** Calendar-aligned bounds of the period containing `anchor` (weeks start on Monday). */
export function periodBounds(preset: Exclude<InsightPeriodPreset, 'custom'>, anchor: Date): { date_from: string; date_to: string } {
  const year = anchor.getFullYear()
  const month = anchor.getMonth()
  if (preset === 'week') {
    const start = new Date(year, month, anchor.getDate() - ((anchor.getDay() + 6) % 7))
    return { date_from: isoDate(start), date_to: isoDate(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6)) }
  }
  if (preset === 'month') return { date_from: isoDate(new Date(year, month, 1)), date_to: isoDate(new Date(year, month + 1, 0)) }
  if (preset === 'quarter') {
    const first = Math.floor(month / 3) * 3
    return { date_from: isoDate(new Date(year, first, 1)), date_to: isoDate(new Date(year, first + 3, 0)) }
  }
  return { date_from: `${year}-01-01`, date_to: `${year}-12-31` }
}

export function shiftAnchor(preset: Exclude<InsightPeriodPreset, 'custom'>, anchor: Date, step: number): Date {
  if (preset === 'week') return new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + 7 * step)
  if (preset === 'month') return new Date(anchor.getFullYear(), anchor.getMonth() + step, 1)
  if (preset === 'quarter') return new Date(anchor.getFullYear(), anchor.getMonth() + 3 * step, 1)
  return new Date(anchor.getFullYear() + step, 0, 1)
}

function periodTitle(preset: InsightPeriodPreset, period: { date_from: string; date_to: string }) {
  const [year, month] = period.date_from.split('-').map(Number)
  if (preset === 'month') return `${year} оны ${month}-р сар`
  if (preset === 'quarter') return `${year} оны ${Math.floor((month - 1) / 3) + 1}-р улирал`
  if (preset === 'year') return `${year} он`
  return `${period.date_from} – ${period.date_to}`
}

function errorDetail(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export function ReportInsightsPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('download')
  const [preset, setPreset] = useState<InsightPeriodPreset>('month')
  const [anchor, setAnchor] = useState(() => new Date())
  const [custom, setCustom] = useState(() => periodBounds('month', new Date()))
  const [scope, setScope] = useState<ReportScope>('all')
  const [employeeId, setEmployeeId] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [groupBy, setGroupBy] = useState<ReportGroupBy>('worker')
  const [types, setTypes] = useState<ReportType[]>(['daily', 'monthly', 'next_month_plan'])
  const [approvedOnly, setApprovedOnly] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [summary, setSummary] = useState<ReportSummaryResult>()
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [question, setQuestion] = useState('')
  const chatLogRef = useRef<HTMLDivElement>(null)

  const scopeOptions = useReportInsightScope()
  const summarize = useReportSummary()
  const chat = useReportSummary()
  const period = preset === 'custom' ? custom : periodBounds(preset, anchor)
  const validPeriod = Boolean(period.date_from && period.date_to && period.date_from <= period.date_to)
  const scopeReady = scope === 'all' || (scope === 'employee' ? Boolean(employeeId) : Boolean(departmentId))
  const exportParams: ReportExportParams = useMemo(() => ({
    ...period, group_by: groupBy, report_types: types, approved_only: approvedOnly,
    employee_ids: scope === 'employee' && employeeId ? [Number(employeeId)] : [],
    department_ids: scope === 'department' && departmentId ? [Number(departmentId)] : [],
  }), [period.date_from, period.date_to, groupBy, types, approvedOnly, scope, employeeId, departmentId]) // eslint-disable-line react-hooks/exhaustive-deps
  const preview = useReportExportPreview(exportParams, tab === 'download' && validPeriod && scopeReady && types.length > 0)
  const summaryInput = {
    ...period, scope, report_types: types,
    employee_id: scope === 'employee' ? Number(employeeId) || undefined : undefined,
    department_id: scope === 'department' ? Number(departmentId) || undefined : undefined,
  }
  const contextKey = `${period.date_from}|${period.date_to}|${scope}|${employeeId}|${departmentId}|${types.join(',')}`

  // A new period or scope is a new context: stale answers would be misleading.
  useEffect(() => { setSummary(undefined); setTurns([]) }, [contextKey])
  useEffect(() => { chatLogRef.current?.scrollTo({ top: chatLogRef.current.scrollHeight, behavior: 'smooth' }) }, [turns.length, chat.isPending])

  const employees = scopeOptions.data?.employees ?? []
  const departments = scopeOptions.data?.departments ?? []
  const toggleType = (key: ReportType) => setTypes((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])

  const download = async () => {
    setDownloading(true)
    try {
      const result = await downloadReportExport(exportParams)
      toast.success(result.count > 1 ? `${result.count} тайлан zip-ээр татагдлаа` : 'Тайлан татагдлаа')
    } catch (error: any) {
      // Blob responses carry JSON errors as Blob; read them for a useful message.
      let message = 'Татаж чадсангүй'
      const data = error?.response?.data
      if (data instanceof Blob) { try { message = JSON.parse(await data.text()).detail || message } catch { /* keep fallback */ } }
      toast.error(message)
    } finally { setDownloading(false) }
  }

  const runSummary = async () => {
    try { setSummary(await summarize.mutateAsync(summaryInput)) } catch (error) { toast.error(errorDetail(error, 'Хураангуй гаргаж чадсангүй')) }
  }

  const ask = async (text: string) => {
    const prompt = text.trim()
    if (!prompt || chat.isPending || !scopeReady || !validPeriod) return
    const history = turns.map(({ role, content }) => ({ role, content }))
    setTurns((current) => [...current, { role: 'user', content: prompt }])
    setQuestion('')
    try {
      const result = await chat.mutateAsync({ ...summaryInput, prompt, history })
      setTurns((current) => [...current, { role: 'assistant', content: result.answer, degraded: result.degraded }])
    } catch (error) {
      setTurns((current) => current.slice(0, -1))
      setQuestion(prompt)
      toast.error(errorDetail(error, 'OYUNS Agent хариулж чадсангүй'))
    }
  }

  const saveMarkdown = (content: string, suffix: string) => saveBlob(new Blob([content], { type: 'text/markdown;charset=utf-8' }), `oyuns_${suffix}_${period.date_from}_${period.date_to}.md`)
  const copy = async (content: string) => { try { await navigator.clipboard.writeText(content); toast.success('Хуулагдлаа') } catch { toast.error('Хуулж чадсангүй') } }

  return <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={onClose}>
    <motion.aside className="detail-sheet report-insights-sheet" role="dialog" aria-modal="true" aria-labelledby="report-insights-title" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}>
      <div className="sheet-header"><div><span className="eyebrow">REPORT INSIGHTS</span><h2 id="report-insights-title">Тайлан татах ба хураангуй</h2></div><button onClick={onClose} aria-label="Хаах"><X /></button></div>

      <section className="report-insights-controls" aria-label="Хугацаа ба хамрах хүрээ">
        <div className="segmented-control report-insights-presets" role="group" aria-label="Хугацаа">
          {PRESETS.map((item) => <button type="button" key={item.key} className={preset === item.key ? 'active' : ''} aria-pressed={preset === item.key} onClick={() => { setPreset(item.key); if (item.key !== 'custom') setAnchor(new Date()) }}>{item.label}</button>)}
        </div>
        {preset === 'custom'
          ? <div className="report-insights-custom"><label>Эхлэх<input type="date" value={custom.date_from} max={custom.date_to} onChange={(event) => setCustom({ ...custom, date_from: event.target.value })} /></label><label>Дуусах<input type="date" value={custom.date_to} min={custom.date_from} onChange={(event) => setCustom({ ...custom, date_to: event.target.value })} /></label></div>
          : <div className="report-insights-stepper"><button type="button" onClick={() => setAnchor(shiftAnchor(preset, anchor, -1))} aria-label="Өмнөх хугацаа"><ChevronLeft size={16} /></button><div><strong>{periodTitle(preset, period)}</strong><small>{period.date_from} – {period.date_to}</small></div><button type="button" onClick={() => setAnchor(shiftAnchor(preset, anchor, 1))} aria-label="Дараах хугацаа"><ChevronRight size={16} /></button></div>}

        <div className="report-insights-scope">
          <DropdownSelect ariaLabel="Хамрах хүрээ" value={scope} onChange={(value) => setScope(value as ReportScope)} options={[{ value: 'all', label: 'Бүх ажилтан' }, { value: 'employee', label: 'Нэг ажилтан' }, { value: 'department', label: 'Хэлтэс' }]} />
          {scope === 'employee' && <DropdownSelect ariaLabel="Ажилтан сонгох" value={employeeId} onChange={setEmployeeId} options={[{ value: '', label: 'Ажилтан сонгох…', disabled: true }, ...employees.map((item) => ({ value: String(item.id), label: `${item.name}${item.department ? ` · ${item.department}` : ''}${item.is_active ? '' : ' (идэвхгүй)'}` }))]} />}
          {scope === 'department' && <DropdownSelect ariaLabel="Хэлтэс сонгох" value={departmentId} onChange={setDepartmentId} options={[{ value: '', label: departments.length ? 'Хэлтэс сонгох…' : 'Хэлтэс бүртгэгдээгүй', disabled: true }, ...departments.map((item) => ({ value: String(item.id), label: item.name }))]} />}
        </div>
        <div className="report-insights-types" role="group" aria-label="Тайлангийн төрөл">
          {REPORT_TYPES.map((item) => <label key={item.key} className={types.includes(item.key) ? 'active' : ''}><input type="checkbox" checked={types.includes(item.key)} onChange={() => toggleType(item.key)} />{item.label}</label>)}
        </div>
      </section>

      <div className="segmented-control report-insights-tabs" role="tablist" aria-label="Үйлдэл">
        <button type="button" role="tab" aria-selected={tab === 'download'} className={tab === 'download' ? 'active' : ''} onClick={() => setTab('download')}><FileArchive size={15} />Татах</button>
        <button type="button" role="tab" aria-selected={tab === 'summary'} className={tab === 'summary' ? 'active' : ''} onClick={() => setTab('summary')}><Sparkles size={15} />Хураангуй</button>
        <button type="button" role="tab" aria-selected={tab === 'chat'} className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')}><Bot size={15} />OYUNS чат</button>
      </div>

      {!validPeriod && <p className="report-insights-note error">Эхлэх огноо дуусах огнооноос хойш байж болохгүй.</p>}
      {validPeriod && !scopeReady && <p className="report-insights-note">{scope === 'employee' ? 'Ажилтнаа сонгоно уу.' : 'Хэлтсээ сонгоно уу.'}</p>}

      {tab === 'download' && <section className="report-insights-body" role="tabpanel" aria-label="Татах">
        <div className="report-insights-row">
          <span>Хавтас</span>
          <div className="segmented-control" role="group" aria-label="Хавтасны бүтэц"><button type="button" className={groupBy === 'worker' ? 'active' : ''} aria-pressed={groupBy === 'worker'} onClick={() => setGroupBy('worker')}>Ажилтнаар</button><button type="button" className={groupBy === 'department' ? 'active' : ''} aria-pressed={groupBy === 'department'} onClick={() => setGroupBy('department')}>Хэлтсээр</button></div>
        </div>
        <label className="report-insights-toggle"><input type="checkbox" checked={approvedOnly} onChange={(event) => setApprovedOnly(event.target.checked)} />Зөвхөн батлагдсан тайлан</label>
        <div className="report-insights-preview" aria-live="polite">
          {preview.isFetching && !preview.data ? <span>Тооцоолж байна…</span> : preview.data && <>
            <strong>{preview.data.report_count} тайлан{preview.data.format === 'zip' ? ' · ZIP' : preview.data.format === 'md' ? ' · Markdown файл' : ''}</strong>
            {preview.data.groups.length > 0 && <ul>{preview.data.groups.slice(0, 12).map((group) => <li key={group.name}><FileText size={13} />{group.name}<span>{group.count}</span></li>)}{preview.data.groups.length > 12 && <li className="more">+{preview.data.groups.length - 12} хавтас</li>}</ul>}
          </>}
        </div>
        <button type="button" className="primary-action" disabled={downloading || !validPeriod || !scopeReady || !types.length || !preview.data?.report_count} onClick={download}><Download size={16} />{downloading ? 'Бэлтгэж байна…' : preview.data?.format === 'md' ? 'Тайлан татах' : 'ZIP татах'}</button>
      </section>}

      {tab === 'summary' && <section className="report-insights-body" role="tabpanel" aria-label="Хураангуй">
        <p className="report-insights-note">OYUNS Agent сонгосон хугацааны тайлан болон KPI-г (даалгавар, ажилласан цаг, тайлангийн идэвх) нэгтгэнэ.</p>
        <button type="button" className="primary-action" disabled={summarize.isPending || !validPeriod || !scopeReady || !types.length} onClick={runSummary}><Sparkles size={16} />{summary ? 'Дахин гаргах' : 'Хураангуй гаргах'}</button>
        {summarize.isPending && <AiGeneratingAnimation className="report-insights-generating" />}
        {summary && !summarize.isPending && <article className="report-insights-answer">
          <div className="report-insights-kpis">
            <span><strong>{summary.report_count}</strong>тайлан</span>
            <span><strong>{summary.kpis.task_completion_rate ?? 0}%</strong>даалгавар дууссан</span>
            <span><strong>{summary.kpis.tasks_overdue_open ?? 0}</strong>хэтэрсэн</span>
            <span><strong>{((summary.kpis.worked_minutes ?? 0) / 60).toFixed(0)}ц</strong>ажилласан</span>
          </div>
          {summary.degraded && <p className="report-insights-note">AI түр ашиглах боломжгүй тул автомат нэгтгэлийг харуулав.</p>}
          <div className="report-insights-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{summary.answer}</ReactMarkdown></div>
          <footer><button type="button" className="secondary-action" onClick={() => copy(summary.answer)}><Copy size={15} />Хуулах</button><button type="button" className="secondary-action" onClick={() => saveMarkdown(summary.answer, 'summary')}><Download size={15} />.md татах</button></footer>
        </article>}
      </section>}

      {tab === 'chat' && <section className="report-insights-body report-insights-chat" role="tabpanel" aria-label="OYUNS чат">
        <div ref={chatLogRef} className="report-insights-chat-log" role="log" aria-live="polite">
          {!turns.length && <div className="report-insights-chat-empty"><Bot /><strong>Тайлангаас асуух</strong><span>Ашиг, зардал, ROI, KPI эсвэл бизнест анхаарах зүйлсийн талаар асуугаарай. Хариулт зөвхөн сонгосон хугацаа ба хүрээний өгөгдөлд тулгуурлана.</span></div>}
          {turns.map((turn, index) => <div key={index} className={`report-insights-turn ${turn.role}`}>
            {turn.role === 'assistant' ? <><div className="report-insights-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown></div>{turn.degraded && <small>AI түр ашиглах боломжгүй — автомат нэгтгэл</small>}<footer><button type="button" onClick={() => copy(turn.content)} aria-label="Хуулах"><Copy size={13} /></button><button type="button" onClick={() => saveMarkdown(turn.content, 'answer')} aria-label=".md татах"><Download size={13} /></button></footer></> : <p>{turn.content}</p>}
          </div>)}
          {chat.isPending && <AiGeneratingAnimation className="report-insights-generating" />}
        </div>
        <div className="report-insights-chips">{PROMPT_CHIPS.map((chip) => <button type="button" key={chip} disabled={chat.isPending || !scopeReady || !validPeriod} onClick={() => ask(chip)}>{chip}</button>)}</div>
        <form className="report-insights-compose" onSubmit={(event) => { event.preventDefault(); void ask(question) }}>
          <textarea rows={2} maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void ask(question) } }} placeholder="Жишээ: Борлуулалтын хэлтсийн зардал, орлогын талаар тайланд юу бичигдсэн бэ?" aria-label="OYUNS Agent-д асуулт" />
          <button type="submit" className="chat-send-button" disabled={!question.trim() || chat.isPending || !scopeReady || !validPeriod} aria-label="Илгээх"><Send /></button>
        </form>
      </section>}
    </motion.aside>
  </motion.div>
}
