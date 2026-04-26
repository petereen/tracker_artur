import { useState } from 'react'
import { Badge, Card, PageHeader, Btn } from '../components/ui'
import { useAnswers, useEmployees } from '../api/hooks'

export function JournalPage() {
  const [empFilter, setEmpFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')

  const { data: employees = [] } = useEmployees()
  const { data: rows = [] } = useAnswers({
    emp_id: empFilter ? Number(empFilter) : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  })

  return (
    <div>
      <PageHeader title="Журнал ответов" sub={`${rows.length} записей`}>
        <a href="/api/answers/export?format=xlsx"
          className="inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border text-[13px] px-3 py-1 bg-accent text-white border-accent hover:opacity-85">
          Экспорт Excel
        </a>
      </PageHeader>

      <Card className="!p-0 overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border flex gap-3 flex-wrap items-center">
          <select value={empFilter} onChange={(e) => setEmpFilter(e.target.value)}
            className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none">
            <option value="">Все сотрудники</option>
            {employees.map((e: any) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none" />
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none" />
          <div className="ml-auto text-[13px] text-muted">{rows.length} записей</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse min-w-[700px]">
            <thead>
              <tr className="bg-surface2">
                {['Сотрудник', 'Дата', 'Вопросы / Ответы', 'Статус'].map((h) => (
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
                      {r.status === 'completed' ? 'Заполнен' : r.status === 'missed' ? 'Пропущен' : 'Частично'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="px-5 py-8 text-center text-muted">Нет данных</div>}
        </div>
      </Card>
    </div>
  )
}
