import { useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useEmployees, useCreateEmployee, useUpdateEmployee } from '../api/hooks'

const TZ_OPTIONS = [
  { value: 'Europe/Moscow',       label: 'Москва (UTC+3)' },
  { value: 'Europe/Kaliningrad',  label: 'Калининград (UTC+2)' },
  { value: 'Asia/Yekaterinburg',  label: 'Екатеринбург (UTC+5)' },
  { value: 'Asia/Novosibirsk',    label: 'Новосибирск (UTC+7)' },
  { value: 'Asia/Almaty',         label: 'Алматы (UTC+5)' },
]

export function EmployeesPage() {
  const { data: employees = [] } = useEmployees()
  const create = useCreateEmployee()
  const update = useUpdateEmployee()

  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ name: '', telegram_id: '', telegram_username: '', timezone: 'Europe/Moscow' })

  const filtered = employees.filter((e: any) =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    (e.telegram_username || '').includes(search)
  )

  const submit = async () => {
    await create.mutateAsync(form)
    setShowModal(false)
    setForm({ name: '', telegram_id: '', telegram_username: '', timezone: 'Europe/Moscow' })
  }

  const toggle = (emp: any) => update.mutate({ id: emp.id, is_active: !emp.is_active })

  const fillColor = (v: number) => v >= 85 ? 'text-green' : v >= 60 ? 'text-yellow' : 'text-red'
  const fillBg = (v: number) => v >= 85 ? 'bg-green' : v >= 60 ? 'bg-yellow' : 'bg-red'

  return (
    <div>
      <PageHeader title="Сотрудники" sub={`${employees.filter((e: any) => e.is_active).length} активных · ${employees.length} всего`}>
        <Btn variant="primary" onClick={() => setShowModal(true)}>+ Добавить</Btn>
      </PageHeader>

      <Card className="p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-border">
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по имени или @username…"
            className="w-full bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none focus:border-accent" />
        </div>
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-surface2">
              {['Сотрудник', 'Telegram', 'ID', 'Часовой пояс', 'Статус', ''].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((e: any, i: number) => (
              <tr key={e.id} className={`transition-colors hover:bg-surface2 ${i < filtered.length - 1 ? 'border-b border-border2' : ''}`}>
                <td className="px-4 py-3 font-medium">{e.name}</td>
                <td className="px-4 py-3 text-muted font-mono text-xs">{e.telegram_username || '—'}</td>
                <td className="px-4 py-3 text-muted2 font-mono text-[11px]">{e.telegram_id}</td>
                <td className="px-4 py-3 text-muted text-xs">{e.timezone}</td>
                <td className="px-4 py-3"><Badge color={e.is_active ? 'green' : 'muted'}>{e.is_active ? 'Активен' : 'Неактивен'}</Badge></td>
                <td className="px-4 py-3">
                  <div className="flex gap-1.5">
                    <Btn variant={e.is_active ? 'danger' : 'ghost'} onClick={() => toggle(e)}>{e.is_active ? 'Откл.' : 'Вкл.'}</Btn>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="px-5 py-8 text-center text-muted">Сотрудники не найдены</div>}
      </Card>

      {showModal && (
        <Modal title="Новый сотрудник" onClose={() => setShowModal(false)}>
          <div className="flex flex-col gap-3.5">
            <Input label="Имя и фамилия" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="Иван Петров" fullWidth />
            <Input label="Telegram ID" value={form.telegram_id} onChange={(v) => setForm((f) => ({ ...f, telegram_id: v }))} placeholder="123456789" fullWidth />
            <Input label="Telegram username" value={form.telegram_username} onChange={(v) => setForm((f) => ({ ...f, telegram_username: v }))} placeholder="@username" fullWidth />
            <Select label="Часовой пояс" value={form.timezone} onChange={(v) => setForm((f) => ({ ...f, timezone: v }))} options={TZ_OPTIONS} fullWidth />
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={() => setShowModal(false)}>Отмена</Btn>
              <Btn variant="primary" onClick={submit} disabled={create.isPending}>Добавить</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
