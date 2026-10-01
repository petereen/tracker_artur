import { createElement, useState } from 'react'
import { createPortal } from 'react-dom'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Contact, ExternalLink, FileCheck2, FileText, History as HistoryIcon, Info, Landmark, MessagesSquare, Paperclip, Pencil, Plus, RefreshCw, Trash2, X, type LucideIcon } from 'lucide-react'
import {
  downloadCRMFile, useCRMFiles, useCRMParty, useCRMPartyDocuments, useCRMPartyHistory, useDeleteCRMBankAccount, useDeleteCRMContact, useDeleteCRMFile,
  useDeleteCRMParty, useRefreshCRMTaxStatus, useSaveCRMBankAccount, useSaveCRMContact, useUploadCRMFile,
  type CRMActivity, type CRMBankAccount, type CRMCapabilities, type CRMContact, type CRMLookups, type CRMPartyDetail,
} from '../../api/crm'
import { useContractList } from '../../api/enterprise'
import { labelMap, labelOr } from '../../utils/labelMap'
import { Badge, Btn, Modal } from '../ui'
import { ActivitiesPanel } from './ActivitiesPanel'
import { CheckField, Field, TextInput, crmErrorText, formatDate, formatDateTime, formatMoney } from './shared'

type Tab = 'overview' | 'contacts' | 'bank' | 'activities' | 'contracts' | 'documents' | 'files' | 'history'
const TAB_KEYS: Tab[] = ['overview', 'contacts', 'bank', 'activities', 'contracts', 'documents', 'files', 'history']
const TAB_ICONS: Record<Tab, LucideIcon> = { overview: Info, contacts: Contact, bank: Landmark, activities: MessagesSquare, contracts: FileText, documents: FileCheck2, files: Paperclip, history: HistoryIcon }
const FIELD_KEYS = ['code', 'name', 'registry_no', 'tax_id', 'group_id', 'price_list_id', 'sales_discount_pct', 'customer_since', 'inactive_since', 'status', 'responsible_employee_id', 'parent_party_id', 'vat_payer', 'city_tax_payer', 'is_customer', 'is_supplier', 'payment_term_id', 'credit_limit'] as const
const FIELD_LABELS = labelMap<(typeof FIELD_KEYS)[number]>('crm.detail.field', FIELD_KEYS)

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
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('overview')
  const party = useCRMParty(partyId)
  const refreshTax = useRefreshCRMTaxStatus()
  const remove = useDeleteCRMParty()
  const data = party.data
  const canEdit = capabilities.parties.edit

  const refresh = async () => {
    try {
      const result = await refreshTax.mutateAsync(partyId)
      toast.success(result.changed.length ? t('crm.detail.refreshed', { fields: result.changed.map((key) => labelOr('crm.detail.field', key)).join(', ') }) : t('crm.detail.taxUnchanged'))
    } catch (error) { toast.error(crmErrorText(error)) }
  }
  const destroy = async () => {
    if (!data || !window.confirm(t('crm.detail.confirmDelete', { name: data.name }))) return
    try { await remove.mutateAsync(data.id); toast.success(t('crm.common.deleted')); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }

  return createPortal(<div className="hr-drawer-backdrop" onClick={onClose}>
    <aside className="hr-drawer crm-detail" role="dialog" aria-label={t('crm.detail.ariaDialog')} onClick={(event) => event.stopPropagation()}>
      {!data ? <div className="hr-empty">{party.isError ? crmErrorText(party.error) : t('crm.common.loading')}</div> : <>
        <header>
          <div>
            <span className="eyebrow">{t('crm.detail.eyebrow', { code: data.code })}</span>
            <h2>{data.name}</h2>
            <p>{[data.business_name, data.tax_id && t('crm.common.taxIdShort', { id: data.tax_id }), data.registry_no && t('crm.common.regShort', { id: data.registry_no })].filter(Boolean).join(' · ') || '—'}</p>
            <div className="hr-drawer-badges crm-checks">
              <Badge color={data.is_active ? 'green' : 'muted'}>{data.is_active ? t('crm.common.active') : t('crm.common.inactive')}</Badge>
              {data.party_type === 'prospect' && <Badge color="purple">{t('crm.common.lead')}</Badge>}
              {data.is_customer && <Badge color="blue">{t('crm.common.customer')}</Badge>}
              {data.is_supplier && <Badge color="yellow">{t('crm.common.supplier')}</Badge>}
              {data.duplicate_tax_id && <Badge color="red">{t('crm.detail.dupTax')}</Badge>}
            </div>
          </div>
          <div className="hr-drawer-header-actions">
            {canEdit && <button onClick={() => onEdit(data)} aria-label={t('crm.common.edit')}><Pencil size={16} /></button>}
            <button onClick={onClose} aria-label={t('crm.common.close')}><X size={18} /></button>
          </div>
        </header>

        <div className="crm-stats">
          <div><small>{t('crm.detail.statOpen')}</small><strong>{data.stats.activities_open}</strong></div>
          <div><small>{t('crm.detail.statOverdue')}</small><strong className={data.stats.activities_overdue ? 'crm-overdue' : ''}>{data.stats.activities_overdue}</strong></div>
          <div><small>{t('crm.detail.statRevenue')}</small><strong>{formatMoney(data.stats.expected_revenue_open, data.currency)}</strong></div>
          <div><small>{t('crm.detail.statLast')}</small><strong>{formatDate(data.stats.last_activity_at)}</strong></div>
        </div>

        <nav className="page-tabs crm-detail-tabs"><div className="page-tabs-list">{TAB_KEYS.map((key) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{createElement(TAB_ICONS[key], { size: 15 })}{t(`crm.detail.tab.${key}`)}</button>)}</div></nav>

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
  const { t } = useTranslation()
  return <>
    <section className="hr-drawer-section"><h3>{t('crm.detail.sectionGeneral')}</h3><dl>
      <dt>{t('crm.common.group')}</dt><dd>{data.group_name || '—'}</dd>
      <dt>{t('crm.common.responsible')}</dt><dd>{data.responsible_name || '—'}</dd>
      <dt>{t('crm.party.parent')}</dt><dd>{data.parent_party_id ? <button className="crm-link" onClick={() => onOpenParty(data.parent_party_id!)}>{data.parent_name}</button> : '—'}{data.settle_via_parent && ` ${t('crm.detail.settledViaParent')}`}</dd>
      <dt>{t('crm.party.since')}</dt><dd>{formatDate(data.customer_since)}</dd>
      {data.inactive_since && <><dt>{t('crm.party.inactiveSince')}</dt><dd>{formatDate(data.inactive_since)}</dd></>}
      <dt>{t('crm.party.nameEn')}</dt><dd>{data.name_en || '—'}</dd>
      <dt>{t('crm.party.tags')}</dt><dd>{data.tags.length ? data.tags.join(', ') : '—'}</dd>
    </dl></section>
    <section className="hr-drawer-section"><h3>{t('crm.detail.tab.contacts')}</h3><dl>
      <dt>{t('crm.common.phone')}</dt><dd>{data.phone || '—'}</dd>
      <dt>{t('crm.common.mail')}</dt><dd>{data.email || '—'}</dd>
      <dt>{t('crm.common.web')}</dt><dd>{data.website ? <a href={data.website.startsWith('http') ? data.website : `https://${data.website}`} target="_blank" rel="noreferrer">{data.website}</a> : '—'}</dd>
      <dt>{t('crm.detail.address')}</dt><dd>{data.legal_address || '—'}</dd>
      <dt>{t('crm.party.location')}</dt><dd>{[data.location, data.informal_address].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>
    <section className="hr-drawer-section"><h3>{t('crm.detail.sectionTax')}</h3><dl>
      <dt>{t('crm.detail.vatCity')}</dt><dd>{data.vat_payer ? t('crm.detail.vatYes') : t('crm.detail.vatNo')} · {data.city_tax_payer ? t('crm.detail.cityYes') : t('crm.detail.cityNo')}{data.tax_status_checked_at && <span className="crm-muted"> · {t('crm.detail.checked', { date: formatDate(data.tax_status_checked_at) })}</span>}</dd>
      <dt>{t('crm.party.paymentTerm')}</dt><dd>{data.payment_term_name || '—'}</dd>
      <dt>{t('crm.party.creditLimit')}</dt><dd>{formatMoney(data.credit_limit, data.currency)}</dd>
      <dt>{t('crm.party.settlementAccount')}</dt><dd>{data.settlement_account_name || '—'}</dd>
      <dt>{t('crm.party.priceList')}</dt><dd>{data.price_list_name || '—'}</dd>
      <dt>{t('crm.detail.sales')}</dt><dd>{[data.sales_discount_pct && t('crm.detail.discount', { pct: data.sales_discount_pct }), data.sales_lead_days != null && t('crm.detail.leadDays', { n: data.sales_lead_days }), data.sales_note].filter(Boolean).join(' · ') || '—'}</dd>
      <dt>{t('crm.detail.purchases')}</dt><dd>{[data.purchase_discount_pct && t('crm.detail.discount', { pct: data.purchase_discount_pct }), data.purchase_lead_days != null && t('crm.detail.leadDays', { n: data.purchase_lead_days }), data.purchase_note].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>
    {data.children.length > 0 && <section className="hr-drawer-section"><h3>{t('crm.detail.branches', { n: data.children.length })}</h3>
      <div className="crm-list">{data.children.map((child) => <article key={child.id}><div><strong>{child.name}</strong><small>{child.code}</small></div><button className="secondary-action" onClick={() => onOpenParty(child.id)}>{t('crm.detail.open')}</button></article>)}</div>
      {data.group_stats && <p className="crm-muted">{t('crm.detail.groupTotals', { open: data.group_stats.activities_open, overdue: data.group_stats.activities_overdue })}</p>}
    </section>}
    {data.links.length > 0 && <section className="hr-drawer-section"><h3>{t('crm.detail.links')}</h3>
      <div className="crm-list">{data.links.map((link, index) => <article key={index}><div><strong>{link.label}</strong><small>{link.url}</small></div>{/^https?:/.test(link.url) && <a className="secondary-action" href={link.url} target="_blank" rel="noreferrer"><ExternalLink size={13} /></a>}</article>)}</div>
    </section>}
    <div className="crm-actions">
      <div>{onRefresh && (data.tax_id || data.registry_no) && <Btn onClick={onRefresh} disabled={refreshing}><RefreshCw size={14} />{t('crm.detail.refreshTax')}</Btn>}</div>
      <div>{onDelete && <Btn variant="danger" onClick={onDelete}><Trash2 size={14} />{t('crm.common.delete')}</Btn>}</div>
    </div>
  </>
}

function Contacts({ party, canEdit }: { party: CRMPartyDetail; canEdit: boolean }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<CRMContact | 'new' | null>(null)
  const remove = useDeleteCRMContact(party.id)
  return <>
    <div className="crm-list">
      {party.contacts.map((contact) => <article key={contact.id}>
        <div><strong>{contact.name}{contact.nickname && ` (${contact.nickname})`} {contact.is_default && <Badge color="blue">{t('crm.common.main')}</Badge>} {!contact.is_active && <Badge color="muted">{t('crm.common.inactive')}</Badge>}</strong>
          <small>{[contact.position, contact.phone, contact.email].filter(Boolean).join(' · ') || '—'}</small>{contact.note && <small>{contact.note}</small>}</div>
        {canEdit && <div className="crm-row-actions"><button onClick={() => setEditing(contact)} aria-label={t('crm.common.edit')}><Pencil size={13} /></button><button aria-label={t('crm.common.delete')} onClick={() => { if (window.confirm(t('crm.detail.confirmRemove', { name: contact.name }))) void remove.mutateAsync(contact.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button></div>}
      </article>)}
      {!party.contacts.length && <div className="hr-empty">{t('crm.detail.noContacts')}</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />{t('crm.detail.addContact')}</Btn></div>}
    {editing && <ContactModal partyId={party.id} contact={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </>
}

function ContactModal({ partyId, contact, onClose }: { partyId: number; contact: CRMContact | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState({ name: contact?.name ?? '', nickname: contact?.nickname ?? '', position: contact?.position ?? '', phone: contact?.phone ?? '', email: contact?.email ?? '', address: contact?.address ?? '', note: contact?.note ?? '', is_default: contact?.is_default ?? false, is_active: contact?.is_active ?? true })
  const save = useSaveCRMContact(partyId)
  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    if (!form.name.trim()) { toast.error(t('crm.common.nameRequired')); return }
    try { await save.mutateAsync(contact ? { id: contact.id, ...form } : form); toast.success(t('crm.common.saved')); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={contact ? t('crm.detail.editContact') : t('crm.detail.addContact')} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label={t('crm.common.name')}><TextInput value={form.name} onChange={(value) => set('name', value)} /></Field>
      <Field label={t('crm.detail.nickname')}><TextInput value={form.nickname} onChange={(value) => set('nickname', value)} /></Field>
      <Field label={t('crm.detail.position')}><TextInput value={form.position} onChange={(value) => set('position', value)} /></Field>
      <Field label={t('crm.common.phone')}><TextInput value={form.phone} onChange={(value) => set('phone', value)} /></Field>
      <Field label={t('crm.common.mail')}><TextInput value={form.email} onChange={(value) => set('email', value)} type="email" /></Field>
      <Field label={t('crm.detail.addressSocial')}><TextInput value={form.address} onChange={(value) => set('address', value)} /></Field>
      <Field label={t('crm.common.note')} wide><TextInput value={form.note} onChange={(value) => set('note', value)} /></Field>
      <div className="crm-checks hr-form-wide"><CheckField label={t('crm.common.mainDefault')} checked={form.is_default} onChange={(value) => set('is_default', value)} /><CheckField label={t('crm.common.active')} checked={form.is_active} onChange={(value) => set('is_active', value)} /></div>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>{t('crm.common.cancel')}</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>{t('crm.common.save')}</Btn></div></div>
  </Modal>
}

function BankAccounts({ party, canEdit }: { party: CRMPartyDetail; canEdit: boolean }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<CRMBankAccount | 'new' | null>(null)
  const remove = useDeleteCRMBankAccount(party.id)
  return <>
    <div className="crm-list">
      {party.bank_accounts.map((account) => <article key={account.id}>
        <div><strong>{account.bank_name} · {account.account_no} {account.is_default && <Badge color="blue">{t('crm.common.main')}</Badge>} {!account.is_active && <Badge color="muted">{t('crm.common.inactive')}</Badge>}</strong>
          <small>{[account.account_name, account.currency, account.iban_prefix && `IBAN ${account.iban_prefix}`, account.note].filter(Boolean).join(' · ')}</small></div>
        {canEdit && <div className="crm-row-actions"><button onClick={() => setEditing(account)} aria-label={t('crm.common.edit')}><Pencil size={13} /></button><button aria-label={t('crm.common.delete')} onClick={() => { if (window.confirm(t('crm.detail.confirmDeleteBank'))) void remove.mutateAsync(account.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button></div>}
      </article>)}
      {!party.bank_accounts.length && <div className="hr-empty">{t('crm.detail.noBank')}</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />{t('crm.detail.addBank')}</Btn></div>}
    {editing && <BankModal partyId={party.id} account={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </>
}

function BankModal({ partyId, account, onClose }: { partyId: number; account: CRMBankAccount | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState({ bank_name: account?.bank_name ?? '', currency: account?.currency ?? 'MNT', iban_prefix: account?.iban_prefix ?? '', account_no: account?.account_no ?? '', account_name: account?.account_name ?? '', note: account?.note ?? '', is_default: account?.is_default ?? false, is_active: account?.is_active ?? true })
  const save = useSaveCRMBankAccount(partyId)
  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    if (!form.bank_name.trim() || !form.account_no.trim()) { toast.error(t('crm.detail.bankRequired')); return }
    try { await save.mutateAsync(account ? { id: account.id, ...form } : form); toast.success(t('crm.common.saved')); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={account ? t('crm.detail.editBank') : t('crm.detail.newBank')} onClose={onClose}>
    <div className="hr-form-grid">
      <Field label={t('crm.detail.bank')}><TextInput value={form.bank_name} onChange={(value) => set('bank_name', value)} /></Field>
      <Field label={t('crm.common.currency')}><TextInput value={form.currency} onChange={(value) => set('currency', value.toUpperCase().slice(0, 3))} /></Field>
      <Field label={t('crm.detail.accountNo')}><TextInput value={form.account_no} onChange={(value) => set('account_no', value)} /></Field>
      <Field label={t('crm.detail.ibanPrefix')}><TextInput value={form.iban_prefix} onChange={(value) => set('iban_prefix', value)} /></Field>
      <Field label={t('crm.detail.accountName')} wide><TextInput value={form.account_name} onChange={(value) => set('account_name', value)} /></Field>
      <Field label={t('crm.common.note')} wide><TextInput value={form.note} onChange={(value) => set('note', value)} /></Field>
      <div className="crm-checks hr-form-wide"><CheckField label={t('crm.common.mainDefault')} checked={form.is_default} onChange={(value) => set('is_default', value)} /><CheckField label={t('crm.common.active')} checked={form.is_active} onChange={(value) => set('is_active', value)} /></div>
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>{t('crm.common.cancel')}</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>{t('crm.common.save')}</Btn></div></div>
  </Modal>
}

/** Contracts registered with this counterparty (d028); lists only the ones the viewer may open. */
function Contracts({ partyId }: { partyId: number }) {
  const { t } = useTranslation()
  const contracts = useContractList('registry', { party_id: partyId })
  const rows = contracts.data?.items ?? []
  return <div className="crm-list">
    {rows.map((row) => <article key={row.public_id}>
      <div>
        <strong>{row.code ? `${row.code} · ` : ''}{row.title}</strong>
        <small>{[row.contract_number && `№${row.contract_number}`, labelOr('contracts.status', row.status), row.signed_on && formatDate(row.signed_on), row.effective_end_on && t('crm.detail.contractEnds', { date: formatDate(row.effective_end_on) }), row.is_active === false && t('crm.detail.contractInactive')].filter(Boolean).join(' · ')}</small>
      </div>
      <div className="crm-row-actions">
        {row.amount !== null && row.amount !== undefined && <strong>{formatMoney(row.amount, row.currency)}</strong>}
        <a className="secondary-action" href={`/contracts/${row.public_id}`} aria-label={t('crm.detail.openContract')}><ExternalLink size={13} /></a>
      </div>
    </article>)}
    {!rows.length && <div className="hr-empty">{contracts.isLoading ? t('crm.common.loading') : t('crm.detail.noContracts')}</div>}
    <a className="secondary-action" style={{ width: 'fit-content' }} href={`/contracts?party=${partyId}`}>{t('crm.detail.allContracts')}</a>
  </div>
}

function Documents({ party }: { party: CRMPartyDetail }) {
  const { t } = useTranslation()
  const [includeChildren, setIncludeChildren] = useState(false)
  const documents = useCRMPartyDocuments(party.id, includeChildren)
  const rows = documents.data ?? []
  return <>
    {party.children.length > 0 && <CheckField label={t('crm.detail.includeBranchDocs')} checked={includeChildren} onChange={setIncludeChildren} />}
    <div className="crm-list" style={{ marginTop: 10 }}>
      {rows.map((row) => <article key={row.id}>
        <div><strong>{labelOr('crm.detail.doc', row.document_type)} · {row.number}</strong><small>{formatDate(row.posting_date)} · {row.status}{row.due_date && ` · ${t('crm.detail.payBy', { date: formatDate(row.due_date) })}`}</small></div>
        <div style={{ textAlign: 'right' }}><strong>{formatMoney(row.grand_total, row.currency)}</strong>{Number(row.outstanding_amount) > 0 && <small className="crm-overdue" style={{ display: 'block' }}>{t('crm.detail.outstanding', { amount: formatMoney(row.outstanding_amount, row.currency) })}</small>}</div>
      </article>)}
      {!rows.length && <div className="hr-empty">{documents.isLoading ? t('crm.common.loading') : t('crm.detail.noDocuments')}</div>}
    </div>
  </>
}

function Files({ partyId, canEdit }: { partyId: number; canEdit: boolean }) {
  const { t } = useTranslation()
  const files = useCRMFiles('parties', partyId)
  const upload = useUploadCRMFile('parties', partyId)
  const remove = useDeleteCRMFile()
  const rows = files.data ?? []
  return <div className="crm-list">
    {rows.map((file) => <article key={file.id}>
      <div><strong>{file.filename}</strong><small>{t('crm.common.fileMeta', { size: Math.ceil(file.size / 1024), date: formatDateTime(file.created_at) })}</small></div>
      <div className="crm-row-actions">
        <button onClick={() => void downloadCRMFile(file).catch((error) => toast.error(crmErrorText(error)))}>{t('crm.common.download')}</button>
        {canEdit && <button aria-label={t('crm.common.delete')} onClick={() => { if (window.confirm(t('crm.detail.confirmDelete', { name: file.filename }))) void remove.mutateAsync(file.id).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button>}
      </div>
    </article>)}
    {!rows.length && <div className="hr-empty">{t('crm.common.noFiles')}</div>}
    {canEdit && <label className="secondary-action" style={{ cursor: 'pointer', width: 'fit-content' }}><Paperclip size={14} />{t('crm.common.addFile')}
      <input type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload.mutateAsync(file).then(() => toast.success(t('crm.common.fileAdded'))).catch((error) => toast.error(crmErrorText(error))) }} />
    </label>}
  </div>
}

function History({ partyId, lookups }: { partyId: number; lookups: CRMLookups }) {
  const { t } = useTranslation()
  const history = useCRMPartyHistory(partyId)
  const names: Record<string, Record<string, string>> = {
    group_id: Object.fromEntries(lookups.party_groups.map((row) => [String(row.id), row.name])),
    responsible_employee_id: Object.fromEntries(lookups.employees.map((row) => [String(row.id), row.name])),
    payment_term_id: Object.fromEntries(lookups.payment_terms.map((row) => [String(row.id), row.name])),
    price_list_id: Object.fromEntries(lookups.price_lists.map((row) => [String(row.id), row.name])),
  }
  const show = (key: string, value: unknown) => {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'boolean') return value ? t('crm.detail.yes') : t('crm.detail.no')
    return names[key]?.[String(value)] ?? String(value)
  }
  const rows = history.data ?? []
  return <div className="crm-list">
    {rows.map((row) => {
      const keys = Object.keys({ ...row.before, ...row.after }).filter((key) => key in FIELD_LABELS)
      return <article key={row.id}><div>
        <strong>{labelOr('crm.detail.action', row.action)} · {row.actor_name || t('crm.detail.system')}</strong>
        <small>{formatDateTime(row.created_at)}</small>
        {row.action === 'updated' || row.action === 'tax_status_refreshed'
          ? keys.map((key) => <span className="crm-history-change" key={key}>{FIELD_LABELS[key as keyof typeof FIELD_LABELS]}: <code>{show(key, row.before[key])}</code> → <code>{show(key, row.after[key])}</code></span>)
          : Object.entries(row.after).filter(([key]) => !(key in FIELD_LABELS)).slice(0, 3).map(([key, value]) => <span className="crm-history-change" key={key}>{String(value)}</span>)}
      </div></article>
    })}
    {!rows.length && <div className="hr-empty">{history.isLoading ? t('crm.common.loading') : t('crm.detail.noHistory')}</div>}
  </div>
}
