import i18n from '../i18n'
import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { useReportPolicy, useUpdateReportPolicy, type CustomReportPeriod, type DepartmentReportRule, type ReportFrequencySettings, type ReportPolicyInput } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

const STANDARD = [
  { value: 'daily', get label() { return i18n.t('reports.policy.std.daily') } },
  { value: 'weekly', get label() { return i18n.t('reports.policy.std.weekly') } },
  { value: 'monthly', get label() { return i18n.t('reports.policy.std.monthly') } },
  { value: 'quarterly', get label() { return i18n.t('reports.policy.std.quarterly') } },
  { value: 'half_yearly', get label() { return i18n.t('reports.policy.std.half_yearly') } },
  { value: 'yearly', get label() { return i18n.t('reports.policy.std.yearly') } },
]
const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const weekdayName = (index: number) => i18n.t(`reports.policy.weekday.${WEEKDAY_KEYS[index]}`)
const monthName = (index: number) => i18n.t('reports.policy.monthN', { n: index + 1 })
const MONTH_SPAN_FREQUENCIES = new Set(['quarterly', 'half_yearly', 'yearly'])
const DAYS_OF_MONTH = Array.from({ length: 28 }, (_, index) => index + 1)
const HOURS = Array.from({ length: 24 }, (_, index) => index)

function defaultSettings(frequency: string): ReportFrequencySettings {
  const settings: ReportFrequencySettings = { reminder_days: null, due_days: 0, reminder_hour: null }
  if (frequency === 'weekly') settings.start_weekday = 0
  if (frequency === 'monthly' || MONTH_SPAN_FREQUENCIES.has(frequency)) settings.start_day = 1
  if (MONTH_SPAN_FREQUENCIES.has(frequency)) settings.start_month = 1
  return settings
}

function numberOrNull(value: string, min: number, max: number) {
  if (value.trim() === '') return null
  const number = Math.round(Number(value))
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : null
}

/** Period start and reminder schedule of one report frequency. */
function FrequencyScheduleCard({ frequency, label, value, onChange, disabled, companyReminderDays, preview }: { frequency: string; label: string; value: ReportFrequencySettings; onChange: (next: ReportFrequencySettings) => void; disabled: boolean; companyReminderDays: number; preview?: { start: string; end: string; due: string } }) {
  const { t } = useTranslation()
  const set = (patch: Partial<ReportFrequencySettings>) => onChange({ ...value, ...patch })
  const monthSpan = MONTH_SPAN_FREQUENCIES.has(frequency)
  return <article className="report-schedule-card panel" aria-label={t('reports.policy.scheduleLabel', { label })}>
    <header><strong>{label}</strong>{preview && <small>{t('reports.policy.currentPeriod')} {preview.start} – {preview.end}{preview.due !== preview.end ? t('reports.create.dueDateHint', { date: preview.due }) : ''}</small>}</header>
    <div className="report-schedule-grid">
      {frequency === 'weekly' && <label>{t('reports.policy.weekStartDay')}<select value={value.start_weekday ?? 0} disabled={disabled} onChange={(event) => set({ start_weekday: Number(event.target.value) })}>{WEEKDAY_KEYS.map((day, index) => <option key={day} value={index}>{weekdayName(index)}</option>)}</select></label>}
      {monthSpan && <label>{frequency === 'yearly' ? t('reports.policy.fiscalStartMonth') : t('reports.policy.firstPeriodStartMonth')}<select value={value.start_month ?? 1} disabled={disabled} onChange={(event) => set({ start_month: Number(event.target.value) })}>{Array.from({ length: 12 }, (_, index) => <option key={index} value={index + 1}>{monthName(index)}</option>)}</select></label>}
      {(frequency === 'monthly' || monthSpan) && <label>{t('reports.policy.startDayOfMonth')}<select value={value.start_day ?? 1} disabled={disabled} onChange={(event) => set({ start_day: Number(event.target.value) })}>{DAYS_OF_MONTH.map((day) => <option key={day} value={day}>{day}</option>)}</select></label>}
      <label>{t('reports.policy.remindBefore')}<input type="number" min={1} max={60} value={value.reminder_days ?? ''} placeholder={t('reports.policy.companyDays', { n: companyReminderDays })} disabled={disabled} onChange={(event) => set({ reminder_days: numberOrNull(event.target.value, 1, 60) })} /></label>
      <label>{t('reports.policy.dueAfter')}<input type="number" min={0} max={60} value={value.due_days} disabled={disabled} onChange={(event) => set({ due_days: numberOrNull(event.target.value, 0, 60) ?? 0 })} /></label>
      <label>{t('reports.policy.reminderHour')}<select value={value.reminder_hour ?? ''} disabled={disabled} onChange={(event) => set({ reminder_hour: event.target.value === '' ? null : Number(event.target.value) })}><option value="">{t('reports.policy.morningHour')}</option>{HOURS.map((hour) => <option key={hour} value={hour}>{`${String(hour).padStart(2, '0')}:00`}</option>)}</select></label>
    </div>
  </article>
}
const UNIT_LABELS: Record<CustomReportPeriod['unit'], string> = { get day() { return i18n.t('reports.policy.unitShort.day') }, get week() { return i18n.t('reports.policy.unitShort.week') }, get month() { return i18n.t('reports.policy.unitShort.month') } }

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
  const { t } = useTranslation()
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
      frequency_settings: policy.data.frequency_settings ?? {},
    })
  }, [policy.data])

  const frequencyOptions = useMemo(() => [
    ...STANDARD,
    ...(form?.custom_periods ?? []).map((item) => ({ value: `custom:${item.id}`, label: item.label })),
  ], [form?.custom_periods])

  if (policy.isLoading || !form) return <p className="query-region-state">{t('reports.policy.loading')}</p>
  if (policy.isError) return <p className="query-region-state" role="alert">{t('reports.policy.loadFailed')}</p>

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
  // Frequencies someone actually reports on get a period/schedule card.
  const usedFrequencies = frequencyOptions.filter((option) => option.value !== 'daily' && (
    form.worker_frequencies.includes(option.value)
    || form.departments.some((rule) => rule.worker_frequencies?.includes(option.value) || rule.department_frequencies.includes(option.value))
  ))
  const settingsFor = (frequency: string) => ({ ...defaultSettings(frequency), ...(form.frequency_settings?.[frequency] ?? {}) })
  const setSettings = (frequency: string, next: ReportFrequencySettings) => setForm({ ...form, frequency_settings: { ...form.frequency_settings, [frequency]: next } })
  const save = () => update.mutate({
    ...form,
    // Only settings of frequencies that still exist are sent.
    frequency_settings: Object.fromEntries(Object.entries(form.frequency_settings ?? {}).filter(([frequency]) => frequencyOptions.some((option) => option.value === frequency))),
    // Drop rules that no longer change anything.
    departments: form.departments.filter((rule) => rule.worker_frequencies !== null || rule.department_frequencies.length > 0),
  })

  return <div className="report-policy-settings">
    {!canEdit && <p className="settings-readonly-note">{t('reports.policy.readOnly')}</p>}
    <section className="report-policy-block">
      <h3>{t('reports.policy.frequencyTitle')}</h3>
      <p>{t('reports.policy.frequencyHint')}</p>
      <FrequencyPicker label={t('reports.policy.allEmployees')} options={frequencyOptions} value={form.worker_frequencies} onChange={(next) => setForm({ ...form, worker_frequencies: next })} disabled={!canEdit} />
      <label className="report-reminder-days">{t('reports.policy.reminderDays')}
        <input type="number" min={1} max={14} value={form.reminder_days} disabled={!canEdit} onChange={(event) => setForm({ ...form, reminder_days: Math.max(1, Math.min(14, Number(event.target.value) || 1)) })} />
      </label>
    </section>

    <section className="report-policy-block">
      <h3>{t('reports.policy.scheduleTitle')}</h3>
      <p>{t('reports.policy.scheduleHint')}</p>
      {usedFrequencies.length === 0 ? <p className="query-region-state">{t('reports.policy.noActiveFrequency')}</p> : <div className="report-schedule-list">{usedFrequencies.map((option) => <FrequencyScheduleCard
        key={option.value} frequency={option.value.startsWith('custom:') ? 'custom' : option.value} label={option.label}
        value={settingsFor(option.value)} onChange={(next) => setSettings(option.value, next)} disabled={!canEdit}
        companyReminderDays={form.reminder_days} preview={policy.data?.current_periods?.[option.value]} />)}</div>}
    </section>

    <section className="report-policy-block">
      <h3>{t('reports.policy.customTitle')}</h3>
      <p>{t('reports.policy.customHint')}</p>
      {form.custom_periods.length > 0 && <ul className="report-custom-list">{form.custom_periods.map((item) => <li key={item.id}>
        <span><strong>{item.label}</strong><small>{t('reports.policy.customSummary', { interval: item.interval, unit: UNIT_LABELS[item.unit], date: item.anchor_date })}</small></span>
        {canEdit && <button type="button" className="danger-action compact" onClick={() => removeCustomPeriod(item.id)} aria-label={t('reports.policy.deleteItem', { label: item.label })}><Trash2 size={14} /></button>}
      </li>)}</ul>}
      {canEdit && <div className="report-custom-form">
        <label>{t('reports.policy.name')}<input value={newPeriod.label} maxLength={80} onChange={(event) => setNewPeriod({ ...newPeriod, label: event.target.value })} placeholder={t('reports.policy.namePlaceholder')} /></label>
        <label>{t('reports.policy.every')}<input type="number" min={1} max={newPeriod.unit === 'day' ? 366 : newPeriod.unit === 'week' ? 52 : 24} value={newPeriod.interval} onChange={(event) => setNewPeriod({ ...newPeriod, interval: Math.max(1, Number(event.target.value) || 1) })} /></label>
        <label>{t('reports.policy.unit')}<select value={newPeriod.unit} onChange={(event) => setNewPeriod({ ...newPeriod, unit: event.target.value as CustomReportPeriod['unit'] })}><option value="day">{t('reports.policy.unit.day')}</option><option value="week">{t('reports.policy.unit.week')}</option><option value="month">{t('reports.policy.unit.month')}</option></select></label>
        <label>{t('reports.policy.startDate')}<input type="date" value={newPeriod.anchor_date} onChange={(event) => setNewPeriod({ ...newPeriod, anchor_date: event.target.value })} /></label>
        <button type="button" className="secondary-action compact" onClick={addCustomPeriod} disabled={!newPeriod.label.trim() || form.custom_periods.length >= 12}><Plus size={14} />{t('reports.policy.add')}</button>
      </div>}
    </section>

    <section className="report-policy-block">
      <h3>{t('reports.insights.byDepartment')}</h3>
      <p>{t('reports.policy.deptHint')}</p>
      {departments.length === 0 ? <p className="query-region-state">{t('reports.policy.noDepartments')}</p> : <div className="report-department-list">{departments.map((department) => {
        const rule = ruleFor(department.id)
        const overrides = rule?.worker_frequencies != null
        return <article key={department.id} className="report-department-rule panel">
          <header><strong>{department.name}</strong><small>{department.manager_name ? t('reports.policy.manager', { name: department.manager_name }) : t('reports.policy.noManager')}</small></header>
          <label className="report-override-toggle"><input type="checkbox" checked={overrides} disabled={!canEdit} onChange={() => setRule(department.id, { worker_frequencies: overrides ? null : [...form.worker_frequencies] })} /><span>{t('reports.policy.deptOverride')}</span></label>
          {overrides && <FrequencyPicker label={t('reports.policy.employeeReport')} options={frequencyOptions} value={rule?.worker_frequencies ?? []} onChange={(next) => setRule(department.id, { worker_frequencies: next })} disabled={!canEdit} />}
          <FrequencyPicker label={t('reports.policy.departmentReport')} options={frequencyOptions} exclude={['daily']} value={rule?.department_frequencies ?? []} onChange={(next) => setRule(department.id, { department_frequencies: next })} disabled={!canEdit} />
        </article>
      })}</div>}
    </section>

    {canEdit && <div className="report-policy-actions"><button type="button" className="primary-action" onClick={save} disabled={update.isPending}><Save size={16} />{t('reports.policy.save')}</button></div>}
  </div>
}
