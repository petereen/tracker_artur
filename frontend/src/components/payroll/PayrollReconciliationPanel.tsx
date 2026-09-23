import { useState } from 'react'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'
import { usePayrollReconciliation, useResolvePayrollReconciliation } from '../../api/enterprise'

function message(error: any) {
  return error?.response?.data?.detail?.code || error?.response?.data?.detail?.message || 'Тулгалтын үйлдэл амжилтгүй'
}

export function PayrollReconciliationPanel({ runId, canResolve }: { runId: number; canResolve: boolean }) {
  const report = usePayrollReconciliation(runId)
  const resolve = useResolvePayrollReconciliation()
  const [selected, setSelected] = useState<string[]>([])
  const [note, setNote] = useState('')
  const issues = report.data?.issues || []
  const open = issues.filter((issue) => !issue.resolved)
  const submit = async () => {
    if (!selected.length || !note.trim()) return
    try {
      await resolve.mutateAsync({ id: runId, issue_keys: selected, note: note.trim() })
      setSelected([])
      setNote('')
      toast.success('Тулгалтын тэмдэглэл хадгалагдлаа')
    } catch (error) {
      toast.error(message(error))
    }
  }
  return <section className="payroll-v2-stage-card" aria-live="polite">
    <h2>Бодолтын тулгалт</h2>
    {report.isLoading && <p>Тулгалтыг ачаалж байна…</p>}
    {report.isError && <p role="alert">Тулгалтыг ачаалж чадсангүй. <button className="payroll-v2-button secondary" onClick={() => report.refetch()}>Дахин оролдох</button></p>}
    {report.data && <>
      <p>{report.data.unresolved_errors} алдаа, {report.data.unresolved_warnings} анхааруулга шийдэгдээгүй. Алдааг шийдсэний дараа хяналтад шилжүүлнэ.</p>
      {!issues.length && <p>Тулгалтын зөрчил олдсонгүй.</p>}
      {issues.map((issue) => <div className="payroll-setup-mini-row" key={issue.key}>
        <span><strong>{issue.employee_id ? `Ажилтан #${issue.employee_id}: ` : ''}{issue.message}</strong><small>{issue.code} · {issue.severity === 'error' ? 'Алдаа' : 'Анхааруулга'} · {issue.resolved ? 'Шийдсэн' : 'Нээлттэй'}</small></span>
        {canResolve && !issue.resolved && <label><input type="checkbox" checked={selected.includes(issue.key)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, issue.key] : current.filter((key) => key !== issue.key))} />Шийдсэн</label>}
      </div>)}
      {canResolve && open.length > 0 && <div className="payroll-v2-action-row"><label>Шийдвэрлэсэн тайлбар<input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Баримт болон засварыг тэмдэглэнэ үү" /></label><button className="payroll-v2-button secondary" disabled={!selected.length || !note.trim() || resolve.isPending} onClick={submit}>Тэмдэглэх</button></div>}
      {open.some((issue) => issue.code === 'missing_bank_details') && <Link to="/erp/payroll/setup?tab=assignments">Банкны мэдээлэл засах</Link>}
      {open.some((issue) => issue.code === 'unapproved_time_entry' || issue.code === 'missing_approved_time') && <Link to="/erp/payroll/inputs">Циклийн оролт шалгах</Link>}
    </>}
  </section>
}
