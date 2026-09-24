import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Check, CircleAlert, LockKeyhole, Plus, RefreshCw, WalletCards } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useApproveMonthlyPayrollRow, useApproveMonthlyPayrollRun, useCalculateMonthlyPayrollRun, useCloseMonthlyPayrollMonth,
  useCreateMonthlyPayrollMonth, useCreateMonthlyPayrollRun, useMarkMonthlyPayrollPaid,
  useMonthlyPayrollArchives, useMonthlyPayrollMonth, useMonthlyPayrollMonths,
  useMonthlyPayrollRun, usePayrollCapabilities, useRefreshMonthlyPayrollAdvances,
  useSaveMonthlyPayrollRow, useUnlockMonthlyPayrollMonth, downloadMonthlyPayrollExport,
  useMonthlyPayrollCalendar, useSetMonthlyPayrollCalendarDay, useMonthlyPayrollSettings, useSaveMonthlyPayrollSettings,
  useMonthlyPayrollClosingStats,
  useMonthlyPayrollReport, downloadMonthlyPayrollReport,
  useMonthlyPayrollAdvanceDates, useFlagMonthlyPayrollRow, useUnflagMonthlyPayrollRow,
  useRefreshMonthlyPayrollTime, downloadMonthlyPayrollArchiveExport,
  useHRDepartments,
  useERPAccountOptions,
  useRevertMonthlyPayrollRowOverrides,
  useOverrideMonthlyPayrollComputedCell, useRevertMonthlyPayrollComputedCell,
  useSyncMonthlyPayrollWorkers,
  useImportMonthlyPayrollInputs, downloadMonthlyPayrollInputTemplate,
  useWorkerDirectory, useMonthlyPayrollWorkerHistory, downloadMonthlyPayrollWorkerHistory,
  useMonthlyPayrollRuleSets, useMonthlyPayrollRuleTemplate, useCreateMonthlyPayrollRuleDraft,
  useUpdateMonthlyPayrollRuleDraft, useValidateMonthlyPayrollRuleDraft, usePublishMonthlyPayrollRuleDraft,
} from '../api/enterprise'
import type { MonthlyPayrollCompanySettings, MonthlyPayrollReportKind, MonthlyPayrollRuleSet } from '../api/enterprise'

function requestError(error: any) { const detail = error?.response?.data?.detail; return String(detail?.message || detail || 'Үйлдэл амжилтгүй боллоо.') }
const current = new Date()
const dateFor = (year: number, month: number, day: number) => `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
const formatPayrollMoney = (value: string) => new Intl.NumberFormat('mn-MN', { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
function MonthlyShell({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return <main className="payroll-v2-shell"><div className="payroll-v2-content"><div className="payroll-compact-toolbar"><nav className="payroll-compact-nav" aria-label="Цалингийн навигаци"><Link to="/erp/payroll">Тойм</Link><Link className="active" to="/erp/payroll/monthly">Сарын цалин</Link><Link to="/erp/payroll/monthly/reports">Тайлан</Link><Link to="/hr?tab=payroll">HR тохиргоо</Link></nav>{actions ? <div className="payroll-compact-actions">{actions}</div> : null}</div>{children}</div></main>
}

export function MonthlyPayrollWorkspace({ detail = false, reports = false }: { detail?: boolean; reports?: boolean }) {
  const { runId } = useParams()
  if (reports) return <MonthlyReports />
  return detail && runId ? <MonthlyRunDetail runId={Number(runId)} /> : <MonthlyMonthBoard />
}

export function MonthlyPayrollDashboard() {
  const months = useMonthlyPayrollMonths()
  const navigate = useNavigate()
  const year = current.getFullYear()
  const monthNumber = current.getMonth() + 1
  const month = months.data?.find((item) => item.year === year && item.month === monthNumber)
  const stats = useMonthlyPayrollClosingStats(month?.id, Boolean(month))
  const totals = stats.data?.totals || {}
  const runs = month?.runs || []
  return <MonthlyShell actions={<button className="payroll-v2-button primary" onClick={() => navigate('/erp/payroll/monthly')}><Plus size={15} />Сарын бодолт эхлүүлэх</button>}>
    <header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">ЦАЛИН · ТОЙМ</span><h1>{new Intl.DateTimeFormat('mn-MN', { month: 'long', year: 'numeric' }).format(new Date(year, monthNumber - 1, 1))}</h1><p>Урьдчилгаа, сүүл цалин болон сарын хаалтын явц.</p></div></header>
    <section className="payroll-v2-metric-grid compact">
      <article><span>Нийт цалин</span><strong>{formatPayrollMoney(String(totals.gross || 0))}</strong></article>
      <article><span>Ажилтны НДШ</span><strong>{formatPayrollMoney(String(totals.employee_shi || 0))}</strong></article>
      <article><span>ХХОАТ</span><strong>{formatPayrollMoney(String(totals.pit || 0))}</strong></article>
      <article><span>Байгууллагын НДШ</span><strong>{formatPayrollMoney(String(totals.employer_shi || 0))}</strong></article>
      <article><span>Урьдчилгаа</span><strong>{formatPayrollMoney(String(totals.advance_total || 0))}</strong></article>
      <article><span>Сүүл цалин</span><strong>{formatPayrollMoney(String(totals.net_pay || 0))}</strong></article>
    </section>
    <section className="payroll-v2-section">
      <div className="payroll-v2-section-head"><div><h2>Сарын бодолтын явц</h2><p>{month ? `${runs.length} бодолт · ${month.status === 'closed' ? 'хаасан' : 'нээлттэй'}` : 'Сарын бүртгэл хараахан нээгдээгүй байна.'}</p></div><Link to="/erp/payroll/monthly">Сарын бүртгэл <ArrowLeft size={14} /></Link></div>
      <div className="payroll-v2-active-grid monthly-run-list">
        {runs.map((run) => <button key={run.id} className="payroll-v2-run-card" onClick={() => navigate(`/erp/payroll/monthly/runs/${run.id}`)}>
          <div><strong>{run.run_type === 'advance' ? 'Урьдчилгаа цалин' : 'Сүүл цалин'}</strong><span className={`payroll-v2-chip ${['paid', 'closed'].includes(run.status) ? 'success' : run.status === 'approved' ? 'info' : 'warning'}`}>{run.status === 'draft' ? 'Ноорог' : run.status === 'approved' ? 'Баталсан' : run.status === 'paid' ? 'Төлсөн' : 'Хаасан'}</span></div>
          <strong>{run.pay_date}</strong><p>{run.cutoff_date ? `Таслах өдөр: ${run.cutoff_date}` : 'Сарын эцсийн тооцоо'}</p>
        </button>)}
        {month && !runs.length && <p className="payroll-v2-muted">Энэ сард бодолт үүсгээгүй байна.</p>}
        {!month && <button className="payroll-v2-button primary" onClick={() => navigate('/erp/payroll/monthly')}>Сар нээх <Plus size={15} /></button>}
      </div>
    </section>
  </MonthlyShell>
}

const reportLabels: Record<MonthlyPayrollReportKind, string> = { 'salary-register': 'Цалингийн бүртгэл', 'tax-shi': 'Татвар, НДШ', overtime: 'Илүү цаг', 'department-cost': 'Хэлтсийн зардал', 'advance-final': 'Урьдчилгаа ба сүүл цалин', 'other-deductions': 'Бусад суутгал' }
function MonthlyReports() {
  const month = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, '0')}`
  const [kind, setKind] = useState<MonthlyPayrollReportKind>('salary-register')
  const [fromMonth, setFromMonth] = useState(month)
  const [toMonth, setToMonth] = useState(month)
  const [departmentId, setDepartmentId] = useState<number | undefined>()
  const departments = useHRDepartments()
  const report = useMonthlyPayrollReport(kind, fromMonth, toMonth, departmentId)
  const rows = report.data?.rows || []
  const columns = rows[0] ? Object.keys(rows[0]) : []
  return <MonthlyShell><header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">САРЫН ТАЙЛАН</span><h1>Цалингийн тайлан</h1><p>Хаасан сарууд архивын баталгаажсан өгөгдлөөс уншина.</p></div></header><section className="payroll-v2-section"><div className="monthly-report-controls"><label>Тайлан<select value={kind} onChange={(event) => setKind(event.target.value as MonthlyPayrollReportKind)}>{Object.entries(reportLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Эхлэх сар<input type="month" value={fromMonth} onChange={(event) => setFromMonth(event.target.value)} /></label><label>Дуусах сар<input type="month" value={toMonth} onChange={(event) => setToMonth(event.target.value)} /></label><label>Хэлтэс<select value={departmentId || ''} onChange={(event) => setDepartmentId(Number(event.target.value) || undefined)}><option value="">Бүх хэлтэс</option>{departments.data?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label><button className="payroll-v2-button secondary" disabled={!rows.length} onClick={() => downloadMonthlyPayrollReport(kind, fromMonth, toMonth, departmentId).catch((error) => toast.error(requestError(error)))}>Excel татах</button></div>{report.isLoading ? <p>Тайлан ачаалж байна…</p> : report.error ? <p role="alert">{requestError(report.error)}</p> : <div className="payroll-v2-table-wrap"><table className="payroll-v2-table"><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.employee_id || row.month}-${index}`}>{columns.map((key) => <td key={key}>{typeof row[key] === 'object' ? JSON.stringify(row[key]) : String(row[key] ?? '')}</td>)}</tr>)}{!rows.length && <tr><td colSpan={columns.length || 1}>Сонгосон хугацаанд тайлангийн мөр алга.</td></tr>}</tbody></table></div>}</section></MonthlyShell>
}

function MonthlyMonthBoard() {
  const months = useMonthlyPayrollMonths()
  const createMonth = useCreateMonthlyPayrollMonth()
  const createRun = useCreateMonthlyPayrollRun()
  const closeMonth = useCloseMonthlyPayrollMonth()
  const unlockMonth = useUnlockMonthlyPayrollMonth()
  const capabilities = usePayrollCapabilities()
  const navigate = useNavigate()
  const [year, setYear] = useState(current.getFullYear())
  const [monthNumber, setMonthNumber] = useState(current.getMonth() + 1)
  const [runType, setRunType] = useState<'advance' | 'final'>('advance')
  const [payDay, setPayDay] = useState('10')
  const [oneOffAdvance, setOneOffAdvance] = useState(false)
  const [oneOffEmployeeIds, setOneOffEmployeeIds] = useState<number[]>([])
  const oneOffWorkers = useWorkerDirectory(oneOffAdvance)
  const [reviewClose, setReviewClose] = useState(false)
  const month = useMemo(() => months.data?.find((item) => item.year === year && item.month === monthNumber), [months.data, year, monthNumber])
  const advanceDates = useMonthlyPayrollAdvanceDates(month?.id)
  const monthName = new Intl.DateTimeFormat('mn-MN', { month: 'long', year: 'numeric' }).format(new Date(year, monthNumber - 1, 1))
  const canCreate = Boolean(capabilities.data?.capabilities.create)
  const canApprove = Boolean(capabilities.data?.capabilities.approve)
  const canPay = Boolean(capabilities.data?.capabilities.pay)
  const canAdminister = Boolean(capabilities.data?.capabilities.administer)
  const ensureMonth = async () => {
    try { await createMonth.mutateAsync({ year, month: monthNumber }); toast.success('Цалингийн сар нээгдлээ') }
    catch (error) { toast.error(requestError(error)) }
  }
  const addRun = async () => {
    if (!month || !payDay) return
    try {
      const day = runType === 'final' ? new Date(year, monthNumber, 0).getDate() : Math.min(Number(payDay), new Date(year, monthNumber, 0).getDate())
      const run = await createRun.mutateAsync({ monthId: month.id, run_type: runType, pay_date: dateFor(year, monthNumber, day), cutoff_date: runType === 'advance' ? dateFor(year, monthNumber, Math.max(1, day - 1)) : undefined, ...(runType === 'advance' && oneOffAdvance ? { employee_ids: oneOffEmployeeIds } : {}) })
      toast.success(runType === 'advance' ? 'Урьдчилгааны бодолт үүслээ' : 'Сүүл цалингийн бодолт үүслээ')
      navigate(`/erp/payroll/monthly/runs/${run.id}`)
    } catch (error) { toast.error(requestError(error)) }
  }
  const close = async () => {
    if (!month) return
    try { await closeMonth.mutateAsync(month.id); setReviewClose(false); toast.success('Сар хаагдаж архивлагдлаа') }
    catch (error) { toast.error(requestError(error)) }
  }
  const unlock = async () => {
    if (!month) return
    const reason = window.prompt('Сарыг нээх шалтгаан бичнэ үү')
    if (!reason?.trim()) return
    try { await unlockMonth.mutateAsync({ id: month.id, reason: reason.trim() }); toast.success('Сарыг дахин нээлээ') }
    catch (error) { toast.error(requestError(error)) }
  }
  return <MonthlyShell actions={<span className="payroll-v2-kicker">ЦАЛИН · САРЫН БОДОЛТ</span>}>
    <header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">RUN BASED MONTHLY PAYROLL</span><h1>Сарын цалин</h1><p>Урьдчилгаа болон сүүл цалинг тусдаа бодож, сар бүр архивлана.</p></div><WalletCards size={34} /></header>
    <section className="payroll-v2-section">
      <div className="payroll-v2-section-head"><div><h2>{monthName}</h2><p>{month ? `Дүрмийн хувилбар v${String(month.rule_snapshot.version || '')} · ${month.status === 'closed' ? 'Хаасан' : 'Нээлттэй'}` : 'Эхлээд цалингийн сарыг нээнэ үү.'}</p></div>
        <label>Сар <input aria-label="Цалингийн сар" type="month" value={`${year}-${String(monthNumber).padStart(2, '0')}`} onChange={(event) => { if (!event.target.value) return; const [y, m] = event.target.value.split('-').map(Number); setYear(y); setMonthNumber(m) }} /></label>
      </div>
      {!month && <><button className="payroll-v2-button primary" disabled={!canCreate || createMonth.isPending} onClick={ensureMonth}><Plus size={15} />Сар нээх</button>{canAdminister && <MonthlyCalendarEditor year={year} monthNumber={monthNumber} />}</>}
      {month && <>
        <div className="payroll-v2-action-row monthly-run-create">
          <label>Бодолтын төрөл<select value={runType} onChange={(event) => { const type = event.target.value as 'advance' | 'final'; setRunType(type); setOneOffAdvance(false); setPayDay(type === 'advance' ? '10' : '25') }}><option value="advance">Урьдчилгаа цалин</option><option value="final">Сүүл цалин</option></select></label>
          {runType === 'advance' && <label>Төлбөрийн өдөр{!oneOffAdvance ? <select value={payDay} onChange={(event) => setPayDay(event.target.value)}><option value="">Өдөр сонгох</option>{advanceDates.data?.map((item) => <option key={item.date} value={item.day}>{item.date}</option>)}</select> : <input type="number" min="1" max="31" value={payDay} onChange={(event) => setPayDay(event.target.value)} />}</label>}
          {runType === 'advance' && <label className="monthly-one-off-toggle"><input type="checkbox" checked={oneOffAdvance} onChange={(event) => { setOneOffAdvance(event.target.checked); setOneOffEmployeeIds([]); if (event.target.checked) setPayDay('15'); else setPayDay('10') }} />Нэг удаагийн урьдчилгаа</label>}
          {runType === 'advance' && oneOffAdvance && <label>Ажилтан сонгох<select multiple value={oneOffEmployeeIds.map(String)} onChange={(event) => setOneOffEmployeeIds(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}>{oneOffWorkers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select><small>Олон ажилтан сонгохын тулд Ctrl эсвэл ⌘ дарна уу.</small></label>}
          <button className="payroll-v2-button primary" disabled={!canCreate || month.status !== 'open' || createRun.isPending || !payDay || (oneOffAdvance && oneOffEmployeeIds.length === 0)} onClick={addRun}><Plus size={15} />Шинэ бодолт үүсгэх</button>
        </div>
        <div className="payroll-v2-active-grid monthly-run-list">
          {month.runs.map((run) => <button key={run.id} className="payroll-v2-run-card" onClick={() => navigate(`/erp/payroll/monthly/runs/${run.id}`)}>
            <div><strong>{run.run_type === 'advance' ? 'Урьдчилгаа цалин' : 'Сүүл цалин'}</strong><span className={`payroll-v2-chip ${run.status === 'paid' || run.status === 'closed' ? 'success' : run.status === 'approved' ? 'info' : 'warning'}`}>{run.status === 'draft' ? 'Ноорог' : run.status === 'approved' ? 'Баталсан' : run.status === 'paid' ? 'Төлсөн' : 'Хаасан'}</span></div>
            <strong>{new Intl.DateTimeFormat('mn-MN', { day: 'numeric', month: 'long' }).format(new Date(`${run.pay_date}T12:00:00`))}</strong><p>{run.cutoff_date ? `Таслах өдөр: ${run.cutoff_date}` : 'Сарын эцсийн тооцоо'}</p>
          </button>)}
          {!month.runs.length && <p className="payroll-v2-muted">Одоогоор бодолт үүсгээгүй байна.</p>}
        </div>
        {month.status === 'open' && <button className="payroll-v2-button secondary" disabled={!canApprove || !month.runs.length || closeMonth.isPending} onClick={() => setReviewClose(true)}>Сарын хаалтын тайлан</button>}
        {reviewClose && month.status === 'open' && <ClosingStatsReview monthId={month.id} pending={closeMonth.isPending} onCancel={() => setReviewClose(false)} onConfirm={close} />}
        {month.status === 'closed' && <><ArchiveSummary monthId={month.id} />{canAdminister && <button className="payroll-v2-button secondary" disabled={unlockMonth.isPending} onClick={unlock}><LockKeyhole size={15} />Шалтгаантайгаар дахин нээх</button>}</>}
      </>}
      {canAdminister && <MonthlySettingsPanel />}
      {canAdminister && <MonthlyRuleSetEditor />}
      <MonthlyWorkerHistory />
    </section>
  </MonthlyShell>
}

function ClosingStatsReview({ monthId, pending, onCancel, onConfirm }: { monthId: number; pending: boolean; onCancel: () => void; onConfirm: () => void }) {
  const stats = useMonthlyPayrollClosingStats(monthId)
  const totals = stats.data?.totals || {}
  const overtime = stats.data?.overtime || {}
  const quality = stats.data?.quality || {}
  if (stats.isLoading) return <section className="payroll-v2-stage-card"><h3>Хаалтын тайлан ачаалж байна…</h3></section>
  if (stats.error) return <section className="payroll-v2-stage-card"><h3>Хаалтын тайланг ачаалж чадсангүй.</h3><button onClick={onCancel}>Буцах</button></section>
  return <section className="payroll-v2-stage-card monthly-closing-stats"><div className="payroll-v2-section-head"><div><span className="payroll-v2-kicker">САР ХААХЫН ӨМНӨ</span><h2>Хаалтын тайлан</h2></div><strong>{stats.data?.headcount?.on_register || 0} ажилтан</strong></div><div className="payroll-v2-metric-grid compact"><article><span>Нийт цалин</span><strong>{formatPayrollMoney(String(totals.gross || 0))}</strong></article><article><span>Ажилтны НДШ</span><strong>{formatPayrollMoney(String(totals.employee_shi || 0))}</strong></article><article><span>ХХОАТ</span><strong>{formatPayrollMoney(String(totals.pit || 0))}</strong></article><article><span>Сүүл цалин</span><strong>{formatPayrollMoney(String(totals.net_pay || 0))}</strong></article><article><span>Компанийн зардал</span><strong>{formatPayrollMoney(String(totals.company_cost || 0))}</strong></article><article><span>Урьдчилгаа</span><strong>{formatPayrollMoney(String(totals.advance_total || 0))}</strong></article></div><p>Илүү цаг: {formatPayrollMoney(String(Object.values(overtime.amounts || {}).reduce((sum: number, value: any) => sum + Number(value), 0)))} · Банкны дүнг шалгаж, бүх бодолт батлагдсан эсэхийг нягтална уу.</p><p>Чанарын тэмдэглэгээ: гар засвар {quality.manual_rows || 0} · НДШ cap {quality.shi_cap_hits || 0} · Анхааруулгатай мөр {quality.rows_with_warnings || 0}</p><div className="payroll-v2-action-row"><button className="payroll-v2-button secondary" onClick={onCancel}>Буцах</button><button className="payroll-v2-button primary" disabled={pending} onClick={onConfirm}><LockKeyhole size={15} />Баталгаажуулж сар хаах</button></div></section>
}

function MonthlySettingsPanel() {
  const settings = useMonthlyPayrollSettings()
  const save = useSaveMonthlyPayrollSettings()
  const accounts = useERPAccountOptions()
  const [draft, setDraft] = useState<MonthlyPayrollCompanySettings | null>(null)
  useEffect(() => { if (settings.data) setDraft(settings.data) }, [settings.data])
  if (!draft) return null
  const update = (key: keyof MonthlyPayrollCompanySettings, value: any) => setDraft((currentDraft) => currentDraft ? { ...currentDraft, [key]: value } : currentDraft)
  return <details className="payroll-v2-stage-card monthly-settings"><summary><strong>Байгууллагын цалингийн тохиргоо</strong></summary><div className="monthly-settings-grid">
    <label>Компанийн нэр<input value={draft.legal_company_name || ''} onChange={(event) => update('legal_company_name', event.target.value || null)} /></label>
    <label>Өдрийн норм цаг<input type="number" min="1" max="24" step="0.25" value={draft.daily_norm_hours} onChange={(event) => update('daily_norm_hours', event.target.value)} /></label>
    <label>ҮОМШӨ хувь<input type="number" min="0.005" max="0.025" step="0.001" value={draft.employer_injury_rate} onChange={(event) => update('employer_injury_rate', event.target.value)} /></label>
    <label>Ажлын өдрийн илүү цаг<input type="number" min="1.5" max="10" step="0.1" value={draft.weekday_overtime_multiplier} onChange={(event) => update('weekday_overtime_multiplier', event.target.value)} /></label>
    <label>Амралтын өдрийн нэмэгдэл<input type="number" min="1.5" max="10" step="0.1" value={draft.rest_day_overtime_multiplier} onChange={(event) => update('rest_day_overtime_multiplier', event.target.value)} /></label>
    <label>Баярын өдрийн нэмэгдэл<input type="number" min="2" max="10" step="0.1" value={draft.public_holiday_overtime_multiplier} onChange={(event) => update('public_holiday_overtime_multiplier', event.target.value)} /></label>
    <label>Урьдчилгааны үндсэн арга<select value={draft.default_advance_basis} onChange={(event) => update('default_advance_basis', event.target.value)}><option value="FIXED">Тогтмол дүн</option><option value="PERCENT">Үндсэн цалингийн хувь</option><option value="WORKED-TO-DATE">Ажилласан цагаар</option></select></label>
    <label>Урьдчилгааны үндсэн хувь<input type="number" min="1" max="100" value={draft.default_advance_percent} onChange={(event) => update('default_advance_percent', event.target.value)} /></label>
    <label>Бусад суутгалын төрлүүд (мөр тус бүрээр)<textarea rows={4} value={draft.deduction_types.join('\n')} onChange={(event) => update('deduction_types', event.target.value.split('\n').map((value: string) => value.trim()).filter(Boolean))} /></label>
    <label>Цалингийн зардлын данс<select value={draft.salary_expense_account_id || ''} onChange={(event) => update('salary_expense_account_id', Number(event.target.value) || null)}><option value="">Данс сонгох</option>{accounts.data?.filter((account) => account.is_active && !account.is_group).map((account) => <option key={account.id} value={account.id}>{account.code} · {account.name}</option>)}</select></label>
    <label>Ажил олгогчийн НДШ данс<select value={draft.employer_shi_account_id || ''} onChange={(event) => update('employer_shi_account_id', Number(event.target.value) || null)}><option value="">Данс сонгох</option>{accounts.data?.filter((account) => account.is_active && !account.is_group).map((account) => <option key={account.id} value={account.id}>{account.code} · {account.name}</option>)}</select></label>
    <label>Урьдчилгаа тооцооны данс<select value={draft.advance_clearing_account_id || ''} onChange={(event) => update('advance_clearing_account_id', Number(event.target.value) || null)}><option value="">Данс сонгох</option>{accounts.data?.filter((account) => account.is_active && !account.is_group).map((account) => <option key={account.id} value={account.id}>{account.code} · {account.name}</option>)}</select></label>
  </div><button className="payroll-v2-button secondary" disabled={save.isPending} onClick={() => save.mutate(draft, { onSuccess: () => toast.success('Тохиргоо хадгалагдлаа'), onError: (error) => toast.error(requestError(error)) })}>Тохиргоо хадгалах</button><small>Эдгээр тохиргоо дараа нээх саруудад үйлчилнэ. Нээсэн сарын дүрэм, хуанли өөрчлөгдөхгүй.</small></details>
}

function MonthlyCalendarEditor({ year, monthNumber }: { year: number; monthNumber: number }) {
  const days = useMonthlyPayrollCalendar(year, monthNumber)
  const update = useSetMonthlyPayrollCalendarDay(year, monthNumber)
  return <details className="payroll-v2-stage-card monthly-calendar"><summary><strong>Ажлын календарь · амралтын болон баярын өдөр</strong></summary><div className="monthly-calendar-grid">{days.data?.map((day) => <div key={day.date}><strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString('mn-MN', { weekday: 'short', day: 'numeric' })}</strong><select value={day.day_type} disabled={update.isPending} onChange={(event) => {
    const day_type = event.target.value as typeof day.day_type
    const holiday_name = day_type === 'public_holiday' ? window.prompt('Баярын өдрийн нэр', day.holiday_name || '') : null
    update.mutate({ date: day.date, day_type, holiday_name }, { onError: (error) => toast.error(requestError(error)) })
  }}><option value="working">Ажлын өдөр</option><option value="weekly_rest">Долоо хоногийн амралт</option><option value="public_holiday">Нийтийн амралт</option></select></div>)}</div></details>
}

type RuleRateRow = { code: string; rate: string }
type RulePitRow = { lower: string; upper: string; rate: string; base_tax: string }
type RuleReliefRow = { lower: string; upper: string; amount: string }
type RuleEditorDraft = { id?: number; version?: number; status?: MonthlyPayrollRuleSet['status']; valid_from: string; valid_to: string; minimum_wage: string; shi_cap_multiplier: string; employee_rates: RuleRateRow[]; employer_rates: RuleRateRow[]; pit_brackets: RulePitRow[]; relief_tiers: RuleReliefRow[]; overtime_multipliers: RuleRateRow[]; source_references: string }
function ruleDraft(rule: Partial<MonthlyPayrollRuleSet>): RuleEditorDraft { return { id: rule.id, version: rule.version, status: rule.status, valid_from: rule.valid_from || '', valid_to: rule.valid_to || '', minimum_wage: rule.minimum_wage || '', shi_cap_multiplier: rule.shi_cap_multiplier || '10', employee_rates: Object.entries(rule.employee_rates || {}).map(([code, rate]) => ({ code, rate })), employer_rates: Object.entries(rule.employer_rates || {}).map(([code, rate]) => ({ code, rate })), pit_brackets: (rule.pit_brackets || []).map((tier) => ({ lower: tier.lower, upper: tier.upper || '', rate: tier.rate, base_tax: tier.base_tax || '0' })), relief_tiers: (rule.relief_tiers || []).map((tier) => ({ lower: tier.lower, upper: tier.upper || '', amount: tier.amount })), overtime_multipliers: Object.entries(rule.overtime_multipliers || {}).map(([code, rate]) => ({ code, rate })), source_references: (rule.source_references || []).join('\n') } }
function MonthlyRuleSetEditor() {
  const rules = useMonthlyPayrollRuleSets()
  const template = useMonthlyPayrollRuleTemplate()
  const create = useCreateMonthlyPayrollRuleDraft()
  const update = useUpdateMonthlyPayrollRuleDraft()
  const validate = useValidateMonthlyPayrollRuleDraft()
  const publish = usePublishMonthlyPayrollRuleDraft()
  const [draft, setDraft] = useState<RuleEditorDraft | null>(null)
  const set = (key: 'valid_from' | 'valid_to' | 'minimum_wage' | 'shi_cap_multiplier' | 'source_references', value: string) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, [key]: value, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setRates = (key: 'employee_rates' | 'employer_rates' | 'overtime_multipliers', rows: RuleRateRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, [key]: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setPIT = (rows: RulePitRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, pit_brackets: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setRelief = (rows: RuleReliefRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, relief_tiers: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const startDraft = (rule?: MonthlyPayrollRuleSet) => {
    const source = rule || rules.data?.find((item) => item.status === 'published')
    if (source) setDraft({ ...ruleDraft(source), id: undefined, version: undefined, status: undefined })
    else if (template.data) setDraft(ruleDraft(template.data))
    else toast.error('Дүрмийн загвар ачаалж байна.')
  }
  const payload = () => ({ valid_from: draft!.valid_from, valid_to: draft!.valid_to || null, minimum_wage: draft!.minimum_wage, shi_cap_multiplier: draft!.shi_cap_multiplier, employee_rates: Object.fromEntries(draft!.employee_rates.map(({ code, rate }) => [code.trim(), rate])), employer_rates: Object.fromEntries(draft!.employer_rates.map(({ code, rate }) => [code.trim(), rate])), pit_brackets: draft!.pit_brackets.map((tier) => ({ lower: tier.lower, upper: tier.upper || null, rate: tier.rate, base_tax: tier.base_tax || '0' })), relief_tiers: draft!.relief_tiers.map((tier) => ({ lower: tier.lower, upper: tier.upper || null, amount: tier.amount })), overtime_multipliers: Object.fromEntries(draft!.overtime_multipliers.map(({ code, rate }) => [code.trim(), rate])), source_references: draft!.source_references.split('\n').map((line) => line.trim()).filter(Boolean) })
  const saveDraft = async () => {
    if (!draft) return
    try {
      const saved = draft.id ? await update.mutateAsync({ id: draft.id, ...payload() }) : await create.mutateAsync(payload())
      setDraft(ruleDraft(saved))
      toast.success(`Ноорог хувилбар ${saved.version} хадгалагдлаа`)
      return saved
    } catch (error) { toast.error(requestError(error)); return undefined }
  }
  const checkDraft = async () => { const saved = await saveDraft(); if (!saved) return; validate.mutate(saved.id, { onSuccess: (result) => { setDraft(ruleDraft(result)); toast.success(result.status === 'validated' ? 'Дүрэм шалгалтад тэнцлээ' : `Шалгах алдаа: ${(result.validation_issues || []).join(', ')}`) }, onError: (error) => toast.error(requestError(error)) }) }
  const publishDraft = () => { if (!draft?.id || draft.status !== 'validated') { toast.error('Нооргийг хадгалж шалгасны дараа нийтэлнэ үү.'); return }; publish.mutate(draft.id, { onSuccess: (result) => { setDraft(ruleDraft(result)); toast.success(`Хувилбар ${result.version} нийтлэгдлээ`) }, onError: (error) => toast.error(requestError(error)) }) }
  const busy = create.isPending || update.isPending || validate.isPending || publish.isPending
  return <details className="payroll-v2-stage-card monthly-settings monthly-rules"><summary><strong>Хууль, татварын хүчинтэй дүрмийн хувилбар</strong></summary>
    <p className="payroll-v2-muted">Шинэ дүрэм ноороглож, эх сурвалж тэмдэглэн шалгасны дараа нийтэлнэ. Нээсэн сарууд өөрийн дүрмийн хуулбарыг хадгална.</p>
    <div className="monthly-rule-toolbar"><label>Хувилбар<select value={draft?.id || ''} onChange={(event) => { const selected = rules.data?.find((item) => item.id === Number(event.target.value)); setDraft(selected ? ruleDraft(selected) : null) }}><option value="">Ноорог сонгох</option>{rules.data?.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.status === 'published' ? 'Нийтэлсэн' : item.status === 'validated' ? 'Шалгасан' : 'Ноорог'} · {item.valid_from}</option>)}</select></label><button className="payroll-v2-button secondary" disabled={busy} onClick={() => startDraft()}>Одоогийн дүрмээс шинэ хувилбар</button></div>
    {draft && <><div className="monthly-settings-grid">
      <label>Хүчинтэй эхлэх өдөр<input type="date" disabled={draft.status === 'published'} value={draft.valid_from} onChange={(event) => set('valid_from', event.target.value)} /></label><label>Хүчинтэй дуусах өдөр<input type="date" disabled={draft.status === 'published'} value={draft.valid_to} onChange={(event) => set('valid_to', event.target.value)} /></label><label>Хөдөлмөрийн хөлсний доод хэмжээ<input type="number" disabled={draft.status === 'published'} min="1" value={draft.minimum_wage} onChange={(event) => set('minimum_wage', event.target.value)} /></label><label>НДШ дээд хязгаарын үржүүлэгч<input type="number" disabled={draft.status === 'published'} min="1" step="0.1" value={draft.shi_cap_multiplier} onChange={(event) => set('shi_cap_multiplier', event.target.value)} /></label>
      <RateRowsEditor title="Ажилтны НДШ хувь" percent rows={draft.employee_rates} disabled={draft.status === 'published'} onChange={(rows) => setRates('employee_rates', rows)} /><RateRowsEditor title="Ажил олгогчийн НДШ хувь" percent rows={draft.employer_rates} disabled={draft.status === 'published'} onChange={(rows) => setRates('employer_rates', rows)} /><TierRowsEditor title="ХХОАТ шатлал" rows={draft.pit_brackets} disabled={draft.status === 'published'} onChange={setPIT} /><ReliefRowsEditor rows={draft.relief_tiers} disabled={draft.status === 'published'} onChange={setRelief} /><RateRowsEditor title="Илүү цагийн үржүүлэгч" rows={draft.overtime_multipliers} disabled={draft.status === 'published'} onChange={(rows) => setRates('overtime_multipliers', rows)} /><label>Хуулийн заалт, албан эх сурвалжийн холбоос · мөр тус бүрээр<textarea disabled={draft.status === 'published'} rows={5} value={draft.source_references} onChange={(event) => set('source_references', event.target.value)} placeholder="Хуулийн нэр, зүйл заалт, legalinfo.mn холбоос" /></label>
    </div><div className="monthly-rule-actions"><button className="payroll-v2-button secondary" disabled={busy || draft.status === 'published'} onClick={saveDraft}>Ноорог хадгалах</button><button className="payroll-v2-button secondary" disabled={busy || draft.status === 'published'} onClick={checkDraft}>Шалгах</button><button className="payroll-v2-button primary" disabled={busy || draft.status !== 'validated'} onClick={publishDraft}>Нийтлэх</button></div>{draft.status && <p className="monthly-rule-status">Төлөв: {draft.status === 'published' ? 'Нийтэлсэн' : draft.status === 'validated' ? 'Шалгалт тэнцсэн' : 'Ноорог'} · v{draft.version}</p>}{draft.status === 'draft' && <small>Эх сурвалж болон шатлалын утгыг шалгаж байж нийтлэх боломж нээгдэнэ.</small>}</>}
    {!draft && rules.isLoading && <p>Хувилбар ачаалж байна…</p>}{!draft && rules.error && <p role="alert">{requestError(rules.error)}</p>}
  </details>
}

function RateRowsEditor({ title, rows, disabled, percent = false, onChange }: { title: string; rows: RuleRateRow[]; disabled: boolean; percent?: boolean; onChange: (rows: RuleRateRow[]) => void }) {
  return <fieldset className="monthly-rule-editor-fieldset"><legend>{title}</legend>{rows.map((row, index) => <div className="monthly-rule-edit-row rate" key={`${title}-${index}`}><label>Код<input aria-label={`${title}: код`} disabled={disabled} value={row.code} onChange={(event) => onChange(rows.map((item, i) => i === index ? { ...item, code: event.target.value } : item))} /></label><label>{percent ? 'Хувь (%)' : 'Үржүүлэгч'}<input aria-label={`${title}: утга`} type="number" min="0" max={percent ? 100 : undefined} step={percent ? '0.01' : '0.0001'} disabled={disabled} value={percent ? String(Number(row.rate || 0) * 100) : row.rate} onChange={(event) => onChange(rows.map((item, i) => i === index ? { ...item, rate: percent ? String(Number(event.target.value || 0) / 100) : event.target.value } : item))} /></label><button type="button" className="payroll-v2-button compact secondary" disabled={disabled} aria-label={`${title} мөр хасах`} onClick={() => onChange(rows.filter((_, i) => i !== index))}>Хасах</button></div>)}<button type="button" className="payroll-v2-button compact secondary" disabled={disabled} onClick={() => onChange([...rows, { code: '', rate: '0' }])}>+ Мөр нэмэх</button></fieldset>
}

function TierRowsEditor({ title, rows, disabled, onChange }: { title: string; rows: RulePitRow[]; disabled: boolean; onChange: (rows: RulePitRow[]) => void }) {
  const edit = (index: number, key: keyof RulePitRow, value: string) => onChange(rows.map((row, i) => i === index ? { ...row, [key]: value } : row))
  return <fieldset className="monthly-rule-editor-fieldset"><legend>{title}</legend>{rows.map((row, index) => <div className="monthly-rule-edit-row tier" key={`pit-${index}`}><label>Эхлэх орлого<input type="number" min="0" step="1" disabled={disabled} value={row.lower} onChange={(event) => edit(index, 'lower', event.target.value)} /></label><label>Дуусах орлого<input type="number" min="0" step="1" disabled={disabled} value={row.upper} placeholder="Дээд хязгааргүй" onChange={(event) => edit(index, 'upper', event.target.value)} /></label><label>Хувь (%)<input type="number" min="0" max="100" step="0.1" disabled={disabled} value={String(Number(row.rate || 0) * 100)} onChange={(event) => edit(index, 'rate', String(Number(event.target.value || 0) / 100))} /></label><label>Суурь татвар<input type="number" min="0" step="1" disabled={disabled} value={row.base_tax} onChange={(event) => edit(index, 'base_tax', event.target.value)} /></label><button type="button" className="payroll-v2-button compact secondary" disabled={disabled} aria-label={`${title} мөр хасах`} onClick={() => onChange(rows.filter((_, i) => i !== index))}>Хасах</button></div>)}<button type="button" className="payroll-v2-button compact secondary" disabled={disabled} onClick={() => { const previous = rows[rows.length - 1]; onChange([...rows, { lower: previous?.upper || previous?.lower || '0', upper: '', rate: '0', base_tax: '0' }]) }}>+ Шатлал нэмэх</button></fieldset>
}

function ReliefRowsEditor({ rows, disabled, onChange }: { rows: RuleReliefRow[]; disabled: boolean; onChange: (rows: RuleReliefRow[]) => void }) {
  const edit = (index: number, key: keyof RuleReliefRow, value: string) => onChange(rows.map((row, i) => i === index ? { ...row, [key]: value } : row))
  return <fieldset className="monthly-rule-editor-fieldset"><legend>Татварын хөнгөлөлтийн шатлал</legend>{rows.map((row, index) => <div className="monthly-rule-edit-row tier" key={`relief-${index}`}><label>Эхлэх орлого<input type="number" min="0" step="1" disabled={disabled} value={row.lower} onChange={(event) => edit(index, 'lower', event.target.value)} /></label><label>Дуусах орлого<input type="number" min="0" step="1" disabled={disabled} value={row.upper} placeholder="Дээд хязгааргүй" onChange={(event) => edit(index, 'upper', event.target.value)} /></label><label>Хөнгөлөлтийн дүн<input type="number" min="0" step="1" disabled={disabled} value={row.amount} onChange={(event) => edit(index, 'amount', event.target.value)} /></label><button type="button" className="payroll-v2-button compact secondary" disabled={disabled} aria-label="Хөнгөлөлтийн мөр хасах" onClick={() => onChange(rows.filter((_, i) => i !== index))}>Хасах</button></div>)}<button type="button" className="payroll-v2-button compact secondary" disabled={disabled} onClick={() => { const previous = rows[rows.length - 1]; onChange([...rows, { lower: previous?.upper || previous?.lower || '0', upper: '', amount: '0' }]) }}>+ Шатлал нэмэх</button></fieldset>
}

function ArchiveSummary({ monthId }: { monthId: number }) {
  const archives = useMonthlyPayrollArchives(monthId)
  return <section className="payroll-v2-stage-card"><h3>Сарын архив</h3>{archives.data?.map((item) => <details key={item.id}><summary>Хувилбар {item.version} · {new Date(item.closed_at).toLocaleString('mn-MN')} · {item.snapshot.runs?.length || 0} бодолт</summary>{item.snapshot.runs?.map((entry: any) => <div key={entry.run.id}><strong>{entry.run.run_type === 'advance' ? 'Урьдчилгаа' : 'Сүүл цалин'} · {entry.run.pay_date}</strong> <button className="payroll-v2-button compact secondary" onClick={() => downloadMonthlyPayrollArchiveExport(item.id, entry.run.id).catch((error) => toast.error(requestError(error)))}>Архивын Excel татах</button><div className="payroll-v2-table-wrap"><table className="payroll-v2-table"><thead><tr><th>Ажилтан</th><th>Төлөв</th><th>Олговол зохих</th><th>Урьдчилгаа</th><th>Сүүл цалин</th></tr></thead><tbody>{entry.rows.map((row: any) => <tr key={row.employee_id}><td>{row.identity.name}</td><td>{row.status}</td><td>{formatPayrollMoney(String(row.result.gross || 0))}</td><td>{formatPayrollMoney(String(row.result.advance || 0))}</td><td>{formatPayrollMoney(String(row.result.net_pay || 0))}</td></tr>)}</tbody></table></div></div>)}</details>)}</section>
}

function MonthlyWorkerHistory() {
  const workers = useWorkerDirectory()
  const [employeeId, setEmployeeId] = useState<number | undefined>()
  const history = useMonthlyPayrollWorkerHistory(employeeId)
  return <details className="payroll-v2-stage-card monthly-worker-history"><summary><strong>Ажилтны архивын түүх</strong></summary><label>Ажилтан<select value={employeeId || ''} onChange={(event) => setEmployeeId(Number(event.target.value) || undefined)}><option value="">Ажилтан сонгох</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>{employeeId && <><button className="payroll-v2-button secondary" onClick={() => downloadMonthlyPayrollWorkerHistory(employeeId).catch((error) => toast.error(requestError(error)))}>Түүх Excel татах</button><div className="payroll-v2-table-wrap"><table className="payroll-v2-table"><thead><tr><th>Сар</th><th>Бодолт</th><th>Огноо</th><th>Нийт цалин</th><th>НДШ</th><th>ХХОАТ</th><th>Урьдчилгаа</th><th>Сүүл цалин</th></tr></thead><tbody>{history.data?.map((row, index) => <tr key={`${row.month}-${row.run_type}-${index}`}><td>{row.month}</td><td>{row.run_type === 'advance' ? 'Урьдчилгаа' : 'Сүүл цалин'}</td><td>{row.pay_date}</td><td>{formatPayrollMoney(String(row.gross || 0))}</td><td>{formatPayrollMoney(String(row.employee_shi || 0))}</td><td>{formatPayrollMoney(String(row.pit || 0))}</td><td>{formatPayrollMoney(String(row.advance || 0))}</td><td>{formatPayrollMoney(String(row.net_pay || 0))}</td></tr>)}</tbody></table>{!history.data?.length && <p>Архивласан цалингийн мөр олдсонгүй.</p>}</div></>}</details>
}

function MonthlyRunDetail({ runId }: { runId: number }) {
  const navigate = useNavigate()
  const run = useMonthlyPayrollRun(runId)
  const month = useMonthlyPayrollMonth(run.data?.month_id)
  const caps = usePayrollCapabilities()
  const calculate = useCalculateMonthlyPayrollRun()
  const approve = useApproveMonthlyPayrollRun()
  const approveRow = useApproveMonthlyPayrollRow(runId)
  const pay = useMarkMonthlyPayrollPaid()
  const refresh = useRefreshMonthlyPayrollAdvances()
  const refreshTime = useRefreshMonthlyPayrollTime()
  const syncWorkers = useSyncMonthlyPayrollWorkers()
  const importInputs = useImportMonthlyPayrollInputs(runId)
  const flagRow = useFlagMonthlyPayrollRow(runId)
  const unflagRow = useUnflagMonthlyPayrollRow(runId)
  const revertOverrides = useRevertMonthlyPayrollRowOverrides(runId)
  const overrideComputed = useOverrideMonthlyPayrollComputedCell(runId)
  const revertComputed = useRevertMonthlyPayrollComputedCell(runId)
  const [drafts, setDrafts] = useState<Record<number, Record<string, any>>>({})
  const [computedDrafts, setComputedDrafts] = useState<Record<number, { field: string; value: string; reason: string }>>({})
  const [editing, setEditing] = useState<number | null>(null)
  const [workerSearch, setWorkerSearch] = useState('')
  const [departmentFilter, setDepartmentFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  useEffect(() => {
    if (!run.data?.rows) return
    setDrafts(Object.fromEntries(run.data.rows.map((row) => [row.employee_id, { ...row.inputs, other_deduction_amount: row.inputs.other_deductions?.[0]?.amount || '', other_deduction_note: row.inputs.other_deductions?.[0]?.note || '', other_deduction_type: row.inputs.other_deductions?.[0]?.type || 'Бусад' }])))
  }, [run.data?.id, run.data?.rows])
  const mutate = async (task: { mutateAsync: (id: number) => Promise<unknown> }, success: string) => {
    try { await task.mutateAsync(runId); toast.success(success) } catch (error) { toast.error(requestError(error)) }
  }
  const finalRun = run.data?.run_type === 'final'
  const save = useSaveMonthlyPayrollRow(runId)
  if (run.isLoading || !run.data) return <MonthlyShell><div className="payroll-v2-loading">Бодолт ачаалж байна…</div></MonthlyShell>
  const data = run.data
  const editable = data.status === 'draft' && Boolean(caps.data?.capabilities.create)
  const canCalculate = data.status === 'draft' && Boolean(caps.data?.capabilities.calculate)
  const visibleRows = data.rows.filter((row) => {
    const search = workerSearch.trim().toLocaleLowerCase()
    return (!search || `${row.identity.name || ''} ${row.identity.job_title || ''} ${row.identity.rd || ''}`.toLocaleLowerCase().includes(search))
      && (!departmentFilter || (row.identity as any).department === departmentFilter)
      && (statusFilter === 'all' || row.status === statusFilter)
  })
  const groupedRows = Array.from(visibleRows.reduce((groups, row) => {
    const department = String((row.identity as any).department || 'Бусад')
    groups.set(department, [...(groups.get(department) || []), row])
    return groups
  }, new Map<string, typeof data.rows>()).entries()).sort(([a], [b]) => a.localeCompare(b, 'mn'))
  const departments = Array.from(new Set(data.rows.map((row) => String((row.identity as any).department || 'Бусад')))).sort((a, b) => a.localeCompare(b, 'mn'))
  const approvedCount = data.rows.filter((row) => row.status === 'approved').length
  const totalOf = (key: string) => data.rows.reduce((total, row) => total + Number(row.result[key] || 0), 0)
  const saveRow = async (employeeId: number) => {
    const input = drafts[employeeId] || {}
    const other_deductions = input.other_deduction_amount ? [{ type: input.other_deduction_type || 'Бусад', amount: input.other_deduction_amount, note: input.other_deduction_note || '' }] : []
    try {
      const payload: Record<string, unknown> = { ...input, other_deductions, reason: 'Нягтлангийн засвар' }
      delete payload.other_deduction_amount
      delete payload.other_deduction_note
      delete payload.other_deduction_type
      if (payload.fixed_advance === '') delete payload.fixed_advance
      if (payload.advance_percent === '') delete payload.advance_percent
      await save.mutateAsync({ employeeId, ...payload })
      setEditing(null)
      toast.success('Мөрийн оролт хадгалагдлаа')
    } catch (error) { toast.error(requestError(error)) }
  }
  const approveOne = async (employeeId: number) => {
    try { await approveRow.mutateAsync(employeeId); toast.success('Мөр батлагдлаа') }
    catch (error) { toast.error(requestError(error)) }
  }
  const set = (employeeId: number, key: string, value: any) => setDrafts((prev) => ({ ...prev, [employeeId]: { ...(prev[employeeId] || {}), [key]: value } }))
  const setComputed = (employeeId: number, key: 'field' | 'value' | 'reason', value: string) => setComputedDrafts((prev) => { const currentDraft = prev[employeeId] || { field: 'gross', value: '', reason: '' }; return { ...prev, [employeeId]: { ...currentDraft, [key]: value } } })
  return <MonthlyShell actions={<button className="payroll-v2-button secondary" onClick={() => navigate('/erp/payroll/monthly')}><ArrowLeft size={15} />Сарын жагсаалт</button>}>
    <header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">{data.run_type === 'advance' ? 'УРЬДЧИЛГАА ЦАЛИН' : 'СҮҮЛ ЦАЛИН'} · {data.status === 'draft' ? 'НООРОГ' : 'БАТАЛСАН БҮРТГЭЛ'}</span><h1>{data.pay_date}</h1><p>{data.rows.length} ажилтан · {month.data ? `${month.data.year} оны ${month.data.month} сар` : ''} · {data.status}</p></div></header>
    {data.run_type === 'final' && data.rows.some((row) => row.warnings.includes('advance_not_calculated') || row.warnings.includes('advance_changed')) && <div className="payroll-v2-rejected"><CircleAlert size={18} /><div><strong>Урьдчилгааны мэдээлэл шинэчлэх шаардлагатай</strong><p>Батлагдсан урьдчилгаануудын нийлбэрийг дахин татна уу.</p></div>{canCalculate && <button className="payroll-v2-button secondary" disabled={refresh.isPending} onClick={() => mutate(refresh, 'Урьдчилгаа дахин татагдлаа')}><RefreshCw size={15} />Урьдчилгаа дахин татах</button>}</div>}
    <section className="payroll-v2-section"><div className="monthly-register-toolbar"><label>Ажилтан хайх<input value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} placeholder="Нэр, албан тушаал, регистр" /></label><label>Хэлтэс<select value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)}><option value="">Бүх хэлтэс</option>{departments.map((department) => <option key={department}>{department}</option>)}</select></label><label>Төлөв<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">Бүгд</option><option value="draft">Ноорог</option><option value="approved">Баталсан</option><option value="flagged">Шалгах</option></select></label><span>Баталсан {approvedCount}/{data.rows.length} · Анхааруулга {data.rows.filter((row) => row.warnings.length).length}</span></div><div className="payroll-v2-table-wrap"><table className="payroll-v2-table"><thead><tr><th>Ажилтан</th>{data.run_type === 'advance' ? <><th>Суурь</th><th>Ажилласан цаг</th><th>Урьдчилгаа</th></> : <><th>Үндсэн цалин</th><th>Илүү цаг</th><th>НДШ</th><th>ХХОАТ</th><th>Урьдчилгаа</th><th>Бусад суутгал</th><th>Сүүл цалин</th></>}<th>Үйлдэл</th></tr></thead><tbody>
      {groupedRows.flatMap(([department, rows]) => [<tr className="monthly-department-group" key={`department-${department}`}><th colSpan={data.run_type === 'advance' ? 5 : 10}>{department} · {rows.length} ажилтан</th></tr>, ...rows.map((row) => { const input = drafts[row.employee_id] || row.inputs; const editingRow = editing === row.employee_id; const computedDraft = computedDrafts[row.employee_id] || { field: 'gross', value: '', reason: '' }; return <tr key={row.employee_id} className={row.warnings.includes('overtime_work') ? 'monthly-overtime-row' : ''}>
        <th>{row.identity.name}<small>{row.identity.job_title || ''}{row.identity.rd ? ` · ${row.identity.rd}` : ''}</small></th>
        {data.run_type === 'advance' ? <><td>{formatPayrollMoney(String(row.profile.base_salary || 0))}</td><td>{editingRow ? <label className="monthly-inline-input">Ажилласан цаг<input type="number" min="0" value={input.worked_to_date_hours || ''} onChange={(event) => set(row.employee_id, 'worked_to_date_hours', event.target.value)} /></label> : `${input.worked_to_date_hours || 0} цаг`}</td><td>{editingRow && <div className="monthly-inline-input"><label>Тооцох суурь<select value={String(input.advance_basis || row.profile.advance_basis || 'FIXED')} onChange={(event) => set(row.employee_id, 'advance_basis', event.target.value)}><option value="FIXED">Тогтмол дүн</option><option value="PERCENT">Үндсэн цалингийн хувь</option><option value="WORKED-TO-DATE">Ажилласан цагаар</option></select></label>{String(input.advance_basis || row.profile.advance_basis) === 'FIXED' && <label>Дүн<input type="number" min="1" value={input.fixed_advance || ''} onChange={(event) => set(row.employee_id, 'fixed_advance', event.target.value)} placeholder="Профайлын дүн" /></label>}{String(input.advance_basis || row.profile.advance_basis) === 'PERCENT' && <label>Хувь<input type="number" min="1" max="100" value={input.advance_percent || ''} onChange={(event) => set(row.employee_id, 'advance_percent', event.target.value)} placeholder="Профайлын хувь" /></label>}</div>}{formatPayrollMoney(String(row.result.advance || 0))}</td></> : <><td>{formatPayrollMoney(String(row.result.gross || 0))}{editingRow && <div className="monthly-inline-input"><label>Ажилласан цаг<input type="number" min="0" value={input.worked_normal_hours || ''} onChange={(event) => set(row.employee_id, 'worked_normal_hours', event.target.value)} /></label><label>Ээлжийн амралт<input type="number" min="0" value={input.leave_pay || ''} onChange={(event) => set(row.employee_id, 'leave_pay', event.target.value)} /></label></div>}</td><td>{formatPayrollMoney(String(row.result.overtime_pay || 0))}{editingRow && <div className="monthly-inline-input"><label>Ажлын өдөр илүү цаг<input type="number" min="0" value={input.overtime_hours?.weekday || ''} onChange={(event) => set(row.employee_id, 'overtime_hours', { ...input.overtime_hours, weekday: event.target.value })} /></label><label>Амралтын өдөр<input type="number" min="0" value={input.overtime_hours?.rest_day || ''} onChange={(event) => set(row.employee_id, 'overtime_hours', { ...input.overtime_hours, rest_day: event.target.value })} /></label><label>Баярын өдөр<input type="number" min="0" value={input.overtime_hours?.public_holiday || ''} onChange={(event) => set(row.employee_id, 'overtime_hours', { ...input.overtime_hours, public_holiday: event.target.value })} /></label><label>Урамшуулал<input type="number" min="0" value={input.bonus || ''} onChange={(event) => set(row.employee_id, 'bonus', event.target.value)} /></label></div>}</td><td>{formatPayrollMoney(String(row.result.employee_shi || 0))}</td><td>{formatPayrollMoney(String(row.result.pit || 0))}</td><td>{formatPayrollMoney(String(row.result.advance || 0))}</td><td>{formatPayrollMoney(String(row.result.other_deductions || 0))}{editingRow && <div className="monthly-inline-input"><label>Суутгалын төрөл<input value={input.other_deduction_type || 'Бусад'} onChange={(event) => set(row.employee_id, 'other_deduction_type', event.target.value)} /></label><label>Суутгалын дүн<input type="number" min="0" value={input.other_deduction_amount || ''} onChange={(event) => set(row.employee_id, 'other_deduction_amount', event.target.value)} /></label><label>Тайлбар<input value={input.other_deduction_note || ''} onChange={(event) => set(row.employee_id, 'other_deduction_note', event.target.value)} /></label></div>}</td><td><strong>{formatPayrollMoney(String(row.result.net_pay || 0))}</strong></td></>}
        <td><span className={`payroll-v2-chip ${row.status === 'approved' ? 'success' : row.status === 'flagged' ? 'danger' : 'warning'}`}>{row.status === 'approved' ? 'Баталсан' : row.status === 'flagged' ? 'Шалгах' : 'Ноорог'}</span>{row.warnings.map((warning) => <small className="monthly-warning" key={warning}>{warning === 'negative_final_pay' ? 'Сүүл цалин сөрөг' : warning === 'profile_missing' ? 'HR цалингийн профайл дутуу' : warning === 'salary_history_missing_or_incomplete' ? 'Цалингийн түүх дутуу' : warning === 'advance_changed' ? 'Урьдчилгаа өөрчлөгдсөн' : warning === 'zero_worked_hours' ? 'Ажилласан цаг 0' : warning === 'advance_above_estimated_net' ? 'Урьдчилгаа цэвэр цалингаас их' : warning === 'worked_to_date_without_time' ? 'Ирцийн цаг алга' : warning === 'deduction_details_missing' ? 'Суутгалын тайлбар дутуу' : warning === 'worked_hours_above_planned' ? 'Ажилласан цаг төлөвлөгөөнөөс их' : warning === 'base_below_minimum_wage' ? 'Үндсэн цалин доод хэмжээнээс бага' : warning === 'overtime_work' ? 'Илүү цагтай' : warning === 'computed_cell_overridden' ? 'Тооцсон дүнг гараар зассан' : warning === 'row_flagged' ? `Шалгах тэмдэглэгээ: ${input.flag_reason || ''}` : 'Урьдчилгаа бодоогүй'}</small>)}{editable && row.status === 'draft' && (editingRow ? <button className="payroll-v2-button compact primary" onClick={() => saveRow(row.employee_id)}>Хадгалах</button> : <button className="payroll-v2-button compact secondary" onClick={() => setEditing(row.employee_id)}>Засах</button>)}{editable && row.status === 'draft' && caps.data?.capabilities.approve && <button className="payroll-v2-button compact secondary" disabled={approveRow.isPending} onClick={() => approveOne(row.employee_id)}>Мөр батлах</button>}{editable && row.status === 'draft' && <button className="payroll-v2-button compact secondary" onClick={() => { const reason = window.prompt('Шалгах шалтгаан'); if (reason?.trim()) flagRow.mutate({ employeeId: row.employee_id, reason: reason.trim() }, { onError: (error) => toast.error(requestError(error)) }) }}>Шалгах тэмдэглэх</button>}{editable && row.status === 'flagged' && <button className="payroll-v2-button compact secondary" onClick={() => unflagRow.mutate(row.employee_id, { onError: (error) => toast.error(requestError(error)) })}>Тэмдэглэгээ арилгах</button>}<details className="monthly-row-drawer"><summary>Тооцоо ба түүх</summary><div className="monthly-row-drawer-body"><p><strong>Тооцооны оролт</strong>: ажилласан {input.worked_normal_hours ?? input.worked_to_date_hours ?? 0} цаг · илүү цаг {Object.values(input.overtime_hours || {}).reduce((sum: number, value: any) => sum + Number(value || 0), 0)} цаг · урьдчилгаа {formatPayrollMoney(String(row.result.advance || 0))} · суутгал {formatPayrollMoney(String(row.result.total_deductions || 0))}</p><p><strong>Тооцооны мөр</strong>: нийт {formatPayrollMoney(String(row.result.gross || 0))} → НДШ {formatPayrollMoney(String(row.result.employee_shi || 0))} → ХХОАТ {formatPayrollMoney(String(row.result.pit || 0))} → сүүл цалин {formatPayrollMoney(String(row.result.net_pay || 0))}</p>{input.day_lines?.length > 0 && <div className="payroll-v2-table-wrap"><table className="payroll-v2-table"><thead><tr><th>Огноо</th><th>Өдөр</th><th>Ердийн цаг</th><th>Илүү цаг</th><th>Эх сурвалж</th></tr></thead><tbody>{input.day_lines.map((line: any) => <tr key={line.date}><td>{line.date}</td><td>{line.day_type}</td><td>{line.normal_hours || 0}</td><td>{Object.values(line.overtime_hours || {}).reduce((sum: number, value: any) => sum + Number(value || 0), 0)}</td><td>{line.source || 'Ирц'}</td></tr>)}</tbody></table></div>}{row.audit && row.audit.length > 0 && <div><strong>Засварын түүх</strong>{row.audit.map((audit: any, index: number) => <p key={index}>{audit.field} · {audit.reason || 'шалтгаангүй'} · {audit.at}</p>)}</div>}{editable && <div className="monthly-computed-override"><strong>Тооцсон дүнг шалтгаантай засах</strong><select value={computedDraft.field} onChange={(event) => setComputed(row.employee_id, 'field', event.target.value)}><option value="gross">Олговол зохих</option><option value="employee_shi">Ажилтны НДШ</option><option value="employer_shi">Байгууллагын НДШ</option><option value="pit">ХХОАТ</option><option value="advance">Урьдчилгаа</option><option value="other_deductions">Бусад суутгал</option></select><input type="number" min="0" value={computedDraft.value} placeholder={String(row.result[computedDraft.field] || '0')} onChange={(event) => setComputed(row.employee_id, 'value', event.target.value)} /><input value={computedDraft.reason} placeholder="Засварын шалтгаан" onChange={(event) => setComputed(row.employee_id, 'reason', event.target.value)} /><button className="payroll-v2-button compact secondary" disabled={overrideComputed.isPending || !computedDraft.value || !computedDraft.reason.trim()} onClick={() => overrideComputed.mutate({ employeeId: row.employee_id, field: computedDraft.field, value: computedDraft.value, reason: computedDraft.reason.trim() }, { onSuccess: () => toast.success('Тооцсон дүн шинэчлэгдлээ'), onError: (error) => toast.error(requestError(error)) })}>Дүнг засах</button></div>}{(row.result.computed_overrides || []).map((field: string) => <p key={field}>Гараар зассан: {field} <button className="payroll-v2-button compact secondary" disabled={!editable || revertComputed.isPending} onClick={() => { const reason = window.prompt('Тооцсон дүнг буцаах шалтгаан'); if (reason?.trim()) revertComputed.mutate({ employeeId: row.employee_id, field, reason: reason.trim() }, { onSuccess: () => toast.success('Тооцоог буцаалаа'), onError: (error) => toast.error(requestError(error)) }) }}>Буцаах</button></p>)}{editable && row.audit?.some((audit) => audit.field === 'inputs') && <button className="payroll-v2-button compact secondary" disabled={revertOverrides.isPending} onClick={() => { const reason = window.prompt('Буцаалтын шалтгаан'); if (reason?.trim()) revertOverrides.mutate({ employeeId: row.employee_id, reason: reason.trim() }, { onError: (error) => toast.error(requestError(error)) }) }}>Оруулгын засварыг буцаах</button>}</div></details></td>
      </tr> })])}
      {!visibleRows.length && <tr><td colSpan={data.run_type === 'advance' ? 5 : 10}>Шүүлтэд тохирох ажилтан алга.</td></tr>}
    </tbody><tfoot><tr><th>Нийт</th>{data.run_type === 'advance' ? <><td></td><td></td><td>{formatPayrollMoney(String(totalOf('advance')))}</td></> : <><td>{formatPayrollMoney(String(totalOf('gross')))}</td><td>{formatPayrollMoney(String(totalOf('overtime_pay')))}</td><td>{formatPayrollMoney(String(totalOf('employee_shi')))}</td><td>{formatPayrollMoney(String(totalOf('pit')))}</td><td>{formatPayrollMoney(String(totalOf('advance')))}</td><td>{formatPayrollMoney(String(totalOf('other_deductions')))}</td><td>{formatPayrollMoney(String(totalOf('net_pay')))}</td></>}<td>{approvedCount}/{data.rows.length} баталсан</td></tr></tfoot></table></div>
    <div className="payroll-v2-action-row monthly-run-footer"><span>Баталгаажуулахын өмнө дүнг шалгана уу.</span>{data.status !== 'draft' && caps.data?.capabilities.export && <button className="payroll-v2-button secondary" onClick={() => downloadMonthlyPayrollExport(runId).catch((error) => toast.error(requestError(error)))}>Excel татах</button>}{editable && caps.data?.capabilities.export && <button className="payroll-v2-button secondary" onClick={() => downloadMonthlyPayrollInputTemplate(runId).catch((error) => toast.error(requestError(error)))}>Excel загвар татах</button>}{editable && <label className="monthly-import-control">Excel оролт оруулах<input type="file" accept=".xlsx" disabled={importInputs.isPending} onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) importInputs.mutate(file, { onSuccess: (result) => toast.success(`${result.updated_rows} мөр импортоллоо`), onError: (error) => toast.error(requestError(error)) }); event.currentTarget.value = '' }} /></label>}{editable && <button className="payroll-v2-button secondary" disabled={syncWorkers.isPending} onClick={() => syncWorkers.mutate(runId, { onSuccess: (result: any) => toast.success(`${result.added_workers || 0} ажилтан нэмэгдлээ`), onError: (error) => toast.error(requestError(error)) })}>Ажилтан шинэчлэх</button>}{editable && <button className="payroll-v2-button secondary" disabled={refreshTime.isPending || save.isPending} onClick={() => mutate(refreshTime, 'Ирц, чөлөө, ажлын цаг шинэчлэгдлээ')}><RefreshCw size={15} />Цаг шинэчлэх</button>}{editable && <button className="payroll-v2-button secondary" disabled={calculate.isPending || save.isPending} onClick={() => mutate(calculate, 'Бодолт шинэчлэгдлээ')}><RefreshCw size={15} />Дахин бодох</button>}{editable && caps.data?.capabilities.approve && <button className="payroll-v2-button primary" disabled={approve.isPending || save.isPending || data.rows.some((row) => row.status === 'flagged')} onClick={() => mutate(approve, 'Бодолт батлагдлаа')}><Check size={15} />Бүгдийг батлах</button>}{data.status === 'approved' && caps.data?.capabilities.pay && <button className="payroll-v2-button primary" disabled={pay.isPending} onClick={() => mutate(pay, 'Төлсөн гэж тэмдэглэлээ')}>Төлсөн гэж тэмдэглэх</button>}{data.status === 'paid' && <span className="payroll-v2-chip success">Төлсөн</span>}</div>
    </section>
  </MonthlyShell>
}
