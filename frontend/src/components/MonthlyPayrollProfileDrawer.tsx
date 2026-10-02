import { useEffect, useMemo, useState } from 'react'
import { Banknote, CalendarDays, Check, Clock3, Plus, Save, ShieldCheck, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { intlLocale } from '../utils/locale'
import {
  useMonthlyPayrollPreview,
  useMonthlyPayrollProfile,
  usePayrollBankAccounts,
  useSaveMonthlyPayrollProfile,
  useSavePayrollBankAccount,
} from '../api/enterprise'
import type { MonthlyPayrollProfilePayload } from '../api/enterprise'
import { plainNumber } from '../utils/numbers'

const localToday = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
// A first salary normally applies to the whole month, not from today.
const monthStart = () => `${localToday().slice(0, 8)}01`
const daysFor = (frequency: MonthlyPayrollProfilePayload['payment_frequency']) => frequency === 'MONTHLY' ? [25] : frequency === 'BIWEEKLY' ? [10, 25] : [7, 14, 21, 28]
const requestMessage = (error: any, fallback: string) => {
  const detail = error?.response?.data?.detail
  return (typeof detail === 'string' ? detail : detail?.message) || fallback
}
const money = (value?: string) => `${new Intl.NumberFormat(intlLocale(), { maximumFractionDigits: 0 }).format(Number(value || 0))} ₮`
const emptyForm = (): MonthlyPayrollProfilePayload => ({
  base_salary: '', effective_from: monthStart(), salary_type: 'PRORATION', meal_allowance: '0', commute_allowance: '0', allowance_basis: 'FIXED', allowance_payout: 'FINAL',
  payment_frequency: 'MONTHLY', pay_days: [25], advance_basis: 'FIXED', advance_values: [], daily_norm_hours: '8', insured_type: '01001', tax_relief_eligible: true,
})

export function MonthlyPayrollProfileDrawer({ employee, onClose }: { employee: { id: number; name: string }; onClose: () => void }) {
  const { t } = useTranslation()
  const saved = useMonthlyPayrollProfile(employee.id)
  const save = useSaveMonthlyPayrollProfile()
  const banksQuery = usePayrollBankAccounts(employee.id)
  const saveBank = useSavePayrollBankAccount()
  const [form, setForm] = useState<MonthlyPayrollProfilePayload>(emptyForm)
  const [ready, setReady] = useState(false)
  const [previewForm, setPreviewForm] = useState<MonthlyPayrollProfilePayload>(form)
  const [bankOpen, setBankOpen] = useState(false)
  const [bank, setBank] = useState({ bank_code: '', account_number: '', account_holder: employee.name, valid_from: localToday(), valid_to: '', is_primary: true })
  const banks = banksQuery.data || []

  useEffect(() => {
    if (!saved.data) return
    const payload: any = { ...saved.data }
    delete payload.salary_history
    const numeric = Object.fromEntries(['base_salary', 'meal_allowance', 'commute_allowance', 'daily_norm_hours'].map((key) => [key, plainNumber(payload[key])]))
    setForm({ ...emptyForm(), ...payload, ...numeric, advance_values: (payload.advance_values || []).map(plainNumber) })
    setReady(true)
  }, [saved.data])

  useEffect(() => {
    const timer = window.setTimeout(() => setPreviewForm(form), 300)
    return () => window.clearTimeout(timer)
  }, [form])

  const advanceCount = Math.max(0, form.pay_days.length - 1)
  const legacyAllowance = form.allowance_basis === 'MONTHLY'
  const preview = useMonthlyPayrollPreview(employee.id, previewForm, previewForm.effective_from.slice(0, 7), ready && Boolean(previewForm.base_salary) && previewForm.allowance_basis !== 'MONTHLY')
  const advanceLabels = useMemo(() => form.payment_frequency === 'WEEKLY' ? [t('mp.pd.advance1'), t('mp.pd.advance2'), t('mp.pd.advance3')] : [t('mp.explain.advance')], [form.payment_frequency, t])

  const setFrequency = (frequency: MonthlyPayrollProfilePayload['payment_frequency']) => {
    const payDays = daysFor(frequency)
    const count = Math.max(0, payDays.length - 1)
    setForm((current) => ({ ...current, payment_frequency: frequency, pay_days: payDays, advance_values: current.advance_basis === 'WORKED-TO-DATE' ? [] : Array.from({ length: count }, (_, index) => current.advance_values[index] || (current.advance_basis === 'PERCENT' ? '40' : '0')) }))
  }
  const setBasis = (basis: MonthlyPayrollProfilePayload['advance_basis']) => setForm((current) => ({ ...current, advance_basis: basis, advance_values: basis === 'WORKED-TO-DATE' ? [] : Array.from({ length: advanceCount }, (_, index) => current.advance_values[index] || (basis === 'PERCENT' ? '40' : '0')) }))
  const setPayDay = (index: number, value: string) => setForm((current) => ({ ...current, pay_days: current.pay_days.map((day, row) => row === index ? Number(value) : day) }))
  const setAdvanceValue = (index: number, value: string) => setForm((current) => ({ ...current, advance_values: current.advance_values.map((item, row) => row === index ? value : item) }))

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    save.mutate({ employeeId: employee.id, ...form }, { onSuccess: () => toast.success(t('mp.pd.saved')), onError: (error: any) => toast.error(error?.response?.data?.detail?.message || t('mp.pd.saveFailed')) })
  }
  const submitBank = () => {
    saveBank.mutate({ employeeId: employee.id, ...bank, valid_to: bank.valid_to || null }, { onSuccess: () => { toast.success(t('mp.pd.bankSaved')); setBank({ ...bank, account_number: '' }); setBankOpen(false) }, onError: () => toast.error(t('mp.pd.bankSaveFailed')) })
  }

  return <div className="hr-drawer-backdrop monthly-payroll-backdrop" onClick={onClose}>
    <aside className="hr-drawer monthly-payroll-drawer" role="dialog" aria-modal="true" aria-labelledby="monthly-payroll-title" onClick={(event) => event.stopPropagation()}>
      <header className="monthly-payroll-heading">
        <div><span className="eyebrow">{t('mp.pd.kicker')}</span><h2 id="monthly-payroll-title">{employee.name}</h2><p>{t('mp.pd.subtitle')}</p></div>
        <button type="button" onClick={onClose} aria-label={t('mp.common.close')}><X size={18} /></button>
      </header>
      {saved.isLoading ? <p className="hr-payroll-loading">{t('mp.pd.loading')}</p> : saved.isError ? <div className="hr-payroll-loading" role="alert"><p>{requestMessage(saved.error, t('mp.pd.loadFailed'))}</p><button type="button" className="secondary-action" onClick={() => saved.refetch()}>{t('mp.pd.reload')}</button></div> : <form className="monthly-payroll-form" onSubmit={submit}>
        <section className="monthly-payroll-section">
          <div className="monthly-payroll-section-title"><Banknote size={18} /><div><h3>{t('mp.pd.basics')}</h3><p>{t('mp.pd.basicsHint')}</p></div></div>
          <label>{t('mp.pd.baseSalary')}<input required type="number" min="0" step="1" value={form.base_salary} onChange={(event) => setForm({ ...form, base_salary: event.target.value })} /></label>
          <label>{t('mp.set.validFromShort')}<input required type="date" value={form.effective_from} onChange={(event) => setForm({ ...form, effective_from: event.target.value })} /></label>
          <div className="monthly-payroll-two-col">
            <label>{t('mp.pd.salaryType')}<select value={form.salary_type} onChange={(event) => setForm({ ...form, salary_type: event.target.value as MonthlyPayrollProfilePayload['salary_type'] })}><option value="PRORATION">{t('mp.basis.WORKED-TO-DATE')}</option><option value="FIXED">{t('mp.pd.fullAmount')}</option></select></label>
            <label>{t('mp.pd.dailyNorm')}<input required type="number" min="0.25" max="24" step="0.25" value={form.daily_norm_hours} onChange={(event) => setForm({ ...form, daily_norm_hours: event.target.value })} /></label>
            <label>{t('mp.pd.allowanceCalc')}<select required value={form.allowance_basis} onChange={(event) => setForm({ ...form, allowance_basis: event.target.value as MonthlyPayrollProfilePayload['allowance_basis'] })}>{legacyAllowance && <option value="MONTHLY" disabled>{t('mp.pd.choose')}</option>}<option value="FIXED">{t('mp.pd.allowanceFixed')}</option><option value="WORKED_DAYS">{t('mp.pd.allowanceWorked')}</option></select></label>
            <label>{t('mp.pd.allowancePayout')}<select value={form.allowance_payout} onChange={(event) => setForm({ ...form, allowance_payout: event.target.value as MonthlyPayrollProfilePayload['allowance_payout'] })}><option value="FINAL">{t('mp.pd.withFinal')}</option><option value="ADVANCE">{t('mp.pd.withAdvance')}</option></select></label>
            <label>{t('mp.pd.meal')}<input type="number" min="0" step="1" value={form.meal_allowance} onChange={(event) => setForm({ ...form, meal_allowance: event.target.value })} /></label>
            <label>{t('mp.pd.commute')}<input type="number" min="0" step="1" value={form.commute_allowance} onChange={(event) => setForm({ ...form, commute_allowance: event.target.value })} /></label>
            <label>{t('mp.pd.insuredType')}<input required value={form.insured_type} onChange={(event) => setForm({ ...form, insured_type: event.target.value })} /></label>
          </div>
          <p className="monthly-payroll-help">{legacyAllowance
            ? t('mp.pd.legacyAllowance')
            : form.allowance_basis === 'FIXED'
              ? t('mp.pd.helpFixed')
              : t('mp.pd.helpWorked')}{form.allowance_payout === 'ADVANCE' ? ` ${t('mp.pd.allowanceAdvanceNote')}` : ` ${t('mp.pd.allowanceFinalNote')}`}</p>
          <label className="monthly-payroll-checkbox"><input type="checkbox" checked={form.tax_relief_eligible} onChange={(event) => setForm({ ...form, tax_relief_eligible: event.target.checked })} /><span>{t('mp.pd.taxRelief')}</span></label>
        </section>

        <section className="monthly-payroll-section schedule-section">
          <div className="monthly-payroll-section-title"><CalendarDays size={18} /><div><h3>{t('mp.pd.schedule')}</h3><p>{t('mp.pd.scheduleHint')}</p></div></div>
          <label>{t('mp.pd.frequency')}<select value={form.payment_frequency} onChange={(event) => setFrequency(event.target.value as MonthlyPayrollProfilePayload['payment_frequency'])}><option value="MONTHLY">{t('mp.pd.monthly')}</option><option value="BIWEEKLY">{t('mp.pd.biweekly')}</option><option value="WEEKLY">{t('mp.pd.weekly')}</option></select></label>
          <div className="monthly-payroll-paydays">{form.pay_days.map((day, index) => <label key={`${form.payment_frequency}-${index}`}>{form.payment_frequency === 'MONTHLY' ? t('mp.pd.payDay') : index === form.pay_days.length - 1 ? t('mp.dash.finalLabel') : advanceLabels[index]}<input aria-label={t('mp.pd.payDayN', { n: index + 1 })} type="number" min="1" max="31" value={day} onChange={(event) => setPayDay(index, event.target.value)} /></label>)}</div>
          {advanceCount > 0 && <div className="monthly-payroll-advance">
            <label>{t('mp.reg.aria.advanceBasis')}<select value={form.advance_basis} onChange={(event) => setBasis(event.target.value as MonthlyPayrollProfilePayload['advance_basis'])}><option value="FIXED">{t('mp.basis.FIXED')}</option><option value="PERCENT">{t('mp.set.basisPercent')}</option><option value="WORKED-TO-DATE">{t('mp.pd.basisWorkedToDate')}</option></select></label>
            {form.advance_basis === 'WORKED-TO-DATE' ? <p className="monthly-payroll-help"><Clock3 size={14} />{t('mp.pd.advanceByHours')}</p> : <div className="monthly-payroll-paydays">{Array.from({ length: advanceCount }, (_, index) => <label key={index}>{advanceLabels[index]} {form.advance_basis === 'PERCENT' ? '(%)' : '(₮)'}<input type="number" min="0" max={form.advance_basis === 'PERCENT' ? 100 : undefined} step={form.advance_basis === 'PERCENT' ? '0.01' : '1'} value={form.advance_values[index] || ''} onChange={(event) => setAdvanceValue(index, event.target.value)} required /></label>)}</div>}
          </div>}
        </section>

        <section className="monthly-payroll-preview">
          <div className="monthly-payroll-preview-head"><div><span>{t('mp.pd.previewKicker')}</span><h3>{preview.data?.month || form.effective_from.slice(0, 7)}</h3></div><ShieldCheck size={20} /></div>
          {form.base_salary && !form.effective_from.endsWith('-01') && <p className="monthly-payroll-help">{t('mp.pd.midMonthNote')}</p>}
          {!form.base_salary ? <p>{t('mp.pd.enterSalary')}</p> : preview.isFetching ? <p>{t('mp.pd.calculating')}</p> : preview.data ? <><div className="monthly-payroll-estimate-grid"><span>{t('mp.pd.totalPay')}<strong>{money(preview.data.gross)}</strong></span><span>{t('mp.dash.employeeShi')}<strong>{money(preview.data.employee_shi)}</strong></span><span>{t('mp.pd.taxBase')}<strong>{money(preview.data.taxable_income)}</strong></span><span>{t('mp.pd.pitRelief')}<strong>{money(preview.data.relief)}</strong></span><span>{t('mp.dash.pit')}<strong>{money(preview.data.pit)}</strong></span><span className="take-home">{t('mp.dash.cash')}<strong>{money(preview.data.net_pay)}</strong></span></div>{preview.data.advance_schedule.length > 0 && <div className="monthly-payroll-advance-estimates"><strong>{t('mp.pd.advanceSchedule')}</strong>{preview.data.advance_schedule.map((row) => <span key={row.pay_date}>{row.pay_date} <b>{money(row.estimated_amount)}</b></span>)}</div>}</> : <p>{preview.error ? requestMessage(preview.error, t('mp.pd.previewFailed')) : t('mp.pd.previewPreparing')}</p>}
        </section>

        <section className="monthly-payroll-section monthly-payroll-bank">
          <div className="monthly-payroll-section-title"><Banknote size={18} /><div><h3>{t('mp.pd.bank')}</h3><p>{t('mp.pd.bankHint')}</p></div><button type="button" className="secondary-action" onClick={() => setBankOpen((value) => !value)}><Plus size={14} />{t('mp.reg.notice.add')}</button></div>
          {banks.map((account: any) => <div className="monthly-payroll-bank-row" key={account.id}><strong>{account.bank_code} ···· {account.account_last4}</strong><span>{account.valid_from} – {account.valid_to || t('mp.pd.untilNow')}</span>{account.is_primary && <small>{t('mp.pd.primary')}</small>}</div>)}
          {!banks.length && <p className="monthly-payroll-help">{t('mp.pd.noBank')}</p>}
          {bankOpen && <div className="monthly-payroll-bank-form"><label>{t('mp.pd.bankName')}<input required value={bank.bank_code} onChange={(event) => setBank({ ...bank, bank_code: event.target.value })} placeholder="KHAN" /></label><label>{t('mp.pd.accountNumber')}<input required value={bank.account_number} onChange={(event) => setBank({ ...bank, account_number: event.target.value })} /></label><label>{t('mp.pd.accountHolder')}<input value={bank.account_holder} onChange={(event) => setBank({ ...bank, account_holder: event.target.value })} /></label><label>{t('mp.pd.validFromBank')}<input required type="date" value={bank.valid_from} onChange={(event) => setBank({ ...bank, valid_from: event.target.value })} /></label><button type="button" className="secondary-action" disabled={saveBank.isPending || !bank.bank_code || !bank.account_number} onClick={submitBank}><Save size={14} />{t('mp.pd.saveBank')}</button></div>}
        </section>

        {saved.data?.salary_history?.length ? <section className="monthly-payroll-history"><strong>{t('mp.pd.history')}</strong>{saved.data.salary_history.map((row) => <span key={row.valid_from}>{row.valid_from}<b>{money(row.monthly_salary)}</b></span>)}</section> : null}
        <footer className="monthly-payroll-footer"><button type="button" className="secondary-action" onClick={onClose}>{t('mp.common.close')}</button><button className="primary-action" disabled={!ready || !form.base_salary || legacyAllowance || save.isPending}><Check size={14} />{save.isPending ? t('mp.pd.saving') : t('mp.set.saveSettings')}</button></footer>
      </form>}
    </aside>
  </div>
}
