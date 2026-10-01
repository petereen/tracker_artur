import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Download, FileUp, ListPlus, Search } from 'lucide-react'
import {
  downloadCRMImportTemplate, downloadCRMPartiesCsv, useBulkCRMActivities, useCRMParties, useImportCRMParties,
  type CRMCapabilities, type CRMImportResult, type CRMLookups, type CRMParty, type CRMPartyFilters,
} from '../../api/crm'
import { Badge, Btn, Card, Modal } from '../ui'
import { CheckField, Field, NativeSelect, TextInput, crmErrorText, formatDate } from './shared'
import { CreateButton } from '../CreateButton'

const PAGE_SIZE = 50

export function CustomersPanel({ lookups, capabilities, onOpen, onCreate }: { lookups: CRMLookups; capabilities: CRMCapabilities; onOpen: (party: CRMParty) => void; onCreate: () => void }) {
  const { t } = useTranslation()
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
      <label className="hr-search"><Search size={15} /><input value={search} onChange={(event) => reset(setSearch)(event.target.value)} placeholder={t('crm.customers.searchPlaceholder')} /></label>
      <NativeSelect value={kind === 'all' ? '' : kind} onChange={(value) => reset(setKind)((value || 'all') as typeof kind)} options={[{ value: 'customer', label: t('crm.common.customer') }, { value: 'supplier', label: t('crm.common.supplier') }, { value: 'prospect', label: t('crm.common.lead') }]} placeholder={t('crm.customers.allKinds')} />
      <NativeSelect value={groupId} onChange={reset(setGroupId)} options={lookups.party_groups.map((row) => ({ value: String(row.id), label: row.name }))} placeholder={t('crm.customers.allGroups')} />
      <NativeSelect value={responsible} onChange={reset(setResponsible)} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} placeholder={t('crm.customers.allResponsible')} />
      {capabilities.parties.create ? <CreateButton label={t('crm.customers.new')} onClick={onCreate} /> : <span />}
    </div>
    <div className="crm-toolbar-flags">
      <NativeSelect value={active} onChange={(value) => reset(setActive)(value as typeof active)} options={[{ value: 'active', label: t('crm.common.active') }, { value: 'inactive', label: t('crm.common.inactive') }]} placeholder={t('crm.customers.stateAny')} />
      <CheckField label={t('crm.customers.duplicatesOnly')} checked={duplicatesOnly} onChange={reset(setDuplicatesOnly)} />
      <Btn onClick={() => void downloadCRMPartiesCsv(filters).catch((error) => toast.error(crmErrorText(error)))}><Download size={14} />{t('crm.customers.export')}</Btn>
      {capabilities.parties.create && <Btn onClick={() => setImporting(true)}><FileUp size={14} />{t('crm.customers.import')}</Btn>}
      {capabilities.activities.create && selected.size > 0 && <Btn onClick={() => setBulk(true)}><ListPlus size={14} />{t('crm.customers.bulkAdd', { n: selected.size })}</Btn>}
    </div>
    <div className="crm-table">
      <table>
        <thead><tr>{capabilities.activities.create && <th />}<th>{t('crm.common.code')}</th><th>{t('crm.common.name')}</th><th>{t('crm.customers.colTax')}</th><th>{t('crm.common.group')}</th><th>{t('crm.common.responsible')}</th><th>{t('crm.common.phone')}</th><th>{t('crm.customers.colSince')}</th><th>{t('crm.common.status')}</th></tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.id} onClick={() => onOpen(row)}>
            {capabilities.activities.create && <td onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={t('crm.customers.selectRow', { name: row.name })} checked={selected.has(row.id)} onChange={() => toggle(row.id)} /></td>}
            <td>{row.code}</td>
            <td><div className="crm-subject"><strong className={row.duplicate_name ? 'crm-duplicate' : ''}>{row.name}</strong>{(row.business_name || row.parent_name) && <small>{[row.business_name, row.parent_name && `↳ ${row.parent_name}`].filter(Boolean).join(' · ')}</small>}</div></td>
            <td className={row.duplicate_tax_id ? 'crm-duplicate' : ''}>{[row.tax_id, row.registry_no].filter(Boolean).join(' / ') || '—'}</td>
            <td>{row.group_name || '—'}</td>
            <td>{row.responsible_name || '—'}</td>
            <td>{row.phone || '—'}</td>
            <td>{formatDate(row.customer_since)}</td>
            <td className="crm-checks">
              {row.is_active ? <Badge color="green">{t('crm.common.active')}</Badge> : <Badge color="muted">{t('crm.common.inactive')}</Badge>}
              {row.party_type === 'prospect' && <Badge color="purple">{t('crm.common.lead')}</Badge>}
              {row.is_supplier && <Badge color="yellow">{t('crm.common.supplier')}</Badge>}
            </td>
          </tr>)}
        </tbody>
      </table>
      {!rows.length && <div className="hr-empty">{parties.isLoading ? t('crm.common.loading') : t('crm.customers.notFound')}</div>}
    </div>
    {total > PAGE_SIZE && <div className="crm-pager">
      <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} / {total}</span>
      <Btn disabled={page === 1} onClick={() => setPage(page - 1)}>{t('crm.common.prev')}</Btn>
      <Btn disabled={page * PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>{t('crm.common.next')}</Btn>
    </div>}
    {importing && <ImportModal onClose={() => setImporting(false)} />}
    {bulk && <BulkActivityModal partyIds={[...selected]} lookups={lookups} onClose={() => setBulk(false)} onDone={() => { setBulk(false); setSelected(new Set()) }} />}
  </Card>
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<CRMImportResult | null>(null)
  const importer = useImportCRMParties()
  const run = async (dryRun: boolean) => {
    if (!file) { toast.error(t('crm.import.selectFile')); return }
    try {
      const response = await importer.mutateAsync({ file, dryRun })
      setResult(response)
      if (!dryRun && response.created) { toast.success(t('crm.import.done', { n: response.created })); onClose() }
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={t('crm.import.title')} onClose={onClose}>
    <p className="crm-muted">{t('crm.import.hintBefore')} <strong>{t('crm.common.group')}</strong> {t('crm.import.hintAfter')}</p>
    <div className="crm-actions" style={{ marginTop: 10 }}><div><Btn onClick={() => void downloadCRMImportTemplate().catch((error) => toast.error(crmErrorText(error)))}><Download size={14} />{t('crm.import.template')}</Btn></div></div>
    <Field label={t('crm.import.file')}><input type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setResult(null) }} /></Field>
    {result && <div className="crm-import-result">
      <div>{t('crm.import.total', { n: result.total_rows })} · {t('crm.import.valid')} <strong>{result.valid_rows}</strong> · {t('crm.import.invalid')} <strong className={result.errors.length ? 'crm-overdue' : ''}>{result.errors.length}</strong></div>
      {result.errors.slice(0, 20).map((row) => <div key={`e${row.row}`} className="crm-overdue">{t('crm.import.row', { n: row.row, message: row.message })}</div>)}
      {result.warnings.slice(0, 20).map((row) => <div key={`w${row.row}`} className="crm-duplicate">{t('crm.import.row', { n: row.row, message: row.message })}</div>)}
    </div>}
    <div className="crm-actions"><div /><div>
      <Btn onClick={() => void run(true)} disabled={!file || importer.isPending}>{t('crm.import.check')}</Btn>
      <Btn variant="primary" onClick={() => void run(false)} disabled={!result || result.errors.length > 0 || !result.valid_rows || importer.isPending}>{t('crm.import.run')}</Btn>
    </div></div>
  </Modal>
}

function BulkActivityModal({ partyIds, lookups, onClose, onDone }: { partyIds: number[]; lookups: CRMLookups; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  const [subject, setSubject] = useState('')
  const [typeId, setTypeId] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [responsible, setResponsible] = useState('')
  const bulk = useBulkCRMActivities()
  const submit = async () => {
    if (!subject.trim()) { toast.error(t('crm.common.subjectRequired')); return }
    try {
      const result = await bulk.mutateAsync({ party_ids: partyIds, template: { subject, type_id: typeId ? Number(typeId) : null, due_at: dueAt ? new Date(dueAt).toISOString() : null, responsible_employee_id: responsible ? Number(responsible) : null } })
      toast.success(t('crm.bulk.created', { n: result.created }))
      onDone()
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={t('crm.bulk.title', { n: partyIds.length })} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label={t('crm.common.subject')} wide><TextInput value={subject} onChange={setSubject} placeholder={t('crm.bulk.subjectPlaceholder')} /></Field>
      <Field label={t('crm.common.type')}><NativeSelect value={typeId} onChange={setTypeId} options={lookups.activity_types.filter((row) => row.is_active).map((row) => ({ value: String(row.id), label: row.name }))} /></Field>
      <Field label={t('crm.common.dueDate')}><TextInput type="datetime-local" value={dueAt} onChange={setDueAt} /></Field>
      <Field label={t('crm.common.responsible')} hint={t('crm.common.responsibleHint')}><NativeSelect value={responsible} onChange={setResponsible} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} /></Field>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>{t('crm.common.cancel')}</Btn><Btn variant="primary" onClick={() => void submit()} disabled={bulk.isPending}>{t('crm.common.create')}</Btn></div></div>
  </Modal>
}
