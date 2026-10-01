import { createElement, useState } from 'react'
import { createPortal } from 'react-dom'
import toast from 'react-hot-toast'
import { Contact, ExternalLink, FileCheck2, FileText, History as HistoryIcon, Info, Landmark, MessagesSquare, Paperclip, Pencil, Plus, RefreshCw, Trash2, X, type LucideIcon } from 'lucide-react'
import {
  downloadCRMFile, useCRMFiles, useCRMParty, useCRMPartyDocuments, useCRMPartyHistory, useDeleteCRMBankAccount, useDeleteCRMContact, useDeleteCRMFile,
  useDeleteCRMParty, useRefreshCRMTaxStatus, useSaveCRMBankAccount, useSaveCRMContact, useUploadCRMFile,
  type CRMActivity, type CRMBankAccount, type CRMCapabilities, type CRMContact, type CRMLookups, type CRMPartyDetail,
} from '../../api/crm'
import { useContractList } from '../../api/enterprise'
import { Badge, Btn, Modal } from '../ui'
import { ActivitiesPanel } from './ActivitiesPanel'
import { CheckField, Field, TextInput, crmErrorText, formatDate, formatDateTime, formatMoney } from './shared'

type Tab = 'overview' | 'contacts' | 'bank' | 'activities' | 'contracts' | 'documents' | 'files' | 'history'
const TAB_LABELS: Record<Tab, string> = { overview: 'Ерөнхий', contacts: 'Холбоо барих', bank: 'Банкны данс', activities: 'Харилцаа холбоо', contracts: 'Гэрээ', documents: 'Баримтууд', files: 'Файл', history: 'Лог' }
const TAB_ICONS: Record<Tab, LucideIcon> = { overview: Info, contacts: Contact, bank: Landmark, activities: MessagesSquare, contracts: FileText, documents: FileCheck2, files: Paperclip, history: HistoryIcon }
const CONTRACT_STATUS_LABELS: Record<string, string> = { DRAFT: 'Ноорог', PENDING_REVIEW: 'Хянагдаж байна', CHANGES_REQUESTED: 'Засвар шаардлагатай', APPROVED: 'Баталгаажсан', REJECTED: 'Буцаагдсан', SIGNED_AND_STAMPED: 'Гарын үсэг зурсан' }
const FIELD_LABELS: Record<string, string> = {
  code: 'Код', name: 'Нэр', registry_no: 'РД', tax_id: 'ТТД', group_id: 'Бүлэг', price_list_id: 'Үнийн жагсаалт', sales_discount_pct: 'Борлуулалт %',
  customer_since: 'Харилцагч болсон', inactive_since: 'Идэвхгүй болсон', status: 'Төлөв', responsible_employee_id: 'Хариуцагч', parent_party_id: 'Толгой харилцагч',
  vat_payer: 'НӨАТ', city_tax_payer: 'НХАТ', is_customer: 'Худалдан авагч', is_supplier: 'Нийлүүлэгч', payment_term_id: 'Төлбөрийн нөхцөл', credit_limit: 'Лимит',
}
const ACTION_LABELS: Record<string, string> = { created: 'Бүртгэсэн', updated: 'Өөрчилсөн', deleted: 'Устгасан', tax_status_refreshed: 'Татварын төлөв шинэчилсэн', contact_added: 'Холбоо барих нэмсэн', contact_removed: 'Холбоо барих хассан', bank_account_added: 'Данс нэмсэн', bank_account_updated: 'Данс өөрчилсөн', bank_account_removed: 'Данс хассан' }

export function CustomerDetail({ partyId, lookups, capabilities, isManager, onClose, onEdit, onOpenActivity, onNewActivity, onOpenParty }: {
  partyId: number
  lookups: CRMLookups
  capabilities: CRMCapabilities
  isManager: boolean
  onClose: () => void
  onEdit: (party: CRMPartyDetail) => void
  onOpenActivity: (activity: CRMActivity) => void
  onNewActivity: (party: CRMPartyDetail) => void
  onOpenParty: (partyId: number) => void
}) {
  const [tab, setTab] = useState<Tab>('overview')
  const party = useCRMParty(partyId)
  const refreshTax = useRefreshCRMTaxStatus()
  const remove = useDeleteCRMParty()
  const data = party.data
  const canEdit = capabilities.parties.edit

  const refresh = async () => {
    try {
      const result = await refreshTax.mutateAsync(partyId)
      toast.success(result.changed.length ? `Шинэчлэгдлээ: ${result.changed.map((key) => FIELD_LABELS[key] || key).join(', ')}` : 'Татварын мэдээлэл өөрчлөгдөөгүй')
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  const destroy = async () => {
    if (!data || !window.confirm(`${data.name}-ийг устгах уу?`)) return
    try { await remove.mutateAsync(data.id); toast.success('Устгалаа'); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }

  return createPortal(<div className="hr-drawer-backdrop" onClick={onClose}>
    <aside className="hr-drawer crm-detail" role="dialog" aria-label="Харилцагчийн дэлгэрэнгүй" onClick={(event) => event.stopPropagation()}>
      {!data ? <div className="hr-empty">{party.isError ? crmErrorText(party.error) : 'Ачаалж байна…'}</div> : <>
        <header>
          <div>
            <span className="eyebrow">ХАРИЛЦАГЧ · {data.code}</span>
            <h2>{data.name}</h2>
            <p>{[data.business_name, data.tax_id && `ТТД ${data.tax_id}`, data.registry_no && `РД ${data.registry_no}`].filter(Boolean).join(' · ') || '—'}</p>
            <div className="hr-drawer-badges crm-checks">
              <Badge color={data.is_active ? 'green' : 'muted'}>{data.is_active ? 'Идэвхтэй' : 'Идэвхгүй'}</Badge>
              {data.party_type === 'prospect' && <Badge color="purple">Lead</Badge>}
              {data.is_customer && <Badge color="blue">Худалдан авагч</Badge>}
              {data.is_supplier && <Badge color="yellow">Нийлүүлэгч</Badge>}
              {data.duplicate_tax_id && <Badge color="red">ТТД давхардсан</Badge>}
            </div>
          </div>
          <div className="hr-drawer-header-actions">
            {canEdit && <button onClick={() => onEdit(data)} aria-label="Засах"><Pencil size={16} /></button>}
            <button onClick={onClose} aria-label="Хаах"><X size={18} /></button>
          </div>
        </header>

        <div className="crm-stats">
          <div><small>Нээлттэй</small><strong>{data.stats.activities_open}</strong></div>
          <div><small>Хэтэрсэн</small><strong className={data.stats.activities_overdue ? 'crm-overdue' : ''}>{data.stats.activities_overdue}</strong></div>
          <div><small>Хүлээгдэж буй орлого</small><strong>{formatMoney(data.stats.expected_revenue_open, data.currency)}</strong></div>
          <div><small>Сүүлийн харилцаа</small><strong>{formatDate(data.stats.last_activity_at)}</strong></div>
        </div>

        <nav className="page-tabs crm-detail-tabs"><div className="page-tabs-list">{(Object.keys(TAB_LABELS) as Tab[]).map((key) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{createElement(TAB_ICONS[key], { size: 15 })}{TAB_LABELS[key]}</button>)}</div></nav>

        {tab === 'overview' && <Overview data={data} onOpenParty={onOpenParty} onRefresh={canEdit ? refresh : undefined} refreshing={refreshTax.isPending} onDelete={capabilities.parties.archive ? destroy : undefined} />}
        {tab === 'contacts' && <Contacts party={data} canEdit={canEdit} />}
        {tab === 'bank' && <BankAccounts party={data} canEdit={canEdit} />}
        {tab === 'activities' && <ActivitiesPanel compact lookups={lookups} capabilities={capabilities} isManager={isManager} partyId={data.id} onOpen={onOpenActivity} onCreate={() => onNewActivity(data)} />}
        {tab === 'contracts' && <Contracts partyId={data.id} />}
        {tab === 'documents' && <Documents party={data} />}
        {tab === 'files' && <Files partyId={data.id} canEdit={canEdit} />}
        {tab === 'history' && <History partyId={data.id} lookups={lookups} />}
      </>}
    </aside>
  </div>, document.body)
}

function Overview({ data, onOpenParty, onRefresh, refreshing, onDelete }: { data: CRMPartyDetail; onOpenParty: (id: number) => void; onRefresh?: () => void; refreshing: boolean; onDelete?: () => void }) {
  return <>
    <section className="hr-drawer-section"><h3>Ерөнхий мэдээлэл</h3><dl>
      <dt>Бүлэг</dt><dd>{data.group_name || '—'}</dd>
      <dt>Хариуцагч</dt><dd>{data.responsible_name || '—'}</dd>
      <dt>Толгой харилцагч</dt><dd>{data.parent_party_id ? <button className="crm-link" onClick={() => onOpenParty(data.parent_party_id!)}>{data.parent_name}</button> : '—'}{data.settle_via_parent && ' (тооцоо толгойгоор)'}</dd>
      <dt>Харилцагч болсон</dt><dd>{formatDate(data.customer_since)}</dd>
      {data.inactive_since && <><dt>Идэвхгүй болсон</dt><dd>{formatDate(data.inactive_since)}</dd></>}
      <dt>Нэр /EN/</dt><dd>{data.name_en || '—'}</dd>
      <dt>Tags</dt><dd>{data.tags.length ? data.tags.join(', ') : '—'}</dd>
    </dl></section>
    <section className="hr-drawer-section"><h3>Холбоо барих</h3><dl>
      <dt>Утас</dt><dd>{data.phone || '—'}</dd>
      <dt>Mail</dt><dd>{data.email || '—'}</dd>
      <dt>Web</dt><dd>{data.website ? <a href={data.website.startsWith('http') ? data.website : `https://${data.website}`} target="_blank" rel="noreferrer">{data.website}</a> : '—'}</dd>
      <dt>Хаяг</dt><dd>{data.legal_address || '—'}</dd>
      <dt>Байршил</dt><dd>{[data.location, data.informal_address].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>
    <section className="hr-drawer-section"><h3>Татвар ба тооцоо</h3><dl>
      <dt>НӨАТ / НХАТ</dt><dd>{data.vat_payer ? 'НӨАТ төлөгч' : 'НӨАТ төлөгч биш'} · {data.city_tax_payer ? 'НХАТ төлөгч' : 'НХАТ төлөгч биш'}{data.tax_status_checked_at && <span className="crm-muted"> · шалгасан {formatDate(data.tax_status_checked_at)}</span>}</dd>
      <dt>Төлбөрийн нөхцөл</dt><dd>{data.payment_term_name || '—'}</dd>
      <dt>Тооцооны лимит</dt><dd>{formatMoney(data.credit_limit, data.currency)}</dd>
      <dt>Тооцооны данс</dt><dd>{data.settlement_account_name || '—'}</dd>
      <dt>Үнийн жагсаалт</dt><dd>{data.price_list_name || '—'}</dd>
      <dt>Борлуулалт</dt><dd>{[data.sales_discount_pct && `${data.sales_discount_pct}% хөнгөлөлт`, data.sales_lead_days != null && `${data.sales_lead_days} хоногт`, data.sales_note].filter(Boolean).join(' · ') || '—'}</dd>
      <dt>Худалдан авалт</dt><dd>{[data.purchase_discount_pct && `${data.purchase_discount_pct}% хөнгөлөлт`, data.purchase_lead_days != null && `${data.purchase_lead_days} хоногт`, data.purchase_note].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>
    {data.children.length > 0 && <section className="hr-drawer-section"><h3>Салбарууд ({data.children.length})</h3>
      <div className="crm-list">{data.children.map((child) => <article key={child.id}><div><strong>{child.name}</strong><small>{child.code}</small></div><button className="secondary-action" onClick={() => onOpenParty(child.id)}>Нээх</button></article>)}</div>
      {data.group_stats && <p className="crm-muted">Нийт (салбаруудтай): {data.group_stats.activities_open} нээлттэй, {data.group_stats.activities_overdue} хэтэрсэн</p>}
    </section>}
    {data.links.length > 0 && <section className="hr-drawer-section"><h3>Линк</h3>
      <div className="crm-list">{data.links.map((link, index) => <article key={index}><div><strong>{link.label}</strong><small>{link.url}</small></div>{/^https?:/.test(link.url) && <a className="secondary-action" href={link.url} target="_blank" rel="noreferrer"><ExternalLink size={13} /></a>}</article>)}</div>
    </section>}
    <div className="crm-actions">
      <div>{onRefresh && (data.tax_id || data.registry_no) && <Btn onClick={onRefresh} disabled={refreshing}><RefreshCw size={14} />Татварын мэдээлэл шинэчлэх</Btn>}</div>
      <div>{onDelete && <Btn variant="danger" onClick={onDelete}><Trash2 size={14} />Устгах</Btn>}</div>
    </div>
  </>
}

function Contacts({ party, canEdit }: { party: CRMPartyDetail; canEdit: boolean }) {
  const [editing, setEditing] = useState<CRMContact | 'new' | null>(null)
  const remove = useDeleteCRMContact(party.id)
  return <>
    <div className="crm-list">
      {party.contacts.map((contact) => <article key={contact.id}>
        <div><strong>{contact.name}{contact.nickname && ` (${contact.nickname})`} {contact.is_default && <Badge color="blue">Үндсэн</Badge>} {!contact.is_active && <Badge color="muted">Идэвхгүй</Badge>}</strong>
          <small>{[contact.position, contact.phone, contact.email].filter(Boolean).join(' · ') || '—'}</small>{contact.note && <small>{contact.note}</small>}</div>
        {canEdit && <div className="crm-row-actions"><button onClick={() => setEditing(contact)} aria-label="Засах"><Pencil size={13} /></button><button aria-label="Устгах" onClick={() => { if (window.confirm(`${contact.name}-ийг хасах уу?`)) void remove.mutateAsync(contact.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button></div>}
      </article>)}
      {!party.contacts.length && <div className="hr-empty">Холбоо барих хүн бүртгээгүй</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />Холбоо барих нэмэх</Btn></div>}
    {editing && <ContactModal partyId={party.id} contact={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </>
}

function ContactModal({ partyId, contact, onClose }: { partyId: number; contact: CRMContact | null; onClose: () => void }) {
  const [form, setForm] = useState({ name: contact?.name ?? '', nickname: contact?.nickname ?? '', position: contact?.position ?? '', phone: contact?.phone ?? '', email: contact?.email ?? '', address: contact?.address ?? '', note: contact?.note ?? '', is_default: contact?.is_default ?? false, is_active: contact?.is_active ?? true })
  const save = useSaveCRMContact(partyId)
  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    if (!form.name.trim()) { toast.error('Нэр оруулна уу'); return }
    try { await save.mutateAsync(contact ? { id: contact.id, ...form } : form); toast.success('Хадгаллаа'); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={contact ? 'Холбоо барих засах' : 'Холбоо барих нэмэх'} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label="Нэр"><TextInput value={form.name} onChange={(value) => set('name', value)} /></Field>
      <Field label="Дууддаг нэр"><TextInput value={form.nickname} onChange={(value) => set('nickname', value)} /></Field>
      <Field label="Албан тушаал"><TextInput value={form.position} onChange={(value) => set('position', value)} /></Field>
      <Field label="Утас"><TextInput value={form.phone} onChange={(value) => set('phone', value)} /></Field>
      <Field label="Mail"><TextInput value={form.email} onChange={(value) => set('email', value)} type="email" /></Field>
      <Field label="Хаяг / social"><TextInput value={form.address} onChange={(value) => set('address', value)} /></Field>
      <Field label="Тайлбар" wide><TextInput value={form.note} onChange={(value) => set('note', value)} /></Field>
      <div className="crm-checks hr-form-wide"><CheckField label="Үндсэн (Default)" checked={form.is_default} onChange={(value) => set('is_default', value)} /><CheckField label="Идэвхтэй" checked={form.is_active} onChange={(value) => set('is_active', value)} /></div>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>Болих</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>Хадгалах</Btn></div></div>
  </Modal>
}

function BankAccounts({ party, canEdit }: { party: CRMPartyDetail; canEdit: boolean }) {
  const [editing, setEditing] = useState<CRMBankAccount | 'new' | null>(null)
  const remove = useDeleteCRMBankAccount(party.id)
  return <>
    <div className="crm-list">
      {party.bank_accounts.map((account) => <article key={account.id}>
        <div><strong>{account.bank_name} · {account.account_no} {account.is_default && <Badge color="blue">Үндсэн</Badge>} {!account.is_active && <Badge color="muted">Идэвхгүй</Badge>}</strong>
          <small>{[account.account_name, account.currency, account.iban_prefix && `IBAN ${account.iban_prefix}`, account.note].filter(Boolean).join(' · ')}</small></div>
        {canEdit && <div className="crm-row-actions"><button onClick={() => setEditing(account)} aria-label="Засах"><Pencil size={13} /></button><button aria-label="Устгах" onClick={() => { if (window.confirm('Дансыг устгах уу?')) void remove.mutateAsync(account.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button></div>}
      </article>)}
      {!party.bank_accounts.length && <div className="hr-empty">Банкны данс бүртгээгүй</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />Данс нэмэх</Btn></div>}
    {editing && <BankModal partyId={party.id} account={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </>
}

function BankModal({ partyId, account, onClose }: { partyId: number; account: CRMBankAccount | null; onClose: () => void }) {
  const [form, setForm] = useState({ bank_name: account?.bank_name ?? '', currency: account?.currency ?? 'MNT', iban_prefix: account?.iban_prefix ?? '', account_no: account?.account_no ?? '', account_name: account?.account_name ?? '', note: account?.note ?? '', is_default: account?.is_default ?? false, is_active: account?.is_active ?? true })
  const save = useSaveCRMBankAccount(partyId)
  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    if (!form.bank_name.trim() || !form.account_no.trim()) { toast.error('Банк болон дансны дугаар оруулна уу'); return }
    try { await save.mutateAsync(account ? { id: account.id, ...form } : form); toast.success('Хадгаллаа'); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={account ? 'Данс засах' : 'Банкны данс нэмэх'} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label="Банк"><TextInput value={form.bank_name} onChange={(value) => set('bank_name', value)} /></Field>
      <Field label="Валют"><TextInput value={form.currency} onChange={(value) => set('currency', value.toUpperCase().slice(0, 3))} /></Field>
      <Field label="Дансны дугаар"><TextInput value={form.account_no} onChange={(value) => set('account_no', value)} /></Field>
      <Field label="IBAN prefix"><TextInput value={form.iban_prefix} onChange={(value) => set('iban_prefix', value)} /></Field>
      <Field label="Дансны нэр" wide><TextInput value={form.account_name} onChange={(value) => set('account_name', value)} /></Field>
      <Field label="Тайлбар" wide><TextInput value={form.note} onChange={(value) => set('note', value)} /></Field>
      <div className="crm-checks hr-form-wide"><CheckField label="Үндсэн (Default)" checked={form.is_default} onChange={(value) => set('is_default', value)} /><CheckField label="Идэвхтэй" checked={form.is_active} onChange={(value) => set('is_active', value)} /></div>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>Болих</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>Хадгалах</Btn></div></div>
  </Modal>
}

const DOCUMENT_LABELS: Record<string, string> = { quotation: 'Үнийн санал', sales_order: 'Борлуулалтын захиалга', delivery: 'Хүргэлт', sales_invoice: 'Нэхэмжлэх', sales_credit_note: 'Кредит нот', purchase_order: 'Худалдан авалтын захиалга', purchase_receipt: 'Бараа хүлээн авалт', purchase_invoice: 'Худалдан авалтын нэхэмжлэх', payment_entry: 'Төлбөр', lead: 'Lead', opportunity: 'Боломж' }

/** Contracts registered with this counterparty (d028); lists only the ones the viewer may open. */
function Contracts({ partyId }: { partyId: number }) {
  const contracts = useContractList('registry', { party_id: partyId })
  const rows = contracts.data?.items ?? []
  return <div className="crm-list">
    {rows.map((row) => <article key={row.public_id}>
      <div>
        <strong>{row.code ? `${row.code} · ` : ''}{row.title}</strong>
        <small>{[row.contract_number && `№${row.contract_number}`, CONTRACT_STATUS_LABELS[row.status] || row.status, row.signed_on && formatDate(row.signed_on), row.effective_end_on && `дуусах ${formatDate(row.effective_end_on)}`, row.is_active === false && 'идэвхгүй'].filter(Boolean).join(' · ')}</small>
      </div>
      <div className="crm-row-actions">
        {row.amount !== null && row.amount !== undefined && <strong>{formatMoney(row.amount, row.currency)}</strong>}
        <a className="secondary-action" href={`/contracts/${row.public_id}`} aria-label="Гэрээ нээх"><ExternalLink size={13} /></a>
      </div>
    </article>)}
    {!rows.length && <div className="hr-empty">{contracts.isLoading ? 'Ачаалж байна…' : 'Энэ харилцагчтай бүртгэлтэй гэрээ алга (эсвэл танд харах эрх байхгүй)'}</div>}
    <a className="secondary-action" style={{ width: 'fit-content' }} href={`/contracts?party=${partyId}`}>Гэрээний жагсаалтаас харах</a>
  </div>
}

function Documents({ party }: { party: CRMPartyDetail }) {
  const [includeChildren, setIncludeChildren] = useState(false)
  const documents = useCRMPartyDocuments(party.id, includeChildren)
  const rows = documents.data ?? []
  return <>
    {party.children.length > 0 && <CheckField label="Салбаруудын баримтыг оруулах" checked={includeChildren} onChange={setIncludeChildren} />}
    <div className="crm-list" style={{ marginTop: 10 }}>
      {rows.map((row) => <article key={row.id}>
        <div><strong>{DOCUMENT_LABELS[row.document_type] || row.document_type} · {row.number}</strong><small>{formatDate(row.posting_date)} · {row.status}{row.due_date && ` · төлөх ${formatDate(row.due_date)}`}</small></div>
        <div style={{ textAlign: 'right' }}><strong>{formatMoney(row.grand_total, row.currency)}</strong>{Number(row.outstanding_amount) > 0 && <small className="crm-overdue" style={{ display: 'block' }}>Үлдэгдэл {formatMoney(row.outstanding_amount, row.currency)}</small>}</div>
      </article>)}
      {!rows.length && <div className="hr-empty">{documents.isLoading ? 'Ачаалж байна…' : 'Холбоотой баримт алга'}</div>}
    </div>
  </>
}

function Files({ partyId, canEdit }: { partyId: number; canEdit: boolean }) {
  const files = useCRMFiles('parties', partyId)
  const upload = useUploadCRMFile('parties', partyId)
  const remove = useDeleteCRMFile()
  const rows = files.data ?? []
  return <div className="crm-list">
    {rows.map((file) => <article key={file.id}>
      <div><strong>{file.filename}</strong><small>{Math.ceil(file.size / 1024)} KB · {formatDateTime(file.created_at)}</small></div>
      <div className="crm-row-actions">
        <button onClick={() => void downloadCRMFile(file).catch((error) => toast.error(crmErrorText(error)))}>Татах</button>
        {canEdit && <button aria-label="Устгах" onClick={() => { if (window.confirm(`${file.filename}-ийг устгах уу?`)) void remove.mutateAsync(file.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button>}
      </div>
    </article>)}
    {!rows.length && <div className="hr-empty">Файл хавсаргаагүй</div>}
    {canEdit && <label className="secondary-action" style={{ cursor: 'pointer', width: 'fit-content' }}><Paperclip size={14} />Файл нэмэх
      <input type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload.mutateAsync(file).then(() => toast.success('Файл нэмлээ')).catch((error) => toast.error(crmErrorText(error))) }} />
    </label>}
  </div>
}

function History({ partyId, lookups }: { partyId: number; lookups: CRMLookups }) {
  const history = useCRMPartyHistory(partyId)
  const names: Record<string, Record<string, string>> = {
    group_id: Object.fromEntries(lookups.party_groups.map((row) => [String(row.id), row.name])),
    responsible_employee_id: Object.fromEntries(lookups.employees.map((row) => [String(row.id), row.name])),
    payment_term_id: Object.fromEntries(lookups.payment_terms.map((row) => [String(row.id), row.name])),
    price_list_id: Object.fromEntries(lookups.price_lists.map((row) => [String(row.id), row.name])),
  }
  const show = (key: string, value: unknown) => {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'boolean') return value ? 'Тийм' : 'Үгүй'
    return names[key]?.[String(value)] ?? String(value)
  }
  const rows = history.data ?? []
  return <div className="crm-list">
    {rows.map((row) => {
      const keys = Object.keys({ ...row.before, ...row.after }).filter((key) => key in FIELD_LABELS)
      return <article key={row.id}><div>
        <strong>{ACTION_LABELS[row.action] || row.action} · {row.actor_name || 'Систем'}</strong>
        <small>{formatDateTime(row.created_at)}</small>
        {row.action === 'updated' || row.action === 'tax_status_refreshed'
          ? keys.map((key) => <span className="crm-history-change" key={key}>{FIELD_LABELS[key]}: <code>{show(key, row.before[key])}</code> → <code>{show(key, row.after[key])}</code></span>)
          : Object.entries(row.after).filter(([key]) => !(key in FIELD_LABELS)).slice(0, 3).map(([key, value]) => <span className="crm-history-change" key={key}>{String(value)}</span>)}
      </div></article>
    })}
    {!rows.length && <div className="hr-empty">{history.isLoading ? 'Ачаалж байна…' : 'Өөрчлөлтийн түүх алга'}</div>}
  </div>
}
