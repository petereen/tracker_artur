import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Download, FileUp, ListPlus, Plus, Search } from 'lucide-react'
import {
  downloadCRMImportTemplate, downloadCRMPartiesCsv, useBulkCRMActivities, useCRMParties, useImportCRMParties,
  type CRMCapabilities, type CRMImportResult, type CRMLookups, type CRMParty, type CRMPartyFilters,
} from '../../api/crm'
import { Badge, Btn, Card, Modal } from '../ui'
import { CheckField, Field, NativeSelect, TextInput, crmErrorText, formatDate } from './shared'

const PAGE_SIZE = 50

export function CustomersPanel({ lookups, capabilities, onOpen, onCreate }: { lookups: CRMLookups; capabilities: CRMCapabilities; onOpen: (party: CRMParty) => void; onCreate: () => void }) {
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<NonNullable<CRMPartyFilters['kind']>>('all')
  const [groupId, setGroupId] = useState('')
  const [responsible, setResponsible] = useState('')
  const [active, setActive] = useState<'active' | 'inactive' | ''>('active')
  const [duplicatesOnly, setDuplicatesOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [importing, setImporting] = useState(false)
  const [bulk, setBulk] = useState(false)
  const filters = useMemo<CRMPartyFilters>(() => ({
    search: search || undefined, kind, group_id: groupId ? Number(groupId) : undefined, responsible_employee_id: responsible ? Number(responsible) : undefined,
    is_active: active === '' ? undefined : active === 'active', duplicates_only: duplicatesOnly || undefined, page, page_size: PAGE_SIZE,
  }), [active, duplicatesOnly, groupId, kind, page, responsible, search])
  const parties = useCRMParties(filters)
  const rows = parties.data?.items ?? []
  const total = parties.data?.total ?? 0
  const reset = <T,>(setter: (value: T) => void) => (value: T) => { setter(value); setPage(1) }
  const toggle = (id: number) => setSelected((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next })

  return <Card>
    <div className="crm-toolbar">
      <label className="hr-search"><Search size={15} /><input value={search} onChange={(event) => reset(setSearch)(event.target.value)} placeholder="Нэр, код, ТТД, РД, утас, tag…" /></label>
      <NativeSelect value={kind === 'all' ? '' : kind} onChange={(value) => reset(setKind)((value || 'all') as typeof kind)} options={[{ value: 'customer', label: 'Худалдан авагч' }, { value: 'supplier', label: 'Нийлүүлэгч' }, { value: 'prospect', label: 'Lead' }]} placeholder="Бүх төрөл" />
      <NativeSelect value={groupId} onChange={reset(setGroupId)} options={lookups.party_groups.map((row) => ({ value: String(row.id), label: row.name }))} placeholder="Бүх бүлэг" />
      <NativeSelect value={responsible} onChange={reset(setResponsible)} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} placeholder="Бүх хариуцагч" />
      {capabilities.parties.create ? <Btn variant="primary" onClick={onCreate}><Plus size={15} />Шинэ харилцагч</Btn> : <span />}
    </div>
    <div className="crm-toolbar-flags">
      <NativeSelect value={active} onChange={(value) => reset(setActive)(value as typeof active)} options={[{ value: 'active', label: 'Идэвхтэй' }, { value: 'inactive', label: 'Идэвхгүй' }]} placeholder="Идэвхтэй / идэвхгүй" />
      <CheckField label="Давхардсан ТТД/нэр" checked={duplicatesOnly} onChange={reset(setDuplicatesOnly)} />
      <Btn onClick={() => void downloadCRMPartiesCsv(filters).catch((error) => toast.error(crmErrorText(error)))}><Download size={14} />Экспорт</Btn>
      {capabilities.parties.create && <Btn onClick={() => setImporting(true)}><FileUp size={14} />Импорт</Btn>}
      {capabilities.activities.create && selected.size > 0 && <Btn onClick={() => setBulk(true)}><ListPlus size={14} />{selected.size} харилцагчид харилцаа нэмэх</Btn>}
    </div>
    <div className="crm-table">
      <table>
        <thead><tr>{capabilities.activities.create && <th />}<th>Код</th><th>Нэр</th><th>ТТД / РД</th><th>Бүлэг</th><th>Хариуцагч</th><th>Утас</th><th>Харилцагч болсон</th><th>Төлөв</th></tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.id} onClick={() => onOpen(row)}>
            {capabilities.activities.create && <td onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`${row.name} сонгох`} checked={selected.has(row.id)} onChange={() => toggle(row.id)} /></td>}
            <td>{row.code}</td>
            <td><div className="crm-subject"><strong className={row.duplicate_name ? 'crm-duplicate' : ''}>{row.name}</strong>{(row.business_name || row.parent_name) && <small>{[row.business_name, row.parent_name && `↳ ${row.parent_name}`].filter(Boolean).join(' · ')}</small>}</div></td>
            <td className={row.duplicate_tax_id ? 'crm-duplicate' : ''}>{[row.tax_id, row.registry_no].filter(Boolean).join(' / ') || '—'}</td>
            <td>{row.group_name || '—'}</td>
            <td>{row.responsible_name || '—'}</td>
            <td>{row.phone || '—'}</td>
            <td>{formatDate(row.customer_since)}</td>
            <td className="crm-checks">
              {row.is_active ? <Badge color="green">Идэвхтэй</Badge> : <Badge color="muted">Идэвхгүй</Badge>}
              {row.party_type === 'prospect' && <Badge color="purple">Lead</Badge>}
              {row.is_supplier && <Badge color="yellow">Нийлүүлэгч</Badge>}
            </td>
          </tr>)}
        </tbody>
      </table>
      {!rows.length && <div className="hr-empty">{parties.isLoading ? 'Ачаалж байна…' : 'Харилцагч олдсонгүй'}</div>}
    </div>
    {total > PAGE_SIZE && <div className="crm-pager">
      <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} / {total}</span>
      <Btn disabled={page === 1} onClick={() => setPage(page - 1)}>Өмнөх</Btn>
      <Btn disabled={page * PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>Дараах</Btn>
    </div>}
    {importing && <ImportModal onClose={() => setImporting(false)} />}
    {bulk && <BulkActivityModal partyIds={[...selected]} lookups={lookups} onClose={() => setBulk(false)} onDone={() => { setBulk(false); setSelected(new Set()) }} />}
  </Card>
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<CRMImportResult | null>(null)
  const importer = useImportCRMParties()
  const run = async (dryRun: boolean) => {
    if (!file) { toast.error('Файл сонгоно уу'); return }
    try {
      const response = await importer.mutateAsync({ file, dryRun })
      setResult(response)
      if (!dryRun && response.created) { toast.success(`${response.created} харилцагч импортлолоо`); onClose() }
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title="Харилцагч импортлох" onClose={onClose}>
    <p className="crm-muted">Excel (.xlsx) эсвэл CSV файлыг загварын дагуу бөглөнө. <strong>Бүлэг</strong> баганад бүртгэлтэй бүлгийн нэрийг оруулна.</p>
    <div className="crm-actions" style={{ marginTop: 10 }}><div><Btn onClick={() => void downloadCRMImportTemplate().catch((error) => toast.error(crmErrorText(error)))}><Download size={14} />Загвар татах</Btn></div></div>
    <Field label="Файл"><input type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setResult(null) }} /></Field>
    {result && <div className="crm-import-result">
      <div>Нийт мөр: {result.total_rows} · Зөв: <strong>{result.valid_rows}</strong> · Алдаатай: <strong className={result.errors.length ? 'crm-overdue' : ''}>{result.errors.length}</strong></div>
      {result.errors.slice(0, 20).map((row) => <div key={`e${row.row}`} className="crm-overdue">{row.row}-р мөр: {row.message}</div>)}
      {result.warnings.slice(0, 20).map((row) => <div key={`w${row.row}`} className="crm-duplicate">{row.row}-р мөр: {row.message}</div>)}
    </div>}
    <div className="crm-actions"><div /><div>
      <Btn onClick={() => void run(true)} disabled={!file || importer.isPending}>Шалгах</Btn>
      <Btn variant="primary" onClick={() => void run(false)} disabled={!result || result.errors.length > 0 || !result.valid_rows || importer.isPending}>Импортлох</Btn>
    </div></div>
  </Modal>
}

function BulkActivityModal({ partyIds, lookups, onClose, onDone }: { partyIds: number[]; lookups: CRMLookups; onClose: () => void; onDone: () => void }) {
  const [subject, setSubject] = useState('')
  const [typeId, setTypeId] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [responsible, setResponsible] = useState('')
  const bulk = useBulkCRMActivities()
  const submit = async () => {
    if (!subject.trim()) { toast.error('Утга оруулна уу'); return }
    try {
      const result = await bulk.mutateAsync({ party_ids: partyIds, template: { subject, type_id: typeId ? Number(typeId) : null, due_at: dueAt ? new Date(dueAt).toISOString() : null, responsible_employee_id: responsible ? Number(responsible) : null } })
      toast.success(`${result.created} бүртгэл үүслээ`)
      onDone()
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={`${partyIds.length} харилцагчид харилцаа холбоо нэмэх`} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label="Утга" wide><TextInput value={subject} onChange={setSubject} placeholder="Жишээ: Шинэ жилийн мэндчилгээ илгээх" /></Field>
      <Field label="Төрөл"><NativeSelect value={typeId} onChange={setTypeId} options={lookups.activity_types.filter((row) => row.is_active).map((row) => ({ value: String(row.id), label: row.name }))} /></Field>
      <Field label="Биелэх хугацаа"><TextInput type="datetime-local" value={dueAt} onChange={setDueAt} /></Field>
      <Field label="Хариуцагч" hint="Хоосон бол та"><NativeSelect value={responsible} onChange={setResponsible} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} /></Field>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>Болих</Btn><Btn variant="primary" onClick={() => void submit()} disabled={bulk.isPending}>Үүсгэх</Btn></div></div>
  </Modal>
}
