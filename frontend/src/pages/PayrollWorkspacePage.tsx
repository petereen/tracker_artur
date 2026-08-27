import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Calculator, FileText, LockKeyhole, Play, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { downloadMyPayslip, downloadPayrollExport, downloadPayrollReport, useActor, useApprovePayrollRun, useCalculatePayrollRun, useCreatePayrollBankExport, useCreatePayrollRun, useMyPayrollPayslips, usePayrollProfiles, usePayrollRun, usePayrollRuns, usePayrollStructures, usePostPayrollRun, useReviewPayrollRun } from '../api/enterprise'

export const formatPayrollMoney = (value: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
export const canManagePayroll = (roles: string[]) => roles.includes('admin') || roles.includes('manager')

export function PayrollWorkspacePage() {
  const { runId: runIdParam } = useParams<{ runId?: string }>()
  const runId = runIdParam ? Number(runIdParam) : undefined
  const actor = useActor()
  const profiles = usePayrollProfiles(Boolean(actor.data))
  const structures = usePayrollStructures(Boolean(actor.data))
  const runs = usePayrollRuns(Boolean(actor.data))
  const runDetail = usePayrollRun(runId, Boolean(actor.data))
  const payslips = useMyPayrollPayslips(Boolean(actor.data?.employee_id))
  const create = useCreatePayrollRun(); const calculate = useCalculatePayrollRun(); const review = useReviewPayrollRun(); const approve = useApprovePayrollRun(); const post = usePostPayrollRun(); const bankExport = useCreatePayrollBankExport()
  const [bankCode, setBankCode] = useState('KHAN')
  const [periodStart, setPeriodStart] = useState(() => new Date().toISOString().slice(0, 8) + '01')
  const [periodEnd, setPeriodEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [taxPoint, setTaxPoint] = useState(() => new Date().toISOString().slice(0, 10))
  const canAdmin = canManagePayroll(actor.data?.roles ?? [])
  const activeProfile = profiles.data?.find((profile) => profile.status === 'published' || profile.status === 'active')
  const createRun = () => {
    if (!activeProfile) { toast.error('Publish an approved statutory profile first'); return }
    create.mutate({ run_type: 'single', period_start: periodStart, period_end: periodEnd, tax_point_date: taxPoint, statutory_profile_id: activeProfile.id }, { onSuccess: () => toast.success('Payroll run created'), onError: (error: any) => toast.error(error.response?.data?.detail?.code || 'Payroll run could not be created') })
  }
  if (actor.isLoading) return <div className="panel"><p>Loading payroll…</p></div>
  if (!actor.data) return <div className="panel"><p>Payroll access is unavailable.</p></div>
  const downloadGeneratedExport = async (payload: { artifact_id: number; filename: string }) => {
    try { await downloadPayrollExport(payload.artifact_id, payload.filename) } catch { toast.error('Bank export download failed') }
  }
  if (runId && canAdmin) return <div className="erp-workspace payroll-workspace">
    <div className="view-toolbar"><div><Link to="/erp/payroll" className="secondary-action compact">← All payroll runs</Link><span className="eyebrow">PAYROLL RUN DETAIL</span><h2>{runDetail.data?.run_number || `Run ${runId}`}</h2><p>Immutable calculation trace, cap consumption, YTD values, and reconciliation.</p></div><FileText /></div>
    {runDetail.isLoading ? <section className="panel"><p>Loading run…</p></section> : runDetail.isError || !runDetail.data ? <section className="panel"><p>Payroll run not found.</p></section> : <>
      <section className="erp-kpis"><article className="panel"><small>Status</small><strong>{runDetail.data.status}</strong></article><article className="panel"><small>Gross</small><strong>{formatPayrollMoney(runDetail.data.total_gross)}</strong></article><article className="panel"><small>Employee SHI / PIT</small><strong>{formatPayrollMoney(runDetail.data.total_employee_shi)} / {formatPayrollMoney(runDetail.data.total_pit)}</strong></article><article className="panel"><small>Net pay</small><strong>{formatPayrollMoney(runDetail.data.total_net)}</strong></article></section>
      <section className="panel"><div className="view-toolbar"><div><h3>Bank batch and state reports</h3><p>Templates remain provisional until golden-file comparison with the issuing bank or authority.</p></div><ShieldCheck size={18} /></div><div className="erp-create-fields"><label className="erp-create-field">Bank preset<input value={bankCode} onChange={(event) => setBankCode(event.target.value.toUpperCase())} /></label><button className="secondary-action compact" disabled={bankExport.isPending || !['approved', 'posted', 'paid'].includes(runDetail.data.status)} onClick={() => bankExport.mutate({ id: runId, bank_code: bankCode }, { onSuccess: downloadGeneratedExport, onError: () => toast.error('Bank export could not be generated') })}>Generate payout CSV</button>{(['nd7', 'nd8', 'tt11'] as const).map((kind) => <button key={kind} className="secondary-action compact" onClick={() => downloadPayrollReport(runId, kind).catch(() => toast.error(`${kind.toUpperCase()} export failed`))}>{kind === 'tt11' ? 'ТТ-11' : kind.toUpperCase()}</button>)}</div></section>
      <section className="panel"><h3>Payslips</h3>{runDetail.data.payslips.length ? <div className="erp-document-list">{runDetail.data.payslips.map((slip) => <article key={slip.id}><div><strong>Employee {slip.employee_id}</strong><span>Gross {formatPayrollMoney(slip.gross)} · SHI subject {formatPayrollMoney(slip.shi_subject_gross)} · SHI base {formatPayrollMoney(slip.shi_base)} · PIT {formatPayrollMoney(slip.pit)}</span></div><div><strong>{formatPayrollMoney(slip.net_pay)}</strong><span>{slip.ytd?.taxable ? `YTD taxable ${formatPayrollMoney(slip.ytd.taxable)}` : ''}</span></div></article>)}</div> : <p>No payslips in this run.</p>}</section>
    </>}
  </div>
  return <div className="erp-workspace payroll-workspace">
    <div className="view-toolbar"><div><span className="eyebrow">OYUNS ALL-IN-ONE · PAYROLL</span><h2>Mongolia payroll</h2><p>Effective-dated НДШ / ХХОАТ calculations with immutable snapshots.</p></div><Calculator /></div>
    <div className="erp-settings-notice"><ShieldCheck size={15} /> Rates, thresholds, reliefs, formulas, accounts, and bank layouts are configuration data. Example profiles are not legal advice.</div>
    {canAdmin ? <>
      <section className="erp-kpis">
        <article className="panel"><small>Active statutory profile</small><strong>{activeProfile ? `${activeProfile.code} v${activeProfile.version}` : 'None published'}</strong></article>
        <article className="panel"><small>Example profile guard</small><strong>{activeProfile?.is_example ? 'Review required' : 'Ready'}</strong></article>
        <article className="panel"><small>Payroll runs</small><strong>{runs.data?.length ?? 0}</strong></article>
      </section>
      <section className="panel"><div className="view-toolbar"><div><h3>Statutory profiles & salary structures</h3><p>Only effective-dated, published versions can be selected for a run.</p></div><ShieldCheck size={18} /></div><div className="erp-document-list">{profiles.data?.map((profile) => <article key={`profile-${profile.id}`}><div><strong>{profile.code} · v{profile.version}</strong><span>{profile.status} · {profile.effective_from}{profile.effective_to ? ` – ${profile.effective_to}` : ''} · PIT {profile.pit_withholding_method}</span></div><span>{profile.is_example ? 'EXAMPLE — REVIEW REQUIRED' : `MNT ${profile.minimum_wage} · SHI cap ×${profile.shi_ceiling_multiplier}`}</span></article>)}{structures.data?.map((structure) => <article key={`structure-${structure.id}`}><div><strong>{structure.code} · v{structure.version}</strong><span>{structure.status} · {structure.effective_from} · {structure.components.length} components</span></div><span>{structure.currency}</span></article>)}</div></section>
      <section className="panel erp-create-form"><div className="view-toolbar"><div><h3>Create a consolidated run</h3><p>Employees and approved time inputs are frozen when the run is calculated.</p></div><LockKeyhole size={18} /></div><div className="erp-create-fields"><label className="erp-create-field">Period start<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></label><label className="erp-create-field">Period end<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></label><label className="erp-create-field">Tax point date<input type="date" value={taxPoint} onChange={(event) => setTaxPoint(event.target.value)} /></label></div><button className="primary-action compact" onClick={createRun} disabled={create.isPending}><Play size={14} />Create run</button></section>
      <section className="panel"><div className="view-toolbar"><div><h3>Run lifecycle</h3><p>Calculate, review, approve, and post only after the reconciliation checks pass.</p></div><FileText size={18} /></div>{runs.isLoading ? <p>Loading runs…</p> : runs.data?.length ? <div className="erp-document-list">{runs.data.map((run) => <article key={run.id}><div><strong>{run.run_number}</strong><span>{run.run_type} · {run.period_start} – {run.period_end} · {run.status}</span></div><div><strong>{formatPayrollMoney(run.total_net)}</strong><div className="erp-row-actions">{run.status === 'draft' && <button className="secondary-action compact" onClick={() => calculate.mutate({ id: run.id }, { onError: (error: any) => toast.error(error.response?.data?.detail?.code || 'Calculation failed') })} disabled={calculate.isPending}>Calculate</button>}{run.status === 'calculated' && <button className="secondary-action compact" onClick={() => review.mutate(run.id, { onError: (error: any) => toast.error(error.response?.data?.detail?.code || 'Review failed') })} disabled={review.isPending}>Review</button>}{run.status === 'in_review' && <button className="secondary-action compact" onClick={() => approve.mutate(run.id, { onError: (error: any) => toast.error(error.response?.data?.detail?.code || 'Approval failed') })} disabled={approve.isPending}>Approve</button>}{run.status === 'approved' && <button className="secondary-action compact" onClick={() => post.mutate(run.id, { onError: (error: any) => toast.error(error.response?.data?.detail?.code || 'Posting failed') })} disabled={post.isPending}>Post to GL</button>}<Link className="secondary-action compact" to={`/erp/payroll/runs/${run.id}`}>View</Link></div></div></article>)}</div> : <p>No payroll runs yet.</p>}</section>
    </> : <section className="panel"><div className="view-toolbar"><div><h3>Your finalized payslips</h3><p>Only finalized payslips for your linked employee record are visible here.</p></div><FileText size={18} /></div>{payslips.isLoading ? <p>Loading payslips…</p> : payslips.data?.length ? <div className="erp-document-list">{payslips.data.map((slip) => <article key={slip.id}><div><strong>{slip.payroll_run_id}</strong><span>Gross {formatPayrollMoney(slip.gross)} · SHI {formatPayrollMoney(slip.employee_shi)} · PIT {formatPayrollMoney(slip.pit)}</span></div><div><strong>{formatPayrollMoney(slip.net_pay)}</strong><button className="secondary-action compact" onClick={() => downloadMyPayslip(slip.id).catch(() => toast.error('Payslip download failed'))}>Download</button></div></article>)}</div> : <p>No finalized payslips yet.</p>}</section>}
  </div>
}

export default PayrollWorkspacePage
