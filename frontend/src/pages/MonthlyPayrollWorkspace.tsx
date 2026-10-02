import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { labelMap, labelOr } from '../utils/labelMap'
import { intlLocale } from '../utils/locale'
import { CircleAlert, Download, LockKeyhole, Plus, Trash2, WalletCards, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadMonthlyPayrollArchiveExport, downloadMonthlyPayrollReport, downloadMonthlyPayrollWorkerHistory,
  useCloseMonthlyPayrollMonth, useCreateMonthlyPayrollMonth, useCreateMonthlyPayrollRun, useDeleteMonthlyPayrollRun, useHRDepartments, useMarkMonthlyPayrollPaid,
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
  const { t } = useTranslation()
  const [selected, setSelected, params] = useSelectedMonth()
  const { year, month: monthNumber } = parseMonthKey(selected)
  const months = useMonthlyPayrollMonths()
  const month = useMemo(() => months.data?.find((item) => item.year === year && item.month === monthNumber), [months.data, year, monthNumber])
  const dashboard = useMonthlyPayrollDashboard(selected)
  const createMonth = useCreateMonthlyPayrollMonth()
  const unlockMonth = useUnlockMonthlyPayrollMonth()
  const pay = useMarkMonthlyPayrollPaid()
  const unpay = useMarkMonthlyPayrollUnpaid()
  const deleteRun = useDeleteMonthlyPayrollRun()
  const caps = usePayrollCapabilities()
  const capabilities = caps.data?.capabilities || {}
  const [creating, setCreating] = useState(false)
  const [reviewClose, setReviewClose] = useState(params.get('close') === '1')
  const [reasonDialog, askReason] = useReasonDialog()
  useEffect(() => { if (params.get('close') === '1') setReviewClose(true) }, [params])
  const pipeline = dashboard.data?.pipeline || []
  const open = async () => { try { await createMonth.mutateAsync({ year, month: monthNumber }); toast.success(t('mp.board.monthOpened')) } catch (error) { toast.error(requestError(error)) } }
  const unlock = async () => {
    if (!month) return
    const reason = await askReason(t('mp.board.unlockTitle'), t('mp.board.unlockReason'), t('mp.reg.open'))
    if (reason) unlockMonth.mutate({ id: month.id, reason }, { onSuccess: () => toast.success(t('mp.board.unlocked')), onError: (error) => toast.error(requestError(error)) })
  }
  const removeRun = async (run: { id: number; run_type: string; pay_date: string }) => {
    const reason = await askReason(t('mp.reg.deleteTitle', { title: runTitle(run) }), t('mp.reg.deleteReason'), t('mp.reg.delete'))
    if (reason) deleteRun.mutate({ id: run.id, reason }, { onSuccess: () => toast.success(t('mp.reg.deleted')), onError: (error) => toast.error(requestError(error)) })
  }
  const togglePaid = (runId: number, status: string) => (status === 'paid' ? unpay : pay).mutate(runId, { onSuccess: () => toast.success(status === 'paid' ? t('mp.reg.unpaid') : t('mp.reg.markedPaid')), onError: (error) => toast.error(requestError(error)) })

  return <MonthlyShell canAdminister={Boolean(capabilities.administer)}>
    {reasonDialog}
    <header className="payroll-v2-page-title mp-page-head"><div><h1>{monthTitle(selected)}</h1><p>{month ? t('mp.board.ruleStatus', { version: String(month.rule_snapshot.version || ''), status: month.status === 'closed' ? t('mp.runStatus.closed') : t('mp.board.open') }) : t('mp.board.noRegister')}</p></div><MonthStepper value={selected} onChange={setSelected} /></header>
    {!month && <section className="payroll-v2-stage-card mp-open-month"><WalletCards size={28} /><div><h2>{t('mp.board.openMonthTitle')}</h2><p>{(() => { const [before, after] = t('mp.board.openMonthHint').split('{link}'); return <>{before}<Link to="/erp/payroll/monthly/settings">{t('mp.nav.settings')}</Link>{after}</> })()}</p></div><button className="payroll-v2-button primary" disabled={!capabilities.create || createMonth.isPending} onClick={open}><Plus size={15} />{t('mp.board.openMonth')}</button></section>}
    {month && <>
      <section className="payroll-v2-section">
        <div className="payroll-v2-section-head"><h2>{t('mp.board.runs')}</h2>{month.status === 'open' && capabilities.create && <button className="payroll-v2-button primary" onClick={() => setCreating(true)}><Plus size={15} />{t('mp.dash.newRun')}</button>}</div>
        {creating && <NewRunDialog month={month} hasFinal={Boolean(dashboard.data?.has_final)} onClose={() => setCreating(false)} />}
        <div className="mp-pipeline">{pipeline.map((run) => <article key={run.id} className="mp-pipeline-card">
          <div><Link to={`/erp/payroll/monthly/runs/${run.id}`}><strong>{runTitle(run)}</strong></Link><RunStatusChip status={run.status} /></div>
          <span>{t('mp.dash.runWorkers', { date: run.pay_date, n: run.workers })}</span><b>{formatMoney(run.total)}</b>
          <div className="mp-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={run.workers} aria-valuenow={run.approved_rows}><i style={{ width: `${run.workers ? (run.approved_rows * 100) / run.workers : 0}%` }} /></div>
          <small>{t('mp.dash.approvedOf', { approved: run.approved_rows, total: run.workers })}</small>
          {['approved', 'paid'].includes(run.status) && month.status === 'open' && capabilities.pay && <label className="mp-paid-toggle"><input type="checkbox" checked={run.status === 'paid'} disabled={pay.isPending || unpay.isPending} onChange={() => togglePaid(run.id, run.status)} />{t('mp.runStatus.paid')}</label>}
          {['draft', 'approved'].includes(run.status) && month.status === 'open' && capabilities.create && <button type="button" className="payroll-v2-button danger compact mp-card-delete" disabled={deleteRun.isPending} onClick={() => removeRun(run)}><Trash2 size={12} />{t('mp.reg.delete')}</button>}
        </article>)}
          {!pipeline.length && <p className="mp-empty">{t('mp.board.noRuns')}</p>}
        </div>
      </section>
      {month.status === 'open' && <div className="payroll-v2-action-row"><button className="payroll-v2-button secondary" disabled={!capabilities.approve || !pipeline.length} onClick={() => setReviewClose(true)}><LockKeyhole size={15} />{t('mp.reg.menu.closeMonth')}</button></div>}
      {reviewClose && month.status === 'open' && <ClosingReview month={month} onDone={() => setReviewClose(false)} />}
      {month.status === 'closed' && <><ArchiveSummary monthId={month.id} />{capabilities.administer && <button className="payroll-v2-button secondary" disabled={unlockMonth.isPending} onClick={unlock}><LockKeyhole size={15} />{t('mp.board.reopenWithReason')}</button>}</>}
    </>}
  </MonthlyShell>
}

function NewRunDialog({ month, hasFinal, onClose }: { month: MonthlyPayrollMonth; hasFinal: boolean; onClose: () => void }) {
  const { t } = useTranslation()
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
      toast.success(runType === 'advance' ? t('mp.board.advanceCreated') : t('mp.board.finalCreated'))
      navigate(`/erp/payroll/monthly/runs/${run.id}`)
    } catch (error) { toast.error(requestError(error)) }
  }
  return <section className="payroll-v2-stage-card mp-new-run" aria-label={t('mp.dash.newRun')}>
    <div className="payroll-v2-section-head"><h2>{t('mp.dash.newRun')}</h2><button type="button" className="mp-icon-button" aria-label={t('mp.common.close')} onClick={onClose}><X size={16} /></button></div>
    <fieldset className="mp-type-choice"><legend>{t('mp.board.type')}</legend>
      <label className={runType === 'advance' ? 'active' : ''}><input type="radio" name="run-type" checked={runType === 'advance'} onChange={() => setRunType('advance')} /><strong>{t('mp.board.advanceSalary')}</strong><small>{t('mp.board.advanceSalaryDesc')}</small></label>
      <label className={runType === 'final' ? 'active' : ''}><input type="radio" name="run-type" checked={runType === 'final'} disabled={hasFinal} onChange={() => setRunType('final')} /><strong>{t('mp.dash.finalLabel')}</strong><small>{hasFinal ? t('mp.board.finalExists') : t('mp.board.finalDesc')}</small></label>
    </fieldset>
    {runType === 'advance' && <div className="mp-new-run-grid">
      <label>{t('mp.board.payDay')}<select value={oneOff ? 'other' : day} onChange={(event) => { const value = event.target.value; setOneOff(value === 'other'); setDay(value === 'other' ? '15' : value); setEmployeeIds([]) }}>
        <option value="">{t('mp.board.pickDay')}</option>
        {advanceDates.data?.map((item) => <option key={item.day} value={item.day} disabled={item.run_exists}>{t('mp.board.dayOption', { day: item.day, n: item.workers })}{item.run_exists ? ` · ${t('mp.board.dayCreated')}` : ''}</option>)}
        <option value="other">{t('mp.board.otherDay')}</option>
      </select><small>{t('mp.board.lastPayDayHint')}</small></label>
      {oneOff && <label>{t('mp.board.day')}<input type="number" min="1" max={lastDay} value={day} onChange={(event) => setDay(event.target.value)} /></label>}
      {oneOff && <label>{t('mp.dash.headcount')}<select multiple value={employeeIds.map(String)} onChange={(event) => setEmployeeIds(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select><small>{t('mp.reg.notice.multiSelect')}</small></label>}
      {!oneOff && <label>{t('mp.board.departmentOptional')}<select value={departmentId || ''} onChange={(event) => setDepartmentId(Number(event.target.value) || undefined)}><option value="">{t('mp.reg.allDepartments')}</option>{departments.data?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>}
      {needsCutoff && <label>{t('mp.board.cutoff')}<input type="date" value={cutoff} max={day ? dateFor(Number(day)) : undefined} onChange={(event) => setCutoff(event.target.value)} /><small>{oneOff ? t('mp.board.cutoffOneOff') : t('mp.board.cutoffWorked', { n: selectedDate?.worked_to_date_workers || 0 })}</small></label>}
      {selectedDate?.run_exists && <p className="mp-manual-note">{t('mp.board.runExists')}</p>}
    </div>}
    {runType === 'final' && <p className="payroll-v2-muted">{t('mp.board.finalNote')}</p>}
    <div className="mp-dialog-actions"><button className="payroll-v2-button secondary" onClick={onClose}>{t('mp.common.cancel')}</button><button className="payroll-v2-button primary" disabled={!canCreate || createRun.isPending} onClick={submit}>{t('mp.board.create')}</button></div>
  </section>
}

function ClosingReview({ month, onDone }: { month: MonthlyPayrollMonth; onDone: () => void }) {
  const { t } = useTranslation()
  const stats = useMonthlyPayrollClosingStats(month.id)
  const close = useCloseMonthlyPayrollMonth()
  const [waivers, setWaivers] = useState<Record<number, string>>({})
  const data = stats.data
  if (stats.isLoading) return <section className="payroll-v2-stage-card"><h2>{t('mp.close.loading')}</h2></section>
  if (stats.error || !data) return <section className="payroll-v2-stage-card"><h2>{t('mp.close.failed')}</h2><p>{requestError(stats.error)}</p><button className="payroll-v2-button secondary" onClick={onDone}>{t('mp.close.back')}</button></section>
  const unapproved: Array<{ run_id: number; pay_date: string; status: string }> = data.unapproved_advance_runs || []
  const allWaived = unapproved.length > 0 && unapproved.every((run) => (waivers[run.run_id] || '').trim())
  const issues: string[] = (allWaived ? data.close_issues_with_waivers : data.close_issues) || []
  const totals = data.totals || {}
  const accounting = data.accounting || {}
  const confirm = () => close.mutate({ id: month.id, waivers: Object.fromEntries(Object.entries(waivers).filter(([, reason]) => reason.trim())) }, { onSuccess: (result: any) => { toast.success(t('mp.close.archived', { version: result.archive_version })); onDone() }, onError: (error) => toast.error(requestError(error)) })
  const moneyRows: Array<[string, unknown]> = [
    [t('mp.dash.gross'), totals.gross], [t('mp.explain.pitBefore'), totals.pit_before_relief], [t('mp.explain.relief'), totals.relief], [t('mp.dash.pit'), totals.pit], [t('mp.dash.employeeShi'), totals.employee_shi],
    [t('mp.dash.employerShi'), totals.employer_shi], [t('mp.explain.advance'), totals.advance_total], [t('mp.dash.otherDeductions'), totals.other_deductions], [t('mp.dash.finalLabel'), totals.net_pay], [t('mp.dash.totalCost'), totals.company_cost],
  ]
  const facts = (items: Array<[string, unknown]>, money = false) => <dl>{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{money ? formatMoney(value) : String(value ?? 0)}</dd></div>)}</dl>
  return <section className="payroll-v2-stage-card mp-closing" aria-label={t('mp.dash.closingReport')}>
    <div className="payroll-v2-section-head"><div><span className="payroll-v2-kicker">{t('mp.close.kicker')}</span><h2>{t('mp.dash.closingReport')}</h2></div><button type="button" className="mp-icon-button" aria-label={t('mp.common.close')} onClick={onDone}><X size={16} /></button></div>
    {issues.length > 0 ? <div className="mp-strip danger"><CircleAlert size={16} /><span><strong>{t('mp.close.blocked')}</strong> {issues.map(warningLabel).join(' · ')}</span></div> : <div className="mp-strip success"><span><strong>{t('mp.close.allPassed')}</strong> {t('mp.close.confirmHint')}</span></div>}
    {unapproved.length > 0 && <div className="mp-waivers"><strong>{t('mp.close.unapprovedAdvances')}</strong><p>{t('mp.close.waiveHint')}</p>{unapproved.map((run) => <label key={run.run_id}>{run.pay_date} · {RUN_STATUS_LABELS[run.status] || run.status}<input placeholder={t('mp.close.waiveReason')} value={waivers[run.run_id] || ''} onChange={(event) => setWaivers((current) => ({ ...current, [run.run_id]: event.target.value }))} /></label>)}</div>}
    <div className="mp-closing-grid">
      <div><h3>{t('mp.close.headcount')}</h3>{facts([[t('mp.close.onRegister'), data.headcount?.on_register], [t('mp.close.new'), data.headcount?.new], [t('mp.close.left'), data.headcount?.left], [t('mp.filter.overtime'), data.headcount?.with_extra_work], [t('mp.cell.manualEdit'), data.headcount?.manually_edited]])}</div>
      <div><h3>{t('mp.close.amounts')}</h3>{facts(moneyRows, true)}</div>
      <div><h3>{t('mp.close.averages')}</h3>{facts([[t('mp.dash.avgGross'), data.averages?.average_gross], [t('mp.dash.median'), data.averages?.median_gross], [t('mp.close.avgTakeHome'), data.averages?.average_take_home], [t('mp.close.highest'), data.averages?.highest_gross], [t('mp.close.lowest'), data.averages?.lowest_gross]], true)}</div>
      <div><h3>{t('mp.close.accounting')}</h3><dl>
        <div><dt>{t('mp.close.accountA', { account: accounting.account_a?.account ? `(${accounting.account_a.account.code})` : t('mp.close.noAccount') })}</dt><dd>{formatMoney(accounting.account_a?.total)}</dd></div>
        <div><dt>{t('mp.close.accountB', { account: accounting.account_b?.account ? `(${accounting.account_b.account.code})` : '' })}</dt><dd>{formatMoney(accounting.account_b?.total)}</dd></div>
        {accounting.account_c && <div><dt>{t('mp.close.accountC')}</dt><dd>{formatMoney(accounting.account_c.total)}</dd></div>}
        <div><dt>{t('mp.close.accountAEqualsGross')}</dt><dd>{accounting.account_a?.equals_gross ? '✓' : '✗'}</dd></div>
        <div><dt>{t('mp.close.advanceReconciliation')}</dt><dd>{accounting.advance_reconciliation?.matches ? t('mp.close.matched') : t('mp.close.mismatched')}</dd></div>
      </dl></div>
      <div><h3>{t('mp.close.topOvertime')}</h3>{(data.overtime?.top || []).length ? <ol>{(data.overtime.top as any[]).map((item) => <li key={item.employee_id}>{t('mp.close.topLine', { name: item.name, hours: formatHours(item.hours), amount: formatMoney(item.amount) })}</li>)}</ol> : <p className="mp-empty">{t('mp.close.noOvertime')}</p>}</div>
      <div><h3>{t('mp.close.quality')}</h3>{facts([[t('mp.close.manualRows'), data.quality?.manual_rows], [t('mp.close.computedOverrides'), data.quality?.computed_overrides], [t('mp.close.shiCap'), data.quality?.shi_cap_hits], [t('mp.close.noAdvance'), data.quality?.workers_without_advance], [t('mp.close.flaggedResolved'), data.quality?.flagged_then_resolved]])}</div>
      {data.comparison && <div><h3>{t('mp.close.previousMonth', { month: data.comparison.month })}</h3><dl>{Object.entries(data.comparison.metrics || {}).map(([key, metric]: [string, any]) => <div key={key}><dt>{labelOr('mp.close.cmp', key)}</dt><dd>{key === 'headcount' ? toNumber(metric.change) : formatAmount(metric.change)}{metric.change_pct !== null ? ` (${metric.change_pct}%)` : ''}</dd></div>)}</dl></div>}
    </div>
    <div className="mp-dialog-actions"><button className="payroll-v2-button secondary" onClick={onDone}>{t('mp.close.back')}</button><button className="payroll-v2-button primary" disabled={issues.length > 0 || close.isPending} onClick={confirm}><LockKeyhole size={15} />{t('mp.close.confirm')}</button></div>
  </section>
}

function ArchiveSummary({ monthId }: { monthId: number }) {
  const { t } = useTranslation()
  const archives = useMonthlyPayrollArchives(monthId)
  return <section className="payroll-v2-stage-card"><h2>{t('mp.arch.title')}</h2>{archives.isLoading && <p>{t('common.loading')}</p>}
    {archives.data?.map((item, index) => <details key={item.id} open={index === 0}><summary>{t('mp.arch.summary', { version: item.version, date: new Date(item.closed_at).toLocaleString(intlLocale()), n: item.snapshot.runs?.length || 0 })}{index === 0 ? ` · ${t('mp.arch.latest')}` : ''}</summary>
      {item.snapshot.runs?.map((entry: any) => <div key={entry.run.id} className="mp-archive-run"><div className="payroll-v2-section-head"><strong>{runTitle(entry.run)} · {entry.run.pay_date}{entry.run.waived ? ` · ${t('mp.arch.waived')}` : ''}</strong>{!entry.run.waived && <button className="payroll-v2-button compact secondary" onClick={() => downloadMonthlyPayrollArchiveExport(item.id, entry.run.id).catch((error) => toast.error(requestError(error)))}><Download size={13} />{t('mp.arch.excel')}</button>}</div>
        <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">{t('mp.dash.headcount')}</th><th className="mp-text">{t('mp.reg.department')}</th>{entry.run.run_type === 'final' ? <><th>{t('mp.dash.gross')}</th><th>{t('mp.dash.employeeShiShort')}</th><th>{t('mp.dash.pit')}</th><th>{t('mp.explain.advance')}</th><th>{t('mp.dash.finalLabel')}</th></> : <th>{t('mp.explain.advance')}</th>}</tr></thead><tbody>{entry.rows.map((row: any) => <tr key={row.employee_id}><th className="mp-text">{row.identity.name}{(row.result.computed_overrides || []).length > 0 && <span className="mp-manual-dot" title={t('mp.cell.manualEdit')} />}</th><td className="mp-text">{row.identity.department}</td>{entry.run.run_type === 'final' ? <><td className="mp-num">{formatAmount(row.result.gross)}</td><td className="mp-num">{formatAmount(row.result.employee_shi)}</td><td className="mp-num">{formatAmount(row.result.pit)}</td><td className="mp-num">{formatAmount(row.result.advance)}</td><td className="mp-num">{formatAmount(row.result.net_pay)}</td></> : <td className="mp-num">{formatAmount(row.result.advance)}</td>}</tr>)}</tbody></table></div>
      </div>)}
    </details>)}
  </section>
}

function MonthlyArchive() {
  const { t } = useTranslation()
  const index = useMonthlyPayrollArchiveIndex()
  const caps = usePayrollCapabilities()
  const [openMonth, setOpenMonth] = useState<number | null>(null)
  return <MonthlyShell canAdminister={Boolean(caps.data?.capabilities.administer)}>
    <header className="payroll-v2-page-title"><div><h1>{t('mp.arch.pageTitle')}</h1><p>{t('mp.arch.pageDesc')}</p></div></header>
    <section className="payroll-v2-section"><div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">{t('mp.arch.col.month')}</th><th>{t('mp.dash.headcount')}</th><th>{t('mp.dash.gross')}</th><th>{t('mp.dash.totalCost')}</th><th>{t('mp.arch.col.version')}</th><th>{t('mp.arch.col.runs')}</th><th /></tr></thead><tbody>
      {index.data?.map((item) => <tr key={item.archive_id}><th className="mp-text">{item.month}</th><td className="mp-num">{item.headcount}</td><td className="mp-num">{formatAmount(item.gross)}</td><td className="mp-num">{formatAmount(item.company_cost)}</td><td className="mp-num">v{item.version}</td><td className="mp-num">{item.runs_paid} / {item.runs}</td><td><button className="payroll-v2-button compact secondary" aria-expanded={openMonth === item.month_id} onClick={() => setOpenMonth(openMonth === item.month_id ? null : item.month_id)}>{openMonth === item.month_id ? t('mp.arch.collapse') : t('mp.reg.open')}</button> <Link to={`/erp/payroll?month=${item.month}`}>{t('mp.arch.dashboard')}</Link></td></tr>)}
      {!index.isLoading && !index.data?.length && <tr><td colSpan={7} className="mp-empty">{t('mp.arch.noMonths')}</td></tr>}
    </tbody></table></div>{openMonth && <ArchiveSummary monthId={openMonth} />}</section>
    <MonthlyWorkerHistory />
  </MonthlyShell>
}

function MonthlyWorkerHistory() {
  const { t } = useTranslation()
  const workers = useWorkerDirectory()
  const [employeeId, setEmployeeId] = useState<number | undefined>()
  const history = useMonthlyPayrollWorkerHistory(employeeId)
  return <section className="payroll-v2-stage-card"><h2>{t('mp.arch.workerHistory')}</h2><div className="mp-register-toolbar"><label>{t('mp.dash.headcount')}<select value={employeeId || ''} onChange={(event) => setEmployeeId(Number(event.target.value) || undefined)}><option value="">{t('mp.arch.pickWorker')}</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>{employeeId && <button className="payroll-v2-button secondary compact" onClick={() => downloadMonthlyPayrollWorkerHistory(employeeId).catch((error) => toast.error(requestError(error)))}><Download size={13} />{t('mp.reg.downloadExcel')}</button>}</div>
    {employeeId && <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">{t('mp.arch.col.month')}</th><th className="mp-text">{t('mp.arch.col.run')}</th><th className="mp-text">{t('mp.hours.col.date')}</th><th>{t('mp.dash.gross')}</th><th>{t('mp.dash.employeeShiShort')}</th><th>{t('mp.dash.pit')}</th><th>{t('mp.explain.advance')}</th><th>{t('mp.dash.finalLabel')}</th></tr></thead><tbody>{history.data?.map((row, rowIndex) => <tr key={`${row.month}-${row.run_type}-${rowIndex}`}><td className="mp-text">{row.month}</td><td className="mp-text">{row.run_type === 'advance' ? t('mp.explain.advance') : t('mp.dash.finalLabel')}</td><td className="mp-text">{row.pay_date}</td><td className="mp-num">{formatAmount(row.gross)}</td><td className="mp-num">{formatAmount(row.employee_shi)}</td><td className="mp-num">{formatAmount(row.pit)}</td><td className="mp-num">{formatAmount(row.advance)}</td><td className="mp-num">{formatAmount(row.net_pay)}</td></tr>)}{!history.data?.length && <tr><td colSpan={8} className="mp-empty">{t('mp.arch.noRows')}</td></tr>}</tbody></table></div>}
  </section>
}

const REPORT_LABELS = labelMap('mp.reportKind', ['salary-register', 'tax-shi', 'overtime', 'department-cost', 'advance-final', 'other-deductions'] as const)
const TEXT_COLUMNS = new Set(['month', 'employee_id', 'employee_name', 'department', 'run_type', 'pay_date', 'bucket', 'type', 'note'])
const BUCKET_DAY_TYPES: Record<string, string> = { weekday: 'working', rest_day: 'weekly_rest', public_holiday: 'public_holiday' }

function MonthlyReports() {
  const { t } = useTranslation()
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
  const display = (key: string, value: unknown) => key === 'run_type' ? (value === 'advance' ? t('mp.explain.advance') : t('mp.dash.finalLabel')) : key === 'bucket' ? BUCKET_DAY_TYPES[String(value)] ? i18n.t(`mp.dayType.${BUCKET_DAY_TYPES[String(value)]}`) : String(value) : key === 'hours' ? formatHours(value) : TEXT_COLUMNS.has(key) ? String(value ?? '') : value === undefined || value === null || value === '' ? '' : formatAmount(value)
  return <MonthlyShell canAdminister={Boolean(caps.data?.capabilities.administer)}>
    <header className="payroll-v2-page-title"><div><h1>{t('mp.rep.title')}</h1><p>{t('mp.rep.desc')}</p></div></header>
    <section className="payroll-v2-section"><div className="mp-register-toolbar">
      <label>{t('mp.rep.report')}<select value={kind} onChange={(event) => setKind(event.target.value as MonthlyPayrollReportKind)}>{Object.entries(REPORT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>{t('mp.rep.fromMonth')}<input type="month" value={fromMonth} onChange={(event) => setFromMonth(event.target.value)} /></label>
      <label>{t('mp.rep.toMonth')}<input type="month" value={toMonth} onChange={(event) => setToMonth(event.target.value)} /></label>
      <label>{t('mp.reg.department')}<select value={departmentId || ''} onChange={(event) => setDepartmentId(Number(event.target.value) || undefined)}><option value="">{t('mp.reg.allDepartments')}</option>{departments.data?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
      <button className="payroll-v2-button secondary" disabled={!rows.length} onClick={() => downloadMonthlyPayrollReport(kind, fromMonth, toMonth, departmentId).catch((error) => toast.error(requestError(error)))}><Download size={14} />{t('mp.reg.downloadExcel')}</button>
    </div>
      {report.isLoading ? <p>{t('mp.rep.loading')}</p> : report.error ? <p role="alert">{requestError(report.error)}</p> : <div className="mp-table-wrap"><table className="mp-table compact"><thead><tr>{columns.map((key) => <th key={key} className={TEXT_COLUMNS.has(key) ? 'mp-text' : 'mp-num'}>{labelOr('mp.col', key)}</th>)}</tr></thead><tbody>
        {rows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((key) => <td key={key} className={TEXT_COLUMNS.has(key) ? 'mp-text' : 'mp-num'}>{display(key, row[key])}</td>)}</tr>)}
        {!rows.length && <tr><td className="mp-empty" colSpan={columns.length || 1}>{t('mp.rep.empty')}</td></tr>}
      </tbody></table></div>}
    </section>
  </MonthlyShell>
}
