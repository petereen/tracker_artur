import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CircleAlert, Download, LockKeyhole, Plus, WalletCards, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadMonthlyPayrollArchiveExport, downloadMonthlyPayrollReport, downloadMonthlyPayrollWorkerHistory,
  useCloseMonthlyPayrollMonth, useCreateMonthlyPayrollMonth, useCreateMonthlyPayrollRun, useHRDepartments, useMarkMonthlyPayrollPaid,
  useMarkMonthlyPayrollUnpaid, useMonthlyPayrollAdvanceDates, useMonthlyPayrollArchiveIndex, useMonthlyPayrollArchives,
  useMonthlyPayrollClosingStats, useMonthlyPayrollDashboard, useMonthlyPayrollMonths, useMonthlyPayrollReport,
  useMonthlyPayrollWorkerHistory, usePayrollCapabilities, useUnlockMonthlyPayrollMonth, useWorkerDirectory,
} from '../api/enterprise'
import type { MonthlyPayrollMonth, MonthlyPayrollReportKind } from '../api/enterprise'
import {
  MonthStepper, MonthlyShell, RUN_STATUS_LABELS, RunStatusChip, formatAmount, formatHours, formatMoney, monthKey, monthTitle,
  parseMonthKey, requestError, runTitle, toNumber, useReasonDialog, warningLabel,
} from './monthly-payroll/shared'
import { RunRegister } from './monthly-payroll/RunRegister'
import { MonthlyPayrollSettingsPage } from './monthly-payroll/Settings'
export { MonthlyPayrollDashboard } from './monthly-payroll/Dashboard'

export function MonthlyPayrollWorkspace({ detail = false, reports = false, settings = false, archive = false }: { detail?: boolean; reports?: boolean; settings?: boolean; archive?: boolean }) {
  const { runId } = useParams()
  if (reports) return <MonthlyReports />
  if (settings) return <MonthlyPayrollSettingsPage />
  if (archive) return <MonthlyArchive />
  return detail && runId ? <RunRegister runId={Number(runId)} /> : <MonthlyMonthBoard />
}

function useSelectedMonth() {
  const [params, setParams] = useSearchParams()
  const now = new Date()
  const value = params.get('month') || monthKey(now.getFullYear(), now.getMonth() + 1)
  const setValue = (next: string) => setParams((current) => { const updated = new URLSearchParams(current); updated.set('month', next); updated.delete('close'); return updated }, { replace: true })
  return [value, setValue, params] as const
}

function MonthlyMonthBoard() {
  const [selected, setSelected, params] = useSelectedMonth()
  const { year, month: monthNumber } = parseMonthKey(selected)
  const months = useMonthlyPayrollMonths()
  const month = useMemo(() => months.data?.find((item) => item.year === year && item.month === monthNumber), [months.data, year, monthNumber])
  const dashboard = useMonthlyPayrollDashboard(selected)
  const createMonth = useCreateMonthlyPayrollMonth()
  const unlockMonth = useUnlockMonthlyPayrollMonth()
  const pay = useMarkMonthlyPayrollPaid()
  const unpay = useMarkMonthlyPayrollUnpaid()
  const caps = usePayrollCapabilities()
  const capabilities = caps.data?.capabilities || {}
  const [creating, setCreating] = useState(false)
  const [reviewClose, setReviewClose] = useState(params.get('close') === '1')
  const [reasonDialog, askReason] = useReasonDialog()
  useEffect(() => { if (params.get('close') === '1') setReviewClose(true) }, [params])
  const pipeline = dashboard.data?.pipeline || []
  const open = async () => { try { await createMonth.mutateAsync({ year, month: monthNumber }); toast.success('Цалингийн сар нээгдлээ') } catch (error) { toast.error(requestError(error)) } }
  const unlock = async () => {
    if (!month) return
    const reason = await askReason('Хаасан сарыг дахин нээх', 'Шалтгаан (архивын дараагийн хувилбарт бичигдэнэ)', 'Нээх')
    if (reason) unlockMonth.mutate({ id: month.id, reason }, { onSuccess: () => toast.success('Сар нээгдлээ. Бодолтууд батлагдсан/төлсөн төлөвтэй үлдсэн.'), onError: (error) => toast.error(requestError(error)) })
  }
  const togglePaid = (runId: number, status: string) => (status === 'paid' ? unpay : pay).mutate(runId, { onSuccess: () => toast.success(status === 'paid' ? 'Төлөөгүй болголоо' : 'Төлсөн гэж тэмдэглэлээ'), onError: (error) => toast.error(requestError(error)) })

  return <MonthlyShell canAdminister={Boolean(capabilities.administer)}>
    {reasonDialog}
    <header className="payroll-v2-page-title mp-page-head"><div><span className="payroll-v2-kicker">ЦАЛИН · САРЫН ЦАЛИН</span><h1>{monthTitle(selected)}</h1><p>{month ? `Дүрмийн хувилбар v${String(month.rule_snapshot.version || '')} · ${month.status === 'closed' ? 'Хаасан' : 'Нээлттэй'}` : 'Энэ сарын цалингийн бүртгэл нээгдээгүй.'}</p></div><MonthStepper value={selected} onChange={setSelected} /></header>
    {!month && <section className="payroll-v2-stage-card mp-open-month"><WalletCards size={28} /><div><h2>Сарыг нээх</h2><p>Сар нээхэд тухайн өдрийн хуулийн дүрэм, ажлын календарь хадгалагдана. Календарийг урьдчилан <Link to="/erp/payroll/monthly/settings">Тохиргоо</Link> хэсэгт шалгана уу.</p></div><button className="payroll-v2-button primary" disabled={!capabilities.create || createMonth.isPending} onClick={open}><Plus size={15} />Сар нээх</button></section>}
    {month && <>
      <section className="payroll-v2-section">
        <div className="payroll-v2-section-head"><h2>Бодолтууд</h2>{month.status === 'open' && capabilities.create && <button className="payroll-v2-button primary" onClick={() => setCreating(true)}><Plus size={15} />Шинэ бодолт</button>}</div>
        {creating && <NewRunDialog month={month} hasFinal={Boolean(dashboard.data?.has_final)} onClose={() => setCreating(false)} />}
        <div className="mp-pipeline">{pipeline.map((run) => <article key={run.id} className="mp-pipeline-card">
          <div><Link to={`/erp/payroll/monthly/runs/${run.id}`}><strong>{runTitle(run)}</strong></Link><RunStatusChip status={run.status} /></div>
          <span>{run.pay_date} · {run.workers} ажилтан</span><b>{formatMoney(run.total)}</b>
          <div className="mp-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={run.workers} aria-valuenow={run.approved_rows}><i style={{ width: `${run.workers ? (run.approved_rows * 100) / run.workers : 0}%` }} /></div>
          <small>{run.approved_rows} / {run.workers} батлагдсан</small>
          {['approved', 'paid'].includes(run.status) && month.status === 'open' && capabilities.pay && <label className="mp-paid-toggle"><input type="checkbox" checked={run.status === 'paid'} disabled={pay.isPending || unpay.isPending} onChange={() => togglePaid(run.id, run.status)} />Төлсөн</label>}
        </article>)}
          {!pipeline.length && <p className="mp-empty">Бодолт үүсгээгүй байна. «Шинэ бодолт»-оор урьдчилгаа эсвэл сүүл цалин эхлүүлнэ.</p>}
        </div>
      </section>
      {month.status === 'open' && <div className="payroll-v2-action-row"><button className="payroll-v2-button secondary" disabled={!capabilities.approve || !pipeline.length} onClick={() => setReviewClose(true)}><LockKeyhole size={15} />Сар хаах</button></div>}
      {reviewClose && month.status === 'open' && <ClosingReview month={month} onDone={() => setReviewClose(false)} />}
      {month.status === 'closed' && <><ArchiveSummary monthId={month.id} />{capabilities.administer && <button className="payroll-v2-button secondary" disabled={unlockMonth.isPending} onClick={unlock}><LockKeyhole size={15} />Шалтгаантайгаар дахин нээх</button>}</>}
    </>}
  </MonthlyShell>
}

function NewRunDialog({ month, hasFinal, onClose }: { month: MonthlyPayrollMonth; hasFinal: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const createRun = useCreateMonthlyPayrollRun()
  const advanceDates = useMonthlyPayrollAdvanceDates(month.id)
  const departments = useHRDepartments()
  const [runType, setRunType] = useState<'advance' | 'final' | null>(null)
  const [day, setDay] = useState('')
  const [oneOff, setOneOff] = useState(false)
  const [employeeIds, setEmployeeIds] = useState<number[]>([])
  const [departmentId, setDepartmentId] = useState<number | undefined>()
  const [cutoff, setCutoff] = useState('')
  const workers = useWorkerDirectory(oneOff)
  const lastDay = new Date(month.year, month.month, 0).getDate()
  const dateFor = (value: number) => `${month.year}-${String(month.month).padStart(2, '0')}-${String(Math.min(Math.max(1, value), lastDay)).padStart(2, '0')}`
  const selectedDate = advanceDates.data?.find((item) => String(item.day) === day)
  const needsCutoff = runType === 'advance' && (oneOff || (selectedDate?.worked_to_date_workers || 0) > 0)
  useEffect(() => { if (day) setCutoff(dateFor(Number(day) - 1)) }, [day]) // eslint-disable-line react-hooks/exhaustive-deps
  const canCreate = runType === 'final' ? !hasFinal : runType === 'advance' && Boolean(day) && (!oneOff || employeeIds.length > 0) && !selectedDate?.run_exists
  const submit = async () => {
    if (!runType) return
    try {
      const run = await createRun.mutateAsync({
        monthId: month.id, run_type: runType, pay_date: runType === 'final' ? dateFor(lastDay) : dateFor(Number(day)),
        ...(runType === 'advance' ? { cutoff_date: cutoff || undefined, department_id: oneOff ? undefined : departmentId, ...(oneOff ? { employee_ids: employeeIds } : {}) } : {}),
      } as any)
      toast.success(runType === 'advance' ? 'Урьдчилгааны бодолт үүслээ' : 'Сүүл цалингийн бодолт үүслээ')
      navigate(`/erp/payroll/monthly/runs/${run.id}`)
    } catch (error) { toast.error(requestError(error)) }
  }
  return <section className="payroll-v2-stage-card mp-new-run" aria-label="Шинэ бодолт">
    <div className="payroll-v2-section-head"><h2>Шинэ бодолт</h2><button type="button" className="mp-icon-button" aria-label="Хаах" onClick={onClose}><X size={16} /></button></div>
    <fieldset className="mp-type-choice"><legend>1. Төрөл</legend>
      <label className={runType === 'advance' ? 'active' : ''}><input type="radio" name="run-type" checked={runType === 'advance'} onChange={() => setRunType('advance')} /><strong>Урьдчилгаа цалин</strong><small>HR-ийн урьдчилгааны өдрөөр. Татвар, НДШ-гүй.</small></label>
      <label className={runType === 'final' ? 'active' : ''}><input type="radio" name="run-type" checked={runType === 'final'} disabled={hasFinal} onChange={() => setRunType('final')} /><strong>Сүүл цалин</strong><small>{hasFinal ? 'Энэ сард сүүл цалин үүссэн.' : 'Бүтэн сарын тооцоо, татвар, НДШ, урьдчилгааг татна.'}</small></label>
    </fieldset>
    {runType === 'advance' && <div className="mp-new-run-grid">
      <label>2. Төлбөрийн өдөр<select value={oneOff ? 'other' : day} onChange={(event) => { const value = event.target.value; setOneOff(value === 'other'); setDay(value === 'other' ? '15' : value); setEmployeeIds([]) }}>
        <option value="">Өдөр сонгох</option>
        {advanceDates.data?.map((item) => <option key={item.day} value={item.day} disabled={item.run_exists}>{item.day}-ны өдөр — {item.workers} ажилтан{item.run_exists ? ' · үүссэн' : ''}</option>)}
        <option value="other">Бусад өдөр · нэг удаагийн урьдчилгаа</option>
      </select><small>Ажилтан бүрийн сүүлийн төлбөрийн өдөр сүүл цалинд хамаарна.</small></label>
      {oneOff && <label>Өдөр<input type="number" min="1" max={lastDay} value={day} onChange={(event) => setDay(event.target.value)} /></label>}
      {oneOff && <label>Ажилтан<select multiple value={employeeIds.map(String)} onChange={(event) => setEmployeeIds(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select><small>Ctrl / ⌘ дарж олныг сонгоно.</small></label>}
      {!oneOff && <label>Хэлтэс (заавал биш)<select value={departmentId || ''} onChange={(event) => setDepartmentId(Number(event.target.value) || undefined)}><option value="">Бүх хэлтэс</option>{departments.data?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>}
      {needsCutoff && <label>Таслах өдөр<input type="date" value={cutoff} max={day ? dateFor(Number(day)) : undefined} onChange={(event) => setCutoff(event.target.value)} /><small>{oneOff ? 'Ажилласан цагаар тооцох ажилтанд хэрэглэнэ.' : `${selectedDate?.worked_to_date_workers || 0} ажилтан «ажилласан цагаар» урьдчилгаа авна.`}</small></label>}
      {selectedDate?.run_exists && <p className="mp-manual-note">Энэ өдрийн бодолт үүссэн — нэг удаагийн ажилтныг тэр бодолтын «Ажилтан нэмэх»-ээр нэмнэ.</p>}
    </div>}
    {runType === 'final' && <p className="payroll-v2-muted">Сүүл цалин сарын бүх ажилтныг нэг хүснэгтэд хамарна. Ажилтан бүрийн төлбөрийн өдөр HR профайлаас; хэлтсээр хүснэгт дотор шүүнэ.</p>}
    <div className="mp-dialog-actions"><button className="payroll-v2-button secondary" onClick={onClose}>Болих</button><button className="payroll-v2-button primary" disabled={!canCreate || createRun.isPending} onClick={submit}>Үүсгэх</button></div>
  </section>
}

function ClosingReview({ month, onDone }: { month: MonthlyPayrollMonth; onDone: () => void }) {
  const stats = useMonthlyPayrollClosingStats(month.id)
  const close = useCloseMonthlyPayrollMonth()
  const [waivers, setWaivers] = useState<Record<number, string>>({})
  const data = stats.data
  if (stats.isLoading) return <section className="payroll-v2-stage-card"><h2>Хаалтын тайлан ачаалж байна…</h2></section>
  if (stats.error || !data) return <section className="payroll-v2-stage-card"><h2>Хаалтын тайланг ачаалж чадсангүй</h2><p>{requestError(stats.error)}</p><button className="payroll-v2-button secondary" onClick={onDone}>Буцах</button></section>
  const unapproved: Array<{ run_id: number; pay_date: string; status: string }> = data.unapproved_advance_runs || []
  const allWaived = unapproved.length > 0 && unapproved.every((run) => (waivers[run.run_id] || '').trim())
  const issues: string[] = (allWaived ? data.close_issues_with_waivers : data.close_issues) || []
  const totals = data.totals || {}
  const accounting = data.accounting || {}
  const confirm = () => close.mutate({ id: month.id, waivers: Object.fromEntries(Object.entries(waivers).filter(([, reason]) => reason.trim())) }, { onSuccess: (result: any) => { toast.success(`Сар хаагдаж, архивын ${result.archive_version}-р хувилбар хадгалагдлаа`); onDone() }, onError: (error) => toast.error(requestError(error)) })
  const moneyRows: Array<[string, unknown]> = [
    ['Олговол зохих', totals.gross], ['ХХОАТ (хөнгөлөлтийн өмнө)', totals.pit_before_relief], ['ХХОАТ ХӨН', totals.relief], ['ХХОАТ', totals.pit], ['Ажилтны НДШ', totals.employee_shi],
    ['БНДШ', totals.employer_shi], ['Урьдчилгаа', totals.advance_total], ['Бусад суутгал', totals.other_deductions], ['Сүүл цалин', totals.net_pay], ['Нийт зардал', totals.company_cost],
  ]
  const facts = (items: Array<[string, unknown]>, money = false) => <dl>{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{money ? formatMoney(value) : String(value ?? 0)}</dd></div>)}</dl>
  return <section className="payroll-v2-stage-card mp-closing" aria-label="Сарын хаалтын тайлан">
    <div className="payroll-v2-section-head"><div><span className="payroll-v2-kicker">САР ХААХЫН ӨМНӨ</span><h2>Сарын хаалтын тайлан</h2></div><button type="button" className="mp-icon-button" aria-label="Хаах" onClick={onDone}><X size={16} /></button></div>
    {issues.length > 0 ? <div className="mp-strip danger"><CircleAlert size={16} /><span><strong>Хаах боломжгүй:</strong> {issues.map(warningLabel).join(' · ')}</span></div> : <div className="mp-strip success"><span><strong>Бүх шалгалт тэнцсэн.</strong> Баталгаажуулбал бүх бодолт хаагдаж, архивт хадгалагдана.</span></div>}
    {unapproved.length > 0 && <div className="mp-waivers"><strong>Батлагдаагүй урьдчилгааны бодолт</strong><p>Батлах эсвэл шалтгаантайгаар чөлөөлнө. Чөлөөлсөн бодолт төлөгдөөгүй гэж архивлагдана.</p>{unapproved.map((run) => <label key={run.run_id}>{run.pay_date} · {RUN_STATUS_LABELS[run.status] || run.status}<input placeholder="Чөлөөлөх шалтгаан" value={waivers[run.run_id] || ''} onChange={(event) => setWaivers((current) => ({ ...current, [run.run_id]: event.target.value }))} /></label>)}</div>}
    <div className="mp-closing-grid">
      <div><h3>Толгой тоо</h3>{facts([['Хүснэгтэд', data.headcount?.on_register], ['Шинээр орсон', data.headcount?.new], ['Гарсан', data.headcount?.left], ['Илүү цагтай', data.headcount?.with_extra_work], ['Гараар зассан', data.headcount?.manually_edited]])}</div>
      <div><h3>Мөнгөн дүн</h3>{facts(moneyRows, true)}</div>
      <div><h3>Дундаж ба муж</h3>{facts([['Дундаж олговол зохих', data.averages?.average_gross], ['Медиан', data.averages?.median_gross], ['Дундаж гарт олгох', data.averages?.average_take_home], ['Хамгийн их', data.averages?.highest_gross], ['Хамгийн бага', data.averages?.lowest_gross]], true)}</div>
      <div><h3>Нягтлан бодох бүртгэл</h3><dl>
        <div><dt>A · Цалингийн зардал {accounting.account_a?.account ? `(${accounting.account_a.account.code})` : '(данс сонгоогүй)'}</dt><dd>{formatMoney(accounting.account_a?.total)}</dd></div>
        <div><dt>B · БНДШ {accounting.account_b?.account ? `(${accounting.account_b.account.code})` : ''}</dt><dd>{formatMoney(accounting.account_b?.total)}</dd></div>
        {accounting.account_c && <div><dt>C · Урьдчилгааны тооцоо</dt><dd>{formatMoney(accounting.account_c.total)}</dd></div>}
        <div><dt>A = олговол зохих</dt><dd>{accounting.account_a?.equals_gross ? '✓' : '✗'}</dd></div>
        <div><dt>Урьдчилгааны тулгалт</dt><dd>{accounting.advance_reconciliation?.matches ? '✓ таарсан' : '✗ таарахгүй'}</dd></div>
      </dl></div>
      <div><h3>Илүү цаг · шилдэг 5</h3>{(data.overtime?.top || []).length ? <ol>{(data.overtime.top as any[]).map((item) => <li key={item.employee_id}>{item.name} · {formatHours(item.hours)} ц · {formatMoney(item.amount)}</li>)}</ol> : <p className="mp-empty">Илүү цаг алга.</p>}</div>
      <div><h3>Чанар</h3>{facts([['Гар засвартай мөр', data.quality?.manual_rows], ['Тооцсон дүн засвар', data.quality?.computed_overrides], ['НДШ дээд хязгаар', data.quality?.shi_cap_hits], ['Урьдчилгаагүй ажилтан', data.quality?.workers_without_advance], ['Тэмдэглэж шийдсэн', data.quality?.flagged_then_resolved]])}</div>
      {data.comparison && <div><h3>Өмнөх сар ({data.comparison.month})</h3><dl>{Object.entries(data.comparison.metrics || {}).map(([key, metric]: [string, any]) => <div key={key}><dt>{({ gross: 'Олговол зохих', company_cost: 'Нийт зардал', headcount: 'Ажилтан', overtime_amount: 'Илүү цаг' } as Record<string, string>)[key] || key}</dt><dd>{key === 'headcount' ? toNumber(metric.change) : formatAmount(metric.change)}{metric.change_pct !== null ? ` (${metric.change_pct}%)` : ''}</dd></div>)}</dl></div>}
    </div>
    <div className="mp-dialog-actions"><button className="payroll-v2-button secondary" onClick={onDone}>Буцах</button><button className="payroll-v2-button primary" disabled={issues.length > 0 || close.isPending} onClick={confirm}><LockKeyhole size={15} />Баталгаажуулж сар хаах</button></div>
  </section>
}

function ArchiveSummary({ monthId }: { monthId: number }) {
  const archives = useMonthlyPayrollArchives(monthId)
  return <section className="payroll-v2-stage-card"><h2>Сарын архив</h2>{archives.isLoading && <p>Ачаалж байна…</p>}
    {archives.data?.map((item, index) => <details key={item.id} open={index === 0}><summary>Хувилбар {item.version} · {new Date(item.closed_at).toLocaleString('mn-MN')} · {item.snapshot.runs?.length || 0} бодолт{index === 0 ? ' · хамгийн сүүлийн' : ''}</summary>
      {item.snapshot.runs?.map((entry: any) => <div key={entry.run.id} className="mp-archive-run"><div className="payroll-v2-section-head"><strong>{runTitle(entry.run)} · {entry.run.pay_date}{entry.run.waived ? ' · чөлөөлсөн' : ''}</strong>{!entry.run.waived && <button className="payroll-v2-button compact secondary" onClick={() => downloadMonthlyPayrollArchiveExport(item.id, entry.run.id).catch((error) => toast.error(requestError(error)))}><Download size={13} />Архивын Excel</button>}</div>
        <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">Ажилтан</th><th className="mp-text">Хэлтэс</th>{entry.run.run_type === 'final' ? <><th>Олговол зохих</th><th>НДШ</th><th>ХХОАТ</th><th>Урьдчилгаа</th><th>Сүүл цалин</th></> : <th>Урьдчилгаа</th>}</tr></thead><tbody>{entry.rows.map((row: any) => <tr key={row.employee_id}><th className="mp-text">{row.identity.name}{(row.result.computed_overrides || []).length > 0 && <span className="mp-manual-dot" title="Гараар зассан" />}</th><td className="mp-text">{row.identity.department}</td>{entry.run.run_type === 'final' ? <><td className="mp-num">{formatAmount(row.result.gross)}</td><td className="mp-num">{formatAmount(row.result.employee_shi)}</td><td className="mp-num">{formatAmount(row.result.pit)}</td><td className="mp-num">{formatAmount(row.result.advance)}</td><td className="mp-num">{formatAmount(row.result.net_pay)}</td></> : <td className="mp-num">{formatAmount(row.result.advance)}</td>}</tr>)}</tbody></table></div>
      </div>)}
    </details>)}
  </section>
}

function MonthlyArchive() {
  const index = useMonthlyPayrollArchiveIndex()
  const caps = usePayrollCapabilities()
  const [openMonth, setOpenMonth] = useState<number | null>(null)
  return <MonthlyShell canAdminister={Boolean(caps.data?.capabilities.administer)}>
    <header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">ЦАЛИН · АРХИВ</span><h1>Архив</h1><p>Хаасан сарын өөрчлөгдөхгүй хуулбар: бодолт, мөр, засварын түүх, хадгалсан Excel.</p></div></header>
    <section className="payroll-v2-section"><div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">Сар</th><th>Ажилтан</th><th>Олговол зохих</th><th>Нийт зардал</th><th>Хувилбар</th><th>Бодолт (төлсөн / нийт)</th><th /></tr></thead><tbody>
      {index.data?.map((item) => <tr key={item.archive_id}><th className="mp-text">{item.month}</th><td className="mp-num">{item.headcount}</td><td className="mp-num">{formatAmount(item.gross)}</td><td className="mp-num">{formatAmount(item.company_cost)}</td><td className="mp-num">v{item.version}</td><td className="mp-num">{item.runs_paid} / {item.runs}</td><td><button className="payroll-v2-button compact secondary" aria-expanded={openMonth === item.month_id} onClick={() => setOpenMonth(openMonth === item.month_id ? null : item.month_id)}>{openMonth === item.month_id ? 'Хураах' : 'Нээх'}</button> <Link to={`/erp/payroll?month=${item.month}`}>Самбар</Link></td></tr>)}
      {!index.isLoading && !index.data?.length && <tr><td colSpan={7} className="mp-empty">Хаасан сар алга.</td></tr>}
    </tbody></table></div>{openMonth && <ArchiveSummary monthId={openMonth} />}</section>
    <MonthlyWorkerHistory />
  </MonthlyShell>
}

function MonthlyWorkerHistory() {
  const workers = useWorkerDirectory()
  const [employeeId, setEmployeeId] = useState<number | undefined>()
  const history = useMonthlyPayrollWorkerHistory(employeeId)
  return <section className="payroll-v2-stage-card"><h2>Ажилтны архивын түүх</h2><div className="mp-register-toolbar"><label>Ажилтан<select value={employeeId || ''} onChange={(event) => setEmployeeId(Number(event.target.value) || undefined)}><option value="">Ажилтан сонгох</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>{employeeId && <button className="payroll-v2-button secondary compact" onClick={() => downloadMonthlyPayrollWorkerHistory(employeeId).catch((error) => toast.error(requestError(error)))}><Download size={13} />Excel татах</button>}</div>
    {employeeId && <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">Сар</th><th className="mp-text">Бодолт</th><th className="mp-text">Огноо</th><th>Олговол зохих</th><th>НДШ</th><th>ХХОАТ</th><th>Урьдчилгаа</th><th>Сүүл цалин</th></tr></thead><tbody>{history.data?.map((row, rowIndex) => <tr key={`${row.month}-${row.run_type}-${rowIndex}`}><td className="mp-text">{row.month}</td><td className="mp-text">{row.run_type === 'advance' ? 'Урьдчилгаа' : 'Сүүл цалин'}</td><td className="mp-text">{row.pay_date}</td><td className="mp-num">{formatAmount(row.gross)}</td><td className="mp-num">{formatAmount(row.employee_shi)}</td><td className="mp-num">{formatAmount(row.pit)}</td><td className="mp-num">{formatAmount(row.advance)}</td><td className="mp-num">{formatAmount(row.net_pay)}</td></tr>)}{!history.data?.length && <tr><td colSpan={8} className="mp-empty">Архивласан мөр олдсонгүй.</td></tr>}</tbody></table></div>}
  </section>
}

const REPORT_LABELS: Record<MonthlyPayrollReportKind, string> = { 'salary-register': 'Цалингийн бүртгэл', 'tax-shi': 'Татвар, НДШ (оны эхнээс)', overtime: 'Илүү цаг', 'department-cost': 'Хэлтсийн зардал', 'advance-final': 'Урьдчилгаа ба сүүл цалин', 'other-deductions': 'Бусад суутгал' }
const COLUMN_LABELS: Record<string, string> = {
  month: 'Сар', employee_id: 'ID', employee_name: 'Ажилтан', department: 'Хэлтэс', run_type: 'Бодолт', pay_date: 'Төлбөрийн өдөр', gross: 'Олговол зохих',
  taxable_income: 'Татвар ногдох', employee_shi: 'НДШ', employer_shi: 'БНДШ', pit: 'ХХОАТ', relief: 'ХХОАТ ХӨН', advance: 'Урьдчилгаа', other_deductions: 'Бусад суутгал',
  net_pay: 'Сүүл цалин', bucket: 'Ангилал', hours: 'Цаг', amount: 'Дүн', company_cost: 'Нийт зардал', total: 'Дүн', type: 'Төрөл', note: 'Тайлбар',
  ytd_gross: 'Оны эхнээс олговол', ytd_employee_shi: 'Оны эхнээс НДШ', ytd_employer_shi: 'Оны эхнээс БНДШ', ytd_pit: 'Оны эхнээс ХХОАТ',
}
const TEXT_COLUMNS = new Set(['month', 'employee_id', 'employee_name', 'department', 'run_type', 'pay_date', 'bucket', 'type', 'note'])
const BUCKETS: Record<string, string> = { weekday: 'Ажлын өдөр', rest_day: 'Амралтын өдөр', public_holiday: 'Баярын өдөр' }

function MonthlyReports() {
  const now = new Date()
  const current = monthKey(now.getFullYear(), now.getMonth() + 1)
  const [kind, setKind] = useState<MonthlyPayrollReportKind>('salary-register')
  const [fromMonth, setFromMonth] = useState(current)
  const [toMonth, setToMonth] = useState(current)
  const [departmentId, setDepartmentId] = useState<number | undefined>()
  const departments = useHRDepartments()
  const caps = usePayrollCapabilities()
  const report = useMonthlyPayrollReport(kind, fromMonth, toMonth, departmentId)
  const rows = report.data?.rows || []
  const columns = rows.length ? Array.from(new Set(rows.flatMap((row) => Object.keys(row)))) : []
  const display = (key: string, value: unknown) => key === 'run_type' ? (value === 'advance' ? 'Урьдчилгаа' : 'Сүүл цалин') : key === 'bucket' ? BUCKETS[String(value)] || String(value) : key === 'hours' ? formatHours(value) : TEXT_COLUMNS.has(key) ? String(value ?? '') : value === undefined || value === null || value === '' ? '' : formatAmount(value)
  return <MonthlyShell canAdminister={Boolean(caps.data?.capabilities.administer)}>
    <header className="payroll-v2-page-title"><div><span className="payroll-v2-kicker">ЦАЛИН · ТАЙЛАН</span><h1>Цалингийн тайлан</h1><p>Хаасан сарууд архивын өгөгдлөөс, нээлттэй сарууд одоогийн бодолтоос уншина.</p></div></header>
    <section className="payroll-v2-section"><div className="mp-register-toolbar">
      <label>Тайлан<select value={kind} onChange={(event) => setKind(event.target.value as MonthlyPayrollReportKind)}>{Object.entries(REPORT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Эхлэх сар<input type="month" value={fromMonth} onChange={(event) => setFromMonth(event.target.value)} /></label>
      <label>Дуусах сар<input type="month" value={toMonth} onChange={(event) => setToMonth(event.target.value)} /></label>
      <label>Хэлтэс<select value={departmentId || ''} onChange={(event) => setDepartmentId(Number(event.target.value) || undefined)}><option value="">Бүх хэлтэс</option>{departments.data?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
      <button className="payroll-v2-button secondary" disabled={!rows.length} onClick={() => downloadMonthlyPayrollReport(kind, fromMonth, toMonth, departmentId).catch((error) => toast.error(requestError(error)))}><Download size={14} />Excel татах</button>
    </div>
      {report.isLoading ? <p>Тайлан ачаалж байна…</p> : report.error ? <p role="alert">{requestError(report.error)}</p> : <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr>{columns.map((key) => <th key={key} className={TEXT_COLUMNS.has(key) ? 'mp-text' : 'mp-num'}>{COLUMN_LABELS[key] || key}</th>)}</tr></thead><tbody>
        {rows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((key) => <td key={key} className={TEXT_COLUMNS.has(key) ? 'mp-text' : 'mp-num'}>{display(key, row[key])}</td>)}</tr>)}
        {!rows.length && <tr><td className="mp-empty" colSpan={columns.length || 1}>Сонгосон хугацаанд тайлангийн мөр алга.</td></tr>}
      </tbody></table></div>}
    </section>
  </MonthlyShell>
}
