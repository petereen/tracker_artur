import { useMemo, useState } from 'react'
import { Search, Star } from 'lucide-react'
import { useCRMActivities, useCRMSummary, type CRMActivity, type CRMActivityFilters, type CRMCapabilities, type CRMLookups } from '../../api/crm'
import { Btn, Card } from '../ui'
import { CheckField, NativeSelect, StatusChip, formatDateTime, formatMoney } from './shared'
import { CreateButton } from '../CreateButton'

type Preset = 'open' | 'overdue' | 'today' | 'week' | 'important'
const PAGE_SIZE = 50

const isoDay = (offset = 0) => { const date = new Date(); date.setDate(date.getDate() + offset); return date.toISOString().slice(0, 10) }

export function ActivitiesPanel({ lookups, capabilities, isManager, partyId, compact, onOpen, onCreate }: {
  lookups: CRMLookups
  capabilities: CRMCapabilities
  isManager: boolean
  partyId?: number
  compact?: boolean
  onOpen: (activity: CRMActivity) => void
  onCreate: () => void
}) {
  const [search, setSearch] = useState('')
  const [preset, setPreset] = useState<Preset | null>(compact ? null : 'open')
  const [mine, setMine] = useState(!isManager && !compact)
  const [statusId, setStatusId] = useState('')
  const [typeId, setTypeId] = useState('')
  const [responsible, setResponsible] = useState('')
  const [state, setState] = useState<'open' | 'closed' | 'all'>('all')
  const [includeChildren, setIncludeChildren] = useState(false)
  const [page, setPage] = useState(1)
  const summary = useCRMSummary(mine, !compact)

  const filters = useMemo<CRMActivityFilters>(() => {
    const value: CRMActivityFilters = {
      search: search || undefined, party_id: partyId, include_children: partyId ? includeChildren : undefined, mine: mine || undefined,
      status_id: statusId ? Number(statusId) : undefined, type_id: typeId ? Number(typeId) : undefined,
      responsible_employee_id: responsible ? Number(responsible) : undefined, state, page, page_size: PAGE_SIZE,
    }
    if (preset === 'open') value.state = 'open'
    if (preset === 'overdue') value.overdue = true
    if (preset === 'important') { value.important = true; value.state = 'open' }
    if (preset === 'today') { value.state = 'open'; value.due_to = isoDay(0); value.sort = 'due_at' }
    if (preset === 'week') { value.state = 'open'; value.due_from = isoDay(0); value.due_to = isoDay(6); value.sort = 'due_at' }
    return value
  }, [includeChildren, mine, page, partyId, preset, responsible, search, state, statusId, typeId])
  const activities = useCRMActivities(filters)
  const rows = activities.data?.items ?? []
  const total = activities.data?.total ?? 0
  const choose = (next: Preset) => { setPreset((current) => (current === next ? null : next)); setPage(1) }

  return <div className="crm-workspace">
    {!compact && summary.data && <div className="crm-summary">
      <button type="button" className={preset === 'open' ? 'active' : ''} onClick={() => choose('open')}><small>Нээлттэй</small><strong>{summary.data.open}</strong></button>
      <button type="button" className={`${preset === 'overdue' ? 'active' : ''} ${summary.data.overdue ? 'is-danger' : ''}`} onClick={() => choose('overdue')}><small>Хугацаа хэтэрсэн</small><strong>{summary.data.overdue}</strong></button>
      <button type="button" className={preset === 'today' ? 'active' : ''} onClick={() => choose('today')}><small>Өнөөдөр дуусах</small><strong>{summary.data.due_today}</strong></button>
      <button type="button" className={preset === 'week' ? 'active' : ''} onClick={() => choose('week')}><small>7 хоногт дуусах</small><strong>{summary.data.due_this_week}</strong></button>
      <button type="button" className={preset === 'important' ? 'active' : ''} onClick={() => choose('important')}><small>Чухал</small><strong>{summary.data.important}</strong></button>
    </div>}
    {!compact && summary.data && summary.data.expected_revenue.length > 0 && <div className="crm-muted">
      Нээлттэй бүртгэлийн хүлээгдэж буй орлого: <strong>{summary.data.expected_revenue.map((row) => formatMoney(row.amount, row.currency)).join(' · ')}</strong>
    </div>}

    <Card>
      <div className="crm-toolbar">
        <label className="hr-search"><Search size={15} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} placeholder="Утга, дугаар, холбогдох хүн, reference…" /></label>
        <NativeSelect value={statusId} onChange={(value) => { setStatusId(value); setPage(1) }} options={lookups.statuses.map((row) => ({ value: String(row.id), label: row.name }))} placeholder="Бүх төлөв" />
        <NativeSelect value={typeId} onChange={(value) => { setTypeId(value); setPage(1) }} options={lookups.activity_types.map((row) => ({ value: String(row.id), label: row.name }))} placeholder="Бүх төрөл" />
        <NativeSelect value={responsible} onChange={(value) => { setResponsible(value); setPage(1) }} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} placeholder="Бүх хариуцагч" />
        {capabilities.activities.create ? <CreateButton label="Шинэ бүртгэл" onClick={onCreate} /> : <span />}
      </div>
      <div className="crm-toolbar-flags">
        {!compact && <CheckField label="Зөвхөн миний" checked={mine} onChange={(value) => { setMine(value); setPage(1) }} />}
        {partyId && <CheckField label="Салбаруудыг оруулах" checked={includeChildren} onChange={(value) => { setIncludeChildren(value); setPage(1) }} />}
        {!preset && <NativeSelect value={state === 'all' ? '' : state} onChange={(value) => { setState((value || 'all') as typeof state); setPage(1) }} options={[{ value: 'open', label: 'Нээлттэй' }, { value: 'closed', label: 'Дууссан / хаагдсан' }]} placeholder="Бүгд" />}
        {preset && <button type="button" className="secondary-action" onClick={() => setPreset(null)}>Шүүлтүүр арилгах</button>}
      </div>
      <div className="crm-table">
        <table>
          <thead><tr><th>Дугаар</th><th>Огноо</th>{!partyId && <th>Харилцагч</th>}<th>Утга</th><th>Төрөл</th><th>Хариуцагч</th><th>Биелэх</th><th>Хэтэрсэн</th><th>Төлөв</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={row.id} className={row.is_overdue ? 'is-overdue' : ''} onClick={() => onOpen(row)}>
              <td>{row.is_important && <Star size={12} className="crm-star" aria-label="Чухал" fill="currentColor" />} {row.number}</td>
              <td>{formatDateTime(row.activity_at)}</td>
              {!partyId && <td>{row.party_name ? <div className="crm-subject"><span>{row.party_name}</span><small>{row.contact_name || row.party_code}</small></div> : <span className="crm-muted">Дотоод</span>}</td>}
              <td><div className="crm-subject"><strong>{row.subject}</strong>{row.expected_revenue && <small>{formatMoney(row.expected_revenue, row.currency)}</small>}</div></td>
              <td>{row.type_name || '—'}</td>
              <td>{row.responsible_name || '—'}</td>
              <td>{formatDateTime(row.due_at)}</td>
              <td>{row.overdue_days ? <span className={row.is_overdue ? 'crm-overdue' : ''}>{row.overdue_days}</span> : '—'}</td>
              <td>{row.is_closed ? <StatusChip name="Хаагдсан" color="var(--color-muted)" /> : row.status ? <StatusChip name={row.status.name} color={row.status.color} /> : '—'}</td>
            </tr>)}
          </tbody>
        </table>
        {!rows.length && <div className="hr-empty">{activities.isLoading ? 'Ачаалж байна…' : 'Бүртгэл олдсонгүй'}</div>}
      </div>
      {total > PAGE_SIZE && <div className="crm-pager">
        <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} / {total}</span>
        <Btn disabled={page === 1} onClick={() => setPage(page - 1)}>Өмнөх</Btn>
        <Btn disabled={page * PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>Дараах</Btn>
      </div>}
    </Card>

    {!compact && isManager && summary.data && summary.data.by_responsible.length > 0 && <Card>
      <h3 className="hr-form-section">Хариуцагчаар</h3>
      <div className="crm-list" style={{ marginTop: 10 }}>
        {summary.data.by_responsible.map((row) => <article key={row.employee_id}>
          <div><strong>{row.name}</strong><small>Нээлттэй {row.open}</small></div>
          {row.overdue > 0 && <span className="crm-overdue">{row.overdue} хэтэрсэн</span>}
        </article>)}
      </div>
    </Card>}
  </div>
}
