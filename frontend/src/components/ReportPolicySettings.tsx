import { useEffect, useMemo, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { useReportPolicy, useUpdateReportPolicy, type CustomReportPeriod, type DepartmentReportRule, type ReportPolicyInput } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

const STANDARD = [
  { value: 'daily', label: 'Өдөр' },
  { value: 'weekly', label: '7 хоног' },
  { value: 'monthly', label: 'Сар' },
  { value: 'quarterly', label: 'Улирал' },
  { value: 'yearly', label: 'Жил' },
]
const UNIT_LABELS: Record<CustomReportPeriod['unit'], string> = { day: 'өдөр', week: '7 хоног', month: 'сар' }

function slugify(label: string, taken: Set<string>) {
  const base = label.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30) || 'period'
  let candidate = base
  for (let index = 2; taken.has(candidate); index += 1) candidate = `${base}-${index}`
  return candidate
}

function toggle(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

function FrequencyPicker({ options, value, onChange, disabled, exclude = [], label }: { options: { value: string; label: string }[]; value: string[]; onChange: (next: string[]) => void; disabled?: boolean; exclude?: string[]; label: string }) {
  return <fieldset className="report-frequency-picker role-editor" disabled={disabled}>
    <legend>{label}</legend>
    {options.filter((option) => !exclude.includes(option.value)).map((option) => <label key={option.value}>
      <input type="checkbox" checked={value.includes(option.value)} onChange={() => onChange(toggle(value, option.value))} />
      <span>{option.label}</span>
    </label>)}
  </fieldset>
}

/**
 * Admin report policy: company worker frequencies, custom periods and
 * department rules (worker override + department-level reports).
 */
export function ReportPolicySettings() {
  const policy = useReportPolicy()
  const update = useUpdateReportPolicy()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const [form, setForm] = useState<ReportPolicyInput | null>(null)
  const [newPeriod, setNewPeriod] = useState<Omit<CustomReportPeriod, 'id'>>({ label: '', unit: 'week', interval: 2, anchor_date: new Date().toISOString().slice(0, 10) })

  useEffect(() => {
    if (!policy.data) return
    setForm({
      worker_frequencies: policy.data.worker_frequencies,
      custom_periods: policy.data.custom_periods,
      departments: policy.data.departments,
      reminder_days: policy.data.reminder_days,
    })
  }, [policy.data])

  const frequencyOptions = useMemo(() => [
    ...STANDARD,
    ...(form?.custom_periods ?? []).map((item) => ({ value: `custom:${item.id}`, label: item.label })),
  ], [form?.custom_periods])

  if (policy.isLoading || !form) return <p className="query-region-state">Тайлангийн тохиргоог ачаалж байна…</p>
  if (policy.isError) return <p className="query-region-state" role="alert">Тайлангийн тохиргоог ачаалж чадсангүй.</p>

  const departments = policy.data?.department_options ?? []
  const ruleFor = (departmentId: number): DepartmentReportRule | undefined => form.departments.find((item) => item.department_id === departmentId)
  const setRule = (departmentId: number, patch: Partial<DepartmentReportRule> | null) => {
    const others = form.departments.filter((item) => item.department_id !== departmentId)
    if (patch === null) return setForm({ ...form, departments: others })
    const current = ruleFor(departmentId) ?? { department_id: departmentId, worker_frequencies: null, department_frequencies: [] }
    setForm({ ...form, departments: [...others, { ...current, ...patch }] })
  }
  const addCustomPeriod = () => {
    const label = newPeriod.label.trim()
    if (!label) return
    const id = slugify(label, new Set(form.custom_periods.map((item) => item.id)))
    setForm({ ...form, custom_periods: [...form.custom_periods, { ...newPeriod, label, id }] })
    setNewPeriod({ ...newPeriod, label: '' })
  }
  const removeCustomPeriod = (id: string) => {
    const frequency = `custom:${id}`
    setForm({
      ...form,
      custom_periods: form.custom_periods.filter((item) => item.id !== id),
      worker_frequencies: form.worker_frequencies.filter((item) => item !== frequency),
      departments: form.departments.map((rule) => ({
        ...rule,
        worker_frequencies: rule.worker_frequencies?.filter((item) => item !== frequency) ?? null,
        department_frequencies: rule.department_frequencies.filter((item) => item !== frequency),
      })),
    })
  }
  const save = () => update.mutate({
    ...form,
    // Drop rules that no longer change anything.
    departments: form.departments.filter((rule) => rule.worker_frequencies !== null || rule.department_frequencies.length > 0),
  })

  return <div className="report-policy-settings">
    {!canEdit && <p className="settings-readonly-note">Зөвхөн админ өөрчилнө. Та тохиргоог харах боломжтой.</p>}
    <section className="report-policy-block">
      <h3>Ажилтны тайлангийн давтамж</h3>
      <p>Сонгосон хугацаа бүрт ажилтанд сануулга очиж, тайлан автоматаар үүснэ. Бусад төрлийн тайлан ажилтны жагсаалтад харагдахгүй.</p>
      <FrequencyPicker label="Компанийн бүх ажилтан" options={frequencyOptions} value={form.worker_frequencies} onChange={(next) => setForm({ ...form, worker_frequencies: next })} disabled={!canEdit} />
      <label className="report-reminder-days">Хугацаа дуусахаас өмнө сануулах өдөр
        <input type="number" min={1} max={14} value={form.reminder_days} disabled={!canEdit} onChange={(event) => setForm({ ...form, reminder_days: Math.max(1, Math.min(14, Number(event.target.value) || 1)) })} />
      </label>
    </section>

    <section className="report-policy-block">
      <h3>Тусгай хугацаа</h3>
      <p>Жишээ нь “Хагас жил” (6 сар тутам) эсвэл “Спринт” (2 долоо хоног тутам). Эхлэх огнооноос тоологдоно.</p>
      {form.custom_periods.length > 0 && <ul className="report-custom-list">{form.custom_periods.map((item) => <li key={item.id}>
        <span><strong>{item.label}</strong><small>{item.interval} {UNIT_LABELS[item.unit]} тутам · {item.anchor_date}-с</small></span>
        {canEdit && <button type="button" className="danger-action compact" onClick={() => removeCustomPeriod(item.id)} aria-label={`${item.label} устгах`}><Trash2 size={14} /></button>}
      </li>)}</ul>}
      {canEdit && <div className="report-custom-form">
        <label>Нэр<input value={newPeriod.label} maxLength={80} onChange={(event) => setNewPeriod({ ...newPeriod, label: event.target.value })} placeholder="Хагас жил" /></label>
        <label>Тутам<input type="number" min={1} max={newPeriod.unit === 'day' ? 366 : newPeriod.unit === 'week' ? 52 : 24} value={newPeriod.interval} onChange={(event) => setNewPeriod({ ...newPeriod, interval: Math.max(1, Number(event.target.value) || 1) })} /></label>
        <label>Нэгж<select value={newPeriod.unit} onChange={(event) => setNewPeriod({ ...newPeriod, unit: event.target.value as CustomReportPeriod['unit'] })}><option value="day">өдөр</option><option value="week">7 хоног</option><option value="month">сар</option></select></label>
        <label>Эхлэх огноо<input type="date" value={newPeriod.anchor_date} onChange={(event) => setNewPeriod({ ...newPeriod, anchor_date: event.target.value })} /></label>
        <button type="button" className="secondary-action compact" onClick={addCustomPeriod} disabled={!newPeriod.label.trim() || form.custom_periods.length >= 12}><Plus size={14} />Нэмэх</button>
      </div>}
    </section>

    <section className="report-policy-block">
      <h3>Хэлтсээр</h3>
      <p>Хэлтэс бүрт ажилтны давтамжийг өөрчлөх, мөн хэлтсийн даргаар бичүүлэх хэлтсийн тайлан тохируулна.</p>
      {departments.length === 0 ? <p className="query-region-state">Хэлтэс бүртгэгдээгүй байна. HR хэсгээс хэлтэс нэмнэ үү.</p> : <div className="report-department-list">{departments.map((department) => {
        const rule = ruleFor(department.id)
        const overrides = rule?.worker_frequencies != null
        return <article key={department.id} className="report-department-rule panel">
          <header><strong>{department.name}</strong><small>{department.manager_name ? `Дарга: ${department.manager_name}` : 'Хэлтсийн дарга томилогдоогүй — хэлтсийн тайлан илгээгдэхгүй'}</small></header>
          <label className="report-override-toggle"><input type="checkbox" checked={overrides} disabled={!canEdit} onChange={() => setRule(department.id, { worker_frequencies: overrides ? null : [...form.worker_frequencies] })} /><span>Энэ хэлтсийн ажилтанд өөр давтамж</span></label>
          {overrides && <FrequencyPicker label="Ажилтны тайлан" options={frequencyOptions} value={rule?.worker_frequencies ?? []} onChange={(next) => setRule(department.id, { worker_frequencies: next })} disabled={!canEdit} />}
          <FrequencyPicker label="Хэлтсийн тайлан (даргаар)" options={frequencyOptions} exclude={['daily']} value={rule?.department_frequencies ?? []} onChange={(next) => setRule(department.id, { department_frequencies: next })} disabled={!canEdit} />
        </article>
      })}</div>}
    </section>

    {canEdit && <div className="report-policy-actions"><button type="button" className="primary-action" onClick={save} disabled={update.isPending}><Save size={16} />Хадгалах</button></div>}
  </div>
}
