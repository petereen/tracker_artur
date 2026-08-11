import { useState } from 'react'
import { Badge, Btn, Card, PageHeader } from '../components/ui'
import { useEmployees, useWorkReports } from '../api/hooks'
import { ReportDetailModal } from '../components/ReportDetailModal'
import { DropdownSelect } from '../components/DropdownSelect'

const STATUS_LABELS: Record<string, string> = { awaiting: 'Хүлээгдэж буй', draft: 'Ноорог', editing: 'Засаж байна', approved: 'Батлагдсан' }

export function ReportsPage() {
  const [tab, setTab] = useState<'daily' | 'monthly'>('daily')
  const [employeeId, setEmployeeId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [status, setStatus] = useState('')
  const [detailId, setDetailId] = useState<number | null>(null)
  const { data: employees = [] } = useEmployees()
  const { data: reports = [], isLoading } = useWorkReports({ employee_id: employeeId ? Number(employeeId) : undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined, status: status || undefined, report_type: tab })
  return <div>
    <PageHeader title="Тайлангууд" sub={`${reports.length} ${tab === 'daily' ? 'өдрийн' : 'сарын'} тайлан`} />
    <Card className="admin-table-card !p-0 overflow-hidden">
      <div className="px-5 py-3.5 border-b border-border flex flex-wrap gap-3 items-center">
        <div className="flex gap-1 bg-surface2 rounded-lg p-1"><button onClick={() => setTab('daily')} className={`px-3 py-1.5 rounded text-xs border-none cursor-pointer ${tab === 'daily' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Өдрийн тайлан</button><button onClick={() => setTab('monthly')} className={`px-3 py-1.5 rounded text-xs border-none cursor-pointer ${tab === 'monthly' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Сарын тайлан</button></div>
        <DropdownSelect ariaLabel="Ажилтан сонгох" value={employeeId} onChange={setEmployeeId} options={[{ value: '', label: 'Бүх ажилтан' }, ...employees.map((employee: any) => ({ value: String(employee.id), label: employee.name }))]} />
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-[13px] outline-none" />
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-[13px] outline-none" />
        <DropdownSelect ariaLabel="Тайлангийн төлөв сонгох" value={status} onChange={setStatus} options={[{ value: '', label: 'Бүх төлөв' }, ...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))]} />
      </div>
      <div className="overflow-x-auto"><table className="w-full border-collapse min-w-[800px]"><thead><tr className="bg-surface2">{['Ажилтан', 'Огноо', 'Тайлангийн товч', 'Төлөв', ''].map((label) => <th key={label} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border">{label}</th>)}</tr></thead><tbody>
        {reports.map((report, index) => <tr key={report.id} className={index < reports.length - 1 ? 'border-b border-border2' : ''}><td className="px-4 py-3 text-sm font-medium">{report.employee_name}</td><td className="px-4 py-3 text-xs font-mono text-muted">{report.period_date}</td><td className="px-4 py-3 text-xs max-w-[420px]"><span className="line-clamp-2 whitespace-pre-wrap">{report.text || '—'}</span></td><td className="px-4 py-3"><Badge color={report.status === 'approved' ? 'green' : 'yellow'}>{STATUS_LABELS[report.status]}</Badge></td><td className="px-4 py-3"><Btn onClick={() => setDetailId(report.id)}>Дэлгэрэнгүй</Btn></td></tr>)}
      </tbody></table></div>
      {!isLoading && !reports.length && <div className="p-8 text-center text-muted">Тайлан байхгүй</div>}
    </Card>
    {detailId !== null && <ReportDetailModal reportId={detailId} onClose={() => setDetailId(null)} />}
  </div>
}
