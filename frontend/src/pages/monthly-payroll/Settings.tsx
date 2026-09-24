import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import {
  useCreateMonthlyPayrollRuleDraft, useERPAccountOptions, useMonthlyPayrollCalendar, useMonthlyPayrollMonths, useMonthlyPayrollRuleSets,
  useMonthlyPayrollRuleTemplate, useMonthlyPayrollSettings, usePayrollCapabilities, usePublishMonthlyPayrollRuleDraft,
  useSaveMonthlyPayrollSettings, useSetMonthlyPayrollCalendarDay, useUpdateMonthlyPayrollRuleDraft, useValidateMonthlyPayrollRuleDraft,
} from '../../api/enterprise'
import type { MonthlyPayrollCompanySettings, MonthlyPayrollRuleSet } from '../../api/enterprise'
import { MonthStepper, MonthlyShell, monthKey, parseMonthKey, requestError } from './shared'

export function MonthlyPayrollSettingsPage() {
  const caps = usePayrollCapabilities()
  const now = new Date()
  const [calendarMonth, setCalendarMonth] = useState(monthKey(now.getFullYear(), now.getMonth() + 1))
  const { year, month } = parseMonthKey(calendarMonth)
  if (caps.data && !caps.data.capabilities.administer) return <MonthlyShell><p className="mp-empty">Цалингийн тохиргоог зөвхөн админ өөрчилнө.</p></MonthlyShell>
  return <MonthlyShell canAdminister>
    <header className="payroll-v2-page-title"><div><h1>Цалингийн тохиргоо</h1><p>Байгууллагын тохиргоо, хуулийн дүрмийн хувилбар, ажлын календарь. Нээсэн сарууд өөрийн хуулбарыг хадгална.</p></div></header>
    <MonthlySettingsPanel />
    <MonthlyRuleSetEditor />
    <section className="payroll-v2-stage-card"><div className="payroll-v2-section-head"><h2>Ажлын календарь</h2><MonthStepper value={calendarMonth} onChange={setCalendarMonth} /></div><MonthlyCalendarEditor year={year} monthNumber={month} /></section>
  </MonthlyShell>
}

function MonthlySettingsPanel() {
  const settings = useMonthlyPayrollSettings()
  const save = useSaveMonthlyPayrollSettings()
  const accounts = useERPAccountOptions()
  const [draft, setDraft] = useState<MonthlyPayrollCompanySettings | null>(null)
  useEffect(() => { if (settings.data) setDraft(settings.data) }, [settings.data])
  if (!draft) return null
  const update = (key: keyof MonthlyPayrollCompanySettings, value: any) => setDraft((currentDraft) => currentDraft ? { ...currentDraft, [key]: value } : currentDraft)
  return <details open className="payroll-v2-stage-card monthly-settings"><summary><strong>Байгууллагын цалингийн тохиргоо</strong></summary><div className="monthly-settings-grid">
    <label>Компанийн нэр<input value={draft.legal_company_name || ''} onChange={(event) => update('legal_company_name', event.target.value || null)} /></label>
    <label>Өдрийн норм цаг<input type="number" min="1" max="24" step="0.25" value={draft.daily_norm_hours} onChange={(event) => update('daily_norm_hours', event.target.value)} /></label>
    <label>ҮОМШӨ хувь (%) · БНДШ {(12 + Number(draft.employer_injury_rate || 0) * 100).toFixed(1)}%<input type="number" min="0.5" max="2.5" step="0.1" value={String(Math.round(Number(draft.employer_injury_rate || 0) * 1000) / 10)} onChange={(event) => update('employer_injury_rate', String(Number(event.target.value || 0) / 100))} /></label>
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
  const months = useMonthlyPayrollMonths()
  const locked = Boolean(months.data?.some((item) => item.year === year && item.month === monthNumber))
  const [names, setNames] = useState<Record<string, string>>({})
  const change = (date: string, day_type: 'working' | 'weekly_rest' | 'public_holiday', holiday_name: string | null) => update.mutate({ date, day_type, holiday_name }, { onError: (error) => toast.error(requestError(error)) })
  const working = days.data?.filter((day) => day.day_type === 'working').length || 0
  return <div className="monthly-calendar">
    <p className="payroll-v2-muted">{locked ? 'Энэ сарын цалингийн бодолт нээгдсэн тул календарь хадгалагдсан хуулбараар түгжигдсэн.' : `Ажлын ${working} өдөр. Шилжүүлсэн бямба гарагийг «Ажлын өдөр», баярыг «Нийтийн амралт» болгоно.`}</p>
    <div className="monthly-calendar-grid">{days.data?.map((day) => <div key={day.date} className={`mp-calendar-day ${day.day_type}`}>
      <strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString('mn-MN', { weekday: 'short', day: 'numeric' })}</strong>
      <select aria-label={`${day.date} өдрийн төрөл`} value={day.day_type} disabled={locked || update.isPending} onChange={(event) => change(day.date, event.target.value as typeof day.day_type, event.target.value === 'public_holiday' ? (names[day.date] ?? day.holiday_name ?? null) : null)}><option value="working">Ажлын өдөр</option><option value="weekly_rest">Амралтын өдөр</option><option value="public_holiday">Нийтийн амралт</option></select>
      {day.day_type === 'public_holiday' && <input aria-label={`${day.date} баярын нэр`} placeholder="Баярын нэр" disabled={locked} value={names[day.date] ?? day.holiday_name ?? ''} onChange={(event) => setNames((current) => ({ ...current, [day.date]: event.target.value }))} onBlur={() => names[day.date] !== undefined && names[day.date] !== (day.holiday_name || '') && change(day.date, 'public_holiday', names[day.date] || null)} />}
    </div>)}</div>
  </div>
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

