import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BadgeAlert, Check, Coins, FileCheck2, Plus, ReceiptText, Scale, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useActor,
  useCreatePayrollBenefitApplication,
  useCreatePayrollBenefitClaim,
  useCreatePayrollTaxCategory,
  useCreatePayrollTaxDeclaration,
  useCreatePayrollTaxProof,
  usePayrollBenefitApplications,
  usePayrollBenefitClaims,
  usePayrollIncomeTaxComputation,
  usePayrollFlexibleBenefitComponents,
  usePayrollStructures,
  usePayrollTaxCategories,
  usePayrollTaxDeclarations,
  usePayrollTaxProofs,
  useReviewPayrollBenefitApplication,
  useReviewPayrollBenefitClaim,
  useReviewPayrollTaxDeclaration,
  useReviewPayrollTaxProof,
  useSubmitPayrollBenefitApplication,
  useSubmitPayrollTaxDeclaration,
  useUpdatePayrollStructure,
  useWorkerDirectory,
} from '../api/enterprise'
import { formatPayrollMoney } from './PayrollWorkspacePage'

const errorMessage = (error: any, fallback: string) => error?.response?.data?.detail?.code || fallback

function Status({ value }: { value: string }) {
  return <span className={`payroll-status payroll-status-${value}`}><span aria-hidden="true" />{value.replaceAll('_', ' ')}</span>
}

export function TaxBenefitsWorkspacePage() {
  const actor = useActor()
  const workers = useWorkerDirectory()
  const canAdmin = Boolean(actor.data?.roles?.some((role) => ['admin', 'manager', 'hr'].includes(role)))
  const structures = usePayrollStructures(canAdmin)
  const publishedBenefits = usePayrollFlexibleBenefitComponents()
  const [taxYear, setTaxYear] = useState(new Date().getFullYear())
  const categories = usePayrollTaxCategories()
  const declarations = usePayrollTaxDeclarations(taxYear)
  const proofs = usePayrollTaxProofs()
  const applications = usePayrollBenefitApplications(taxYear)
  const claims = usePayrollBenefitClaims()
  const computation = usePayrollIncomeTaxComputation(taxYear)
  const createCategory = useCreatePayrollTaxCategory()
  const createDeclaration = useCreatePayrollTaxDeclaration()
  const submitDeclaration = useSubmitPayrollTaxDeclaration()
  const reviewDeclaration = useReviewPayrollTaxDeclaration()
  const createProof = useCreatePayrollTaxProof()
  const reviewProof = useReviewPayrollTaxProof()
  const createApplication = useCreatePayrollBenefitApplication()
  const submitApplication = useSubmitPayrollBenefitApplication()
  const reviewApplication = useReviewPayrollBenefitApplication()
  const createClaim = useCreatePayrollBenefitClaim()
  const reviewClaim = useReviewPayrollBenefitClaim()
  const updateStructure = useUpdatePayrollStructure()

  const [categoryForm, setCategoryForm] = useState({ code: '', name: '', treatment: 'tax_deduction' as 'tax_deduction' | 'tax_credit', annual_limit: '0', requires_proof: true })
  const [declarationForm, setDeclarationForm] = useState({ employee_id: '', category_id: '', amount: '', note: '' })
  const [proofForm, setProofForm] = useState({ declaration_id: '', amount: '', reference: '' })
  const [applicationForm, setApplicationForm] = useState({ employee_id: '', component_id: '', amount: '', note: '' })
  const [claimForm, setClaimForm] = useState({ application_id: '', claim_date: new Date().toISOString().slice(0, 10), amount: '', reference: '' })
  const [benefitSetup, setBenefitSetup] = useState({ component_id: '', annual_limit: '' })
  const flexibleComponents = publishedBenefits.data || []
  const workerName = (id: number) => workers.data?.find((worker) => worker.id === id)?.name || `Employee ${id}`
  const ownEmployeeId = actor.data?.employee_id ?? undefined
  const draftComponents = useMemo(() => structures.data?.filter((structure) => structure.status === 'draft').flatMap((structure) => structure.components.filter((component) => component.id).map((component) => ({ ...component, structure }))) || [], [structures.data])

  const enableFlexibleBenefit = () => {
    const selected = draftComponents.find((component) => component.id === Number(benefitSetup.component_id))
    if (!selected) return
    const structure = selected.structure
    updateStructure.mutate({
      id: structure.id,
      code: structure.code,
      name: structure.name,
      effective_from: structure.effective_from,
      effective_to: structure.effective_to,
      currency: 'MNT',
      components: structure.components.map((component, index) => ({
        ...component,
        is_flexible_benefit: component.id === selected.id ? true : component.is_flexible_benefit,
        max_benefit_amount_yearly: component.id === selected.id ? benefitSetup.annual_limit : component.max_benefit_amount_yearly,
        pay_against_benefit_claim: component.id === selected.id ? true : component.pay_against_benefit_claim,
        payer: 'employee',
        position: index,
      })),
    }, { onSuccess: () => { toast.success('Flexible benefit enabled'); setBenefitSetup({ component_id: '', annual_limit: '' }) }, onError: (error) => toast.error(errorMessage(error, 'Could not update salary structure')) })
  }

  const employeePicker = (value: string, onChange: (value: string) => void) => canAdmin ? <select value={value} onChange={(event) => onChange(event.target.value)}><option value="">Choose employee</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select> : null
  const reviewButtons = (approve: () => void, reject: () => void, pending: boolean) => canAdmin && <div className="erp-row-actions"><button className="secondary-action" disabled={pending} onClick={approve}><Check size={14} />Approve</button><button className="icon-action danger-action" disabled={pending} onClick={reject} aria-label="Reject"><X size={15} /></button></div>

  return <div className="erp-workspace payroll-workspace tax-benefits-workspace">
    <div className="view-toolbar payroll-toolbar"><div><span className="eyebrow">OYUNS ALL-IN-ONE · PAYROLL</span><h2>Tax &amp; Benefits</h2><p>Frappe-style declarations, proof review, flexible benefits, and income-tax computation adapted for Mongolia payroll.</p></div><div className="payroll-toolbar-actions"><label className="tax-year-picker">Tax year<input type="number" min="2000" max="2200" value={taxYear} onChange={(event) => setTaxYear(Number(event.target.value))} /></label><div className="payroll-toolbar-icon"><Coins size={22} /></div><Link className="secondary-action" to="/erp/payroll">Back to payroll</Link></div></div>
    <div className="erp-settings-notice payroll-notice"><Scale size={16} /><span>Only approved declarations/proofs and benefit claims affect a calculation. Every applied amount and source ID is frozen into the payroll run snapshot.</span></div>

    <section className="erp-kpis payroll-kpis"><article className="panel"><small>Exemption declarations</small><strong>{declarations.data?.length || 0}</strong><span className="payroll-kpi-detail">{declarations.data?.filter((row) => row.status === 'submitted').length || 0} awaiting review</span></article><article className="panel"><small>Proof submissions</small><strong>{proofs.data?.length || 0}</strong><span className="payroll-kpi-detail">{proofs.data?.filter((row) => row.status === 'approved').length || 0} approved</span></article><article className="panel"><small>Benefit applications</small><strong>{applications.data?.length || 0}</strong><span className="payroll-kpi-detail">{applications.data?.filter((row) => row.status === 'approved').length || 0} approved</span></article><article className="panel"><small>Benefit claims</small><strong>{claims.data?.length || 0}</strong><span className="payroll-kpi-detail">{claims.data?.filter((row) => row.status === 'paid').length || 0} paid through payroll</span></article></section>

    <div className="tax-benefits-grid">
      {canAdmin && <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">BENEFIT SETUP</span><h3>Flexible salary components</h3><p>Mark an earning in a draft salary structure as claim-based before publishing it.</p></div><Coins size={20} /></div>{flexibleComponents.length > 0 && <div className="erp-document-list payroll-list compact-list">{flexibleComponents.map((component) => <article key={component.id}><div className="payroll-list-main"><strong>{component.name}</strong><span>{component.structure} · annual limit {formatPayrollMoney(component.max_benefit_amount_yearly || '0')}</span></div><Status value="active" /></article>)}</div>}<div className="tax-benefits-form"><select value={benefitSetup.component_id} onChange={(event) => setBenefitSetup({ ...benefitSetup, component_id: event.target.value })}><option value="">Choose draft earning</option>{draftComponents.filter((component) => component.component_kind === 'earning').map((component) => <option key={component.id} value={component.id}>{component.name} · {component.structure.name}</option>)}</select><input type="number" min="0.01" step="0.01" placeholder="Annual benefit limit" value={benefitSetup.annual_limit} onChange={(event) => setBenefitSetup({ ...benefitSetup, annual_limit: event.target.value })} /><button className="primary-action" type="button" disabled={!benefitSetup.component_id || !benefitSetup.annual_limit || updateStructure.isPending} onClick={enableFlexibleBenefit}><Plus size={14} />Enable flexible benefit</button></div>{!draftComponents.length && <p className="payroll-helper">Create or keep a salary structure draft in Payroll to configure claim-based benefits.</p>}</section>}
      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">TAX SETUP</span><h3>Exemption categories</h3><p>Configure deductions from taxable income or credits against calculated PIT.</p></div><BadgeAlert size={20} /></div>{categories.data?.length ? <div className="erp-document-list payroll-list compact-list">{categories.data.map((row) => <article key={row.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{row.name}</strong><Status value={row.treatment} /></div><span>{row.code} · limit {row.annual_limit === '0.0000' || row.annual_limit === '0' ? 'not capped' : formatPayrollMoney(row.annual_limit)}</span><small>{row.requires_proof ? 'Proof required' : 'Declaration approval is sufficient'}</small></div></article>)}</div> : <p className="payroll-editor-empty">No exemption categories configured.</p>}{canAdmin && <form className="tax-benefits-form" onSubmit={(event) => { event.preventDefault(); createCategory.mutate(categoryForm, { onSuccess: () => { toast.success('Exemption category created'); setCategoryForm({ code: '', name: '', treatment: 'tax_deduction', annual_limit: '0', requires_proof: true }) }, onError: (error) => toast.error(errorMessage(error, 'Could not create category')) }) }}><input required placeholder="Code" value={categoryForm.code} onChange={(event) => setCategoryForm({ ...categoryForm, code: event.target.value.toUpperCase() })} /><input required placeholder="Category name" value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} /><select value={categoryForm.treatment} onChange={(event) => setCategoryForm({ ...categoryForm, treatment: event.target.value as typeof categoryForm.treatment })}><option value="tax_deduction">Taxable-income deduction</option><option value="tax_credit">PIT credit</option></select><input type="number" min="0" placeholder="Annual limit" value={categoryForm.annual_limit} onChange={(event) => setCategoryForm({ ...categoryForm, annual_limit: event.target.value })} /><label className="payroll-check-label"><input type="checkbox" checked={categoryForm.requires_proof} onChange={(event) => setCategoryForm({ ...categoryForm, requires_proof: event.target.checked })} />Proof required</label><button className="primary-action" disabled={createCategory.isPending}><Plus size={14} />Add category</button></form>}</section>

      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">EXEMPTION</span><h3>Employee declarations</h3><p>Employees declare eligible annual amounts; payroll reviewers approve them.</p></div><FileCheck2 size={20} /></div><div className="erp-document-list payroll-list compact-list">{declarations.data?.map((row) => <article key={row.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{workerName(row.employee_id)}</strong><Status value={row.status} /></div><span>{categories.data?.find((category) => category.id === row.category_id)?.name || `Category ${row.category_id}`} · {formatPayrollMoney(row.declared_amount)}</span></div>{row.status === 'draft' ? <button className="secondary-action" disabled={submitDeclaration.isPending} onClick={() => submitDeclaration.mutate(row.id)}>Submit</button> : row.status === 'submitted' ? reviewButtons(() => reviewDeclaration.mutate({ id: row.id, approve: true }), () => reviewDeclaration.mutate({ id: row.id, approve: false }), reviewDeclaration.isPending) : null}</article>)}</div><form className="tax-benefits-form" onSubmit={(event) => { event.preventDefault(); createDeclaration.mutate({ employee_id: canAdmin ? Number(declarationForm.employee_id) : ownEmployeeId, category_id: Number(declarationForm.category_id), tax_year: taxYear, declared_amount: declarationForm.amount, note: declarationForm.note || undefined }, { onSuccess: () => { toast.success('Declaration saved as draft'); setDeclarationForm({ employee_id: '', category_id: '', amount: '', note: '' }) }, onError: (error) => toast.error(errorMessage(error, 'Could not save declaration')) }) }}>{employeePicker(declarationForm.employee_id, (employee_id) => setDeclarationForm({ ...declarationForm, employee_id }))}<select required value={declarationForm.category_id} onChange={(event) => setDeclarationForm({ ...declarationForm, category_id: event.target.value })}><option value="">Choose category</option>{categories.data?.filter((row) => row.is_active).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select><input required type="number" min="0.01" step="0.01" placeholder="Declared amount" value={declarationForm.amount} onChange={(event) => setDeclarationForm({ ...declarationForm, amount: event.target.value })} /><input placeholder="Note (optional)" value={declarationForm.note} onChange={(event) => setDeclarationForm({ ...declarationForm, note: event.target.value })} /><button className="primary-action" disabled={createDeclaration.isPending || (canAdmin && !declarationForm.employee_id)}><Plus size={14} />Save declaration</button></form></section>

      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">EXEMPTION</span><h3>Proof submissions</h3><p>Approved proof is capped by the declaration and category annual limit.</p></div><ReceiptText size={20} /></div><div className="erp-document-list payroll-list compact-list">{proofs.data?.map((row) => <article key={row.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{row.reference}</strong><Status value={row.status} /></div><span>{formatPayrollMoney(row.amount)} · declaration #{row.declaration_id}</span></div>{row.status === 'submitted' && reviewButtons(() => reviewProof.mutate({ id: row.id, approve: true }), () => reviewProof.mutate({ id: row.id, approve: false }), reviewProof.isPending)}</article>)}</div><form className="tax-benefits-form" onSubmit={(event) => { event.preventDefault(); createProof.mutate({ declarationId: Number(proofForm.declaration_id), amount: proofForm.amount, reference: proofForm.reference }, { onSuccess: () => { toast.success('Proof submitted'); setProofForm({ declaration_id: '', amount: '', reference: '' }) }, onError: (error) => toast.error(errorMessage(error, 'Could not submit proof')) }) }}><select required value={proofForm.declaration_id} onChange={(event) => setProofForm({ ...proofForm, declaration_id: event.target.value })}><option value="">Choose declaration</option>{declarations.data?.filter((row) => ['submitted', 'approved'].includes(row.status)).map((row) => <option key={row.id} value={row.id}>{workerName(row.employee_id)} · #{row.id}</option>)}</select><input required type="number" min="0.01" step="0.01" placeholder="Proof amount" value={proofForm.amount} onChange={(event) => setProofForm({ ...proofForm, amount: event.target.value })} /><input required placeholder="Document/reference" value={proofForm.reference} onChange={(event) => setProofForm({ ...proofForm, reference: event.target.value })} /><button className="primary-action" disabled={createProof.isPending}><Plus size={14} />Submit proof</button></form></section>

      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">BENEFITS</span><h3>Benefit applications</h3><p>Employees allocate annual flexible-benefit limits from their salary structure.</p></div><Coins size={20} /></div>{!flexibleComponents.length && <div className="payroll-inline-error">Add a flexible earning component to a salary structure before accepting applications.</div>}<div className="erp-document-list payroll-list compact-list">{applications.data?.map((row) => <article key={row.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{workerName(row.employee_id)}</strong><Status value={row.status} /></div><span>{flexibleComponents.find((component) => component.id === row.salary_component_id)?.name || `Benefit ${row.salary_component_id}`} · requested {formatPayrollMoney(row.requested_amount)}</span>{row.status === 'approved' && <small>Approved {formatPayrollMoney(row.approved_amount)}</small>}</div>{row.status === 'draft' ? <button className="secondary-action" onClick={() => submitApplication.mutate(row.id)}>Submit</button> : row.status === 'submitted' ? reviewButtons(() => reviewApplication.mutate({ id: row.id, approved_amount: row.requested_amount, approve: true }), () => reviewApplication.mutate({ id: row.id, approved_amount: '0', approve: false }), reviewApplication.isPending) : null}</article>)}</div><form className="tax-benefits-form" onSubmit={(event) => { event.preventDefault(); createApplication.mutate({ employee_id: canAdmin ? Number(applicationForm.employee_id) : ownEmployeeId, salary_component_id: Number(applicationForm.component_id), tax_year: taxYear, requested_amount: applicationForm.amount, note: applicationForm.note || undefined }, { onSuccess: () => { toast.success('Benefit application saved'); setApplicationForm({ employee_id: '', component_id: '', amount: '', note: '' }) }, onError: (error) => toast.error(errorMessage(error, 'Could not save benefit application')) }) }}>{employeePicker(applicationForm.employee_id, (employee_id) => setApplicationForm({ ...applicationForm, employee_id }))}<select required value={applicationForm.component_id} onChange={(event) => setApplicationForm({ ...applicationForm, component_id: event.target.value })}><option value="">Choose flexible benefit</option>{flexibleComponents.map((component) => <option key={component.id} value={component.id}>{component.name} · {component.structure}</option>)}</select><input required type="number" min="0.01" step="0.01" placeholder="Requested amount" value={applicationForm.amount} onChange={(event) => setApplicationForm({ ...applicationForm, amount: event.target.value })} /><input placeholder="Note (optional)" value={applicationForm.note} onChange={(event) => setApplicationForm({ ...applicationForm, note: event.target.value })} /><button className="primary-action" disabled={createApplication.isPending || !flexibleComponents.length || (canAdmin && !applicationForm.employee_id)}><Plus size={14} />Save application</button></form></section>

      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">BENEFITS</span><h3>Benefit claims</h3><p>Approved claims enter the matching payroll period and become frozen payslip lines.</p></div><ReceiptText size={20} /></div><div className="erp-document-list payroll-list compact-list">{claims.data?.map((row) => <article key={row.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{row.reference}</strong><Status value={row.status} /></div><span>{formatPayrollMoney(row.amount)} · {row.claim_date}</span>{row.payroll_run_id && <small>Payroll run #{row.payroll_run_id}</small>}</div>{row.status === 'submitted' && reviewButtons(() => reviewClaim.mutate({ id: row.id, approve: true }), () => reviewClaim.mutate({ id: row.id, approve: false }), reviewClaim.isPending)}</article>)}</div><form className="tax-benefits-form" onSubmit={(event) => { event.preventDefault(); createClaim.mutate({ application_id: Number(claimForm.application_id), claim_date: claimForm.claim_date, amount: claimForm.amount, reference: claimForm.reference }, { onSuccess: () => { toast.success('Benefit claim submitted'); setClaimForm({ application_id: '', claim_date: new Date().toISOString().slice(0, 10), amount: '', reference: '' }) }, onError: (error) => toast.error(errorMessage(error, 'Could not submit benefit claim')) }) }}><select required value={claimForm.application_id} onChange={(event) => setClaimForm({ ...claimForm, application_id: event.target.value })}><option value="">Choose approved application</option>{applications.data?.filter((row) => row.status === 'approved').map((row) => <option key={row.id} value={row.id}>{workerName(row.employee_id)} · {formatPayrollMoney(row.approved_amount)}</option>)}</select><input required type="date" value={claimForm.claim_date} onChange={(event) => setClaimForm({ ...claimForm, claim_date: event.target.value })} /><input required type="number" min="0.01" step="0.01" placeholder="Claim amount" value={claimForm.amount} onChange={(event) => setClaimForm({ ...claimForm, amount: event.target.value })} /><input required placeholder="Receipt/reference" value={claimForm.reference} onChange={(event) => setClaimForm({ ...claimForm, reference: event.target.value })} /><button className="primary-action" disabled={createClaim.isPending}><Plus size={14} />Submit claim</button></form></section>
    </div>

    <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">REPORTS</span><h3>Income tax computation</h3><p>Year-to-date payroll values with approved declaration adjustments.</p></div><Scale size={20} /></div>{computation.data?.rows.length ? <div className="tax-computation-table"><div className="tax-computation-head"><span>Employee</span><span>Gross</span><span>Taxable</span><span>SHI</span><span>Relief</span><span>PIT</span></div>{computation.data.rows.map((row) => <div key={row.employee_id}><strong>{workerName(row.employee_id)}</strong><span>{formatPayrollMoney(row.gross)}</span><span>{formatPayrollMoney(row.taxable_income)}</span><span>{formatPayrollMoney(row.employee_shi)}</span><span>{formatPayrollMoney(row.pit_relief)}</span><strong>{formatPayrollMoney(row.pit)}</strong><small>Approved declaration: deduction {formatPayrollMoney(row.approved_tax_deduction)} · credit {formatPayrollMoney(row.approved_tax_credit)}</small></div>)}</div> : <div className="payroll-empty"><Scale size={24} /><strong>No tax computation yet</strong><p>Calculated payroll runs for {taxYear} will appear here.</p></div>}</section>
  </div>
}

export default TaxBenefitsWorkspacePage
