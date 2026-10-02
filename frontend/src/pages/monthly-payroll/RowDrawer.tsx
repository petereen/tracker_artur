import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useAcceptMonthlyPayrollHRChange, useMonthlyPayrollSettings, useOverrideMonthlyPayrollComputedCell,
  useRevertMonthlyPayrollComputedCell, useRevertMonthlyPayrollRowOverrides, useSaveMonthlyPayrollRow,
} from '../../api/enterprise'
import type { MonthlyPayrollMonth, MonthlyPayrollRun, MonthlyPayrollRunRow } from '../../api/enterprise'
import { formatAmount, formatHours, monthFigures, requestError, toNumber, warningLabel } from './shared'
import { plainNumber } from '../../utils/numbers'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { labelMap } from '../../utils/labelMap'
import { intlLocale } from '../../utils/locale'

type Tab = 'calculation' | 'days' | 'advances' | 'deductions' | 'history'
type Explanation = { id: string; label: string; formula: string; inputs: string; value: string; manual: boolean }
const OVERRIDABLE: Array<[string, string]> = [['gross', 'mp.dash.gross'], ['employee_shi', 'mp.dash.employeeShi'], ['employer_shi', 'mp.dash.employerShi'], ['pit', 'mp.dash.pit'], ['advance', 'mp.explain.advance'], ['other_deductions', 'mp.dash.otherDeductions']]
const overridableLabel = (field: string) => { const entry = OVERRIDABLE.find(([key]) => key === field); return entry ? i18n.t(entry[1]) : field }
const FUNDS = labelMap('mp.fund', ['pension', 'benefit', 'unemployment', 'health', 'injury'])
const DAY_TYPES = labelMap('mp.dayType', ['working', 'weekly_rest', 'public_holiday'])
const SOURCES = labelMap('mp.daySource', ['worktime', 'approved_worktime', 'manual', 'attendance'])
const BUCKET_DAY_TYPES: Record<string, string> = { weekday: 'working', rest_day: 'weekly_rest', public_holiday: 'public_holiday' }
const bucketName = (bucket: string) => BUCKET_DAY_TYPES[bucket] ? DAY_TYPES[BUCKET_DAY_TYPES[bucket] as keyof typeof DAY_TYPES] : bucket
const AUDIT_FIELDS = ['inputs', 'excel_import', 'overrides_reverted', 'time_inputs', 'worker_sync', 'worker_added', 'status', 'hr_profile_accepted', 'advances_refreshed'] as const
// Stored deduction-type values stay in Mongolian (they are data); only their display follows the language.
const DEFAULT_DEDUCTION_TYPES = ['Торгууль / сахилгын шийтгэл', 'Хохирол / ажилтнаас авах авлага', 'Бусад'] // i18n-ignore
const DEDUCTION_TYPE_KEYS: Record<string, string> = { [DEFAULT_DEDUCTION_TYPES[0]]: 'mp.deductionType.penalty', [DEFAULT_DEDUCTION_TYPES[1]]: 'mp.deductionType.damage', [DEFAULT_DEDUCTION_TYPES[2]]: 'mp.deductionType.other' }
const deductionTypeLabel = (type: string) => DEDUCTION_TYPE_KEYS[type] ? i18n.t(DEDUCTION_TYPE_KEYS[type]) : type
const auditLabel = (field: string) => {
  if (field.startsWith('computed:')) return i18n.t('mp.audit.computed', { label: overridableLabel(field.split(':')[1]) }) + (field.endsWith(':revert') ? ` ${i18n.t('mp.audit.revertedSuffix')}` : '')
  return (AUDIT_FIELDS as readonly string[]).includes(field) ? i18n.t(`mp.audit.${field}`) : field
}
const brief = (value: unknown) => value === null || value === undefined ? '—' : typeof value === 'object' ? '' : String(value)
const hoursOf = (value: unknown) => i18n.t('mp.unit.hours', { value: formatHours(value) })

function allowanceLine(row: MonthlyPayrollRunRow, result: Record<string, any>): Explanation {
  const { profile } = row
  const rates = `${formatAmount(profile.meal_allowance)} + ${formatAmount(profile.commute_allowance)}`
  const daily = profile.allowance_basis === 'FIXED' || profile.allowance_basis === 'WORKED_DAYS'
  const label = i18n.t('mp.explain.allowance')
  if (!daily) {
    // Snapshots taken before daily rates hold monthly amounts.
    return { id: 'allowance', label, manual: false, formula: i18n.t(profile.salary_type === 'FIXED' ? 'mp.explain.allowanceFormulaFixedSalary' : 'mp.explain.allowanceFormulaProrated'), inputs: rates, value: formatAmount(result.meal_commute) }
  }
  return {
    id: 'allowance', label, manual: profile.allowance_basis === 'WORKED_DAYS' && JSON.stringify(row.inputs.worked_days ?? null) !== JSON.stringify(row.inputs._source_snapshot?.worked_days ?? null),
    formula: i18n.t(profile.allowance_basis === 'FIXED' ? 'mp.explain.allowanceFormulaFixedDays' : 'mp.explain.allowanceFormulaWorkedDays'),
    inputs: `(${rates}) × ${i18n.t('mp.unit.days', { value: formatHours(result.allowance_days) })}`, value: formatAmount(result.meal_commute),
  }
}

function explain(row: MonthlyPayrollRunRow, month: MonthlyPayrollMonth, isFinal: boolean): Explanation[] {
  const { inputs, profile } = row
  const result = monthFigures(row)
  const overrides: string[] = isFinal ? row.result.computed_overrides || [] : []
  const rate = i18n.t('mp.row.rate', { salary: formatAmount(profile.base_salary), hours: formatHours(result.planned_hours), rate: formatAmount(result.hourly_rate) })
  const basis = row.result.advance_basis
  const advanceLine: Explanation[] = isFinal ? [] : [{
    id: 'advanceThis', label: i18n.t('mp.explain.advanceThis'), manual: (row.result.computed_overrides || []).includes('advance') || Boolean(inputs.fixed_advance || inputs.advance_percent),
    formula: i18n.t(basis === 'PERCENT' ? 'mp.explain.advancePercent' : basis === 'FIXED' ? 'mp.explain.advanceFixed' : 'mp.explain.advanceWorked'),
    inputs: basis === 'PERCENT' ? `${formatAmount(profile.base_salary)} × ${row.result.advance_value}%` : basis === 'FIXED' ? formatAmount(row.result.advance_value) : `${hoursOf(inputs.worked_to_date_hours)} × ${formatAmount(row.result.hourly_rate)}`,
    value: formatAmount(row.result.advance),
  }]
  const workedLine: Explanation[] = isFinal ? [] : [{
    id: 'worked', label: i18n.t('mp.explain.worked'), manual: JSON.stringify(inputs.worked_normal_hours ?? null) !== JSON.stringify(inputs._source_snapshot?.worked_normal_hours ?? null),
    formula: i18n.t('mp.explain.workedFormula'),
    inputs: i18n.t('mp.unit.hoursPlus', { a: formatHours(inputs.worked_to_date_hours), b: formatHours(inputs.projected_remaining_hours) }), value: formatHours(inputs.worked_normal_hours),
  }]
  const segments: any[] = profile.salary_segments as any[] || []
  const employeeRates = Object.entries((month.rule_snapshot.employee_rates || {}) as Record<string, string>)
  const employerRates = Object.entries((month.rule_snapshot.employer_rates || {}) as Record<string, string>)
  const fundRates = (entries: Array<[string, string]>) => entries.map(([code, value]) => `${FUNDS[code as keyof typeof FUNDS] || code} ${formatHours(toNumber(value) * 100)}%`).join(' + ')
  const baseInputs = profile.salary_type === 'FIXED'
    ? (segments.length ? segments.map((segment) => `${segment.valid_from} – ${segment.valid_to}: ${formatAmount(segment.monthly_salary)}`).join('; ') + ` ${i18n.t('mp.explain.baseMonthDays', { n: result.planned_days })}` : formatAmount(profile.base_salary))
    : segments.length > 1 ? segments.map((segment) => `${segment.valid_from} – ${segment.valid_to}: ${formatAmount(segment.monthly_salary)} ÷ ${hoursOf(result.planned_hours)}`).join('; ') + ` × ${hoursOf(inputs.worked_normal_hours)}` : `${rate} × ${hoursOf(inputs.worked_normal_hours)}`
  const lines: Explanation[] = [
    ...advanceLine,
    { id: 'planned', label: i18n.t('mp.explain.planned'), manual: false, formula: i18n.t('mp.explain.plannedFormula'), inputs: i18n.t('mp.explain.plannedInputs', { days: result.planned_days, hours: formatHours(profile.daily_norm_hours) }), value: formatHours(result.planned_hours) },
    ...workedLine,
    { id: 'base', label: i18n.t('mp.explain.base'), manual: false, formula: i18n.t(profile.salary_type === 'FIXED' ? 'mp.explain.baseFormulaFixed' : 'mp.explain.baseFormulaHourly'), inputs: baseInputs, value: formatAmount(result.base_pay) },
    { id: 'overtimePay', label: i18n.t('mp.explain.overtimePay'), manual: false, formula: i18n.t('mp.explain.overtimeFormula'), inputs: Object.entries(inputs.overtime_hours || {}).filter(([, hours]) => toNumber(hours) > 0).map(([bucket, hours]) => `${bucketName(bucket)} ${hoursOf(hours)}`).join(', ') || i18n.t('mp.explain.noOvertime'), value: formatAmount(result.overtime_pay) },
    allowanceLine(row, result),
    { id: 'gross', label: i18n.t('mp.explain.gross'), manual: overrides.includes('gross'), formula: i18n.t('mp.explain.grossFormula'), inputs: `${formatAmount(result.base_pay)} + ${formatAmount(result.overtime_pay)} + ${formatAmount(inputs.leave_pay)} + ${formatAmount(result.meal_commute)} + ${formatAmount(inputs.bonus)}`, value: formatAmount(result.gross) },
    { id: 'employeeShi', label: i18n.t('mp.explain.employeeShi'), manual: overrides.includes('employee_shi'), formula: i18n.t('mp.explain.employeeShiFormula'), inputs: `${formatAmount(result.shi_base)} × (${fundRates(employeeRates)})`, value: formatAmount(result.employee_shi) },
    { id: 'taxable', label: i18n.t('mp.explain.taxable'), manual: false, formula: i18n.t('mp.explain.taxableFormula'), inputs: `${formatAmount(result.gross)} − ${formatAmount(result.employee_shi)}`, value: formatAmount(result.taxable_income) },
    { id: 'pitBefore', label: i18n.t('mp.explain.pitBefore'), manual: false, formula: i18n.t('mp.explain.pitBeforeFormula'), inputs: formatAmount(result.taxable_income), value: formatAmount(result.pit_before_relief) },
    { id: 'relief', label: i18n.t('mp.explain.relief'), manual: false, formula: i18n.t('mp.explain.reliefFormula'), inputs: profile.tax_relief_eligible === false ? i18n.t('mp.explain.noRelief') : formatAmount(result.taxable_income), value: formatAmount(result.relief) },
    { id: 'pit', label: i18n.t('mp.explain.pit'), manual: overrides.includes('pit'), formula: i18n.t('mp.explain.pitFormula'), inputs: `${formatAmount(result.pit_before_relief)} − ${formatAmount(result.relief)}`, value: formatAmount(result.pit) },
    isFinal
      ? { id: 'advance', label: i18n.t('mp.explain.advance'), manual: overrides.includes('advance'), formula: i18n.t('mp.explain.advanceFinalFormula'), inputs: (result.advance_lines || []).map((line: any) => `${line.pay_date || '#' + line.run_id}: ${formatAmount(line.amount)}`).join(' + ') || i18n.t('mp.explain.noApprovedAdvance'), value: formatAmount(result.advance) }
      : { id: 'advance', label: i18n.t('mp.explain.monthAdvance'), manual: false, formula: i18n.t('mp.explain.monthAdvanceFormula'), inputs: `${formatAmount(result.prior_advances)} + ${formatAmount(row.result.advance)}`, value: formatAmount(result.advance) },
    { id: 'otherDeductions', label: i18n.t('mp.explain.other'), manual: overrides.includes('other_deductions'), formula: i18n.t('mp.explain.otherFormula'), inputs: (inputs.other_deductions || []).map((line: any) => `${deductionTypeLabel(line.type)}: ${formatAmount(line.amount)}`).join(' + ') || '—', value: formatAmount(result.other_deductions) },
    { id: 'totalDeductions', label: i18n.t('mp.explain.totalDeductions'), manual: false, formula: i18n.t(isFinal ? 'mp.explain.totalFormulaFinal' : 'mp.explain.totalFormulaAdvance'), inputs: isFinal ? `${formatAmount(result.advance)} + ${formatAmount(result.pit)} + ${formatAmount(result.employee_shi)} + ${formatAmount(result.other_deductions)}` : `${formatAmount(result.advance)} + ${formatAmount(result.pit)} + ${formatAmount(result.employee_shi)} + ${formatAmount(result.meal_commute)} + ${formatAmount(result.other_deductions)}`, value: formatAmount(result.total_deductions) },
    { id: 'net', label: i18n.t(isFinal ? 'mp.explain.net' : 'mp.explain.netEstimated'), manual: false, formula: i18n.t('mp.explain.netFormula'), inputs: `${formatAmount(result.gross)} − ${formatAmount(result.total_deductions)}`, value: formatAmount(result.net_pay) },
    { id: 'employerShi', label: i18n.t('mp.explain.employerShi'), manual: overrides.includes('employer_shi'), formula: i18n.t('mp.explain.employerShiFormula'), inputs: `${formatAmount(result.shi_base)} × (${fundRates(employerRates)})`, value: formatAmount(result.employer_shi) },
  ]
  // Other deductions are entered in the final run only.
  return isFinal ? lines : lines.filter((line) => line.id !== 'otherDeductions')
}

export function RowDrawer({ row, run, month, editable, onClose, askReason }: {
  row: MonthlyPayrollRunRow; run: MonthlyPayrollRun; month: MonthlyPayrollMonth; editable: boolean; onClose: () => void
  askReason: (title: string, label?: string, confirm?: string) => Promise<string | null>
}) {
  const { t } = useTranslation()
  const isFinal = run.run_type === 'final'
  const [tab, setTab] = useState<Tab>('calculation')
  const settings = useMonthlyPayrollSettings()
  const save = useSaveMonthlyPayrollRow(run.id)
  const override = useOverrideMonthlyPayrollComputedCell(run.id)
  const revert = useRevertMonthlyPayrollComputedCell(run.id)
  const revertInputs = useRevertMonthlyPayrollRowOverrides(run.id)
  const acceptHR = useAcceptMonthlyPayrollHRChange(run.id)
  const [lines, setLines] = useState<Array<{ type: string; amount: string; note: string }>>([])
  const [overrideField, setOverrideField] = useState('gross')
  const [overrideValue, setOverrideValue] = useState('')
  useEffect(() => { setLines((row.inputs.other_deductions || []).map((line: any) => ({ type: line.type || '', amount: plainNumber(line.amount), note: line.note || '' }))) }, [row.inputs.other_deductions])
  useEffect(() => { const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close) }, [onClose])
  const deductionTypes = settings.data?.deduction_types?.length ? settings.data.deduction_types : DEFAULT_DEDUCTION_TYPES
  const tabs: Array<[Tab, string]> = [['calculation', t('mp.row.tab.calculation')], ['days', t('mp.row.tab.days')], ...(isFinal ? [['advances', t('mp.row.tab.advances')], ['deductions', t('mp.row.tab.deductions')]] as Array<[Tab, string]> : []), ['history', t('mp.row.tab.history')]]
  const saveLines = async () => {
    const invalid = lines.find((line) => toNumber(line.amount) <= 0)
    if (invalid) { toast.error(t('mp.row.deductionAmountPositive')); return }
    try { await save.mutateAsync({ employeeId: row.employee_id, other_deductions: lines.map((line) => ({ ...line, amount: String(line.amount) })), reason: t('mp.row.deductionsReason') }); toast.success(t('mp.row.deductionsSaved')) } catch (error) { toast.error(requestError(error)) }
  }
  const applyOverride = async () => {
    const reason = await askReason(t('mp.row.overrideTitle'), t('mp.row.overrideReason'), t('mp.row.fix'))
    if (!reason) return
    try { await override.mutateAsync({ employeeId: row.employee_id, field: overrideField, value: overrideValue, reason }); setOverrideValue(''); toast.success(t('mp.row.overrideDone')) } catch (error) { toast.error(requestError(error)) }
  }
  const revertOverride = async (field: string) => {
    const reason = await askReason(t('mp.row.revertTitle'), t('mp.reason.label'), t('mp.row.revert'))
    if (reason) revert.mutate({ employeeId: row.employee_id, field, reason }, { onSuccess: () => toast.success(t('mp.row.revertedAuto')), onError: (error) => toast.error(requestError(error)) })
  }
  const revertAllInputs = async () => {
    const reason = await askReason(t('mp.row.revertAllInputs'), t('mp.reason.label'), t('mp.row.revert'))
    if (reason) revertInputs.mutate({ employeeId: row.employee_id, reason }, { onSuccess: () => toast.success(t('mp.row.revertedInputs')), onError: (error) => toast.error(requestError(error)) })
  }
  const pending = row.inputs._hr_pending

  // Portal to <body>: the workspace content sits below the app header's stacking context.
  return createPortal(<div className="mp-drawer-backdrop" onClick={onClose}>
    <aside className="mp-drawer" role="dialog" aria-modal="true" aria-labelledby="mp-drawer-title" onClick={(event) => event.stopPropagation()}>
      <header><div><span className="payroll-v2-kicker">{row.identity.department || t('mp.common.other')} · {row.identity.job_title || ''}</span><h2 id="mp-drawer-title">{row.identity.name}</h2>{row.warnings.length > 0 && <p>{row.warnings.map(warningLabel).join(' · ')}</p>}</div><button type="button" className="mp-icon-button" aria-label={t('mp.common.close')} onClick={onClose}><X size={16} /></button></header>
      <div className="mp-tabs" role="tablist">{tabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
      <div className="mp-drawer-body">
        {tab === 'calculation' && <>
          <table className="mp-explain"><thead><tr><th>{t('mp.row.col.column')}</th><th>{t('mp.row.col.formula')}</th><th>{t('mp.row.col.input')}</th><th>{t('mp.row.col.value')}</th></tr></thead><tbody>
            {explain(row, month, isFinal).map((item) => <tr key={item.id}><th>{item.label}<small className={item.manual ? 'manual' : 'auto'}>{item.manual ? t('mp.row.manual') : t('mp.row.auto')}</small></th><td>{item.formula}</td><td>{item.inputs}</td><td className="mp-num">{item.value}</td></tr>)}
          </tbody></table>
          {(() => { const figures = monthFigures(row); const sum = toNumber(figures.total_deductions) + toNumber(figures.net_pay); return <p className="mp-check">{t('mp.row.check', { sum: formatAmount(sum) })} {sum === toNumber(figures.gross) ? t('mp.row.checkOk') : t('mp.row.checkBad')}</p> })()}
          {!isFinal && <p className="mp-manual-note">{t('mp.row.advanceNote')}</p>}
          {(row.result.computed_overrides || []).length > 0 && <div className="mp-overrides"><strong>{t('mp.row.manualAmounts')}</strong>{(row.result.computed_overrides as string[]).map((field) => <span key={field}>{overridableLabel(field)}{editable && <button type="button" className="payroll-v2-button secondary compact" onClick={() => revertOverride(field)}>{t('mp.row.makeAuto')}</button>}</span>)}</div>}
          {editable && row.profile.complete !== false && <div className="mp-override-form"><strong>{t('mp.row.overrideForm')}</strong><select aria-label={t('mp.row.overrideField')} value={overrideField} onChange={(event) => setOverrideField(event.target.value)}>{OVERRIDABLE.filter(([key]) => isFinal || key === 'advance').map(([key, label]) => <option key={key} value={key}>{i18n.t(label)}</option>)}</select><input aria-label={t('mp.row.newAmount')} type="number" min="0" value={overrideValue} placeholder={formatAmount(row.result[overrideField])} onChange={(event) => setOverrideValue(event.target.value)} /><button type="button" className="payroll-v2-button secondary compact" disabled={!overrideValue || override.isPending} onClick={applyOverride}>{t('mp.row.fix')}</button><small>{t('mp.row.overrideHint')}</small></div>}
        </>}
        {tab === 'days' && <>{(row.inputs.day_lines || []).length ? <table className="mp-explain"><thead><tr><th>{t('mp.hours.col.date')}</th><th>{t('mp.row.col.type')}</th><th>{t('mp.row.col.totalHours')}</th><th>{t('mp.hours.col.normal')}</th><th>{t('mp.hours.col.overtime')}</th><th>{t('mp.hours.col.source')}</th></tr></thead><tbody>{(row.inputs.day_lines as any[]).map((line) => <tr key={line.date}><td>{line.date}</td><td>{DAY_TYPES[line.day_type as keyof typeof DAY_TYPES] || line.day_type}</td><td className="mp-num">{formatHours(line.hours)}</td><td className="mp-num">{formatHours(line.normal_hours)}</td><td className="mp-num">{formatHours(Object.values(line.overtime_hours || {}).reduce((sum: number, value) => sum + toNumber(value), 0))}</td><td>{SOURCES[line.source as keyof typeof SOURCES] || t('mp.row.attendanceFallback')}</td></tr>)}</tbody></table> : <p className="mp-empty">{t('mp.row.noDayLines')}</p>}
          {(row.inputs.missing_dates || []).length > 0 && <p className="mp-manual-note">{t('mp.row.missingDates', { list: (row.inputs.missing_dates as string[]).join(', ') })}</p>}</>}
        {tab === 'advances' && <>{(row.result.advance_lines || []).length ? <table className="mp-explain"><thead><tr><th>{t('mp.row.col.payDate')}</th><th>{t('mp.row.col.run')}</th><th>{t('mp.row.col.value')}</th></tr></thead><tbody>{(row.result.advance_lines as any[]).map((line) => <tr key={line.run_id}><td>{line.pay_date || '—'}</td><td>#{line.run_id}</td><td className="mp-num">{formatAmount(line.amount)}</td></tr>)}</tbody><tfoot><tr><td colSpan={2}>{t('mp.row.totalPulled')}</td><td className="mp-num">{formatAmount(row.result.advance)}</td></tr></tfoot></table> : <p className="mp-empty">{t('mp.row.noAdvances')}</p>}
          {row.warnings.includes('advance_not_calculated') && <p className="mp-manual-note">{t('mp.row.advanceNotCalcNote')}</p>}
          {row.warnings.includes('advance_changed') && <p className="mp-manual-note">{t('mp.row.advanceChangedNote')}</p>}</>}
        {tab === 'deductions' && <div className="mp-deductions">
          {lines.map((line, index) => <div key={index} className="mp-deduction-line">
            <label>{t('mp.row.col.type')}<select disabled={!editable} value={line.type} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, type: event.target.value } : item))}><option value="">{t('mp.row.select')}</option>{deductionTypes.map((type) => <option key={type} value={type}>{deductionTypeLabel(type)}</option>)}{line.type && !deductionTypes.includes(line.type) && <option value={line.type}>{deductionTypeLabel(line.type)}</option>}</select></label>
            <label>{t('mp.row.col.value')}<input disabled={!editable} type="number" min="1" value={line.amount} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, amount: event.target.value } : item))} /></label>
            <label>{t('mp.row.col.note')}<input disabled={!editable} value={line.note} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, note: event.target.value } : item))} /></label>
            {editable && <button type="button" className="mp-icon-button" aria-label={t('mp.row.removeLine')} onClick={() => setLines(lines.filter((_, i) => i !== index))}><Trash2 size={14} /></button>}
          </div>)}
          {!lines.length && <p className="mp-empty">{t('mp.row.noDeductions')}</p>}
          {editable && <div className="mp-dialog-actions"><button type="button" className="payroll-v2-button secondary compact" onClick={() => setLines([...lines, { type: deductionTypes[0], amount: '', note: '' }])}><Plus size={13} />{t('mp.row.addLine')}</button><button type="button" className="payroll-v2-button primary compact" disabled={save.isPending} onClick={saveLines}>{t('mp.row.saveDeductions')}</button></div>}
          <small>{t('mp.row.deductionsNote')}</small>
        </div>}
        {tab === 'history' && <>
          {pending && <div className="mp-strip info"><span><strong>{t('mp.row.hrChangedStrong')}</strong> {['name', 'job_title', 'department'].filter((key) => pending.identity?.[key] !== (row.identity as any)[key]).map((key) => `${key}: ${(row.identity as any)[key] || '—'} → ${pending.identity?.[key] || '—'}`).join('; ')}{['base_salary', 'salary_type', 'payment_frequency', 'advance_basis', 'meal_allowance', 'commute_allowance', 'allowance_basis'].filter((key) => JSON.stringify(pending.profile?.[key]) !== JSON.stringify((row.profile as any)[key])).map((key) => ` ${key}: ${brief((row.profile as any)[key])} → ${brief(pending.profile?.[key])}`).join(';')}</span>{editable && <button type="button" className="payroll-v2-button primary compact" disabled={acceptHR.isPending} onClick={() => acceptHR.mutate(row.employee_id, { onSuccess: () => toast.success(t('mp.row.hrAccepted')), onError: (error) => toast.error(requestError(error)) })}>{t('mp.row.accept')}</button>}</div>}
          {(row.audit || []).length ? <ol className="mp-audit">{[...(row.audit || [])].reverse().map((item, index) => <li key={index}><strong>{auditLabel(item.field)}</strong>{brief(item.old) || brief(item.new) ? <span>{brief(item.old)} → {brief(item.new)}</span> : null}<small>{item.reason || t('mp.row.noReason')} · {new Date(item.at).toLocaleString(intlLocale())}</small></li>)}</ol> : <p className="mp-empty">{t('mp.row.noHistory')}</p>}
          {editable && (row.audit || []).some((item) => ['inputs', 'excel_import'].includes(item.field)) && <button type="button" className="payroll-v2-button secondary compact" onClick={revertAllInputs}>{t('mp.row.revertAllInputs')}</button>}
        </>}
      </div>
    </aside>
  </div>, document.body)
}
