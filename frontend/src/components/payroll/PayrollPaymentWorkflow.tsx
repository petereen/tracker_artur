import { useState } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  downloadPayrollExport, useCreatePayrollBankExport, useImportPayrollStatement,
  useMatchPayrollStatementLine, usePayrollBankExportProfiles, usePayrollPaymentAllocations,
  usePayrollPaymentBatch, usePayrollPaymentBatches, usePayrollStatementImport,
  usePayrollStatementImports, usePreparePayrollPayments, usePublishPayrollPayslips,
  useRejectPayrollPayment, useReversePayrollPayment, useSettlePayrollPayment, useSubmitPayrollPaymentBatch,
} from '../../api/enterprise'
import type { PayrollPaymentAllocation } from '../../api/enterprise'

const message = (error: any) => error?.response?.data?.detail?.message || error?.response?.data?.detail?.code || 'Үйлдэл амжилтгүй'
const money = (amount: string) => new Intl.NumberFormat('mn-MN', { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(amount))

function StatementMatching({ accountId, allocations, canPay }: { accountId: number; allocations: PayrollPaymentAllocation[]; canPay: boolean }) {
  const statements = usePayrollStatementImports(canPay)
  const [selectedId, setSelectedId] = useState<number>()
  const statementId = selectedId || statements.data?.find((row) => row.payment_account_id === accountId)?.id
  const statement = usePayrollStatementImport(statementId, canPay)
  const create = useImportPayrollStatement()
  const match = useMatchPayrollStatementLine()
  const [entry, setEntry] = useState({ transaction_date: '', transaction_reference: '', amount: '' })
  const addLine = async () => {
    if (!entry.transaction_date || !entry.transaction_reference.trim() || Number(entry.amount) <= 0) return
    const line = { ...entry, transaction_reference: entry.transaction_reference.trim(), amount: entry.amount, currency: 'MNT' as const }
    const bytes = new TextEncoder().encode(JSON.stringify({ accountId, line }))
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    const source_checksum = Array.from(new Uint8Array(digest)).map((part) => part.toString(16).padStart(2, '0')).join('')
    try {
      const result = await create.mutateAsync({ payment_account_id: accountId, source_checksum, lines: [line] })
      setSelectedId(result.id)
      setEntry({ transaction_date: '', transaction_reference: '', amount: '' })
      toast.success('Хуулгын мөр нэмэгдлээ')
    } catch (error) { toast.error(message(error)) }
  }
  return <section className="payroll-v2-stage-card"><h2>Банкны тулгалт</h2><p>Банкны баталгаажсан лавлагаа, огноо, дүнг бүртгээд төлсөн ажилтантай тулгана.</p>{canPay && <div className="payroll-v2-form-grid"><label>Гүйлгээний өдөр<input type="date" value={entry.transaction_date} onChange={(event) => setEntry({ ...entry, transaction_date: event.target.value })} /></label><label>Банкны лавлагаа<input value={entry.transaction_reference} onChange={(event) => setEntry({ ...entry, transaction_reference: event.target.value })} /></label><label>Дүн (MNT)<input type="number" min="0.01" step="0.01" value={entry.amount} onChange={(event) => setEntry({ ...entry, amount: event.target.value })} /></label><button className="payroll-v2-button secondary" disabled={create.isPending || !entry.transaction_date || !entry.transaction_reference.trim() || Number(entry.amount) <= 0} onClick={addLine}>Хуулгын мөр оруулах</button></div>}{statements.data?.some((row) => row.payment_account_id === accountId) && <label>Хуулга сонгох<select value={statementId || ''} onChange={(event) => setSelectedId(Number(event.target.value))}>{statements.data.filter((row) => row.payment_account_id === accountId).map((row) => <option key={row.id} value={row.id}>#{row.id} · {row.status}</option>)}</select></label>}{statement.data?.lines.map((line) => { const options = allocations.filter((row) => row.status === 'settled' && Number(row.amount) === Number(line.amount) && (!line.transaction_reference || line.transaction_reference === row.transaction_reference)); return <div className="payroll-setup-mini-row" key={line.id}><span><strong>{line.transaction_reference || `Мөр #${line.id}`}</strong><small>{line.transaction_date} · {money(line.amount)} · {line.match_status}</small></span>{canPay && line.match_status !== 'matched' && <select aria-label={`Мөр #${line.id} тулгах`} defaultValue="" disabled={match.isPending} onChange={(event) => { if (!event.target.value) return; match.mutate({ lineId: line.id, allocationId: Number(event.target.value) }, { onSuccess: () => toast.success('Мөр тулгагдлаа'), onError: (error) => toast.error(message(error)) }) }}><option value="">Төлбөр сонгох</option>{options.map((row) => <option key={row.id} value={row.id}>Ажилтан #{row.employee_id} · {row.transaction_reference}</option>)}</select>}</div> })}<p aria-live="polite">{statement.data?.status === 'reconciled' ? 'Хуулга бүрэн тулгагдсан.' : 'Тулгалт хүлээгдэж байна.'}</p></section>
}

export function PayrollPaymentWorkflow({ runId, status, canPay, canRelease, released }: { runId: number; status: string; canPay: boolean; canRelease: boolean; released: boolean }) {
  const batches = usePayrollPaymentBatches(runId)
  const batchId = batches.data?.[0]?.id
  const batch = usePayrollPaymentBatch(batchId, Boolean(batchId))
  const allocations = usePayrollPaymentAllocations({ runId }, Boolean(batchId))
  const prepare = usePreparePayrollPayments()
  const submit = useSubmitPayrollPaymentBatch()
  const settle = useSettlePayrollPayment()
  const reject = useRejectPayrollPayment()
  const reverse = useReversePayrollPayment()
  const publish = usePublishPayrollPayslips()
  const templates = usePayrollBankExportProfiles(canPay)
  const bankExport = useCreatePayrollBankExport()
  const [bankCode, setBankCode] = useState('')
  const [nextBatchKey, setNextBatchKey] = useState(() => crypto.randomUUID())
  const [references, setReferences] = useState<Record<number, string>>({})
  const [reasons, setReasons] = useState<Record<number, string>>({})
  const [reversalReasons, setReversalReasons] = useState<Record<number, string>>({})
  const [reversalReferences, setReversalReferences] = useState<Record<number, string>>({})
  const act = async (call: Promise<unknown>, success: string) => { try { await call; toast.success(success) } catch (error) { toast.error(message(error)) } }
  const prepareRemaining = async () => {
    try {
      await prepare.mutateAsync({ id: runId, idempotency_key: nextBatchKey })
      setNextBatchKey(crypto.randomUUID())
      toast.success('Төлбөр бэлтгэгдлээ')
    } catch (error) { toast.error(message(error)) }
  }
  const rows = allocations.data?.length ? allocations.data : batch.data?.allocations || []
  return <><section className="payroll-v2-stage-card"><h2>Төлбөр ба цалингийн хуудас</h2><p>Бодит банкны лавлагаатай төлөгдсөн дүнг бүртгэнэ. Бүх ажилтны төлбөр дуусмагц хуудсыг гаргана.</p>{!batchId && canPay && <button className="payroll-v2-button primary" disabled={status !== 'posted' || prepare.isPending} onClick={prepareRemaining}>Төлбөр бэлтгэх</button>}{batch.data && <><div className="payroll-v2-payment-summary"><div><span>Багц</span><strong>{batch.data.batch_reference}</strong></div><div><span>Төлөв</span><strong>{batch.data.status}</strong></div><div><span>Дүн</span><strong>{money(batch.data.total_amount)}</strong></div></div>{canPay && batch.data.status === 'prepared' && <button className="payroll-v2-button secondary" disabled={submit.isPending} onClick={() => act(submit.mutateAsync(batch.data!.id), 'Банк руу илгээсэн төлөвт шилжлээ')}>Банк руу илгээснийг тэмдэглэх</button>}{rows.map((row) => <div className="payroll-setup-mini-row" key={row.id}><span><strong>Ажилтан #{row.employee_id}</strong><small>Багц #{row.payment_batch_id || batch.data?.id} · {money(row.amount)} · {row.status}{row.transaction_reference ? ` · ${row.transaction_reference}` : ''}</small></span>{canPay && ['pending', 'bank_submitted'].includes(row.status) && <div className="payroll-v2-action-row"><label>Банкны лавлагаа<input value={references[row.id] || ''} onChange={(event) => setReferences({ ...references, [row.id]: event.target.value })} /></label><button className="payroll-v2-button compact primary" title={row.status !== 'bank_submitted' ? 'Эхлээд банк руу илгээснийг тэмдэглэнэ үү' : undefined} disabled={row.status !== 'bank_submitted' || !references[row.id]?.trim() || settle.isPending} onClick={() => act(settle.mutateAsync({ paymentId: row.payment_batch_id || batch.data!.id, allocationId: row.id, transaction_reference: references[row.id].trim(), evidence: { source: 'bank_confirmation' } }), 'Төлбөр баталгаажлаа')}>Төлөгдсөн</button><label>Татгалзсан шалтгаан<input value={reasons[row.id] || ''} onChange={(event) => setReasons({ ...reasons, [row.id]: event.target.value })} /></label><button className="payroll-v2-button compact danger" disabled={!reasons[row.id]?.trim() || reject.isPending} onClick={() => act(reject.mutateAsync({ paymentId: row.payment_batch_id || batch.data!.id, allocationId: row.id, reason: reasons[row.id].trim() }), 'Татгалзсан төлбөр бүртгэгдлээ')}>Татгалзсан</button></div>}{canPay && row.status === 'settled' && <div className="payroll-v2-action-row"><label>Буцаалтын шалтгаан<input value={reversalReasons[row.id] || ''} onChange={(event) => setReversalReasons({ ...reversalReasons, [row.id]: event.target.value })} /></label><label>Банкны буцаалтын лавлагаа<input value={reversalReferences[row.id] || ''} onChange={(event) => setReversalReferences({ ...reversalReferences, [row.id]: event.target.value })} /></label><button className="payroll-v2-button compact danger" disabled={!reversalReasons[row.id]?.trim() || !reversalReferences[row.id]?.trim() || reverse.isPending} onClick={() => act(reverse.mutateAsync({ allocationId: row.id, reason: reversalReasons[row.id].trim(), transaction_reference: reversalReferences[row.id].trim() }), 'Төлбөр буцаагдлаа')}>Төлбөр буцаах</button></div>}</div>)}{canPay && status === 'partially_settled' && batch.data?.status === 'settled' && <button className="payroll-v2-button secondary" disabled={prepare.isPending} onClick={prepareRemaining}>Үлдэгдэл төлбөр бэлтгэх</button>}{canPay && batch.data?.allocations?.some((row) => ['rejected', 'reversed'].includes(row.status)) && <button className="payroll-v2-button secondary" disabled={prepare.isPending} onClick={() => act(prepare.mutateAsync({ id: runId, retry_of_batch_id: batch.data!.id }), 'Дахин төлөх багц үүслээ')}>Татгалзсан дүнг дахин бэлтгэх</button>}{canPay && templates.data?.some((row) => row.status === 'published' && !row.is_provisional) && <div className="payroll-v2-action-row"><select aria-label="Банкны layout" value={bankCode} onChange={(event) => setBankCode(event.target.value)}><option value="">Банкны layout сонгох</option>{templates.data.filter((row) => row.status === 'published' && !row.is_provisional).map((row) => <option key={row.id} value={row.bank_code}>{row.bank_code} · v{row.version}</option>)}</select><button className="payroll-v2-button secondary" disabled={!bankCode || bankExport.isPending} onClick={() => bankExport.mutate({ id: runId, bank_code: bankCode }, { onSuccess: (artifact) => downloadPayrollExport(artifact.artifact_id, artifact.filename).catch((error) => toast.error(message(error))), onError: (error) => toast.error(message(error)) })}>Банкны файл татах</button></div>}</>}{canRelease && <button className="payroll-v2-button primary" disabled={released || !['settled', 'payslips_released'].includes(status) || publish.isPending} onClick={() => act(publish.mutateAsync({ id: runId }), 'Цалингийн хуудас гарлаа')}>{released ? 'Хуудас гарсан' : 'Цалингийн хуудас гаргах'}</button>}{!canRelease && <p>Хуудас гаргах эрх шаардлагатай.</p>}{!batchId && status === 'posted' && !canPay && <Link to="/erp/payroll/setup?tab=accounting">Төлбөрийн эрхтэй ажилтанд шилжүүлэх</Link>}</section>{batch.data && <StatementMatching accountId={batch.data.payment_account_id} allocations={allocations.data || []} canPay={canPay} />}</>
}
