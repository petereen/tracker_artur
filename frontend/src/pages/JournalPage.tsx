import { useState } from 'react'
import { Badge, Card, PageHeader } from '../components/ui'
import { useAnswers, useEmployees, useWorkReports } from '../api/hooks'
import { DropdownSelect } from '../components/DropdownSelect'

const REPORT_TYPE_LABELS: Record<string, string> = {
  daily: 'Өдрийн тайлан',
  monthly: 'Сарын тайлан',
  next_month_plan: 'Дараа сарын төлөвлөгөө',
  daily_test: 'Өдрийн тайлангийн тест',
  monthly_test: 'Сарын тайлангийн тест',
  next_month_plan_test: 'Төлөвлөгөөний тест',
}

const REPORT_STATUS_LABELS: Record<string, string> = {
  awaiting: 'Хүлээгдэж буй', draft: 'Ноорог', editing: 'Засаж байна', approved: 'Батлагдсан', deleted: 'Устгасан',
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit' }) : '—'
}

function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export function JournalPage() {
  const [empFilter, setEmpFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [range, setRange] = useState<'day' | 'week' | 'month' | 'all' | 'custom'>('all')
  const [tab, setTab] = useState<'answers' | 'reports'>('answers')
  const [reportType, setReportType] = useState('')
  const [reportStatus, setReportStatus] = useState('')
  const setQuickRange = (days: number, key: 'day' | 'week' | 'month') => {
    const start = new Date()
    start.setDate(start.getDate() - days + 1)
    setRange(key); setDateFrom(localDate(start)); setDateTo(localDate())
  }
  const setAllTime = () => { setRange('all'); setDateFrom(''); setDateTo('') }

  const { data: employees = [] } = useEmployees()
  const { data: rows = [] } = useAnswers({
    emp_id: empFilter ? Number(empFilter) : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  })
  const { data: reports = [] } = useWorkReports({
    employee_id: empFilter ? Number(empFilter) : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    report_type: reportType || undefined,
    status: reportStatus || undefined,
  })

  return (
    <div>
      <PageHeader title="Бүртгэл" sub={`${tab === 'answers' ? rows.length : reports.length} бичлэг`}>
        {tab === 'answers' && <a href="/api/answers/export?format=xlsx"
          className="inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border text-[13px] px-3 py-1 bg-accent text-white border-accent hover:opacity-85">
          Excel татах
        </a>}
      </PageHeader>

      <Card className="admin-table-card !p-0 overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border flex gap-3 flex-wrap items-center">
          <div className="flex gap-1 bg-surface2 rounded-lg p-1">
            <button onClick={() => setTab('answers')} className={`px-3 py-1.5 rounded text-xs cursor-pointer border-none ${tab === 'answers' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Асуулгын хариулт</button>
            <button onClick={() => setTab('reports')} className={`px-3 py-1.5 rounded text-xs cursor-pointer border-none ${tab === 'reports' ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>Ажлын тайлан</button>
          </div>
          <div className="flex gap-1 bg-surface2 rounded-lg p-1">
            {[['day', 'Өнөөдөр'], ['week', '7 хоног'], ['month', '30 хоног'], ['all', 'Бүх']].map(([key, label]) => (
              <button key={key} onClick={() => key === 'day' ? setQuickRange(1, 'day') : key === 'week' ? setQuickRange(7, 'week') : key === 'month' ? setQuickRange(30, 'month') : setAllTime()}
                className={`px-2.5 py-1.5 rounded text-xs cursor-pointer border-none ${range === key ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>{label}</button>
            ))}
          </div>
          <DropdownSelect ariaLabel="Ажилтан сонгох" value={empFilter} onChange={setEmpFilter} options={[{ value: '', label: 'Бүх ажилтан' }, ...employees.map((e: any) => ({ value: String(e.id), label: e.name }))]} />
          <input type="date" value={dateFrom} onChange={(e) => { setRange('custom'); setDateFrom(e.target.value) }}
            className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none" />
          <input type="date" value={dateTo} onChange={(e) => { setRange('custom'); setDateTo(e.target.value) }}
            className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none" />
          {tab === 'reports' && <>
            <DropdownSelect ariaLabel="Тайлангийн төрөл сонгох" value={reportType} onChange={setReportType} options={[{ value: '', label: 'Бүх төрөл' }, ...Object.entries(REPORT_TYPE_LABELS).map(([value, label]) => ({ value, label }))]} />
            <DropdownSelect ariaLabel="Тайлангийн төлөв сонгох" value={reportStatus} onChange={setReportStatus} options={[{ value: '', label: 'Бүх төлөв' }, ...Object.entries(REPORT_STATUS_LABELS).filter(([key]) => key !== 'deleted').map(([value, label]) => ({ value, label }))]} />
          </>}
          <div className="ml-auto text-[13px] text-muted">{tab === 'answers' ? rows.length : reports.length} бичлэг</div>
        </div>
        {tab === 'answers' && <div className="overflow-x-auto">
          <table className="w-full border-collapse min-w-[700px]">
            <thead>
              <tr className="bg-surface2">
                {['Ажилтан', 'Огноо', 'Асуулт / Хариулт', 'Төлөв'].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 50).map((r: any, i: number) => (
                <tr key={r.session_id} className={`transition-colors hover:bg-surface2 ${i < rows.length - 1 ? 'border-b border-border2' : ''}`}>
                  <td className="px-4 py-2.5 font-medium text-[13px]">{r.employee_name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.date}</td>
                  <td className="px-4 py-2.5 text-xs text-muted max-w-[300px]">
                    {r.answers.map((a: any, j: number) => (
                      <span key={j} className="mr-3"><span className="text-muted2">{a.question.slice(0, 20)}…</span> <span className="text-text font-mono">{a.value ?? '—'}</span></span>
                    ))}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge color={r.status === 'completed' ? 'green' : r.status === 'missed' ? 'red' : 'yellow'}>
                      {r.status === 'completed' ? 'Бөглөсөн' : r.status === 'missed' ? 'Алгассан' : 'Хэсэгчлэн'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="px-5 py-8 text-center text-muted">Мэдээлэл алга</div>}
        </div>}
        {tab === 'reports' && <div className="overflow-x-auto">
          <table className="w-full border-collapse min-w-[850px]">
            <thead><tr className="bg-surface2">
              {['Ажилтан', 'Огноо', 'Төрөл', 'Тайлан', 'Эхэлсэн / Дууссан', 'Төлөв'].map((h) => <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border whitespace-nowrap">{h}</th>)}
            </tr></thead>
            <tbody>{reports.map((report, i) => <tr key={report.id} className={`transition-colors hover:bg-surface2 ${i < reports.length - 1 ? 'border-b border-border2' : ''}`}>
              <td className="px-4 py-2.5 font-medium text-[13px]">{report.employee_name}</td>
              <td className="px-4 py-2.5 font-mono text-xs text-muted">{report.period_date}</td>
              <td className="px-4 py-2.5 text-xs">{REPORT_TYPE_LABELS[report.report_type]}</td>
              <td className="px-4 py-2.5 text-xs max-w-[360px] whitespace-pre-wrap">{report.text || '—'}</td>
              <td className="px-4 py-2.5 text-xs text-muted">{report.report_type === 'daily' ? `${formatTime(report.started_at)} / ${formatTime(report.ended_at)}` : '—'}</td>
              <td className="px-4 py-2.5"><Badge color={report.status === 'approved' ? 'green' : report.latest_revision_status === 'deleted' ? 'red' : report.status === 'awaiting' ? 'yellow' : 'blue'}>{REPORT_STATUS_LABELS[report.latest_revision_status === 'deleted' ? 'deleted' : report.status]}</Badge></td>
            </tr>)}</tbody>
          </table>
          {reports.length === 0 && <div className="px-5 py-8 text-center text-muted">Мэдээлэл алга</div>}
        </div>}
      </Card>
    </div>
  )
}
