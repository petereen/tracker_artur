import { useState, useEffect } from 'react'
import { Btn, Card, Input, PageHeader } from '../components/ui'
import { useEmployees, useSchedules, useUpdateSchedule } from '../api/hooks'

const DAY_NAMES = ['Да', 'Мя', 'Лх', 'Пү', 'Ба', 'Бя', 'Ня']

export function SchedulePage() {
  const { data: employees = [] } = useEmployees()
  const { data: schedules = [] } = useSchedules()
  const updateSchedule = useUpdateSchedule()

  const [selected, setSelected] = useState<number | null>(null)
  const [form, setForm] = useState<any>(null)

  useEffect(() => {
    if (employees.length && !selected) setSelected(employees[0].id)
  }, [employees])

  useEffect(() => {
    if (selected && schedules.length) {
      const sch = schedules.find((s: any) => s.employee_id === selected)
      if (sch) setForm({ ...sch })
    }
  }, [selected, schedules])

  const f = (key: string, val: any) => setForm((prev: any) => ({ ...prev, [key]: val }))

  const toggleDay = (d: number) => {
    const days: number[] = form.weekdays || []
    f('weekdays', days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort())
  }

  const save = () => updateSchedule.mutate(form)

  const emp = employees.find((e: any) => e.id === selected)

  return (
    <div>
      <PageHeader title="Хуваарь" sub="Ажилтан бүрийн хувийн хуваарь" />
      <div className="grid grid-cols-[220px_1fr] gap-4">
        <Card className="!p-0 overflow-hidden self-start">
          {employees.map((e: any) => (
            <div key={e.id} onClick={() => setSelected(e.id)}
              className={`px-4 py-3 cursor-pointer border-b border-border2 flex gap-2.5 items-center transition-colors
                ${selected === e.id ? 'bg-accent-dim' : 'hover:bg-surface2'}`}>
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${e.is_active ? 'bg-green' : 'bg-muted2'}`} />
              <div>
                <div className={`text-[13px] ${selected === e.id ? 'font-semibold text-accent' : 'font-normal text-text'}`}>{e.name.split(' ')[0]}</div>
                <div className="text-[11px] text-muted">{e.name.split(' ')[1]}</div>
              </div>
            </div>
          ))}
        </Card>

        {form && emp && (
          <div className="flex flex-col gap-4">
            <Card>
              <div className="font-semibold text-[15px] mb-4">
                {emp.name} <span className="font-normal text-[13px] text-muted">{emp.timezone}</span>
              </div>

              <div className="mb-5">
                <div className="text-xs text-muted font-medium mb-2">Асуулгын хувилбар</div>
                <div className="flex gap-2">
                  {['A', 'B'].map((v) => (
                    <button key={v} onClick={() => f('variant', v)}
                      style={{ borderColor: form.variant === v ? '#388BFD' : '#30363D', background: form.variant === v ? '#1C3A6B' : 'transparent', color: form.variant === v ? '#388BFD' : '#7D8590' }}
                      className="px-5 py-2 rounded-lg border cursor-pointer font-medium text-[13px] transition-all">
                      Хувилбар {v} {v === 'A' ? '— нэг чек-ин' : '— өглөө + орой'}
                    </button>
                  ))}
                </div>
              </div>

              <div className={`grid gap-4 mb-5 ${form.variant === 'B' ? 'grid-cols-3' : 'grid-cols-2'}`}>
                <Input label="Оройн чек-ин" value={form.evening_time || ''} onChange={(v) => f('evening_time', v)} type="time" />
                {form.variant === 'B' && <Input label="Өглөөний сануулга" value={form.morning_time || ''} onChange={(v) => f('morning_time', v)} type="time" />}
                <Input label="Алгассан гэж тооцох цаг" value={form.deadline_time || ''} onChange={(v) => f('deadline_time', v)} type="time" />
              </div>

              <div className="mb-5">
                <div className="text-xs text-muted font-medium mb-2">Долоо хоногийн өдрүүд</div>
                <div className="flex gap-1.5">
                  {DAY_NAMES.map((d, i) => {
                    const idx = i + 1
                    const on = (form.weekdays || []).includes(idx)
                    return (
                      <button key={d} onClick={() => toggleDay(idx)}
                        style={{ borderColor: on ? '#388BFD' : '#30363D', background: on ? '#1C3A6B' : 'transparent', color: on ? '#388BFD' : '#7D8590' }}
                        className="w-9 h-9 rounded-lg border cursor-pointer font-medium text-xs transition-all">
                        {d}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-muted font-medium mb-1.5">Сануулга 1 (минут)</div>
                  <input type="number" value={form.reminder_intervals?.[0] ?? 60} onChange={(e) => f('reminder_intervals', [+e.target.value, form.reminder_intervals?.[1] ?? 120])}
                    className="w-full bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent" />
                </div>
                <div>
                  <div className="text-xs text-muted font-medium mb-1.5">Сануулга 2 (минут)</div>
                  <input type="number" value={form.reminder_intervals?.[1] ?? 120} onChange={(e) => f('reminder_intervals', [form.reminder_intervals?.[0] ?? 60, +e.target.value])}
                    className="w-full bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent" />
                </div>
              </div>
            </Card>

            <div className="flex justify-end gap-2.5">
              <Btn onClick={() => setSelected(selected)}>Сэргээх</Btn>
              <Btn variant="primary" size="lg" onClick={save} disabled={updateSchedule.isPending}>Хуваарь хадгалах</Btn>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
