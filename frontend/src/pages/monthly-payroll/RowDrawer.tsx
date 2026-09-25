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

type Tab = 'calculation' | 'days' | 'advances' | 'deductions' | 'history'
type Explanation = { label: string; formula: string; inputs: string; value: string; manual: boolean }
const OVERRIDABLE: Array<[string, string]> = [['gross', 'Олговол зохих'], ['employee_shi', 'Ажилтны НДШ'], ['employer_shi', 'БНДШ'], ['pit', 'ХХОАТ'], ['advance', 'Урьдчилгаа'], ['other_deductions', 'Бусад суутгал']]
const FUNDS: Record<string, string> = { pension: 'Тэтгэвэр', benefit: 'Тэтгэмж', unemployment: 'Ажилгүйдэл', health: 'Эрүүл мэнд', injury: 'ҮОМШӨ' }
const DAY_TYPES: Record<string, string> = { working: 'Ажлын өдөр', weekly_rest: 'Амралтын өдөр', public_holiday: 'Баярын өдөр' }
const SOURCES: Record<string, string> = { worktime: 'Ажлын цаг (бүртгэл)', approved_worktime: 'Батлагдсан ажлын цаг', manual: 'HR ирц', attendance: 'HR ирц (норм өдөр)' }
const BUCKET_NAMES: Record<string, string> = { weekday: 'Ажлын өдөр', rest_day: 'Амралтын өдөр', public_holiday: 'Баярын өдөр' }
const AUDIT_LABELS: Record<string, string> = { inputs: 'Оролт засав', excel_import: 'Excel оролт', overrides_reverted: 'Засвар буцаав', time_inputs: 'Цаг шинэчлэв', worker_sync: 'Ажилтан нэмэв', worker_added: 'Нэг удаагийн урьдчилгаа', status: 'Төлөв', hr_profile_accepted: 'HR өөрчлөлт хүлээн авав', advances_refreshed: 'Урьдчилгаа дахин татав' }
const auditLabel = (field: string) => field.startsWith('computed:') ? `Тооцсон дүн: ${OVERRIDABLE.find(([key]) => key === field.split(':')[1])?.[1] || field}${field.endsWith(':revert') ? ' (буцаав)' : ''}` : AUDIT_LABELS[field] || field
const brief = (value: unknown) => value === null || value === undefined ? '—' : typeof value === 'object' ? '' : String(value)

function allowanceLine(row: MonthlyPayrollRunRow, result: Record<string, any>): Explanation {
  const { profile } = row
  const rates = `${formatAmount(profile.meal_allowance)} + ${formatAmount(profile.commute_allowance)}`
  const daily = profile.allowance_basis === 'FIXED' || profile.allowance_basis === 'WORKED_DAYS'
  if (!daily) {
    // Snapshots taken before daily rates hold monthly amounts.
    return { label: 'Хоол унаа', manual: false, formula: profile.salary_type === 'FIXED' ? 'Хоол + унаа' : '(Хоол + унаа) × ажилласан ÷ ажиллах цаг', inputs: rates, value: formatAmount(result.meal_commute) }
  }
  return {
    label: 'Хоол унаа', manual: profile.allowance_basis === 'WORKED_DAYS' && JSON.stringify(row.inputs.worked_days ?? null) !== JSON.stringify(row.inputs._source_snapshot?.worked_days ?? null),
    formula: profile.allowance_basis === 'FIXED' ? '(Хоол + унаа) × ажиллах өдөр' : '(Хоол + унаа) × ажилласан өдөр',
    inputs: `(${rates}) × ${formatHours(result.allowance_days)} өдөр`, value: formatAmount(result.meal_commute),
  }
}

function explain(row: MonthlyPayrollRunRow, month: MonthlyPayrollMonth, isFinal: boolean): Explanation[] {
  const { inputs, profile } = row
  const result = monthFigures(row)
  const overrides: string[] = isFinal ? row.result.computed_overrides || [] : []
  const rate = `${formatAmount(profile.base_salary)} ÷ ${formatHours(result.planned_hours)} цаг = ${formatAmount(result.hourly_rate)}`
  const basis = row.result.advance_basis
  const advanceLine: Explanation[] = isFinal ? [] : [{
    label: 'Энэ бодолтын урьдчилгаа', manual: (row.result.computed_overrides || []).includes('advance') || Boolean(inputs.fixed_advance || inputs.advance_percent),
    formula: basis === 'PERCENT' ? 'Үндсэн цалин × хувь' : basis === 'FIXED' ? 'HR-ийн оруулсан дүн' : 'Таслах өдөр хүртэл олсон цалин − өмнө батлагдсан урьдчилгаа',
    inputs: basis === 'PERCENT' ? `${formatAmount(profile.base_salary)} × ${row.result.advance_value}%` : basis === 'FIXED' ? formatAmount(row.result.advance_value) : `${formatHours(inputs.worked_to_date_hours)} цаг × ${formatAmount(row.result.hourly_rate)}`,
    value: formatAmount(row.result.advance),
  }]
  const workedLine: Explanation[] = isFinal ? [] : [{
    label: 'Ажилласан цаг', manual: JSON.stringify(inputs.worked_normal_hours ?? null) !== JSON.stringify(inputs._source_snapshot?.worked_normal_hours ?? null),
    formula: 'Таслах өдөр хүртэл ажилласан цаг + үлдсэн ажлын өдрийн төлөвлөсөн цаг (цагийн бүртгэлгүй бол бүтэн сар)',
    inputs: `${formatHours(inputs.worked_to_date_hours)} + ${formatHours(inputs.projected_remaining_hours)} цаг`, value: formatHours(inputs.worked_normal_hours),
  }]
  const segments: any[] = profile.salary_segments as any[] || []
  const employeeRates = Object.entries((month.rule_snapshot.employee_rates || {}) as Record<string, string>)
  const employerRates = Object.entries((month.rule_snapshot.employer_rates || {}) as Record<string, string>)
  const lines: Explanation[] = [
    ...advanceLine,
    { label: 'Ажиллах цаг', manual: false, formula: 'Хуанлийн ажлын өдөр × өдрийн норм', inputs: `${result.planned_days} өдөр × ${formatHours(profile.daily_norm_hours)} цаг`, value: formatHours(result.planned_hours) },
    ...workedLine,
    { label: 'Тооцсон цалин', manual: false, formula: profile.salary_type === 'FIXED' ? 'Үндсэн цалин × ажилласан ажлын өдөр ÷ сарын ажлын өдөр' : 'Цагийн үнэлгээ × ажилласан цаг', inputs: profile.salary_type === 'FIXED' ? (segments.length ? segments.map((segment) => `${segment.valid_from} – ${segment.valid_to}: ${formatAmount(segment.monthly_salary)}`).join('; ') + ` (сард ${result.planned_days} ажлын өдөр)` : formatAmount(profile.base_salary)) : segments.length > 1 ? segments.map((segment) => `${segment.valid_from} – ${segment.valid_to}: ${formatAmount(segment.monthly_salary)} ÷ ${formatHours(result.planned_hours)} цаг`).join('; ') + ` × ${formatHours(inputs.worked_normal_hours)} цаг` : `${rate} × ${formatHours(inputs.worked_normal_hours)} цаг`, value: formatAmount(result.base_pay) },
    { label: 'Илүү цагийн хөлс', manual: false, formula: 'Цагийн үнэлгээ × (ажлын өдрийн илүү цаг × 1.5 + амралтын өдөр × 1.5 + баяр × 2.0)', inputs: Object.entries(inputs.overtime_hours || {}).filter(([, hours]) => toNumber(hours) > 0).map(([bucket, hours]) => `${BUCKET_NAMES[bucket] || bucket} ${formatHours(hours)} цаг`).join(', ') || 'Илүү цаггүй', value: formatAmount(result.overtime_pay) },
    allowanceLine(row, result),
    { label: 'Олговол зохих цалин', manual: overrides.includes('gross'), formula: 'Тооцсон + илүү цаг + ээлжийн амралт + хоол унаа + урамшуулал', inputs: `${formatAmount(result.base_pay)} + ${formatAmount(result.overtime_pay)} + ${formatAmount(inputs.leave_pay)} + ${formatAmount(result.meal_commute)} + ${formatAmount(inputs.bonus)}`, value: formatAmount(result.gross) },
    { label: 'Ажилтны НДШ', manual: overrides.includes('employee_shi'), formula: 'НДШ суурь (дээд хязгаартай) × ажилтны хувь', inputs: `${formatAmount(result.shi_base)} × (${employeeRates.map(([code, value]) => `${FUNDS[code] || code} ${formatHours(toNumber(value) * 100)}%`).join(' + ')})`, value: formatAmount(result.employee_shi) },
    { label: 'Татвар ногдох орлого', manual: false, formula: 'Олговол зохих − ажилтны НДШ', inputs: `${formatAmount(result.gross)} − ${formatAmount(result.employee_shi)}`, value: formatAmount(result.taxable_income) },
    { label: 'ХХОАТ (хөнгөлөлтийн өмнө)', manual: false, formula: 'Шатлалт хувь (10% / 15% / 20%)', inputs: formatAmount(result.taxable_income), value: formatAmount(result.pit_before_relief) },
    { label: 'ХХОАТ ХӨН', manual: false, formula: 'Орлогын шатлалаас хамаарах хөнгөлөлт, татвараас хэтрэхгүй', inputs: profile.tax_relief_eligible === false ? 'Хөнгөлөлт тооцохгүй' : formatAmount(result.taxable_income), value: formatAmount(result.relief) },
    { label: 'ХХОАТ', manual: overrides.includes('pit'), formula: 'Хөнгөлөлтийн өмнөх татвар − ХХОАТ ХӨН', inputs: `${formatAmount(result.pit_before_relief)} − ${formatAmount(result.relief)}`, value: formatAmount(result.pit) },
    isFinal
      ? { label: 'Урьдчилгаа', manual: overrides.includes('advance'), formula: 'Батлагдсан урьдчилгааны бодолтуудын нийлбэр', inputs: (result.advance_lines || []).map((line: any) => `${line.pay_date || '#' + line.run_id}: ${formatAmount(line.amount)}`).join(' + ') || 'Батлагдсан урьдчилгаа алга', value: formatAmount(result.advance) }
      : { label: 'Сарын урьдчилгаа', manual: false, formula: 'Өмнө батлагдсан урьдчилгаа + энэ бодолтын урьдчилгаа', inputs: `${formatAmount(result.prior_advances)} + ${formatAmount(row.result.advance)}`, value: formatAmount(result.advance) },
    { label: 'Бусад суутгал', manual: overrides.includes('other_deductions'), formula: 'Суутгалын мөрүүдийн нийлбэр (татварын дараа)', inputs: (inputs.other_deductions || []).map((line: any) => `${line.type}: ${formatAmount(line.amount)}`).join(' + ') || '—', value: formatAmount(result.other_deductions) },
    { label: 'Суутгалын дүн', manual: false, formula: 'Урьдчилгаа + ХХОАТ + НДШ + бусад суутгал', inputs: `${formatAmount(result.advance)} + ${formatAmount(result.pit)} + ${formatAmount(result.employee_shi)} + ${formatAmount(result.other_deductions)}`, value: formatAmount(result.total_deductions) },
    { label: isFinal ? 'Сүүл цалин' : 'Сүүл цалин (тооцоолсон)', manual: false, formula: 'Олговол зохих − суутгалын дүн', inputs: `${formatAmount(result.gross)} − ${formatAmount(result.total_deductions)}`, value: formatAmount(result.net_pay) },
    { label: 'БНДШ', manual: overrides.includes('employer_shi'), formula: 'НДШ суурь × байгууллагын хувь', inputs: `${formatAmount(result.shi_base)} × (${employerRates.map(([code, value]) => `${FUNDS[code] || code} ${formatHours(toNumber(value) * 100)}%`).join(' + ')})`, value: formatAmount(result.employer_shi) },
  ]
  // Other deductions are entered in the final run only.
  return isFinal ? lines : lines.filter((line) => line.label !== 'Бусад суутгал')
}

export function RowDrawer({ row, run, month, editable, onClose, askReason }: {
  row: MonthlyPayrollRunRow; run: MonthlyPayrollRun; month: MonthlyPayrollMonth; editable: boolean; onClose: () => void
  askReason: (title: string, label?: string, confirm?: string) => Promise<string | null>
}) {
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
  const deductionTypes = settings.data?.deduction_types?.length ? settings.data.deduction_types : ['Торгууль / сахилгын шийтгэл', 'Хохирол / ажилтнаас авах авлага', 'Бусад']
  const tabs: Array<[Tab, string]> = [['calculation', 'Тооцооны задаргаа'], ['days', 'Өдрөөр'], ...(isFinal ? [['advances', 'Урьдчилгаа'], ['deductions', 'Суутгал']] as Array<[Tab, string]> : []), ['history', 'Түүх']]
  const saveLines = async () => {
    const invalid = lines.find((line) => toNumber(line.amount) <= 0)
    if (invalid) { toast.error('Суутгалын дүн 0-ээс их байх ёстой.'); return }
    try { await save.mutateAsync({ employeeId: row.employee_id, other_deductions: lines.map((line) => ({ ...line, amount: String(line.amount) })), reason: 'Бусад суутгал засав' }); toast.success('Суутгал хадгалагдлаа') } catch (error) { toast.error(requestError(error)) }
  }
  const applyOverride = async () => {
    const reason = await askReason('Тооцсон дүнг гараар засах', 'Засварын шалтгаан', 'Засах')
    if (!reason) return
    try { await override.mutateAsync({ employeeId: row.employee_id, field: overrideField, value: overrideValue, reason }); setOverrideValue(''); toast.success('Дүн засагдаж, хамааралтай дүнгүүд дахин бодогдлоо') } catch (error) { toast.error(requestError(error)) }
  }
  const revertOverride = async (field: string) => {
    const reason = await askReason('Автомат тооцоо руу буцаах', 'Шалтгаан', 'Буцаах')
    if (reason) revert.mutate({ employeeId: row.employee_id, field, reason }, { onSuccess: () => toast.success('Автомат тооцоонд буцлаа'), onError: (error) => toast.error(requestError(error)) })
  }
  const revertAllInputs = async () => {
    const reason = await askReason('Бүх гар оролтыг буцаах', 'Шалтгаан', 'Буцаах')
    if (reason) revertInputs.mutate({ employeeId: row.employee_id, reason }, { onSuccess: () => toast.success('Оролтыг цагийн бүртгэлийн утга руу буцаалаа'), onError: (error) => toast.error(requestError(error)) })
  }
  const pending = row.inputs._hr_pending

  // Portal to <body>: the workspace content sits below the app header's stacking context.
  return createPortal(<div className="mp-drawer-backdrop" onClick={onClose}>
    <aside className="mp-drawer" role="dialog" aria-modal="true" aria-labelledby="mp-drawer-title" onClick={(event) => event.stopPropagation()}>
      <header><div><span className="payroll-v2-kicker">{row.identity.department || 'Бусад'} · {row.identity.job_title || ''}</span><h2 id="mp-drawer-title">{row.identity.name}</h2>{row.warnings.length > 0 && <p>{row.warnings.map(warningLabel).join(' · ')}</p>}</div><button type="button" className="mp-icon-button" aria-label="Хаах" onClick={onClose}><X size={16} /></button></header>
      <div className="mp-tabs" role="tablist">{tabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
      <div className="mp-drawer-body">
        {tab === 'calculation' && <>
          <table className="mp-explain"><thead><tr><th>Багана</th><th>Томьёо</th><th>Оролт</th><th>Дүн</th></tr></thead><tbody>
            {explain(row, month, isFinal).map((item) => <tr key={item.label}><th>{item.label}<small className={item.manual ? 'manual' : 'auto'}>{item.manual ? 'гараар' : 'автомат'}</small></th><td>{item.formula}</td><td>{item.inputs}</td><td className="mp-num">{item.value}</td></tr>)}
          </tbody></table>
          {(() => { const figures = monthFigures(row); const sum = toNumber(figures.total_deductions) + toNumber(figures.net_pay); return <p className="mp-check">Шалгалт: суутгалын дүн + сүүл цалин = {formatAmount(sum)} {sum === toNumber(figures.gross) ? '= олговол зохих ✓' : '≠ олговол зохих ✗'}</p> })()}
          {!isFinal && <p className="mp-manual-note">Урьдчилгаанд НДШ, ХХОАТ суутгахгүй. Сарын дүн нь тооцоолсон төлөв бөгөөд эцсийн тооцоо сүүл цалингийн бодолтод хийгдэнэ.</p>}
          {(row.result.computed_overrides || []).length > 0 && <div className="mp-overrides"><strong>Гараар зассан дүн</strong>{(row.result.computed_overrides as string[]).map((field) => <span key={field}>{OVERRIDABLE.find(([key]) => key === field)?.[1] || field}{editable && <button type="button" className="payroll-v2-button secondary compact" onClick={() => revertOverride(field)}>Автомат болгох</button>}</span>)}</div>}
          {editable && row.profile.complete !== false && <div className="mp-override-form"><strong>Тооцсон дүнг засах</strong><select aria-label="Засах багана" value={overrideField} onChange={(event) => setOverrideField(event.target.value)}>{OVERRIDABLE.filter(([key]) => isFinal || key === 'advance').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><input aria-label="Шинэ дүн" type="number" min="0" value={overrideValue} placeholder={formatAmount(row.result[overrideField])} onChange={(event) => setOverrideValue(event.target.value)} /><button type="button" className="payroll-v2-button secondary compact" disabled={!overrideValue || override.isPending} onClick={applyOverride}>Засах</button><small>Доош урсах дүнгүүд (НДШ, татвар, сүүл цалин) дахин бодогдоно; гараар зассан дүн хэвээр үлдэнэ.</small></div>}
        </>}
        {tab === 'days' && <>{(row.inputs.day_lines || []).length ? <table className="mp-explain"><thead><tr><th>Огноо</th><th>Төрөл</th><th>Нийт цаг</th><th>Ердийн</th><th>Илүү</th><th>Эх сурвалж</th></tr></thead><tbody>{(row.inputs.day_lines as any[]).map((line) => <tr key={line.date}><td>{line.date}</td><td>{DAY_TYPES[line.day_type] || line.day_type}</td><td className="mp-num">{formatHours(line.hours)}</td><td className="mp-num">{formatHours(line.normal_hours)}</td><td className="mp-num">{formatHours(Object.values(line.overtime_hours || {}).reduce((sum: number, value) => sum + toNumber(value), 0))}</td><td>{SOURCES[line.source] || 'Ирц'}</td></tr>)}</tbody></table> : <p className="mp-empty">Цагийн бүртгэлээс өдрийн мөр ирээгүй — цагийг гараар эсвэл Excel-ээр оруулсан.</p>}
          {(row.inputs.missing_dates || []).length > 0 && <p className="mp-manual-note">Ирц дутуу өдөр: {(row.inputs.missing_dates as string[]).join(', ')}</p>}</>}
        {tab === 'advances' && <>{(row.result.advance_lines || []).length ? <table className="mp-explain"><thead><tr><th>Төлбөрийн өдөр</th><th>Бодолт</th><th>Дүн</th></tr></thead><tbody>{(row.result.advance_lines as any[]).map((line) => <tr key={line.run_id}><td>{line.pay_date || '—'}</td><td>#{line.run_id}</td><td className="mp-num">{formatAmount(line.amount)}</td></tr>)}</tbody><tfoot><tr><td colSpan={2}>Нийт татсан</td><td className="mp-num">{formatAmount(row.result.advance)}</td></tr></tfoot></table> : <p className="mp-empty">Энэ ажилтанд батлагдсан урьдчилгаа татагдаагүй.</p>}
          {row.warnings.includes('advance_not_calculated') && <p className="mp-manual-note">«Урьдчилгаа бодоогүй»: HR хуваарьт урьдчилгааны өдөр байгаа ч батлагдсан бодолт алга. Мэдсээр баталж болно.</p>}
          {row.warnings.includes('advance_changed') && <p className="mp-manual-note">«Урьдчилгаа өөрчлөгдсөн»: бодолтын толгойноос «Урьдчилгаа дахин татах»-ыг дарна уу.</p>}</>}
        {tab === 'deductions' && <div className="mp-deductions">
          {lines.map((line, index) => <div key={index} className="mp-deduction-line">
            <label>Төрөл<select disabled={!editable} value={line.type} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, type: event.target.value } : item))}><option value="">Сонгох</option>{deductionTypes.map((type) => <option key={type}>{type}</option>)}{line.type && !deductionTypes.includes(line.type) && <option>{line.type}</option>}</select></label>
            <label>Дүн<input disabled={!editable} type="number" min="1" value={line.amount} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, amount: event.target.value } : item))} /></label>
            <label>Тайлбар<input disabled={!editable} value={line.note} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, note: event.target.value } : item))} /></label>
            {editable && <button type="button" className="mp-icon-button" aria-label="Мөр хасах" onClick={() => setLines(lines.filter((_, i) => i !== index))}><Trash2 size={14} /></button>}
          </div>)}
          {!lines.length && <p className="mp-empty">Бусад суутгал алга.</p>}
          {editable && <div className="mp-dialog-actions"><button type="button" className="payroll-v2-button secondary compact" onClick={() => setLines([...lines, { type: deductionTypes[0], amount: '', note: '' }])}><Plus size={13} />Мөр нэмэх</button><button type="button" className="payroll-v2-button primary compact" disabled={save.isPending} onClick={saveLines}>Суутгал хадгалах</button></div>}
          <small>Бусад суутгал татвар, НДШ-ийн дараа хасагдана; НДШ, ХХОАТ-ын суурийг өөрчлөхгүй.</small>
        </div>}
        {tab === 'history' && <>
          {pending && <div className="mp-strip info"><span><strong>HR мэдээлэл өөрчлөгдсөн.</strong> {['name', 'job_title', 'department'].filter((key) => pending.identity?.[key] !== (row.identity as any)[key]).map((key) => `${key}: ${(row.identity as any)[key] || '—'} → ${pending.identity?.[key] || '—'}`).join('; ')}{['base_salary', 'salary_type', 'payment_frequency', 'advance_basis', 'meal_allowance', 'commute_allowance', 'allowance_basis'].filter((key) => JSON.stringify(pending.profile?.[key]) !== JSON.stringify((row.profile as any)[key])).map((key) => ` ${key}: ${brief((row.profile as any)[key])} → ${brief(pending.profile?.[key])}`).join(';')}</span>{editable && <button type="button" className="payroll-v2-button primary compact" disabled={acceptHR.isPending} onClick={() => acceptHR.mutate(row.employee_id, { onSuccess: () => toast.success('HR өөрчлөлтийг хүлээн авлаа'), onError: (error) => toast.error(requestError(error)) })}>Хүлээн авах</button>}</div>}
          {(row.audit || []).length ? <ol className="mp-audit">{[...(row.audit || [])].reverse().map((item, index) => <li key={index}><strong>{auditLabel(item.field)}</strong>{brief(item.old) || brief(item.new) ? <span>{brief(item.old)} → {brief(item.new)}</span> : null}<small>{item.reason || 'шалтгаангүй'} · {new Date(item.at).toLocaleString('mn-MN')}</small></li>)}</ol> : <p className="mp-empty">Засварын түүх алга — бүх дүн автомат.</p>}
          {editable && (row.audit || []).some((item) => ['inputs', 'excel_import'].includes(item.field)) && <button type="button" className="payroll-v2-button secondary compact" onClick={revertAllInputs}>Бүх гар оролтыг буцаах</button>}
        </>}
      </div>
    </aside>
  </div>, document.body)
}
