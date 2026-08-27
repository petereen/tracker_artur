import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowRight, Calculator, CheckCircle2, CircleAlert, Coins, Download, FileText, LockKeyhole, Pencil, Play, Plus, ShieldCheck, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadMyPayslip,
  downloadPayrollExport,
  downloadPayrollReport,
  useActor,
  useApprovePayrollRun,
  useCalculatePayrollRun,
  useCreatePayrollBankExport,
  useCreatePayrollProfile,
  useCreatePayrollRun,
  useCreatePayrollStructure,
  useDeletePayrollProfile,
  useDeletePayrollStructure,
  useMyPayrollPayslips,
  usePayrollEmployeeProfiles,
  usePayrollProfiles,
  usePayrollRun,
  usePayrollRuns,
  usePayrollStructures,
  usePostPayrollRun,
  usePublishPayrollProfile,
  usePublishPayrollStructure,
  useReviewPayrollRun,
  useSavePayrollEmployeeProfile,
  useWorkerDirectory,
  useUpdatePayrollProfile,
  useUpdatePayrollStructure,
} from '../api/enterprise'
import type { PayrollPITBracket, PayrollProfile, PayrollProfileInput, PayrollReliefTier, PayrollSHIRate, PayrollStructure, PayrollStructureInput } from '../api/enterprise'

export const formatPayrollMoney = (value: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
export const canManagePayroll = (roles: string[]) => roles.includes('admin') || roles.includes('manager') || roles.includes('hr')

const isPublished = (status?: string) => status === 'published' || status === 'active'
const errorCode = (error: any, fallback: string) => error?.response?.data?.detail?.code || fallback

function StatusBadge({ status }: { status: string }) {
  return <span className={`payroll-status payroll-status-${status}`}><span aria-hidden="true" />{status.replaceAll('_', ' ')}</span>
}

function EmptyState({ title, copy, action }: { title: string; copy: string; action?: ReactNode }) {
  return <div className="payroll-empty"><div className="payroll-empty-icon"><FileText size={20} /></div><strong>{title}</strong><p>{copy}</p>{action}</div>
}

const emptyProfile = (): PayrollProfileInput => ({
  code: '', version: 1, effective_from: new Date().toISOString().slice(0, 10), effective_to: null,
  tax_point_basis: 'payment_date', currency: 'MNT', minimum_wage: '0', shi_ceiling_multiplier: '0',
  pit_withholding_method: 'ytd_cumulative', rounding_policy: { quantum: '0.01' },
  leave_policy: { lookback_months: 12, missing_history_fallback: 'error' }, source_references: [], is_example: false,
  shi_rates: [], pit_brackets: [], relief_tiers: [],
})

const emptyStructure = (): PayrollStructureInput => ({ code: '', name: '', effective_from: new Date().toISOString().slice(0, 10), effective_to: null, currency: 'MNT', components: [] })
const emptyRate = (): PayrollSHIRate => ({ payer: 'employee', insurance_fund: '', insured_category: 'employee', hazard_class: 'standard', rate: '0', base_floor: '0', exemption_code: null })
const emptyBracket = (): PayrollPITBracket => ({ period_basis: 'annual', lower_bound: '0', upper_bound: null, marginal_rate: '0', base_tax: '0' })
const emptyRelief = (): PayrollReliefTier => ({ eligibility_code: '', lower_bound: '0', upper_bound: null, fixed_amount: '0', amount_basis: 'annual', formula: null })

function profileInputFrom(profile?: PayrollProfile): PayrollProfileInput {
  if (!profile) return emptyProfile()
  return {
    code: profile.code, version: profile.version, effective_from: profile.effective_from, effective_to: profile.effective_to,
    tax_point_basis: (profile.tax_point_basis as PayrollProfileInput['tax_point_basis']) || 'payment_date', currency: 'MNT',
    minimum_wage: profile.minimum_wage, shi_ceiling_multiplier: profile.shi_ceiling_multiplier,
    pit_withholding_method: (profile.pit_withholding_method as PayrollProfileInput['pit_withholding_method']) || 'ytd_cumulative',
    rounding_policy: profile.rounding_policy || { quantum: '0.01' }, leave_policy: profile.leave_policy || { lookback_months: 12, missing_history_fallback: 'error' },
    source_references: profile.source_references || [], is_example: profile.is_example,
    shi_rates: profile.shi_rates || [], pit_brackets: profile.pit_brackets || [], relief_tiers: profile.relief_tiers || [],
  }
}

function ProfileEditor({ value, editing, pending, onChange, onClose, onSubmit }: { value: PayrollProfileInput; editing: boolean; pending: boolean; onChange: (value: PayrollProfileInput) => void; onClose: () => void; onSubmit: () => void }) {
  const set = <K extends keyof PayrollProfileInput>(key: K, next: PayrollProfileInput[K]) => onChange({ ...value, [key]: next })
  const updateRate = (index: number, next: Partial<PayrollSHIRate>) => set('shi_rates', value.shi_rates.map((row, rowIndex) => rowIndex === index ? { ...row, ...next } : row))
  const updateBracket = (index: number, next: Partial<PayrollPITBracket>) => set('pit_brackets', value.pit_brackets.map((row, rowIndex) => rowIndex === index ? { ...row, ...next } : row))
  const updateRelief = (index: number, next: Partial<PayrollReliefTier>) => set('relief_tiers', value.relief_tiers.map((row, rowIndex) => rowIndex === index ? { ...row, ...next } : row))
  return <div className="payroll-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="payroll-modal" role="dialog" aria-modal="true" aria-labelledby="payroll-profile-editor-title"><header className="payroll-modal-header"><div><span className="eyebrow">{editing ? 'DRAFT PROFILE' : 'NEW PROFILE'}</span><h2 id="payroll-profile-editor-title">{editing ? 'Review & edit statutory profile' : 'Add statutory profile'}</h2><p>Update the configuration, then save as draft. Publishing makes this version immutable.</p></div><button type="button" className="payroll-close" onClick={onClose} aria-label="Close"><X size={18} /></button></header><form className="payroll-editor-form" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
    <fieldset><legend>Profile basics</legend><div className="payroll-form-grid"><label>Profile code<input required value={value.code} onChange={(event) => set('code', event.target.value.toUpperCase())} placeholder="MN_2026" /></label><label>Version<input required min="1" type="number" value={value.version} onChange={(event) => set('version', Number(event.target.value))} /></label><label>Effective from<input required type="date" value={value.effective_from} onChange={(event) => set('effective_from', event.target.value)} /></label><label>Effective to<span className="payroll-input-hint">Optional</span><input type="date" value={value.effective_to || ''} onChange={(event) => set('effective_to', event.target.value || null)} /></label><label>Minimum wage (MNT)<input required min="0" type="number" value={value.minimum_wage} onChange={(event) => set('minimum_wage', event.target.value)} /></label><label>SHI ceiling multiplier<input required min="0" step="0.01" type="number" value={value.shi_ceiling_multiplier} onChange={(event) => set('shi_ceiling_multiplier', event.target.value)} /></label><label>PIT withholding<select value={value.pit_withholding_method} onChange={(event) => set('pit_withholding_method', event.target.value as PayrollProfileInput['pit_withholding_method'])}><option value="ytd_cumulative">YTD cumulative</option><option value="isolated_period">Isolated period</option></select></label><label>Tax point basis<select value={value.tax_point_basis} onChange={(event) => set('tax_point_basis', event.target.value as PayrollProfileInput['tax_point_basis'])}><option value="payment_date">Payment date</option><option value="period_end">Period end</option></select></label></div></fieldset>
    <fieldset><div className="payroll-fieldset-heading"><legend>SHI rates</legend><button type="button" className="secondary-action compact" onClick={() => set('shi_rates', [...value.shi_rates, emptyRate()])}><Plus size={14} />Add rate</button></div>{value.shi_rates.length ? <div className="payroll-rule-list">{value.shi_rates.map((row, index) => <div className="payroll-rule-row" key={`rate-${index}`}><input aria-label="Payer" value={row.payer} onChange={(event) => updateRate(index, { payer: event.target.value as PayrollSHIRate['payer'] })} placeholder="employee" /><input aria-label="Insurance fund" value={row.insurance_fund} onChange={(event) => updateRate(index, { insurance_fund: event.target.value })} placeholder="pension" /><input aria-label="Rate" type="number" step="0.0001" min="0" max="1" value={row.rate} onChange={(event) => updateRate(index, { rate: event.target.value })} placeholder="0.085" /><button type="button" className="icon-action danger-action" onClick={() => set('shi_rates', value.shi_rates.filter((_, rowIndex) => rowIndex !== index))} aria-label="Remove rate"><Trash2 size={15} /></button></div>)}</div> : <p className="payroll-editor-empty">No SHI rates yet. Add the employee and employer rates for this profile.</p>}</fieldset>
    <fieldset><div className="payroll-fieldset-heading"><legend>PIT brackets</legend><button type="button" className="secondary-action compact" onClick={() => set('pit_brackets', [...value.pit_brackets, emptyBracket()])}><Plus size={14} />Add bracket</button></div>{value.pit_brackets.length ? <div className="payroll-rule-list">{value.pit_brackets.map((row, index) => <div className="payroll-rule-row payroll-bracket-row" key={`bracket-${index}`}><input aria-label="Lower bound" type="number" min="0" value={row.lower_bound} onChange={(event) => updateBracket(index, { lower_bound: event.target.value })} placeholder="Lower bound" /><input aria-label="Upper bound" type="number" min="0" value={row.upper_bound || ''} onChange={(event) => updateBracket(index, { upper_bound: event.target.value || null })} placeholder="No upper limit" /><input aria-label="Marginal rate" type="number" step="0.0001" min="0" max="1" value={row.marginal_rate} onChange={(event) => updateBracket(index, { marginal_rate: event.target.value })} placeholder="Rate" /><button type="button" className="icon-action danger-action" onClick={() => set('pit_brackets', value.pit_brackets.filter((_, rowIndex) => rowIndex !== index))} aria-label="Remove bracket"><Trash2 size={15} /></button></div>)}</div> : <p className="payroll-editor-empty">No PIT brackets yet. Add at least one bracket before publishing.</p>}</fieldset>
    <fieldset><div className="payroll-fieldset-heading"><legend>Tax reliefs <span className="payroll-input-hint">Optional</span></legend><button type="button" className="secondary-action compact" onClick={() => set('relief_tiers', [...value.relief_tiers, emptyRelief()])}><Plus size={14} />Add relief</button></div>{value.relief_tiers.length ? <div className="payroll-rule-list">{value.relief_tiers.map((row, index) => <div className="payroll-rule-row" key={`relief-${index}`}><input aria-label="Eligibility code" value={row.eligibility_code} onChange={(event) => updateRelief(index, { eligibility_code: event.target.value })} placeholder="Eligibility code" /><input aria-label="Fixed amount" type="number" min="0" value={row.fixed_amount} onChange={(event) => updateRelief(index, { fixed_amount: event.target.value })} placeholder="Fixed amount" /><button type="button" className="icon-action danger-action" onClick={() => set('relief_tiers', value.relief_tiers.filter((_, rowIndex) => rowIndex !== index))} aria-label="Remove relief"><Trash2 size={15} /></button></div>)}</div> : <p className="payroll-editor-empty">No relief tiers configured.</p>}</fieldset>
    <label className="payroll-check-label"><input type="checkbox" checked={value.is_example} onChange={(event) => set('is_example', event.target.checked)} />Keep this marked as an example profile</label><footer className="payroll-modal-footer"><button type="button" className="secondary-action" onClick={onClose}>Cancel</button><button type="submit" className="primary-action" disabled={pending}>{pending ? 'Saving…' : 'Save draft'}</button></footer>
  </form></section></div>
}

function StructureEditor({ value, editing, pending, onChange, onClose, onSubmit }: { value: PayrollStructureInput; editing: boolean; pending: boolean; onChange: (value: PayrollStructureInput) => void; onClose: () => void; onSubmit: () => void }) {
  const updateComponent = (index: number, next: Partial<PayrollStructureInput['components'][number]>) => onChange({ ...value, components: value.components.map((row, rowIndex) => rowIndex === index ? { ...row, ...next } : row) })
  return <div className="payroll-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="payroll-modal" role="dialog" aria-modal="true" aria-labelledby="payroll-structure-editor-title"><header className="payroll-modal-header"><div><span className="eyebrow">{editing ? 'DRAFT STRUCTURE' : 'NEW STRUCTURE'}</span><h2 id="payroll-structure-editor-title">{editing ? 'Edit salary structure' : 'Add salary structure'}</h2><p>Define the earning and deduction formulas used for this effective-dated structure.</p></div><button type="button" className="payroll-close" onClick={onClose} aria-label="Close"><X size={18} /></button></header><form className="payroll-editor-form" onSubmit={(event) => { event.preventDefault(); onSubmit() }}><fieldset><legend>Structure basics</legend><div className="payroll-form-grid"><label>Code<input required value={value.code} onChange={(event) => onChange({ ...value, code: event.target.value.toUpperCase() })} placeholder="MONTHLY_MNT" /></label><label>Name<input required value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} placeholder="Monthly salary" /></label><label>Effective from<input required type="date" value={value.effective_from} onChange={(event) => onChange({ ...value, effective_from: event.target.value })} /></label><label>Effective to<span className="payroll-input-hint">Optional</span><input type="date" value={value.effective_to || ''} onChange={(event) => onChange({ ...value, effective_to: event.target.value || null })} /></label></div></fieldset><fieldset><div className="payroll-fieldset-heading"><legend>Pay components</legend><button type="button" className="secondary-action compact" onClick={() => onChange({ ...value, components: [...value.components, { code: '', name: '', component_kind: 'earning', formula: 'base_salary', proration_basis: 'none', is_taxable: true, is_shi_subject: true, is_non_taxable_allowance: false, account_id: null, cost_center_id: null, payer: 'employee', position: value.components.length }] })}><Plus size={14} />Add component</button></div>{value.components.length ? <div className="payroll-component-list">{value.components.map((row, index) => <div className="payroll-component-row" key={`component-${index}`}><input required aria-label="Component code" value={row.code} onChange={(event) => updateComponent(index, { code: event.target.value.toLowerCase() })} placeholder="base_salary" /><input required aria-label="Component name" value={row.name} onChange={(event) => updateComponent(index, { name: event.target.value })} placeholder="Base salary" /><select aria-label="Component kind" value={row.component_kind} onChange={(event) => updateComponent(index, { component_kind: event.target.value as PayrollStructureInput['components'][number]['component_kind'] })}><option value="earning">Earning</option><option value="deduction">Deduction</option><option value="employer_cost">Employer cost</option></select><input required aria-label="Formula" value={row.formula} onChange={(event) => updateComponent(index, { formula: event.target.value })} placeholder="base_salary" /><button type="button" className="icon-action danger-action" onClick={() => onChange({ ...value, components: value.components.filter((_, rowIndex) => rowIndex !== index) })} aria-label="Remove component"><Trash2 size={15} /></button></div>)}</div> : <p className="payroll-editor-empty">Add at least one component before publishing this structure.</p>}</fieldset><footer className="payroll-modal-footer"><button type="button" className="secondary-action" onClick={onClose}>Cancel</button><button type="submit" className="primary-action" disabled={pending}>{pending ? 'Saving…' : 'Save draft'}</button></footer></form></section></div>
}

export function PayrollWorkspacePage() {
  const { runId: runIdParam } = useParams<{ runId?: string }>()
  const runId = runIdParam ? Number(runIdParam) : undefined
  const actor = useActor()
  const profiles = usePayrollProfiles(Boolean(actor.data))
  const structures = usePayrollStructures(Boolean(actor.data))
  const employeeProfiles = usePayrollEmployeeProfiles(Boolean(actor.data))
  const workers = useWorkerDirectory()
  const runs = usePayrollRuns(Boolean(actor.data))
  const runDetail = usePayrollRun(runId, Boolean(actor.data))
  const payslips = useMyPayrollPayslips(Boolean(actor.data?.employee_id))
  const create = useCreatePayrollRun()
  const calculate = useCalculatePayrollRun()
  const review = useReviewPayrollRun()
  const approve = useApprovePayrollRun()
  const post = usePostPayrollRun()
  const createProfile = useCreatePayrollProfile()
  const updateProfile = useUpdatePayrollProfile()
  const deleteProfile = useDeletePayrollProfile()
  const createStructure = useCreatePayrollStructure()
  const updateStructure = useUpdatePayrollStructure()
  const deleteStructure = useDeletePayrollStructure()
  const saveEmployeeProfile = useSavePayrollEmployeeProfile()
  const publishProfile = usePublishPayrollProfile()
  const publishStructure = usePublishPayrollStructure()
  const bankExport = useCreatePayrollBankExport()
  const [bankCode, setBankCode] = useState('KHAN')
  const [periodStart, setPeriodStart] = useState(() => new Date().toISOString().slice(0, 8) + '01')
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [taxPoint, setTaxPoint] = useState(() => new Date().toISOString().slice(0, 10))
  const [profileEditor, setProfileEditor] = useState<{ value: PayrollProfileInput; id?: number } | null>(null)
  const [structureEditor, setStructureEditor] = useState<{ value: PayrollStructureInput; id?: number } | null>(null)
  const [employeeEditor, setEmployeeEditor] = useState<{ employeeId: number; salary: string } | null>(null)
  const canAdmin = canManagePayroll(actor.data?.roles ?? [])
  const activeProfile = profiles.data?.find((profile) => isPublished(profile.status) && profile.effective_from <= taxPoint && (!profile.effective_to || profile.effective_to >= taxPoint))
  const activeStructure = structures.data?.find((structure) => isPublished(structure.status) && structure.effective_from <= periodEnd && (!structure.effective_to || structure.effective_to >= periodEnd))
  const hasDraftProfile = profiles.data?.some((profile) => profile.status === 'draft')
  const hasDraftStructure = structures.data?.some((structure) => structure.status === 'draft')
  const configuredEmployeeIds = new Set(employeeProfiles.data?.map((profile) => profile.employee_id) || [])
  const unconfiguredWorkers = workers.data?.filter((worker) => !configuredEmployeeIds.has(worker.id)) || []
  const hasEmployeeSetup = Boolean(employeeProfiles.data?.length)
  const setupReady = Boolean(activeProfile && activeStructure && hasEmployeeSetup)
  const setupTitle = setupReady ? 'Your payroll setup is ready' : !activeProfile ? 'Publish a statutory profile first' : !activeStructure ? 'Publish a salary structure first' : 'Add at least one employee'
  const setupCopy = setupReady ? 'Choose a period below to create a consolidated run.' : !activeProfile ? 'Review or add a statutory profile. Published versions are used according to the tax point date.' : !activeStructure ? 'Create or edit a salary structure, add its pay components, then publish it.' : 'Assign a salary structure and base salary to at least one active employee before creating a run.'
  const setupHref = !activeProfile || !activeStructure ? '#profiles' : '#employee-setup'

  const saveProfile = () => {
    if (!profileEditor) return
    const options = { onSuccess: () => { setProfileEditor(null); toast.success('Statutory profile saved as draft') }, onError: (error: any) => toast.error(errorCode(error, 'Profile could not be saved')) }
    if (profileEditor.id) updateProfile.mutate({ id: profileEditor.id, ...profileEditor.value }, options)
    else createProfile.mutate(profileEditor.value, options)
  }
  const saveStructure = () => {
    if (!structureEditor) return
    const options = { onSuccess: () => { setStructureEditor(null); toast.success('Salary structure saved as draft') }, onError: (error: any) => toast.error(errorCode(error, 'Salary structure could not be saved')) }
    if (structureEditor.id) updateStructure.mutate({ id: structureEditor.id, ...structureEditor.value }, options)
    else createStructure.mutate(structureEditor.value, options)
  }
  const removeProfile = (profile: PayrollProfile) => {
    if (profile.status !== 'draft' || !window.confirm(`Delete draft profile ${profile.code}?`)) return
    deleteProfile.mutate(profile.id, { onSuccess: () => toast.success('Draft profile deleted'), onError: (error: any) => toast.error(errorCode(error, 'Profile could not be deleted')) })
  }
  const removeStructure = (structure: PayrollStructure) => {
    if (structure.status !== 'draft' || !window.confirm(`Delete draft structure ${structure.code}?`)) return
    deleteStructure.mutate(structure.id, { onSuccess: () => toast.success('Draft structure deleted'), onError: (error: any) => toast.error(errorCode(error, 'Salary structure could not be deleted')) })
  }
  const saveEmployee = () => {
    if (!employeeEditor || !activeStructure) return
    saveEmployeeProfile.mutate({ employeeId: employeeEditor.employeeId, employee_id: employeeEditor.employeeId, salary_structure_id: activeStructure.id, effective_from: activeStructure.effective_from, base_salary: employeeEditor.salary, insured_category: 'employee', hazard_class: 'standard', residency_status: 'resident', payment_method: 'bank' }, { onSuccess: () => { setEmployeeEditor(null); toast.success('Employee payroll profile saved') }, onError: (error: any) => toast.error(errorCode(error, 'Employee payroll profile could not be saved')) })
  }

  const publishProfileNow = (profile: { id: number; is_example: boolean }) => {
    if (profile.is_example && !window.confirm('This is an example statutory profile. Publish it only after reviewing it against current Mongolian requirements. Continue?')) return
    publishProfile.mutate({ id: profile.id, acknowledge_example: profile.is_example }, {
      onSuccess: () => toast.success('Statutory profile published'),
      onError: (error: any) => toast.error(errorCode(error, 'Profile could not be published')),
    })
  }

  const createRun = () => {
    if (!activeProfile) { toast.error('Publish a statutory profile first'); return }
    if (!activeStructure) { toast.error('Publish a salary structure first'); return }
    if (periodEnd < periodStart) { toast.error('Period end must be after period start'); return }
    create.mutate({ run_type: 'single', period_start: periodStart, period_end: periodEnd, tax_point_date: taxPoint, statutory_profile_id: activeProfile.id }, {
      onSuccess: () => toast.success('Payroll run created — calculate it to freeze employee inputs'),
      onError: (error: any) => toast.error(errorCode(error, 'Payroll run could not be created')),
    })
  }

  const calculateRun = (run: { id: number; statutory_profile_id: number }) => {
    const profile = profiles.data?.find((item) => item.id === run.statutory_profile_id)
    const acknowledgeExample = Boolean(profile?.is_example)
    if (acknowledgeExample && !window.confirm('This run uses an example statutory profile. Continue only if it has been reviewed.')) return
    calculate.mutate({ id: run.id, acknowledge_example: acknowledgeExample }, {
      onSuccess: () => toast.success('Payroll calculated — ready for review'),
      onError: (error: any) => toast.error(errorCode(error, 'Calculation failed')),
    })
  }

  if (actor.isLoading) return <div className="panel payroll-loading"><p>Loading payroll…</p></div>
  if (!actor.data) return <div className="panel payroll-loading"><p>Payroll access is unavailable.</p></div>

  const downloadGeneratedExport = async (payload: { artifact_id: number; filename: string }) => {
    try { await downloadPayrollExport(payload.artifact_id, payload.filename); toast.success('Payout file downloaded') } catch { toast.error('Bank export download failed') }
  }

  if (runId && canAdmin) return <div className="erp-workspace payroll-workspace">
    <div className="view-toolbar payroll-toolbar"><div><Link to="/erp/payroll" className="secondary-action compact">← All payroll runs</Link><span className="eyebrow">PAYROLL RUN DETAIL</span><h2>{runDetail.data?.run_number || `Run ${runId}`}</h2><p>Review the immutable calculation snapshot before exporting or posting.</p></div><div className="payroll-toolbar-icon"><FileText size={22} /></div></div>
    {runDetail.isLoading ? <section className="panel payroll-card"><p>Loading run…</p></section> : runDetail.isError || !runDetail.data ? <section className="panel payroll-card"><EmptyState title="Payroll run not found" copy="It may have been removed or you may not have access to it." action={<Link to="/erp/payroll" className="secondary-action">Back to payroll</Link>} /></section> : <>
      <section className="erp-kpis payroll-kpis"><article className="panel"><small>Status</small><StatusBadge status={runDetail.data.status} /></article><article className="panel"><small>Gross payroll</small><strong>{formatPayrollMoney(runDetail.data.total_gross)}</strong></article><article className="panel"><small>Employee SHI / PIT</small><strong>{formatPayrollMoney(runDetail.data.total_employee_shi)} / {formatPayrollMoney(runDetail.data.total_pit)}</strong></article><article className="panel"><small>Net pay</small><strong>{formatPayrollMoney(runDetail.data.total_net)}</strong></article></section>
      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">DELIVERY</span><h3>Bank batch and state reports</h3><p>Exports unlock after approval and use the run’s frozen payroll snapshot.</p></div><ShieldCheck size={20} /></div><div className="payroll-export-row"><label className="erp-create-field">Bank preset<input aria-label="Bank preset" value={bankCode} onChange={(event) => setBankCode(event.target.value.toUpperCase())} /></label><button className="primary-action" disabled={bankExport.isPending || !['approved', 'posted', 'paid'].includes(runDetail.data.status)} onClick={() => bankExport.mutate({ id: runId, bank_code: bankCode }, { onSuccess: downloadGeneratedExport, onError: () => toast.error('Bank export could not be generated') })}><Download size={15} />{bankExport.isPending ? 'Preparing…' : 'Generate payout CSV'}</button>{(['nd7', 'nd8', 'tt11'] as const).map((kind) => <button key={kind} className="secondary-action" onClick={() => downloadPayrollReport(runId, kind).then(() => toast.success(`${kind.toUpperCase()} report downloaded`)).catch(() => toast.error(`${kind.toUpperCase()} export failed`))}>{kind === 'tt11' ? 'ТТ-11' : kind.toUpperCase()}</button>)}</div>{!['approved', 'posted', 'paid'].includes(runDetail.data.status) && <p className="payroll-helper"><CircleAlert size={15} />Approve this run before generating delivery files.</p>}</section>
      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">CALCULATION SNAPSHOT</span><h3>Payslips</h3></div><span className="payroll-count">{runDetail.data.payslips.length} employees</span></div>{runDetail.data.payslips.length ? <div className="erp-document-list payroll-list">{runDetail.data.payslips.map((slip) => <article key={slip.id}><div><strong>Employee {slip.employee_id}</strong><span>Gross {formatPayrollMoney(slip.gross)} · SHI base {formatPayrollMoney(slip.shi_base)} · PIT {formatPayrollMoney(slip.pit)}</span></div><div><strong>{formatPayrollMoney(slip.net_pay)}</strong><span>{slip.ytd?.taxable ? `YTD taxable ${formatPayrollMoney(slip.ytd.taxable)}` : 'Net pay'}</span></div></article>)}</div> : <EmptyState title="No payslips yet" copy="Calculate the run to generate frozen employee payslips." />}</section>
    </>}
  </div>

  return <div className="erp-workspace payroll-workspace">
    <div className="view-toolbar payroll-toolbar"><div><span className="eyebrow">OYUNS ALL-IN-ONE · PAYROLL</span><h2>Mongolia payroll</h2><p>Run accurate, effective-dated НДШ / ХХОАТ payroll with an immutable audit trail.</p></div><div className="payroll-toolbar-actions"><div className="payroll-toolbar-icon"><Calculator size={22} /></div><Link className="secondary-action" to="/erp/payroll/tax-benefits"><Coins size={15} />Tax &amp; Benefits</Link>{canAdmin && <><button className="secondary-action" onClick={() => setProfileEditor({ value: emptyProfile() })}><Plus size={15} />Add profile</button><button className="secondary-action" onClick={() => setStructureEditor({ value: emptyStructure() })}><Plus size={15} />Add structure</button><a className="primary-action" href="#create-run"><Play size={15} />Create payroll run<ArrowRight size={14} /></a></>}</div></div>
    <div className="erp-settings-notice payroll-notice"><ShieldCheck size={16} /><span>Rates, thresholds, reliefs, formulas, accounts, and bank layouts are configuration data. Example profiles require review before use.</span></div>
    {canAdmin ? <>
      <section className="payroll-next-step"><div className="payroll-next-step-icon">{setupReady ? <CheckCircle2 size={22} /> : <CircleAlert size={22} />}</div><div><span className="eyebrow">{setupReady ? 'READY FOR A RUN' : 'SETUP REQUIRED'}</span><h3>{setupTitle}</h3><p>{setupCopy}</p></div>{!setupReady && <a className="secondary-action" href={setupHref}>Review setup <ArrowRight size={14} /></a>}</section>
      <section className="erp-kpis payroll-kpis"><article className="panel"><small>Active statutory profile</small><strong>{activeProfile ? `${activeProfile.code} · v${activeProfile.version}` : 'None published'}</strong><span className="payroll-kpi-detail">{activeProfile ? `Effective ${activeProfile.effective_from}` : 'Publish a reviewed profile'}</span></article><article className="panel"><small>Salary structure</small><strong>{activeStructure ? `${activeStructure.code} · v${activeStructure.version}` : 'None published'}</strong><span className="payroll-kpi-detail">{activeStructure ? `${activeStructure.components.length} pay components` : 'Publish a structure'}</span></article><article className="panel"><small>Example profile guard</small><StatusBadge status={activeProfile?.is_example ? 'review_required' : 'ready'} /><span className="payroll-kpi-detail">{activeProfile?.is_example ? 'Confirm before calculating' : 'No review needed'}</span></article><article className="panel"><small>Payroll runs</small><strong>{runs.data?.length ?? 0}</strong><span className="payroll-kpi-detail">{runs.data?.length ? 'Across all periods' : 'Create your first run'}</span></article></section>
      <section id="profiles" className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">CONFIGURATION</span><h3>Statutory profiles & salary structures</h3><p>Only effective-dated, published versions can be used in a payroll run.</p></div><ShieldCheck size={20} /></div>{profiles.isLoading || structures.isLoading ? <p>Loading configuration…</p> : profiles.isError || structures.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Configuration could not be loaded. Refresh and try again.</div> : <div className="erp-document-list payroll-list">{profiles.data?.map((profile) => <article key={`profile-${profile.id}`}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{profile.code} · v{profile.version}</strong><StatusBadge status={profile.is_example && profile.status === 'draft' ? 'review_required' : profile.status} /></div><span>{profile.effective_from}{profile.effective_to ? ` – ${profile.effective_to}` : ' onward'} · PIT {profile.pit_withholding_method}</span><small>{profile.is_example ? 'Example profile — review against current requirements before publishing.' : `MNT ${profile.minimum_wage} minimum wage · SHI cap ×${profile.shi_ceiling_multiplier}`}</small></div>{profile.status === 'draft' ? <div className="payroll-item-actions"><button className="secondary-action" onClick={() => setProfileEditor({ id: profile.id, value: profileInputFrom(profile) })}><Pencil size={14} />{profile.is_example ? 'Review & edit' : 'Edit'}</button><button className="secondary-action" disabled={publishProfile.isPending} onClick={() => publishProfileNow(profile)}>{publishProfile.isPending ? 'Publishing…' : profile.is_example ? 'Review & publish' : 'Publish profile'}</button><button className="icon-action danger-action" onClick={() => removeProfile(profile)} aria-label={`Delete ${profile.code}`}><Trash2 size={15} /></button></div> : <span className="payroll-locked"><LockKeyhole size={13} />Locked after publish</span>}</article>)}{structures.data?.map((structure) => <article key={`structure-${structure.id}`}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{structure.code} · v{structure.version}</strong><StatusBadge status={structure.status} /></div><span>{structure.name} · {structure.effective_from} · {structure.components.length} components</span><small>{structure.currency} payroll structure</small></div>{structure.status === 'draft' ? <div className="payroll-item-actions"><button className="secondary-action" onClick={() => setStructureEditor({ id: structure.id, value: { code: structure.code, name: structure.name, effective_from: structure.effective_from, effective_to: structure.effective_to, currency: 'MNT', components: structure.components.map((component, index) => ({ ...component, is_leave_average_eligible: true, payer: 'employee', position: index })) } })}><Pencil size={14} />Edit</button><button className="secondary-action" disabled={publishStructure.isPending || structure.components.length === 0} onClick={() => publishStructure.mutate(structure.id, { onSuccess: () => toast.success('Salary structure published'), onError: (error: any) => toast.error(errorCode(error, 'Salary structure could not be published')) })}>{publishStructure.isPending ? 'Publishing…' : structure.components.length ? 'Publish structure' : 'Add components first'}</button><button className="icon-action danger-action" onClick={() => removeStructure(structure)} aria-label={`Delete ${structure.code}`}><Trash2 size={15} /></button></div> : <span className="payroll-locked"><LockKeyhole size={13} />Locked after publish</span>}</article>)}</div>}{!profiles.data?.length && !structures.data?.length && <EmptyState title="No payroll configuration" copy="Create a statutory profile and salary structure in Payroll settings to get started." />}</section>
      <section id="employee-setup" className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE SETUP</span><h3>Employees ready for payroll</h3><p>Assign the published salary structure and base salary before creating a run.</p></div><span className="payroll-count">{employeeProfiles.data?.length ?? 0} configured</span></div>{employeeProfiles.isLoading || workers.isLoading ? <p>Loading employees…</p> : <><div className="payroll-employee-list">{employeeProfiles.data?.map((profile) => <div key={profile.id}><span className="payroll-employee-avatar">{workers.data?.find((worker) => worker.id === profile.employee_id)?.name.slice(0, 1) || 'E'}</span><div><strong>{workers.data?.find((worker) => worker.id === profile.employee_id)?.name || `Employee ${profile.employee_id}`}</strong><span>{formatPayrollMoney(profile.base_salary)} · {profile.effective_from}</span></div><StatusBadge status="ready" /></div>)}</div>{activeStructure && unconfiguredWorkers.length > 0 && <div className="payroll-employee-form"><label>Employee<select value={employeeEditor?.employeeId || ''} onChange={(event) => setEmployeeEditor({ employeeId: Number(event.target.value), salary: '' })}><option value="">Choose an employee</option>{unconfiguredWorkers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label><label>Base salary (MNT)<input type="number" min="0" value={employeeEditor?.salary || ''} onChange={(event) => employeeEditor && setEmployeeEditor({ ...employeeEditor, salary: event.target.value })} placeholder="0" /></label><button className="primary-action" disabled={!employeeEditor?.employeeId || !employeeEditor.salary || saveEmployeeProfile.isPending} onClick={saveEmployee}>{saveEmployeeProfile.isPending ? 'Saving…' : 'Add employee'}</button></div>}{!activeStructure && <p className="payroll-helper"><CircleAlert size={15} />Publish a salary structure above before assigning employees.</p>}{activeStructure && !unconfiguredWorkers.length && !employeeProfiles.data?.length && <EmptyState title="No active employees" copy="Add an active employee to begin payroll." />}</>}</section>
      <section id="create-run" className="panel payroll-card erp-create-form"><div className="view-toolbar"><div><span className="eyebrow">NEW PAYROLL RUN</span><h3>Create a consolidated run</h3><p>Employees and approved time inputs are frozen when the run is calculated.</p></div><LockKeyhole size={20} /></div><div className="erp-create-fields payroll-date-fields"><label className="erp-create-field">Period start<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></label><label className="erp-create-field">Period end<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></label><label className="erp-create-field">Tax point date<input type="date" value={taxPoint} onChange={(event) => setTaxPoint(event.target.value)} /></label></div><div className="payroll-form-footer"><span className="payroll-helper">{!activeProfile ? 'Publish a statutory profile first.' : !activeStructure ? 'Publish a salary structure first.' : !hasEmployeeSetup ? 'Add an employee profile first.' : `Using ${activeProfile.code} · v${activeProfile.version}`}</span><button className="primary-action" onClick={createRun} disabled={create.isPending || !activeProfile || !activeStructure || !hasEmployeeSetup}><Play size={15} />{create.isPending ? 'Creating…' : 'Create run'}</button></div></section>
      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">WORKFLOW</span><h3>Run lifecycle</h3><p>Move each run forward only after its reconciliation checks pass.</p></div><FileText size={20} /></div>{runs.isLoading ? <p>Loading runs…</p> : runs.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Runs could not be loaded. Refresh and try again.</div> : runs.data?.length ? <div className="erp-document-list payroll-list">{runs.data.map((run) => <article key={run.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{run.run_number}</strong><StatusBadge status={run.status} /></div><span>{run.run_type} · {run.period_start} – {run.period_end}</span><small>Net pay {formatPayrollMoney(run.total_net)}</small></div><div className="erp-row-actions">{run.status === 'draft' && <button className="secondary-action" onClick={() => calculateRun(run)} disabled={calculate.isPending}><Play size={14} />{calculate.isPending ? 'Calculating…' : 'Calculate'}</button>}{run.status === 'calculated' && <button className="secondary-action" onClick={() => review.mutate(run.id, { onSuccess: () => toast.success('Run sent for review'), onError: (error: any) => toast.error(errorCode(error, 'Review failed')) })} disabled={review.isPending}>Review</button>}{run.status === 'in_review' && <button className="secondary-action" onClick={() => approve.mutate(run.id, { onSuccess: () => toast.success('Run approved'), onError: (error: any) => toast.error(errorCode(error, 'Approval failed')) })} disabled={approve.isPending}>Approve</button>}{run.status === 'approved' && <button className="secondary-action" onClick={() => post.mutate(run.id, { onSuccess: () => toast.success('Run posted to GL'), onError: (error: any) => toast.error(errorCode(error, 'Posting failed')) })} disabled={post.isPending}>Post to GL</button>}<Link className="secondary-action" to={`/erp/payroll/runs/${run.id}`}>View details <ArrowRight size={14} /></Link></div></article>)}</div> : <EmptyState title="No payroll runs yet" copy={hasDraftProfile || hasDraftStructure ? 'Publish the configuration above, then create your first run.' : 'Create a run to start the payroll workflow.'} action={<a href="#create-run" className="secondary-action">Create first run <ArrowRight size={14} /></a>} />}</section>
    </> : <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE SELF-SERVICE</span><h3>Your finalized payslips</h3><p>Only finalized payslips for your linked employee record are visible here.</p></div><FileText size={20} /></div>{payslips.isLoading ? <p>Loading payslips…</p> : payslips.data?.length ? <div className="erp-document-list payroll-list">{payslips.data.map((slip) => <article key={slip.id}><div className="payroll-list-main"><strong>{slip.payroll_run_id}</strong><span>Gross {formatPayrollMoney(slip.gross)} · SHI {formatPayrollMoney(slip.employee_shi)} · PIT {formatPayrollMoney(slip.pit)}</span></div><div className="erp-row-actions"><strong>{formatPayrollMoney(slip.net_pay)}</strong><button className="secondary-action" onClick={() => downloadMyPayslip(slip.id).then(() => toast.success('Payslip downloaded')).catch(() => toast.error('Payslip download failed'))}><Download size={14} />Download</button></div></article>)}</div> : <EmptyState title="No finalized payslips yet" copy="Your approved payslips will appear here once payroll is finalized." />}</section>}
    {profileEditor && <ProfileEditor value={profileEditor.value} editing={Boolean(profileEditor.id)} pending={createProfile.isPending || updateProfile.isPending} onChange={(value) => setProfileEditor({ ...profileEditor, value })} onClose={() => setProfileEditor(null)} onSubmit={saveProfile} />}
    {structureEditor && <StructureEditor value={structureEditor.value} editing={Boolean(structureEditor.id)} pending={createStructure.isPending || updateStructure.isPending} onChange={(value) => setStructureEditor({ ...structureEditor, value })} onClose={() => setStructureEditor(null)} onSubmit={saveStructure} />}
  </div>
}

export default PayrollWorkspacePage
