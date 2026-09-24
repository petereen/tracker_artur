import { useEffect, useMemo, useState } from 'react'
import { Banknote, CalendarDays, Check, Clock3, Plus, Save, ShieldCheck, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useMonthlyPayrollPreview,
  useMonthlyPayrollProfile,
  usePayrollBankAccounts,
  useSaveMonthlyPayrollProfile,
  useSavePayrollBankAccount,
} from '../api/enterprise'
import type { MonthlyPayrollProfilePayload } from '../api/enterprise'

const localToday = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
const daysFor = (frequency: MonthlyPayrollProfilePayload['payment_frequency']) => frequency === 'MONTHLY' ? [25] : frequency === 'BIWEEKLY' ? [10, 25] : [7, 14, 21, 28]
const money = (value?: string) => `${new Intl.NumberFormat('mn-MN', { maximumFractionDigits: 0 }).format(Number(value || 0))} ₮`
const emptyForm = (): MonthlyPayrollProfilePayload => ({
  base_salary: '', effective_from: localToday(), salary_type: 'PRORATION', meal_allowance: '0', commute_allowance: '0',
  payment_frequency: 'MONTHLY', pay_days: [25], advance_basis: 'FIXED', advance_values: [], daily_norm_hours: '8', insured_type: '01001', tax_relief_eligible: true,
})

export function MonthlyPayrollProfileDrawer({ employee, onClose }: { employee: { id: number; name: string }; onClose: () => void }) {
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
    setForm({ ...emptyForm(), ...payload, advance_values: payload.advance_values || [] })
    setReady(true)
  }, [saved.data])

  useEffect(() => {
    const timer = window.setTimeout(() => setPreviewForm(form), 300)
    return () => window.clearTimeout(timer)
  }, [form])

  const advanceCount = Math.max(0, form.pay_days.length - 1)
  const preview = useMonthlyPayrollPreview(employee.id, previewForm, previewForm.effective_from.slice(0, 7), ready && Boolean(previewForm.base_salary))
  const advanceLabels = useMemo(() => form.payment_frequency === 'WEEKLY' ? ['1-р урьдчилгаа', '2-р урьдчилгаа', '3-р урьдчилгаа'] : ['Урьдчилгаа'], [form.payment_frequency])

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
    save.mutate({ employeeId: employee.id, ...form }, { onSuccess: () => toast.success('Цалингийн тохиргоо хадгалагдлаа'), onError: (error: any) => toast.error(error?.response?.data?.detail?.message || 'Цалингийн тохиргоо хадгалж чадсангүй') })
  }
  const submitBank = () => {
    saveBank.mutate({ employeeId: employee.id, ...bank, valid_to: bank.valid_to || null }, { onSuccess: () => { toast.success('Банкны данс хадгалагдлаа'); setBank({ ...bank, account_number: '' }); setBankOpen(false) }, onError: () => toast.error('Банкны данс хадгалж чадсангүй') })
  }

  return <div className="hr-drawer-backdrop monthly-payroll-backdrop" onClick={onClose}>
    <aside className="hr-drawer monthly-payroll-drawer" role="dialog" aria-modal="true" aria-labelledby="monthly-payroll-title" onClick={(event) => event.stopPropagation()}>
      <header className="monthly-payroll-heading">
        <div><span className="eyebrow">ЦАЛИНГИЙН ТОХИРГОО</span><h2 id="monthly-payroll-title">{employee.name}</h2><p>Хүчинтэй огноотой цалингийн нөхцөл</p></div>
        <button type="button" onClick={onClose} aria-label="Хаах"><X size={18} /></button>
      </header>
      {saved.isLoading ? <p className="hr-payroll-loading">Ажилтны цалингийн тохиргоог ачаалж байна…</p> : <form className="monthly-payroll-form" onSubmit={submit}>
        <section className="monthly-payroll-section">
          <div className="monthly-payroll-section-title"><Banknote size={18} /><div><h3>Үндсэн нөхцөл</h3><p>Өөрчлөлт бүр цалингийн түүхэд хадгалагдана.</p></div></div>
          <label>Үндсэн цалин (₮)<input required type="number" min="0" step="1" value={form.base_salary} onChange={(event) => setForm({ ...form, base_salary: event.target.value })} /></label>
          <label>Хүчинтэй эхлэх огноо<input required type="date" value={form.effective_from} onChange={(event) => setForm({ ...form, effective_from: event.target.value })} /></label>
          <div className="monthly-payroll-two-col">
            <label>Цалингийн төрөл<select value={form.salary_type} onChange={(event) => setForm({ ...form, salary_type: event.target.value as MonthlyPayrollProfilePayload['salary_type'] })}><option value="PRORATION">Ажилласан цагаар</option><option value="FIXED">Бүтэн дүнгээр</option></select></label>
            <label>Өдрийн норм (цаг)<input required type="number" min="0.25" max="24" step="0.25" value={form.daily_norm_hours} onChange={(event) => setForm({ ...form, daily_norm_hours: event.target.value })} /></label>
            <label>Хоол (₮)<input type="number" min="0" step="1" value={form.meal_allowance} onChange={(event) => setForm({ ...form, meal_allowance: event.target.value })} /></label>
            <label>Унаа (₮)<input type="number" min="0" step="1" value={form.commute_allowance} onChange={(event) => setForm({ ...form, commute_allowance: event.target.value })} /></label>
            <label>Даатгалын төрөл<input required value={form.insured_type} onChange={(event) => setForm({ ...form, insured_type: event.target.value })} /></label>
          </div>
          <label className="monthly-payroll-checkbox"><input type="checkbox" checked={form.tax_relief_eligible} onChange={(event) => setForm({ ...form, tax_relief_eligible: event.target.checked })} /><span>ХХОАТ-ын хөнгөлөлт тооцох</span></label>
        </section>

        <section className="monthly-payroll-section schedule-section">
          <div className="monthly-payroll-section-title"><CalendarDays size={18} /><div><h3>Төлбөрийн хуваарь</h3><p>Өдрүүдийг тухайн сарын календарьт тааруулна.</p></div></div>
          <label>Давтамж<select value={form.payment_frequency} onChange={(event) => setFrequency(event.target.value as MonthlyPayrollProfilePayload['payment_frequency'])}><option value="MONTHLY">Сард нэг удаа</option><option value="BIWEEKLY">Сард хоёр удаа</option><option value="WEEKLY">Долоо хоног бүр</option></select></label>
          <div className="monthly-payroll-paydays">{form.pay_days.map((day, index) => <label key={`${form.payment_frequency}-${index}`}>{form.payment_frequency === 'MONTHLY' ? 'Цалин олгох өдөр' : index === form.pay_days.length - 1 ? 'Сүүл цалин' : advanceLabels[index]}<input aria-label={`${index + 1}-р төлбөрийн өдөр`} type="number" min="1" max="31" value={day} onChange={(event) => setPayDay(index, event.target.value)} /></label>)}</div>
          {advanceCount > 0 && <div className="monthly-payroll-advance">
            <label>Урьдчилгааны суурь<select value={form.advance_basis} onChange={(event) => setBasis(event.target.value as MonthlyPayrollProfilePayload['advance_basis'])}><option value="FIXED">Тогтмол дүн</option><option value="PERCENT">Үндсэн цалингийн хувь</option><option value="WORKED-TO-DATE">Тухайн өдөр хүртэл ажилласнаар</option></select></label>
            {form.advance_basis === 'WORKED-TO-DATE' ? <p className="monthly-payroll-help"><Clock3 size={14} />Урьдчилгааг цалингийн өдөр хүртэлх ажилласан цагаар тооцно.</p> : <div className="monthly-payroll-paydays">{Array.from({ length: advanceCount }, (_, index) => <label key={index}>{advanceLabels[index]} {form.advance_basis === 'PERCENT' ? '(%)' : '(₮)'}<input type="number" min="0" max={form.advance_basis === 'PERCENT' ? 100 : undefined} step={form.advance_basis === 'PERCENT' ? '0.01' : '1'} value={form.advance_values[index] || ''} onChange={(event) => setAdvanceValue(index, event.target.value)} required /></label>)}</div>}
          </div>}
        </section>

        <section className="monthly-payroll-preview">
          <div className="monthly-payroll-preview-head"><div><span>БҮТЭН САРЫН ТООЦОО</span><h3>{preview.data?.month || form.effective_from.slice(0, 7)}</h3></div><ShieldCheck size={20} /></div>
          {!form.base_salary ? <p>Үндсэн цалин оруулбал тооцооны урьдчилсан дүн гарна.</p> : preview.isFetching ? <p>Тооцоолж байна…</p> : preview.data ? <><div className="monthly-payroll-estimate-grid"><span>Нийт цалин<strong>{money(preview.data.gross)}</strong></span><span>Ажилтны НДШ<strong>{money(preview.data.employee_shi)}</strong></span><span>Татварын суурь<strong>{money(preview.data.taxable_income)}</strong></span><span>ХХОАТ хөнгөлөлт<strong>{money(preview.data.relief)}</strong></span><span>ХХОАТ<strong>{money(preview.data.pit)}</strong></span><span className="take-home">Гарт олгох<strong>{money(preview.data.net_pay)}</strong></span></div>{preview.data.advance_schedule.length > 0 && <div className="monthly-payroll-advance-estimates"><strong>Урьдчилгааны хуваарь</strong>{preview.data.advance_schedule.map((row) => <span key={row.pay_date}>{row.pay_date} <b>{money(row.estimated_amount)}</b></span>)}</div>}</> : <p>{preview.error ? 'Тооцооны дүрэм олдсонгүй. Татварын тохиргоог шалгана уу.' : 'Тооцооны дүн бэлдэж байна.'}</p>}
        </section>

        <section className="monthly-payroll-section monthly-payroll-bank">
          <div className="monthly-payroll-section-title"><Banknote size={18} /><div><h3>Банкны данс</h3><p>Цалингийн төлбөрийн жагсаалтад ашиглана.</p></div><button type="button" className="secondary-action" onClick={() => setBankOpen((value) => !value)}><Plus size={14} />Нэмэх</button></div>
          {banks.map((account: any) => <div className="monthly-payroll-bank-row" key={account.id}><strong>{account.bank_code} ···· {account.account_last4}</strong><span>{account.valid_from} – {account.valid_to || 'одоог хүртэл'}</span>{account.is_primary && <small>Үндсэн</small>}</div>)}
          {!banks.length && <p className="monthly-payroll-help">Банкны данс бүртгээгүй.</p>}
          {bankOpen && <div className="monthly-payroll-bank-form"><label>Банк<input required value={bank.bank_code} onChange={(event) => setBank({ ...bank, bank_code: event.target.value })} placeholder="KHAN" /></label><label>Дансны дугаар<input required value={bank.account_number} onChange={(event) => setBank({ ...bank, account_number: event.target.value })} /></label><label>Данс эзэмшигч<input value={bank.account_holder} onChange={(event) => setBank({ ...bank, account_holder: event.target.value })} /></label><label>Хүчинтэй эхлэх<input required type="date" value={bank.valid_from} onChange={(event) => setBank({ ...bank, valid_from: event.target.value })} /></label><button type="button" className="secondary-action" disabled={saveBank.isPending || !bank.bank_code || !bank.account_number} onClick={submitBank}><Save size={14} />Данс хадгалах</button></div>}
        </section>

        {saved.data?.salary_history?.length ? <section className="monthly-payroll-history"><strong>Цалингийн өөрчлөлтийн түүх</strong>{saved.data.salary_history.map((row) => <span key={row.valid_from}>{row.valid_from}<b>{money(row.monthly_salary)}</b></span>)}</section> : null}
        <footer className="monthly-payroll-footer"><button type="button" className="secondary-action" onClick={onClose}>Хаах</button><button className="primary-action" disabled={!ready || !form.base_salary || save.isPending}><Check size={14} />{save.isPending ? 'Хадгалж байна…' : 'Тохиргоо хадгалах'}</button></footer>
      </form>}
    </aside>
  </div>
}
