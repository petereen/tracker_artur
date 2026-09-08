import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, BarChart3, Calculator, CalendarDays, ChevronRight, CircleAlert, ClipboardList, Download, FileText, Filter, Landmark, Plus, RefreshCw, Send, Settings2, ShieldCheck, Users, WalletCards, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadProtectedPayslip,
  useActor,
  useCreatePayrollStructure,
  useERPAccountOptions,
  useMyPayrollPayslips,
  usePayrollPostingProfile,
  usePayrollProfiles,
  usePayrollStructures,
  useSavePayrollPostingProfile,
  useWorkerDirectory,
  usePayrollPeriods,
  useCreatePayrollPeriod,
  usePayrollComponentMasters,
  useCreatePayrollComponentMaster,
  usePayrollStructureAssignments,
  useBulkPayrollStructureAssignment,
  usePayrollAdditionalSalaries,
  useCreatePayrollAdditionalSalary,
  useSubmitPayrollAdditionalSalary,
  useCancelPayrollAdditionalSalary,
  usePayrollEntries,
  usePayrollEntry,
  useCreatePayrollEntry,
  useGetPayrollEntryEmployees,
  useCreatePayrollEntrySalarySlips,
  useSubmitPayrollEntrySalarySlips,
  useMakePayrollBankEntry,
  useSubmitPayrollBankEntry,
  useCancelPayrollEntry,
  useAmendPayrollEntry,
  usePayrollSalarySlips,
  usePayrollSalaryRegister,
  usePayrollBankRemittance,
} from '../api/enterprise'
import type { PayrollEntryInput, PayrollStructureInput, PayrollVariableInput } from '../api/enterprise'
export const formatPayrollMoney = (value: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
export const canManagePayroll = (roles: string[]) => roles.includes('admin') || roles.includes('manager') || roles.includes('hr')
export const localDateValue = (value = new Date()) => { const year = value.getFullYear(); const month = String(value.getMonth() + 1).padStart(2, '0'); const day = String(value.getDate()).padStart(2, '0'); return `${year}-${month}-${day}` }
const errorCode = (error: any, fallback: string) => error?.response?.data?.detail?.code || fallback

function EmptyState({ title, copy, action }: { title: string; copy: string; action?: ReactNode }) {
  return <div className="payroll-empty"><div className="payroll-empty-icon"><FileText size={20} /></div><strong>{title}</strong><p>{copy}</p>{action}</div>
}
export function payrollDocumentStatusLabel(status?: string | null) {
  const labels: Record<string, string> = { draft: 'Ноорог', submitted: 'Илгээсэн', cancelled: 'Цуцалсан', consumed: 'Зарцуулсан', open: 'Нээлттэй', closed: 'Хаасан', active: 'Идэвхтэй', archived: 'Архивласан', unpaid: 'Төлөөгүй', paid: 'Төлсөн' }
  return labels[status || ''] || status?.replaceAll('_', ' ') || 'Тодорхойгүй'
}

export function payrollEntryNextAction(entry: { document_status?: string | null; salary_slips_created?: boolean; salary_slips_submitted?: boolean; bank_entry_id?: number | null }) {
  if (entry.document_status === 'cancelled') return 'amend'
  if (!entry.salary_slips_created) return 'get-employees'
  if (!entry.salary_slips_submitted) return 'submit-slips'
  if (!entry.bank_entry_id) return 'make-bank-entry'
  return 'view'
}

function FrappeStatusBadge({ status }: { status?: string | null }) {
  return <span className={`payroll-status payroll-status-${status || 'unknown'}`}><span aria-hidden="true" />{payrollDocumentStatusLabel(status)}</span>
}

function FrappeWorkspaceShell({ title, subtitle, children, actions }: { title: string; subtitle: string; children: ReactNode; actions?: ReactNode }) {
  return <div className="erp-workspace payroll-workspace frappe-payroll-workspace">
    <div className="frappe-payroll-breadcrumb"><Link to="/erp/payroll">Цалин (Payroll)</Link><ChevronRight size={14} /><span>{title}</span></div>
    <header className="frappe-payroll-header"><div><span className="eyebrow">OYUNS ALL-IN-ONE · PAYROLL</span><h1>{title}</h1><p>{subtitle}</p></div>{actions && <div className="frappe-payroll-header-actions">{actions}</div>}</header>
    {children}
  </div>
}

function PayrollWorkspaceDashboard({ onCreate }: { onCreate: () => void }) {
  const entries = usePayrollEntries(undefined, true)
  const periods = usePayrollPeriods(true)
  const components = usePayrollComponentMasters(true)
  const slips = usePayrollSalarySlips({}, true)
  const workers = useWorkerDirectory()
  const openEntries = entries.data?.filter((entry) => entry.document_status !== 'cancelled' && entry.document_status !== 'submitted').length || 0
  const pendingBank = entries.data?.filter((entry) => entry.salary_slips_submitted && !entry.bank_entry_id).length || 0
  const totalNet = entries.data?.reduce((sum, entry) => sum + Number(entry.total_net || 0), 0) || 0
  const cards = [
    { label: 'Нийт цалингийн зардал', value: formatPayrollMoney(String(totalNet)), detail: 'Сүүлийн Payroll Entry-үүд', icon: WalletCards, tone: 'blue' },
    { label: 'Нээлттэй Payroll Entry', value: String(openEntries), detail: `${periods.data?.filter((period) => period.status === 'open').length || 0} нээлттэй үе`, icon: ClipboardList, tone: 'orange' },
    { label: 'Salary Slip', value: String(slips.data?.length || 0), detail: 'Бүх ажилтны frozen snapshot', icon: FileText, tone: 'green' },
    { label: 'Банкны шилжүүлэг', value: String(pendingBank), detail: 'Баталгаажуулахыг хүлээж буй', icon: Landmark, tone: 'purple' },
  ]
  const groups = [
    { title: 'Мастер өгөгдөл', icon: Settings2, links: [['Salary Components', 'Цалингийн бүрэлдэхүүн', '/erp/payroll/salary-components'], ['Salary Structures', 'Цалингийн бүтэц', '/erp/payroll/salary-structures'], ['Payroll Periods', 'Цалингийн үе', '/erp/payroll/payroll-periods']] },
    { title: 'Цалин бодолт', icon: Calculator, links: [['Structure Assignments', 'Бүтэц оноолт', '/erp/payroll/assignments'], ['Additional Salary', 'Нэмэлт цалин', '/erp/payroll/additional-salaries'], ['Payroll Entries', 'Цалингийн бичилт', '/erp/payroll/payroll-entries'], ['Salary Slips', 'Цалингийн хуудас', '/erp/payroll/salary-slips']] },
    { title: 'Нягтлан бодох', icon: Landmark, links: [['Account mapping', 'Дансны тохиргоо', '/erp/payroll/accounting'], ['Bank Entries', 'Банкны бичилт', '/erp/payroll/payroll-entries']] },
    { title: 'Тайлан', icon: BarChart3, links: [['Salary Register', 'Цалингийн бүртгэл', '/erp/payroll/reports/salary-register'], ['Bank Remittance', 'Банкны шилжүүлэг', '/erp/payroll/reports/bank-remittance'], ['НД-7 / НД-8 / ТТ-11', 'Хуулийн тайлан', '/erp/payroll/tax-benefits']] },
  ]
  return <FrappeWorkspaceShell title="Цалин бодолт" subtitle="Mongolia payroll · Frappe-style баримтын ажлын орчин" actions={<button className="primary-action" onClick={onCreate}><Plus size={16} />Шинэ Payroll Entry</button>}>
    <section className="frappe-payroll-kpis">{cards.map(({ label, value, detail, icon: Icon, tone }) => <article className={`frappe-payroll-kpi ${tone}`} key={label}><span className="frappe-payroll-kpi-icon"><Icon size={19} /></span><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div></article>)}</section>
    <section className="frappe-payroll-groups">{groups.map(({ title, icon: Icon, links }) => <article className="frappe-payroll-group panel" key={title}><div className="frappe-payroll-group-title"><span className="frappe-payroll-group-icon"><Icon size={17} /></span><h2>{title}</h2></div><div className="frappe-payroll-links">{links.map(([en, mn, href]) => <Link to={href} key={href + en}><span><strong>{mn}</strong><small>{en}</small></span><ArrowRight size={15} /></Link>)}</div></article>)}</section>
    <section className="frappe-payroll-dashboard-grid"><article className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">DOCUMENT LIST</span><h2>Сүүлийн Payroll Entries</h2></div><Link className="secondary-action" to="/erp/payroll/payroll-entries">Бүгдийг харах</Link></div>{entries.isLoading ? <p>Уншиж байна…</p> : entries.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Payroll Entry жагсаалт ачааллахад алдаа гарлаа.</div> : entries.data?.length ? <div className="frappe-payroll-document-list">{entries.data.slice(0, 6).map((entry) => <Link className="frappe-payroll-document-row" to={`/erp/payroll/payroll-entries/${entry.id}`} key={entry.id}><span className="frappe-payroll-document-id"><strong>{entry.run_number}</strong><small>{entry.period_start} – {entry.period_end}</small></span><span>{entry.run_type}</span><FrappeStatusBadge status={entry.document_status || entry.status} /><strong>{formatPayrollMoney(entry.total_net)}</strong><ChevronRight size={15} /></Link>)}</div> : <EmptyState title="Payroll Entry алга" copy="Сарын цалингийн бодолтыг эхлүүлэхийн тулд шинэ баримт үүсгэнэ үү." action={<button className="secondary-action" onClick={onCreate}><Plus size={14} />Шинэ баримт</button>} />}</article><article id="periods" className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">SETUP READINESS</span><h2>Тохиргооны бэлэн байдал</h2></div><CalendarDays size={19} /></div><div className="frappe-payroll-readiness"><div><span>Payroll Periods</span><strong>{periods.data?.length || 0}</strong></div><div><span>Salary Components</span><strong>{components.data?.length || 0}</strong></div><div><span>Ажилтнууд</span><strong>{workers.data?.length || 0}</strong></div></div><p className="payroll-helper"><ShieldCheck size={15} />НДШ, ХХОАТ болон encrypted банкны дансны тохиргоог нэг Payroll Entry урсгал ашиглана.</p></article></section>
  </FrappeWorkspaceShell>
}

function PayrollEmployeeSelfServiceView() {
  const payslips = useMyPayrollPayslips(true)
  return <FrappeWorkspaceShell title="Миний цалин" subtitle="Нийтлэгдсэн Salary Slip-ээ харах, хамгаалагдсан PDF-ээр татах орон зай.">
    <section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE SELF-SERVICE</span><h2>Salary Slips</h2><p>Цалингийн бодолтыг зөвхөн Payroll Entry-ийн шинэ урсгалаар боловсруулна.</p></div><FileText size={20} /></div>{payslips.isLoading ? <p>Уншиж байна…</p> : payslips.isError ? <div className="payroll-inline-error"><CircleAlert size={16} />Salary Slip ачааллахад алдаа гарлаа.</div> : payslips.data?.length ? <div className="frappe-payroll-document-list">{payslips.data.map((slip) => <article className="frappe-payroll-document-row" key={slip.id}><span className="frappe-payroll-document-id"><strong>Payroll Entry #{slip.payroll_run_id}</strong><small>Gross {formatPayrollMoney(slip.gross)} · SHI {formatPayrollMoney(slip.employee_shi)} · PIT {formatPayrollMoney(slip.pit)}</small></span><strong>{formatPayrollMoney(slip.net_pay)}</strong><button className="secondary-action" onClick={() => { const password = window.prompt('Create a password for this encrypted PDF (minimum 8 characters).'); if (!password || password.length < 8) { if (password) toast.error('Password must be at least 8 characters'); return } downloadProtectedPayslip(slip.id, password).then(() => toast.success('Encrypted payslip downloaded')).catch(() => toast.error('Payslip download failed')) }}><Download size={14} />Protected PDF</button></article>)}</div> : <EmptyState title="Salary Slip алга" copy="Нийтлэгдсэн цалин энд харагдана." />}</section>
  </FrappeWorkspaceShell>
}

function PayrollEntryCreateView({ onCreated }: { onCreated: (id: number) => void }) {
  const periods = usePayrollPeriods(true)
  const profiles = usePayrollProfiles(true)
  const create = useCreatePayrollEntry()
  const [periodId, setPeriodId] = useState('')
  const [periodStart, setPeriodStart] = useState(localDateValue(new Date(new Date().getFullYear(), new Date().getMonth(), 1)))
  const [periodEnd, setPeriodEnd] = useState(localDateValue(new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0)))
  const [postingDate, setPostingDate] = useState(localDateValue())
  const [profileId, setProfileId] = useState('')
  const [runType, setRunType] = useState<PayrollEntryInput['run_type']>('final')
  const [branch, setBranch] = useState('')
  const [direction, setDirection] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [validateAttendance, setValidateAttendance] = useState(true)
  const selectedPeriod = periods.data?.find((period) => String(period.id) === periodId)
  const selectedProfileId = (profileId ? Number(profileId) : undefined) || selectedPeriod?.statutory_profile_id || profiles.data?.find((profile) => profile.status === 'published')?.id
  const submit = (event: React.FormEvent) => { event.preventDefault(); if (!selectedProfileId) { toast.error('Идэвхтэй statutory profile сонгоно уу'); return } create.mutate({ run_type: runType, payroll_period_id: selectedPeriod?.id, period_start: selectedPeriod?.start_date || periodStart, period_end: selectedPeriod?.end_date || periodEnd, posting_date: postingDate, tax_point_date: selectedPeriod?.end_date || periodEnd, payroll_frequency: 'monthly', statutory_profile_id: selectedProfileId, employee_filter: { work_branch: branch || null, work_direction: direction || null, job_title: jobTitle || null }, validate_attendance: validateAttendance }, { onSuccess: (entry) => { toast.success('Payroll Entry ноорог үүслээ'); onCreated(entry.id) }, onError: (error: any) => toast.error(errorCode(error, 'Payroll Entry үүсгэж чадсангүй')) }) }
  return <FrappeWorkspaceShell title="Шинэ Payroll Entry" subtitle="Цалингийн үе, ажилтны шүүлтүүр, нийтлэлийн дансыг тохируулж ноорог хадгална." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={15} />Workspace</Link>}><form className="panel frappe-payroll-form" onSubmit={submit}><div className="frappe-payroll-form-tabs"><span className="active">Үндсэн мэдээлэл</span><span>Ажилтан</span><span>Нягтлан бодох</span></div><div className="payroll-form-grid"><label>Payroll Period<select value={periodId} onChange={(event) => { const period = periods.data?.find((item) => String(item.id) === event.target.value); setPeriodId(event.target.value); if (period) { setPeriodStart(period.start_date); setPeriodEnd(period.end_date); setProfileId(String(period.statutory_profile_id)) } }}><option value="">Гараар сонгох</option>{periods.data?.map((period) => <option key={period.id} value={period.id}>{period.name} · {period.start_date} – {period.end_date}</option>)}</select></label><label>Бодолтын төрөл<select value={runType} onChange={(event) => setRunType(event.target.value as PayrollEntryInput['run_type'])}><option value="final">Final · Сарын цалин</option><option value="advance">Advance · Урьдчилгаа</option><option value="single">Single · Нэг удаа</option><option value="off_cycle">Off-cycle · Нэмэлт</option></select></label><label>Эхлэх огноо<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} required /></label><label>Дуусах огноо<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} required /></label><label>Posting date<input type="date" value={postingDate} onChange={(event) => setPostingDate(event.target.value)} required /></label><label>Statutory profile<select value={profileId || String(selectedPeriod?.statutory_profile_id || '')} onChange={(event) => setProfileId(event.target.value)}><option value="">Автоматаар сонгох</option>{profiles.data?.map((profile) => <option key={profile.id} value={profile.id}>{profile.code} · v{profile.version}</option>)}</select></label></div><fieldset><legend>Ажилтан сонгох шүүлтүүр</legend><div className="payroll-form-grid"><label>Work branch<input value={branch} onChange={(event) => setBranch(event.target.value)} placeholder="Салбар" /></label><label>Work direction<input value={direction} onChange={(event) => setDirection(event.target.value)} placeholder="Чиглэл" /></label><label>Job title<input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} placeholder="Албан тушаал" /></label></div><label className="payroll-check-label"><input type="checkbox" checked={validateAttendance} onChange={(event) => setValidateAttendance(event.target.checked)} />Approved WorkTime/attendance-ийг шалгах</label></fieldset><div className="frappe-payroll-form-footer"><span className="payroll-helper"><Filter size={14} />Ноорог үүссэний дараа “Get Employees” ажилтнуудыг сонгож, missing attendance-г мэдээлнэ.</span><button className="primary-action" type="submit" disabled={create.isPending}>{create.isPending ? 'Хадгалж байна…' : 'Ноорог хадгалах'}<ArrowRight size={15} /></button></div></form></FrappeWorkspaceShell>
}

function PayrollEntryDetailView({ entryId }: { entryId: number }) {
  const navigate = useNavigate()
  const detail = usePayrollEntry(entryId, true)
  const getEmployees = useGetPayrollEntryEmployees()
  const createSlips = useCreatePayrollEntrySalarySlips()
  const submitSlips = useSubmitPayrollEntrySalarySlips()
  const makeBank = useMakePayrollBankEntry()
  const submitBank = useSubmitPayrollBankEntry()
  const cancel = useCancelPayrollEntry()
  const amend = useAmendPayrollEntry()
  const accounts = useERPAccountOptions(true)
  const [branch, setBranch] = useState('')
  const [direction, setDirection] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [attendance, setAttendance] = useState(true)
  const [paymentAccount, setPaymentAccount] = useState('')
  useEffect(() => {
    if (!detail.data) return
    const filters = detail.data.employee_filter || {}
    setBranch(typeof filters.work_branch === 'string' ? filters.work_branch : '')
    setDirection(typeof filters.work_direction === 'string' ? filters.work_direction : '')
    setJobTitle(typeof filters.job_title === 'string' ? filters.job_title : '')
    setAttendance(detail.data.validate_attendance ?? true)
  }, [detail.data?.id])
  if (detail.isLoading) return <FrappeWorkspaceShell title="Payroll Entry" subtitle="Уншиж байна…"><div className="panel frappe-payroll-loading">Payroll Entry уншиж байна…</div></FrappeWorkspaceShell>
  if (detail.isError || !detail.data) return <FrappeWorkspaceShell title="Payroll Entry" subtitle="Баримт олдсонгүй."><div className="panel payroll-inline-error"><CircleAlert size={16} />Payroll Entry ачааллахад алдаа гарлаа.</div></FrappeWorkspaceShell>
  const entry = detail.data
  const status: string = entry.document_status || entry.status
  const workflowStatus = entry.status
  const hasEmployees = Boolean(entry.employee_ids?.length)
  const canRecheckEmployees = workflowStatus === 'draft' && !entry.salary_slips_created
  const runAction = (mutation: any, variables: any, success: string) => mutation.mutate(variables, { onSuccess: () => { toast.success(success); detail.refetch() }, onError: (error: any) => toast.error(errorCode(error, 'Үйлдэл амжилтгүй боллоо')) })
  const selection = entry.employee_selection
  const refreshEmployees = () => runAction(getEmployees, { id: entry.id, work_branch: branch || null, work_direction: direction || null, job_title: jobTitle || null, validate_attendance: attendance }, hasEmployees ? 'Ажилтны validation дахин шалгагдлаа' : 'Ажилтнууд сонгогдлоо')
  return <FrappeWorkspaceShell title={entry.run_number} subtitle={`${entry.period_start} – ${entry.period_end} · ${entry.run_type}`} actions={<><FrappeStatusBadge status={status} /><Link className="secondary-action" to="/erp/payroll/payroll-entries"><ArrowRight size={14} />Жагсаалт</Link></>}>
    <section className="frappe-payroll-entry-hero"><div><span className="eyebrow">PAYROLL ENTRY · {entry.payroll_frequency || 'monthly'}</span><h2>{entry.run_type === 'final' ? 'Сарын эцсийн цалин' : entry.run_type}</h2><p>Posting date {entry.posting_date || entry.period_end} · MNT · {entry.employee_filter?.work_branch || 'Бүх салбар'}</p></div><div className="frappe-payroll-entry-actions">{canRecheckEmployees && <button className="primary-action" disabled={getEmployees.isPending} onClick={refreshEmployees}><Users size={15} />{getEmployees.isPending ? 'Шалгаж байна…' : hasEmployees ? 'Recheck Employees' : 'Get Employees'}</button>}{workflowStatus === 'draft' && hasEmployees && !entry.salary_slips_created && <button className="primary-action" disabled={createSlips.isPending || Boolean(selection?.errors.length)} onClick={() => runAction(createSlips, entry.id, 'Salary Slips ноорог үүслээ')}><Calculator size={15} />{createSlips.isPending ? 'Бодож байна…' : 'Create Salary Slips'}</button>}{workflowStatus === 'calculated' && !entry.salary_slips_submitted && <button className="primary-action" disabled={submitSlips.isPending} onClick={() => runAction(submitSlips, { id: entry.id }, 'Salary Slips илгээгдэж нийтлэгдлээ')}><Send size={15} />{submitSlips.isPending ? 'Илгээж байна…' : 'Submit Salary Slips'}</button>}{status === 'submitted' && !entry.bank_entry_id && <button className="primary-action" disabled={makeBank.isPending} onClick={() => runAction(makeBank, { id: entry.id, payment_account_id: paymentAccount ? Number(paymentAccount) : undefined }, 'Bank Entry ноорог үүслээ')}><Landmark size={15} />Make Bank Entry</button>}{entry.bank_entry_id && <Link className="secondary-action" to={`/erp/payroll/payroll-entries/${entry.id}#bank-entry`}><Landmark size={15} />Bank Entry #{entry.bank_entry_id}</Link>}{status !== 'cancelled' && <button className="secondary-action" onClick={() => runAction(cancel, { id: entry.id, reason: 'Payroll Entry cancelled from document action' }, 'Payroll Entry цуцлагдлаа')}><X size={15} />Cancel</button>}{status === 'cancelled' && <button className="secondary-action" onClick={() => runAction(amend, { id: entry.id, data: { run_type: entry.run_type === 'reversal' ? 'final' : entry.run_type, payroll_period_id: entry.payroll_period_id, period_start: entry.period_start, period_end: entry.period_end, posting_date: entry.posting_date || entry.period_end, tax_point_date: entry.tax_point_date, payroll_frequency: entry.payroll_frequency || 'monthly', statutory_profile_id: entry.statutory_profile_id, employee_ids: entry.employee_ids || [], employee_filter: entry.employee_filter || {}, payment_account_id: entry.payment_account_id, cost_center_id: entry.cost_center_id, validate_attendance: entry.validate_attendance ?? true } }, 'Шинэ replacement Payroll Entry үүслээ')}><RefreshCw size={15} />Amend</button>}</div></section>
    <section className="frappe-payroll-stepper"><div className={hasEmployees ? 'done' : 'active'}><span>1</span><strong>Get Employees</strong><small>{selection?.employee_ids?.length || entry.employee_ids?.length || 0} ажилтан</small></div><div className={entry.salary_slips_created ? entry.salary_slips_submitted ? 'done' : 'active' : ''}><span>2</span><strong>Create Salary Slips</strong><small>{entry.salary_slips_created ? `${entry.payslips?.length || 0} slip` : 'Хүлээгдэж буй'}</small></div><div className={entry.salary_slips_submitted ? 'done' : ''}><span>3</span><strong>Submit &amp; Accrue</strong><small>{entry.salary_slips_submitted ? 'GL accrual posted' : 'Хүлээгдэж буй'}</small></div><div className={entry.bank_entry_id ? 'done' : ''}><span>4</span><strong>Make Bank Entry</strong><small>{entry.bank_entry_id ? 'Settlement created' : 'Хүлээгдэж буй'}</small></div></section>
    {canRecheckEmployees && <section className="panel frappe-payroll-form"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE SELECTION</span><h3>{hasEmployees ? 'Ажилтны validation-г засварласны дараа дахин шалгах' : 'Ажилтнуудыг шүүх'}</h3><p>work_branch, work_direction, job_title-оор сонгоод HR attendance, leave, employment dates, bank details-ийг нэг бодлогын дагуу шалгана.</p></div><Filter size={18} /></div><div className="payroll-form-grid"><label>Work branch<input value={branch} onChange={(event) => setBranch(event.target.value)} /></label><label>Work direction<input value={direction} onChange={(event) => setDirection(event.target.value)} /></label><label>Job title<input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} /></label></div><label className="payroll-check-label"><input type="checkbox" checked={attendance} onChange={(event) => setAttendance(event.target.checked)} />Ирц/чөлөөний баталгаажуулалтыг шалгах</label></section>}
    {selection && <section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">EMPLOYEE VALIDATION</span><h3>Сонгогдсон ажилтнууд</h3><p>{entry.attendance_policy?.basis === 'confirmed_hr_attendance_and_approved_leave' ? 'Confirmed HR attendance, approved leave, holidays, employment dates, and recurring inputs are frozen again when slips are created.' : 'Saved payroll input policy.'}</p></div><span className="payroll-count">{selection.employee_ids.length} selected</span></div>{selection.errors.length > 0 && <div className="payroll-inline-error"><CircleAlert size={15} />{selection.errors.length} blocking error байна.<ul>{selection.errors.map((issue, index) => <li key={`${issue.code}-${issue.employee_id || 'run'}-${index}`}><strong>{issue.name || `Employee #${issue.employee_id || '—'}`}</strong> · {issue.message || issue.code}{issue.dates?.length ? ` (${issue.dates.join(', ')})` : ''}</li>)}</ul></div>}{selection.warnings.length > 0 && <div className="payroll-inline-warning"><CircleAlert size={15} />{selection.warnings.length} warning байна.</div>}<div className="frappe-payroll-document-list">{selection.employees.map((employee) => <div className="frappe-payroll-document-row" key={employee.id}><span className="frappe-payroll-document-id"><strong>{employee.name}</strong><small>{employee.job_title || 'Албан тушаалгүй'} · {employee.payment_method || 'payment method'}</small></span><span>{employee.work_branch || 'Салбаргүй'}</span><FrappeStatusBadge status={selection.errors.some((issue) => issue.employee_id === employee.id) ? 'error' : 'active'} /></div>)}</div></section>}
    {entry.salary_slips_submitted && !entry.bank_entry_id && <section id="bank-entry" className="panel frappe-payroll-form"><div className="view-toolbar"><div><span className="eyebrow">ACCOUNTING · BANK ENTRY</span><h3>Цалингийн шилжүүлгийн данс</h3><p>Accrual тусдаа нийтлэгдсэн. Одоо net-pay payable-ийг банкны дансаар settlement хийнэ.</p></div><Landmark size={18} /></div><label>Payment account<select value={paymentAccount} onChange={(event) => setPaymentAccount(event.target.value)}><option value="">Сонгох</option>{accounts.data?.filter((account) => !account.is_group).map((account) => <option value={account.id} key={account.id}>{account.code} · {account.name}</option>)}</select></label></section>}
    {entry.bank_entry_id && <section id="bank-entry" className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">BANK ENTRY</span><h3>Settlement document</h3><p>Net pay payable болон сонгосон банкны дансны хооронд balanced entry үүслээ.</p></div><FrappeStatusBadge status={entry.payment_status || 'unpaid'} /></div><div className="frappe-payroll-bank-summary"><strong>{formatPayrollMoney(entry.total_net)}</strong><span>Bank Entry #{entry.bank_entry_id}</span>{entry.payment_status === 'unpaid' && <button className="primary-action" onClick={() => runAction(submitBank, entry.bank_entry_id, 'Банкны бичилт илгээгдлээ')}><Send size={15} />Submit Bank Entry</button>}</div></section>}
    <section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">SALARY SLIPS</span><h3>Frozen payslip snapshots</h3></div><span className="payroll-count">{entry.payslips?.length || 0}</span></div>{entry.payslips?.length ? <div className="frappe-payroll-document-list">{entry.payslips.map((slip) => <div className="frappe-payroll-document-row" key={slip.id}><span className="frappe-payroll-document-id"><strong>Employee #{slip.employee_id}</strong><small>Slip #{slip.id}</small></span><span>Gross {formatPayrollMoney(slip.gross)}</span><span>SHI {formatPayrollMoney(slip.employee_shi)}</span><strong>{formatPayrollMoney(slip.net_pay)}</strong><FrappeStatusBadge status={slip.document_status || status} /></div>)}</div> : <EmptyState title="Salary Slip үүсээгүй" copy="Get Employees хийсний дараа Create Salary Slips дарна уу." />}</section>
  </FrappeWorkspaceShell>
}

function PayrollEntriesListView() {
  const navigate = useNavigate()
  const entries = usePayrollEntries(undefined, true)
  const [status, setStatus] = useState('all')
  const filtered = entries.data?.filter((entry) => status === 'all' || (entry.document_status || entry.status) === status) || []
  return <FrappeWorkspaceShell title="Payroll Entries" subtitle="Payroll Entry баримтуудын жагсаалт, шүүлтүүр, төлөвийн удирдлага." actions={<button className="primary-action" onClick={() => navigate('/erp/payroll/payroll-entries/new')}><Plus size={15} />Шинэ Payroll Entry</button>}><section className="panel frappe-payroll-table-card"><div className="frappe-payroll-list-toolbar"><div className="frappe-payroll-tabs"><button className={status === 'all' ? 'active' : ''} onClick={() => setStatus('all')}>Бүгд</button><button className={status === 'draft' ? 'active' : ''} onClick={() => setStatus('draft')}>Ноорог</button><button className={status === 'submitted' ? 'active' : ''} onClick={() => setStatus('submitted')}>Илгээсэн</button><button className={status === 'cancelled' ? 'active' : ''} onClick={() => setStatus('cancelled')}>Цуцалсан</button></div><button className="secondary-action" onClick={() => entries.refetch()}><RefreshCw size={14} />Шинэчлэх</button></div>{entries.isLoading ? <p>Уншиж байна…</p> : filtered.length ? <div className="frappe-payroll-document-list">{filtered.map((entry) => <Link className="frappe-payroll-document-row" to={`/erp/payroll/payroll-entries/${entry.id}`} key={entry.id}><span className="frappe-payroll-document-id"><strong>{entry.run_number}</strong><small>{entry.period_start} – {entry.period_end}</small></span><span>{entry.run_type}</span><span>{entry.salary_slips_created ? `${entry.total_net} MNT` : 'Not calculated'}</span><FrappeStatusBadge status={entry.document_status || entry.status} /><ChevronRight size={15} /></Link>)}</div> : <EmptyState title="Баримт алга" copy="Энэ шүүлтүүрт тохирох Payroll Entry олдсонгүй." />}</section></FrappeWorkspaceShell>
}

function SalaryComponentsView() {
  const components = usePayrollComponentMasters(true)
  const create = useCreatePayrollComponentMaster()
  const [form, setForm] = useState({ code: '', name: '', component_kind: 'earning' as 'earning' | 'deduction' | 'employer_cost', formula: 'base_salary', is_taxable: true, is_shi_subject: true })
  const submit = (event: React.FormEvent) => { event.preventDefault(); create.mutate({ ...form, proration_basis: 'none', is_non_taxable_allowance: false, is_leave_average_eligible: true, is_flexible_benefit: false, payer: 'employee', account_id: null, cost_center_id: null, metadata_json: {} }, { onSuccess: () => { toast.success('Salary Component master үүслээ'); setForm({ code: '', name: '', component_kind: 'earning', formula: 'base_salary', is_taxable: true, is_shi_subject: true }) }, onError: (error: any) => toast.error(errorCode(error, 'Component үүсгэж чадсангүй')) }) }
  return <FrappeWorkspaceShell title="Salary Components" subtitle="Дахин ашиглагдах цалингийн бүрэлдэхүүн masters. Structure мөрүүд frozen formula-г хадгална." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><div className="frappe-payroll-master-grid"><form className="panel frappe-payroll-form" onSubmit={submit}><div className="view-toolbar"><div><span className="eyebrow">NEW MASTER</span><h3>Шинэ component</h3></div><Plus size={18} /></div><label>Code<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value.toLowerCase().replace(/\s+/g, '_') })} placeholder="base_salary" /></label><label>Name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Үндсэн цалин" /></label><label>Kind<select value={form.component_kind} onChange={(event) => setForm({ ...form, component_kind: event.target.value as typeof form.component_kind })}><option value="earning">Earning</option><option value="deduction">Deduction</option><option value="employer_cost">Employer cost</option></select></label><label>Formula<input required value={form.formula} onChange={(event) => setForm({ ...form, formula: event.target.value })} /></label><label className="payroll-check-label"><input type="checkbox" checked={form.is_taxable} onChange={(event) => setForm({ ...form, is_taxable: event.target.checked })} />ХХОАТ-д татвар ногдох</label><label className="payroll-check-label"><input type="checkbox" checked={form.is_shi_subject} onChange={(event) => setForm({ ...form, is_shi_subject: event.target.checked })} />НДШ-д хамруулах</label><button className="primary-action" disabled={create.isPending}>{create.isPending ? 'Хадгалж байна…' : 'Master хадгалах'}</button></form><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">MASTER LIST</span><h3>Components</h3></div><span className="payroll-count">{components.data?.length || 0}</span></div>{components.data?.length ? <div className="frappe-payroll-document-list">{components.data.map((component) => <div className="frappe-payroll-document-row" key={component.id}><span className="frappe-payroll-document-id"><strong>{component.name}</strong><small>{component.code} · {component.formula}</small></span><span>{component.component_kind}</span><span>{component.is_taxable ? 'Taxable' : 'Non-taxable'}</span><FrappeStatusBadge status={component.status} /></div>)}</div> : <EmptyState title="Component master алга" copy="Эхний Salary Component-оо нэмнэ үү." />}</section></div></FrappeWorkspaceShell>
}

function PayrollPeriodsView() {
  const periods = usePayrollPeriods(true)
  const profiles = usePayrollProfiles(true)
  const create = useCreatePayrollPeriod()
  const [form, setForm] = useState({ code: '', name: '', start_date: localDateValue(new Date(new Date().getFullYear(), new Date().getMonth(), 1)), end_date: localDateValue(new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0)), tax_year: new Date().getFullYear(), statutory_profile_id: '' })
  const submit = (event: React.FormEvent) => { event.preventDefault(); if (!form.statutory_profile_id) { toast.error('Statutory profile сонгоно уу'); return } create.mutate({ ...form, statutory_profile_id: Number(form.statutory_profile_id) }, { onSuccess: () => { toast.success('Payroll Period үүслээ'); setForm({ ...form, code: '', name: '' }) }, onError: (error: any) => toast.error(errorCode(error, 'Payroll Period үүсгэж чадсангүй')) }) }
  return <FrappeWorkspaceShell title="Payroll Periods" subtitle="Effective-dated сарын payroll windows. Нэг байгууллагад давхардсан нээлттэй үе үүсгэхгүй." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><div className="frappe-payroll-master-grid"><form className="panel frappe-payroll-form" onSubmit={submit}><div className="view-toolbar"><div><span className="eyebrow">NEW PERIOD</span><h3>Шинэ payroll period</h3></div><CalendarDays size={18} /></div><label>Code<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} placeholder="2026-08" /></label><label>Name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="2026 оны 8-р сар" /></label><label>Start date<input type="date" required value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label><label>End date<input type="date" required value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} /></label><label>Tax year<input type="number" min="2000" max="2200" required value={form.tax_year} onChange={(event) => setForm({ ...form, tax_year: Number(event.target.value) })} /></label><label>Statutory profile<select required value={form.statutory_profile_id} onChange={(event) => setForm({ ...form, statutory_profile_id: event.target.value })}><option value="">Сонгох</option>{profiles.data?.map((profile) => <option value={profile.id} key={profile.id}>{profile.code} · v{profile.version}</option>)}</select></label><button className="primary-action" disabled={create.isPending}>{create.isPending ? 'Хадгалж байна…' : 'Period хадгалах'}</button></form><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">PERIOD LIST</span><h3>Цалингийн үеүүд</h3></div><span className="payroll-count">{periods.data?.length || 0}</span></div>{periods.data?.length ? <div className="frappe-payroll-document-list">{periods.data.map((period) => <div className="frappe-payroll-document-row" key={period.id}><span className="frappe-payroll-document-id"><strong>{period.name}</strong><small>{period.code} · {period.start_date} – {period.end_date}</small></span><span>{period.tax_year}</span><FrappeStatusBadge status={period.status} /></div>)}</div> : <EmptyState title="Payroll Period алга" copy="Сарын эхлэл/төгсгөлийн огноотой үе үүсгэнэ үү." />}</section></div></FrappeWorkspaceShell>
}

function SalaryStructuresView() {
  const structures = usePayrollStructures(true)
  const masters = usePayrollComponentMasters(true)
  const create = useCreatePayrollStructure()
  const [form, setForm] = useState<PayrollStructureInput>({ code: '', name: '', effective_from: localDateValue(), effective_to: null, currency: 'MNT', components: [] })
  const submit = (event: React.FormEvent) => { event.preventDefault(); if (!form.components.length) { toast.error('Дор хаяж нэг Salary Component сонгоно уу'); return } create.mutate(form, { onSuccess: () => { toast.success('Salary Structure ноорог үүслээ'); setForm({ ...form, code: '', name: '', components: [] }) }, onError: (error: any) => toast.error(errorCode(error, 'Salary Structure үүсгэж чадсангүй')) }) }
  const toggleComponent = (id: number) => { const master = masters.data?.find((item) => item.id === id); if (!master) return; const exists = form.components.some((item) => item.code === master.code); setForm({ ...form, components: exists ? form.components.filter((item) => item.code !== master.code) : [...form.components, { code: master.code, name: master.name, component_kind: master.component_kind, formula: master.formula, proration_basis: master.proration_basis, is_taxable: master.is_taxable, is_shi_subject: master.is_shi_subject, is_non_taxable_allowance: master.is_non_taxable_allowance, is_flexible_benefit: master.is_flexible_benefit, account_id: master.account_id, cost_center_id: master.cost_center_id, payer: master.payer as 'employee' | 'employer', position: form.components.length, is_leave_average_eligible: master.is_leave_average_eligible, metadata_json: master.metadata_json } as PayrollStructureInput['components'][number]] }) }
  return <FrappeWorkspaceShell title="Salary Structures" subtitle="Effective-dated бүтэц. Master-аас мөр сонгож, нийтлэгдсэний дараа formula болон татварын flags frozen болно." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><div className="frappe-payroll-master-grid"><form className="panel frappe-payroll-form" onSubmit={submit}><div className="view-toolbar"><div><span className="eyebrow">NEW STRUCTURE</span><h3>Шинэ бүтэц</h3></div><Settings2 size={18} /></div><label>Code<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value.toUpperCase() })} placeholder="MONTHLY_MNT" /></label><label>Name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Сарын цалин" /></label><label>Effective from<input type="date" required value={form.effective_from} onChange={(event) => setForm({ ...form, effective_from: event.target.value })} /></label><fieldset><legend>Salary Component masters</legend>{masters.data?.length ? masters.data.map((master) => <label className="payroll-check-label" key={master.id}><input type="checkbox" checked={form.components.some((item) => item.code === master.code)} onChange={() => toggleComponent(master.id)} />{master.name} <span className="payroll-input-hint">{master.code}</span></label>) : <p className="payroll-helper">Эхлээд Salary Component master үүсгэнэ үү.</p>}</fieldset><button className="primary-action" disabled={create.isPending}>{create.isPending ? 'Хадгалж байна…' : 'Structure хадгалах'}</button></form><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">STRUCTURE LIST</span><h3>Цалингийн бүтэц</h3></div><span className="payroll-count">{structures.data?.length || 0}</span></div>{structures.data?.length ? <div className="frappe-payroll-document-list">{structures.data.map((structure) => <div className="frappe-payroll-document-row" key={structure.id}><span className="frappe-payroll-document-id"><strong>{structure.name}</strong><small>{structure.code} · {structure.effective_from}</small></span><span>{structure.components.length} components</span><FrappeStatusBadge status={structure.status} /></div>)}</div> : <EmptyState title="Salary Structure алга" copy="Master components-уудаа сонгоод шинэ бүтэц үүсгэнэ үү." />}</section></div></FrappeWorkspaceShell>
}

function PayrollAccountingView() {
  const posting = usePayrollPostingProfile(true)
  const accounts = useERPAccountOptions(true)
  const save = useSavePayrollPostingProfile()
  const roles = ['salary_expense', 'employer_shi_expense', 'employee_shi_payable', 'employer_shi_payable', 'pit_payable', 'net_pay_payable', 'bank']
  const [mapping, setMapping] = useState<Record<string, number>>({})
  const merged = { ...(posting.data?.account_roles || {}), ...mapping }
  return <FrappeWorkspaceShell title="Payroll Accounting" subtitle="Accrual болон Bank Entry-г салгаж, OYUNS GL дансны mapping-г нэг удаа тохируулна." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><section className="panel frappe-payroll-form"><div className="view-toolbar"><div><span className="eyebrow">ACCOUNT MAPPING</span><h3>Payroll account roles</h3><p>Salary Slip submission нь expense/payable accrual үүсгэнэ. Bank Entry нь net-pay payable-ийг дансанд settlement хийнэ.</p></div><WalletCards size={18} /></div><div className="payroll-form-grid">{roles.map((role) => <label key={role}>{role.replaceAll('_', ' ')}<select value={merged[role] || ''} onChange={(event) => setMapping({ ...mapping, [role]: Number(event.target.value) })}><option value="">Choose account</option>{accounts.data?.filter((account) => !account.is_group).map((account) => <option value={account.id} key={account.id}>{account.code} · {account.name}</option>)}</select></label>)}</div><div className="frappe-payroll-form-footer"><span className="payroll-helper">{roles.filter((role) => !merged[role]).length ? `${roles.filter((role) => !merged[role]).length} role дутуу байна.` : 'Бүх role mapped байна.'}</span><button className="primary-action" disabled={save.isPending || roles.some((role) => !merged[role])} onClick={() => save.mutate(merged, { onSuccess: () => { toast.success('Payroll mapping хадгалагдлаа'); setMapping({}) }, onError: (error: any) => toast.error(errorCode(error, 'Mapping хадгалж чадсангүй')) })}>{save.isPending ? 'Хадгалж байна…' : 'Mapping хадгалах'}</button></div></section></FrappeWorkspaceShell>
}

function AdditionalSalariesView() {
  const workers = useWorkerDirectory()
  const components = usePayrollComponentMasters(true)
  const salaries = usePayrollAdditionalSalaries(undefined, true)
  const create = useCreatePayrollAdditionalSalary()
  const submitSalary = useSubmitPayrollAdditionalSalary()
  const cancelSalary = useCancelPayrollAdditionalSalary()
  const [form, setForm] = useState({ employee_id: '', payroll_date: localDateValue(), component_master_id: '', component_kind: 'earning' as 'earning' | 'deduction', amount: '', description: '', source: 'manual' })
  const submit = (event: React.FormEvent) => { event.preventDefault(); if (!form.component_master_id) { toast.error('Salary Component сонгоно уу'); return } create.mutate({ employee_id: Number(form.employee_id), salary_component_id: Number(form.component_master_id), payroll_date: form.payroll_date, component_kind: form.component_kind, amount: form.amount, taxable: true, shi_subject: true, reference: form.description || undefined, source: form.source }, { onSuccess: () => { toast.success('Additional Salary ноорог үүслээ'); setForm({ ...form, employee_id: '', amount: '', description: '' }) }, onError: (error: any) => toast.error(errorCode(error, 'Нэмэлт цалин үүсгэж чадсангүй')) }) }
  return <FrappeWorkspaceShell title="Additional Salary" subtitle="Нэг удаагийн бонус, нөхөн олговор, суутгалын durable баримт. Submitted мөр дараагийн бодолтод нэг удаа хэрэглэгдэнэ." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><div className="frappe-payroll-master-grid"><form className="panel frappe-payroll-form" onSubmit={submit}><div className="view-toolbar"><div><span className="eyebrow">ONE-TIME INPUT</span><h3>Нэмэлт цалин</h3></div><Plus size={18} /></div><label>Ажилтан<select required value={form.employee_id} onChange={(event) => setForm({ ...form, employee_id: event.target.value })}><option value="">Сонгох</option>{workers.data?.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}</select></label><label>Payroll date<input type="date" required value={form.payroll_date} onChange={(event) => setForm({ ...form, payroll_date: event.target.value })} /></label><label>Component<select value={form.component_master_id} onChange={(event) => { const component = components.data?.find((item) => String(item.id) === event.target.value); const componentKind = component?.component_kind === 'deduction' ? 'deduction' : 'earning'; setForm({ ...form, component_master_id: event.target.value, component_kind: componentKind }) }}><option value="">Гараар сонгох</option>{components.data?.map((component) => <option value={component.id} key={component.id}>{component.name}</option>)}</select></label><label>Төрөл<select value={form.component_kind} onChange={(event) => setForm({ ...form, component_kind: event.target.value as typeof form.component_kind })}><option value="earning">Earning</option><option value="deduction">Deduction</option></select></label><label>Дүн (MNT)<input type="number" min="0.01" required value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} /></label><label>Тайлбар<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><button className="primary-action" disabled={create.isPending}>{create.isPending ? 'Хадгалж байна…' : 'Ноорог хадгалах'}</button></form><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">DOCUMENT LIST</span><h3>Нэмэлт цалингийн бичилт</h3></div><span className="payroll-count">{salaries.data?.length || 0}</span></div>{salaries.data?.length ? <div className="frappe-payroll-document-list">{salaries.data.map((salary) => <div className="frappe-payroll-document-row" key={salary.id}><span className="frappe-payroll-document-id"><strong>{salary.number}</strong><small>Employee #{salary.employee_id} · {salary.payroll_date}</small></span><strong>{formatPayrollMoney(salary.amount)}</strong><span>{salary.component_kind}</span><FrappeStatusBadge status={salary.status} />{salary.status === 'draft' && <span className="erp-row-actions"><button className="secondary-action compact" onClick={() => submitSalary.mutate(salary.id, { onSuccess: () => toast.success('Additional Salary илгээгдлээ'), onError: (error: any) => toast.error(errorCode(error, 'Илгээж чадсангүй')) })}>Submit</button><button className="icon-action danger-action" onClick={() => cancelSalary.mutate(salary.id, { onSuccess: () => toast.success('Additional Salary цуцлагдлаа'), onError: (error: any) => toast.error(errorCode(error, 'Цуцалж чадсангүй')) })}><X size={14} /></button></span>}</div>)}</div> : <EmptyState title="Нэмэлт цалин алга" copy="Bonus, reimbursement эсвэл суутгалаа durable баримтаар бүртгэнэ үү." />}</section></div></FrappeWorkspaceShell>
}

function AssignmentsView() {
  const workers = useWorkerDirectory()
  const structures = usePayrollStructures(true)
  const assignments = usePayrollStructureAssignments(true)
  const bulk = useBulkPayrollStructureAssignment()
  const [structureId, setStructureId] = useState('')
  const [employeeIds, setEmployeeIds] = useState<number[]>([])
  const [salary, setSalary] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState(localDateValue())
  const submit = (event: React.FormEvent) => { event.preventDefault(); bulk.mutate({ employee_ids: employeeIds, salary_structure_id: Number(structureId), effective_from: effectiveFrom, base_salary: salary }, { onSuccess: () => { toast.success(`${employeeIds.length} ажилтанд бүтэц оноолоо`); setEmployeeIds([]); setSalary('') }, onError: (error: any) => toast.error(errorCode(error, 'Бүтэц оноож чадсангүй')) }) }
  return <FrappeWorkspaceShell title="Salary Structure Assignments" subtitle="Effective-dated structure assignment. Bulk assign нь EmployeePayrollProfile-ийг non-destructive байдлаар ашиглана." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><div className="frappe-payroll-master-grid"><form className="panel frappe-payroll-form" onSubmit={submit}><div className="view-toolbar"><div><span className="eyebrow">BULK ASSIGN</span><h3>Оноолт хийх</h3></div><Users size={18} /></div><label>Salary Structure<select required value={structureId} onChange={(event) => setStructureId(event.target.value)}><option value="">Сонгох</option>{structures.data?.map((structure) => <option value={structure.id} key={structure.id}>{structure.name} · {structure.code}</option>)}</select></label><label>Ажилтнууд<select multiple value={employeeIds.map(String)} onChange={(event) => setEmployeeIds(Array.from(event.target.selectedOptions).map((option) => Number(option.value)))}>{workers.data?.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}</select></label><label>Үндсэн цалин (MNT)<input type="number" min="0" required value={salary} onChange={(event) => setSalary(event.target.value)} /></label><label>Effective from<input type="date" required value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /></label><button className="primary-action" disabled={bulk.isPending || !employeeIds.length}>{bulk.isPending ? 'Оноож байна…' : 'Bulk assign'}</button></form><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">ASSIGNMENT LIST</span><h3>Идэвхтэй оноолтууд</h3></div><span className="payroll-count">{assignments.data?.length || 0}</span></div>{assignments.data?.length ? <div className="frappe-payroll-document-list">{assignments.data.map((assignment) => <div className="frappe-payroll-document-row" key={assignment.id}><span className="frappe-payroll-document-id"><strong>Employee #{assignment.employee_id}</strong><small>Structure #{assignment.salary_structure_id} · {assignment.effective_from}</small></span><strong>{formatPayrollMoney(assignment.base_salary)}</strong><FrappeStatusBadge status={assignment.document_status || 'submitted'} /></div>)}</div> : <EmptyState title="Оноолт алга" copy="Ажилтнууддаа effective-dated Salary Structure онооно уу." />}</section></div></FrappeWorkspaceShell>
}

function SalarySlipsView() {
  const slips = usePayrollSalarySlips({}, true)
  return <FrappeWorkspaceShell title="Salary Slips" subtitle="Frozen, auditable employee snapshots. ESS-д нийтлэгдсэн хуудаснууд encrypted PDF-ээр хамгаалагдана." actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><section className="panel frappe-payroll-table-card"><div className="frappe-payroll-list-toolbar"><div><span className="eyebrow">DOCUMENT LIST</span><h2>Salary Slips</h2></div><button className="secondary-action" onClick={() => slips.refetch()}><RefreshCw size={14} />Шинэчлэх</button></div>{slips.data?.length ? <div className="frappe-payroll-document-list">{slips.data.map((slip) => <div className="frappe-payroll-document-row" key={slip.id}><span className="frappe-payroll-document-id"><strong>Employee #{slip.employee_id}</strong><small>Payroll Entry #{slip.payroll_run_id}</small></span><span>Gross {formatPayrollMoney(slip.gross)}</span><span>SHI {formatPayrollMoney(slip.employee_shi)}</span><span>PIT {formatPayrollMoney(slip.pit)}</span><strong>{formatPayrollMoney(slip.net_pay)}</strong><FrappeStatusBadge status={slip.document_status || 'submitted'} /></div>)}</div> : <EmptyState title="Salary Slip алга" copy="Submit Salary Slips хийсний дараа энд харагдана." />}</section></FrappeWorkspaceShell>
}

function PayrollReportView({ kind }: { kind: 'salary-register' | 'bank-remittance' }) {
  const entries = usePayrollEntries(undefined, true)
  const [runId, setRunId] = useState<number | undefined>()
  const register = usePayrollSalaryRegister(runId, kind === 'salary-register')
  const remittance = usePayrollBankRemittance(runId, kind === 'bank-remittance')
  const report = kind === 'salary-register' ? register.data : remittance.data
  const title = kind === 'salary-register' ? 'Salary Register' : 'Bank Remittance'
  return <FrappeWorkspaceShell title={title} subtitle={kind === 'salary-register' ? 'Цалингийн нийт дүн, employee SHI/PIT, net pay-ийн тайлан.' : 'Банкны шилжүүлэгт орох ажилтан, encrypted дансны snapshot, net pay.'} actions={<Link className="secondary-action" to="/erp/payroll"><ArrowRight size={14} />Workspace</Link>}><section className="panel frappe-payroll-report-filter"><label>Payroll Entry<select value={runId || ''} onChange={(event) => setRunId(event.target.value ? Number(event.target.value) : undefined)}><option value="">Бүх бичилт</option>{entries.data?.map((entry) => <option key={entry.id} value={entry.id}>{entry.run_number} · {entry.period_end}</option>)}</select></label></section><section className="panel frappe-payroll-table-card"><div className="view-toolbar"><div><span className="eyebrow">REPORT</span><h2>{title}</h2></div><BarChart3 size={19} /></div>{register.isLoading || remittance.isLoading ? <p>Тайлан үүсгэж байна…</p> : report && Object.keys(report).length ? <pre className="frappe-payroll-report-json">{JSON.stringify(report, null, 2)}</pre> : <EmptyState title="Тайлангийн өгөгдөл алга" copy="Submitted Salary Slips-тэй Payroll Entry сонгоно уу." />}</section></FrappeWorkspaceShell>
}

export function PayrollWorkspacePage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { entryId: entryIdParam } = useParams<{ entryId?: string }>()
  const actor = useActor()
  const roles = actor.data?.roles || []
  const manage = canManagePayroll(roles)
  const path = location.pathname
  const entryId = entryIdParam ? Number(entryIdParam) : undefined
  if (!manage) return <PayrollEmployeeSelfServiceView />
  if (path.endsWith('/payroll-entries/new')) return <PayrollEntryCreateView onCreated={(id) => navigate(`/erp/payroll/payroll-entries/${id}`)} />
  if (entryId) return <PayrollEntryDetailView entryId={entryId} />
  if (path.endsWith('/payroll-entries')) return <PayrollEntriesListView />
  if (path.endsWith('/salary-components')) return <SalaryComponentsView />
  if (path.endsWith('/payroll-periods')) return <PayrollPeriodsView />
  if (path.endsWith('/salary-structures')) return <SalaryStructuresView />
  if (path.endsWith('/accounting')) return <PayrollAccountingView />
  if (path.endsWith('/additional-salaries')) return <AdditionalSalariesView />
  if (path.endsWith('/assignments')) return <AssignmentsView />
  if (path.endsWith('/salary-slips')) return <SalarySlipsView />
  if (path.endsWith('/reports/salary-register')) return <PayrollReportView kind="salary-register" />
  if (path.endsWith('/reports/bank-remittance')) return <PayrollReportView kind="bank-remittance" />
  return <PayrollWorkspaceDashboard onCreate={() => navigate('/erp/payroll/payroll-entries/new')} />
}

export default PayrollWorkspacePage
