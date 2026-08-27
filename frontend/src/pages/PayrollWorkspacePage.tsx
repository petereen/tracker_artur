import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowRight, Calculator, CheckCircle2, CircleAlert, Download, FileText, LockKeyhole, Play, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadMyPayslip,
  downloadPayrollExport,
  downloadPayrollReport,
  useActor,
  useApprovePayrollRun,
  useCalculatePayrollRun,
  useCreatePayrollBankExport,
  useCreatePayrollRun,
  useMyPayrollPayslips,
  usePayrollProfiles,
  usePayrollRun,
  usePayrollRuns,
  usePayrollStructures,
  usePostPayrollRun,
  usePublishPayrollProfile,
  usePublishPayrollStructure,
  useReviewPayrollRun,
} from '../api/enterprise'

export const formatPayrollMoney = (value: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
export const canManagePayroll = (roles: string[]) => roles.includes('admin') || roles.includes('manager')

const isPublished = (status?: string) => status === 'published' || status === 'active'
const errorCode = (error: any, fallback: string) => error?.response?.data?.detail?.code || fallback

function StatusBadge({ status }: { status: string }) {
  return <span className={`payroll-status payroll-status-${status}`}><span aria-hidden="true" />{status.replaceAll('_', ' ')}</span>
}

function EmptyState({ title, copy, action }: { title: string; copy: string; action?: ReactNode }) {
  return <div className="payroll-empty"><div className="payroll-empty-icon"><FileText size={20} /></div><strong>{title}</strong><p>{copy}</p>{action}</div>
}

export function PayrollWorkspacePage() {
  const { runId: runIdParam } = useParams<{ runId?: string }>()
  const runId = runIdParam ? Number(runIdParam) : undefined
  const actor = useActor()
  const profiles = usePayrollProfiles(Boolean(actor.data))
  const structures = usePayrollStructures(Boolean(actor.data))
  const runs = usePayrollRuns(Boolean(actor.data))
  const runDetail = usePayrollRun(runId, Boolean(actor.data))
  const payslips = useMyPayrollPayslips(Boolean(actor.data?.employee_id))
  const create = useCreatePayrollRun()
  const calculate = useCalculatePayrollRun()
  const review = useReviewPayrollRun()
  const approve = useApprovePayrollRun()
  const post = usePostPayrollRun()
  const publishProfile = usePublishPayrollProfile()
  const publishStructure = usePublishPayrollStructure()
  const bankExport = useCreatePayrollBankExport()
  const [bankCode, setBankCode] = useState('KHAN')
  const [periodStart, setPeriodStart] = useState(() => new Date().toISOString().slice(0, 8) + '01')
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [taxPoint, setTaxPoint] = useState(() => new Date().toISOString().slice(0, 10))
  const canAdmin = canManagePayroll(actor.data?.roles ?? [])
  const activeProfile = profiles.data?.find((profile) => isPublished(profile.status))
  const activeStructure = structures.data?.find((structure) => isPublished(structure.status))
  const hasDraftProfile = profiles.data?.some((profile) => profile.status === 'draft')
  const hasDraftStructure = structures.data?.some((structure) => structure.status === 'draft')

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
    <div className="view-toolbar payroll-toolbar"><div><span className="eyebrow">OYUNS ALL-IN-ONE · PAYROLL</span><h2>Mongolia payroll</h2><p>Run accurate, effective-dated НДШ / ХХОАТ payroll with an immutable audit trail.</p></div><div className="payroll-toolbar-actions"><div className="payroll-toolbar-icon"><Calculator size={22} /></div>{canAdmin && <a className="primary-action" href="#create-run"><Play size={15} />Create payroll run<ArrowRight size={14} /></a>}</div></div>
    <div className="erp-settings-notice payroll-notice"><ShieldCheck size={16} /><span>Rates, thresholds, reliefs, formulas, accounts, and bank layouts are configuration data. Example profiles require review before use.</span></div>
    {canAdmin ? <>
      <section className="payroll-next-step"><div className="payroll-next-step-icon">{activeProfile && activeStructure ? <CheckCircle2 size={22} /> : <CircleAlert size={22} />}</div><div><span className="eyebrow">{activeProfile && activeStructure ? 'READY FOR A RUN' : 'SETUP REQUIRED'}</span><h3>{activeProfile && activeStructure ? 'Your payroll setup is ready' : 'Finish your payroll setup first'}</h3><p>{activeProfile && activeStructure ? 'Choose a period below to create a consolidated run.' : 'Publish one statutory profile and one salary structure before calculating payroll.'}</p></div>{!activeProfile && <a className="secondary-action" href="#profiles">Review setup <ArrowRight size={14} /></a>}</section>
      <section className="erp-kpis payroll-kpis"><article className="panel"><small>Active statutory profile</small><strong>{activeProfile ? `${activeProfile.code} · v${activeProfile.version}` : 'None published'}</strong><span className="payroll-kpi-detail">{activeProfile ? `Effective ${activeProfile.effective_from}` : 'Publish a reviewed profile'}</span></article><article className="panel"><small>Salary structure</small><strong>{activeStructure ? `${activeStructure.code} · v${activeStructure.version}` : 'None published'}</strong><span className="payroll-kpi-detail">{activeStructure ? `${activeStructure.components.length} pay components` : 'Publish a structure'}</span></article><article className="panel"><small>Example profile guard</small><StatusBadge status={activeProfile?.is_example ? 'review_required' : 'ready'} /><span className="payroll-kpi-detail">{activeProfile?.is_example ? 'Confirm before calculating' : 'No review needed'}</span></article><article className="panel"><small>Payroll runs</small><strong>{runs.data?.length ?? 0}</strong><span className="payroll-kpi-detail">{runs.data?.length ? 'Across all periods' : 'Create your first run'}</span></article></section>
      <section id="profiles" className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">CONFIGURATION</span><h3>Statutory profiles & salary structures</h3><p>Only effective-dated, published versions can be used in a payroll run.</p></div><ShieldCheck size={20} /></div>{profiles.isLoading || structures.isLoading ? <p>Loading configuration…</p> : profiles.isError || structures.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Configuration could not be loaded. Refresh and try again.</div> : <div className="erp-document-list payroll-list">{profiles.data?.map((profile) => <article key={`profile-${profile.id}`}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{profile.code} · v{profile.version}</strong><StatusBadge status={profile.is_example && profile.status === 'draft' ? 'review_required' : profile.status} /></div><span>{profile.effective_from}{profile.effective_to ? ` – ${profile.effective_to}` : ' onward'} · PIT {profile.pit_withholding_method}</span><small>{profile.is_example ? 'Example profile — review against current requirements before publishing.' : `MNT ${profile.minimum_wage} minimum wage · SHI cap ×${profile.shi_ceiling_multiplier}`}</small></div>{profile.status === 'draft' && <button className="secondary-action" disabled={publishProfile.isPending} onClick={() => publishProfileNow(profile)}>{publishProfile.isPending ? 'Publishing…' : profile.is_example ? 'Review & publish' : 'Publish profile'}</button>}</article>)}{structures.data?.map((structure) => <article key={`structure-${structure.id}`}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{structure.code} · v{structure.version}</strong><StatusBadge status={structure.status} /></div><span>{structure.name} · {structure.effective_from} · {structure.components.length} components</span><small>{structure.currency} payroll structure</small></div>{structure.status === 'draft' && <button className="secondary-action" disabled={publishStructure.isPending || structure.components.length === 0} onClick={() => publishStructure.mutate(structure.id, { onSuccess: () => toast.success('Salary structure published'), onError: (error: any) => toast.error(errorCode(error, 'Salary structure could not be published')) })}>{publishStructure.isPending ? 'Publishing…' : structure.components.length ? 'Publish structure' : 'Add components first'}</button>}</article>)}</div>}{!profiles.data?.length && !structures.data?.length && <EmptyState title="No payroll configuration" copy="Create a statutory profile and salary structure in Payroll settings to get started." />}</section>
      <section id="create-run" className="panel payroll-card erp-create-form"><div className="view-toolbar"><div><span className="eyebrow">NEW PAYROLL RUN</span><h3>Create a consolidated run</h3><p>Employees and approved time inputs are frozen when the run is calculated.</p></div><LockKeyhole size={20} /></div><div className="erp-create-fields payroll-date-fields"><label className="erp-create-field">Period start<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></label><label className="erp-create-field">Period end<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></label><label className="erp-create-field">Tax point date<input type="date" value={taxPoint} onChange={(event) => setTaxPoint(event.target.value)} /></label></div><div className="payroll-form-footer"><span className="payroll-helper">{activeProfile ? `Using ${activeProfile.code} · v${activeProfile.version}` : 'Publish a statutory profile to enable this action.'}</span><button className="primary-action" onClick={createRun} disabled={create.isPending || !activeProfile || !activeStructure}><Play size={15} />{create.isPending ? 'Creating…' : 'Create run'}</button></div></section>
      <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">WORKFLOW</span><h3>Run lifecycle</h3><p>Move each run forward only after its reconciliation checks pass.</p></div><FileText size={20} /></div>{runs.isLoading ? <p>Loading runs…</p> : runs.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Runs could not be loaded. Refresh and try again.</div> : runs.data?.length ? <div className="erp-document-list payroll-list">{runs.data.map((run) => <article key={run.id}><div className="payroll-list-main"><div className="payroll-list-title"><strong>{run.run_number}</strong><StatusBadge status={run.status} /></div><span>{run.run_type} · {run.period_start} – {run.period_end}</span><small>Net pay {formatPayrollMoney(run.total_net)}</small></div><div className="erp-row-actions">{run.status === 'draft' && <button className="secondary-action" onClick={() => calculateRun(run)} disabled={calculate.isPending}><Play size={14} />{calculate.isPending ? 'Calculating…' : 'Calculate'}</button>}{run.status === 'calculated' && <button className="secondary-action" onClick={() => review.mutate(run.id, { onSuccess: () => toast.success('Run sent for review'), onError: (error: any) => toast.error(errorCode(error, 'Review failed')) })} disabled={review.isPending}>Review</button>}{run.status === 'in_review' && <button className="secondary-action" onClick={() => approve.mutate(run.id, { onSuccess: () => toast.success('Run approved'), onError: (error: any) => toast.error(errorCode(error, 'Approval failed')) })} disabled={approve.isPending}>Approve</button>}{run.status === 'approved' && <button className="secondary-action" onClick={() => post.mutate(run.id, { onSuccess: () => toast.success('Run posted to GL'), onError: (error: any) => toast.error(errorCode(error, 'Posting failed')) })} disabled={post.isPending}>Post to GL</button>}<Link className="secondary-action" to={`/erp/payroll/runs/${run.id}`}>View details <ArrowRight size={14} /></Link></div></article>)}</div> : <EmptyState title="No payroll runs yet" copy={hasDraftProfile || hasDraftStructure ? 'Publish the configuration above, then create your first run.' : 'Create a run to start the payroll workflow.'} action={<a href="#create-run" className="secondary-action">Create first run <ArrowRight size={14} /></a>} />}</section>
    </> : <section className="panel payroll-card"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE SELF-SERVICE</span><h3>Your finalized payslips</h3><p>Only finalized payslips for your linked employee record are visible here.</p></div><FileText size={20} /></div>{payslips.isLoading ? <p>Loading payslips…</p> : payslips.data?.length ? <div className="erp-document-list payroll-list">{payslips.data.map((slip) => <article key={slip.id}><div className="payroll-list-main"><strong>{slip.payroll_run_id}</strong><span>Gross {formatPayrollMoney(slip.gross)} · SHI {formatPayrollMoney(slip.employee_shi)} · PIT {formatPayrollMoney(slip.pit)}</span></div><div className="erp-row-actions"><strong>{formatPayrollMoney(slip.net_pay)}</strong><button className="secondary-action" onClick={() => downloadMyPayslip(slip.id).then(() => toast.success('Payslip downloaded')).catch(() => toast.error('Payslip download failed'))}><Download size={14} />Download</button></div></article>)}</div> : <EmptyState title="No finalized payslips yet" copy="Your approved payslips will appear here once payroll is finalized." />}</section>}
  </div>
}

export default PayrollWorkspacePage
