import { useState } from 'react'
import toast from 'react-hot-toast'
import { DownloadCloud, Plus, Trash2 } from 'lucide-react'
import { lookupCRMTaxpayer, useSaveCRMParty, type CRMLookups, type CRMParty, type CRMPartyInput, type CRMPartyLink, type CRMTaxpayer } from '../../api/crm'
import { Btn, Modal } from '../ui'
import { CheckField, Field, NativeSelect, PartyPicker, Section, TextArea, TextInput, crmErrorCode, crmErrorText } from './shared'

type Form = {
  code: string; name: string; name_en: string; business_name: string; registry_no: string; tax_id: string
  group_id: string; is_customer: boolean; is_supplier: boolean; is_individual: boolean; is_foreign: boolean; prospect: boolean
  responsible_employee_id: string; parent_party_id: number | null; parent_label: string | null; settle_via_parent: boolean
  customer_since: string; inactive_since: string; is_active: boolean
  phone: string; email: string; website: string; legal_address: string; location: string; informal_address: string; tags: string
  vat_payer: boolean; city_tax_payer: boolean
  settlement_account_id: string; price_list_id: string; credit_limit: string; currency: string; payment_term_id: string
  sales_discount_pct: string; sales_note: string; sales_lead_days: string; purchase_discount_pct: string; purchase_note: string; purchase_lead_days: string; delivery_terms: string
  links: CRMPartyLink[]
}

const str = (value: string | number | null | undefined) => (value === null || value === undefined ? '' : String(value))

function initial(party: CRMParty | null): Form {
  return {
    code: str(party?.code), name: str(party?.name), name_en: str(party?.name_en), business_name: str(party?.business_name), registry_no: str(party?.registry_no), tax_id: str(party?.tax_id),
    group_id: str(party?.group_id), is_customer: party?.is_customer ?? true, is_supplier: party?.is_supplier ?? false, is_individual: party?.is_individual ?? false, is_foreign: party?.is_foreign ?? false,
    prospect: party?.party_type === 'prospect', responsible_employee_id: str(party?.responsible_employee_id), parent_party_id: party?.parent_party_id ?? null, parent_label: party?.parent_name ?? null,
    settle_via_parent: party?.settle_via_parent ?? false, customer_since: str(party?.customer_since), inactive_since: str(party?.inactive_since), is_active: party?.is_active ?? true,
    phone: str(party?.phone), email: str(party?.email), website: str(party?.website), legal_address: str(party?.legal_address), location: str(party?.location), informal_address: str(party?.informal_address),
    tags: (party?.tags ?? []).join(', '), vat_payer: party?.vat_payer ?? false, city_tax_payer: party?.city_tax_payer ?? false,
    settlement_account_id: str(party?.settlement_account_id), price_list_id: str(party?.price_list_id), credit_limit: str(party?.credit_limit), currency: party?.currency ?? 'MNT',
    payment_term_id: str(party?.payment_term_id), sales_discount_pct: str(party?.sales_discount_pct), sales_note: str(party?.sales_note), sales_lead_days: str(party?.sales_lead_days),
    purchase_discount_pct: str(party?.purchase_discount_pct), purchase_note: str(party?.purchase_note), purchase_lead_days: str(party?.purchase_lead_days), delivery_terms: str(party?.delivery_terms),
    links: party?.links ?? [],
  }
}

const num = (value: string) => (value === '' ? null : Number(value))
const txt = (value: string) => value.trim() || null

export function CustomerForm({ party, lookups, onClose, onSaved }: { party: CRMParty | null; lookups: CRMLookups; onClose: () => void; onSaved?: (party: CRMParty) => void }) {
  const [form, setForm] = useState<Form>(() => initial(party))
  const [duplicates, setDuplicates] = useState<CRMTaxpayer['duplicates'] | null>(null)
  const [lookingUp, setLookingUp] = useState(false)
  const save = useSaveCRMParty()
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((current) => ({ ...current, [key]: value }))

  const lookup = async () => {
    if (!form.registry_no.trim() && !form.tax_id.trim()) { toast.error('РД эсвэл ТТД оруулна уу'); return }
    setLookingUp(true)
    try {
      const info = await lookupCRMTaxpayer({ registry_no: form.registry_no.trim() || undefined, tin: form.registry_no.trim() ? undefined : form.tax_id.trim() })
      setForm((current) => ({ ...current, tax_id: info.tin, name: current.name || info.name || '', vat_payer: info.vat_payer, city_tax_payer: info.city_tax_payer }))
      if (info.name && form.name && form.name !== info.name) toast(`Татварт бүртгэлтэй нэр: ${info.name}`)
      const others = info.duplicates.filter((row) => row.party_id !== party?.id)
      if (others.length) setDuplicates(others)
      toast.success('Татварын мэдээлэл татагдлаа')
    } catch (error) {
      toast.error(crmErrorText(error))
    } finally {
      setLookingUp(false)
    }
  }

  const submit = async (confirmDuplicate = false) => {
    if (!form.name.trim()) { toast.error('Нэр оруулна уу'); return }
    const payload: CRMPartyInput = {
      code: txt(form.code) ?? undefined, name: form.name.trim(), name_en: txt(form.name_en), business_name: txt(form.business_name), registry_no: txt(form.registry_no), tax_id: txt(form.tax_id),
      group_id: num(form.group_id), is_customer: form.is_customer, is_supplier: form.is_supplier, is_individual: form.is_individual, is_foreign: form.is_foreign,
      party_type: form.prospect ? 'prospect' : undefined, responsible_employee_id: num(form.responsible_employee_id), parent_party_id: form.parent_party_id, settle_via_parent: form.settle_via_parent,
      customer_since: txt(form.customer_since), inactive_since: txt(form.inactive_since), is_active: form.is_active,
      phone: txt(form.phone), email: txt(form.email), website: txt(form.website), legal_address: txt(form.legal_address), location: txt(form.location), informal_address: txt(form.informal_address),
      tags: form.tags.split(',').map((tag) => tag.trim()).filter(Boolean), vat_payer: form.vat_payer, city_tax_payer: form.city_tax_payer,
      settlement_account_id: num(form.settlement_account_id), price_list_id: num(form.price_list_id), credit_limit: txt(form.credit_limit), currency: form.currency || 'MNT',
      payment_term_id: num(form.payment_term_id), sales_discount_pct: txt(form.sales_discount_pct), sales_note: txt(form.sales_note), sales_lead_days: num(form.sales_lead_days),
      purchase_discount_pct: txt(form.purchase_discount_pct), purchase_note: txt(form.purchase_note), purchase_lead_days: num(form.purchase_lead_days), delivery_terms: txt(form.delivery_terms),
      links: form.links.filter((link) => link.label.trim() && link.url.trim()), confirm_duplicate_tin: confirmDuplicate,
      ...(party ? { version: party.version } : {}),
    }
    try {
      const saved = await save.mutateAsync(party ? { id: party.id, ...payload } : payload)
      if (saved.duplicates?.length) toast(`Ижил нэртэй харилцагч байна: ${saved.duplicates.map((row) => row.code).join(', ')}`)
      toast.success(party ? 'Хадгаллаа' : `${saved.code} кодтой харилцагч бүртгэгдлээ`)
      onSaved?.(saved)
      onClose()
    } catch (error) {
      if (crmErrorCode(error) === 'crm_party_duplicate_tin') {
        setDuplicates((error as { response: { data: { detail: { matches: CRMTaxpayer['duplicates'] } } } }).response.data.detail.matches)
        return
      }
      toast.error(crmErrorText(error))
    }
  }

  const options = <T extends { id: number; name: string; code?: string }>(rows: T[]) => rows.map((row) => ({ value: String(row.id), label: row.code ? `${row.code} ${row.name}` : row.name }))

  return <Modal title={party ? `${party.code} — ${party.name}` : 'Шинэ харилцагч'} onClose={onClose} className="crm-modal">
    <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
      <Section title="Үндсэн мэдээлэл">
        <Field label="Код" hint={party ? undefined : 'Хоосон бол 10001-ээс эхлэн автоматаар олгоно'}><TextInput value={form.code} onChange={(value) => set('code', value)} /></Field>
        <Field label="РД (регистр)">
          <div className="crm-inline"><TextInput value={form.registry_no} onChange={(value) => set('registry_no', value.toUpperCase())} /><Btn onClick={() => void lookup()} disabled={lookingUp}><DownloadCloud size={14} />{lookingUp ? 'Татаж байна…' : 'Татвараас татах'}</Btn></div>
        </Field>
        <Field label="ТТД"><TextInput value={form.tax_id} onChange={(value) => set('tax_id', value)} /></Field>
        <Field label="Нэр"><TextInput value={form.name} onChange={(value) => set('name', value)} required /></Field>
        <Field label="Нэр /EN/"><TextInput value={form.name_en} onChange={(value) => set('name_en', value)} /></Field>
        <Field label="Бизнес нэр"><TextInput value={form.business_name} onChange={(value) => set('business_name', value)} placeholder="Жишээ: Оргил супермаркет" /></Field>
      </Section>
      {duplicates && duplicates.length > 0 && <div className="crm-warning">
        <strong>Энэ ТТД/РД-тай харилцагч бүртгэгдсэн байна:</strong>
        <ul>{duplicates.map((row) => <li key={row.party_id}>{row.code} — {row.name}</li>)}</ul>
        <p>Олон салбартай байгууллагын салбарыг бүртгэж байгаа бол баталгаажуулж үргэлжлүүлнэ үү.</p>
        <Btn onClick={() => void submit(true)} disabled={save.isPending}>Салбар гэж баталгаажуулж хадгалах</Btn>
      </div>}

      <Section title="Ангилал ба хариуцагч">
        <Field label="Бүлэг"><NativeSelect value={form.group_id} onChange={(value) => set('group_id', value)} options={options(lookups.party_groups.filter((row) => row.is_active || String(row.id) === form.group_id))} placeholder="Үндсэн бүлэг" /></Field>
        <Field label="Хариуцагч ажилтан"><NativeSelect value={form.responsible_employee_id} onChange={(value) => set('responsible_employee_id', value)} options={lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))} /></Field>
        <Field label="Толгой харилцагч"><PartyPicker value={form.parent_party_id} label={form.parent_label} excludeId={party?.id} onChange={(picked) => setForm((current) => ({ ...current, parent_party_id: picked?.id ?? null, parent_label: picked?.name ?? null }))} /></Field>
        <Field label="Харилцагч болсон"><TextInput type="date" value={form.customer_since} onChange={(value) => set('customer_since', value)} /></Field>
        <div className="crm-checks hr-form-wide">
          <CheckField label="Худалдан авагч" checked={form.is_customer} onChange={(value) => set('is_customer', value)} />
          <CheckField label="Нийлүүлэгч" checked={form.is_supplier} onChange={(value) => set('is_supplier', value)} />
          <CheckField label="Хувь хүн" checked={form.is_individual} onChange={(value) => set('is_individual', value)} />
          <CheckField label="Гадаад" checked={form.is_foreign} onChange={(value) => set('is_foreign', value)} />
          <CheckField label="Боломжит харилцагч (lead)" checked={form.prospect} onChange={(value) => set('prospect', value)} />
          <CheckField label="Толгой харилцагчаар тооцоо үүснэ" checked={form.settle_via_parent} onChange={(value) => set('settle_via_parent', value)} />
        </div>
      </Section>

      <Section title="Холбоо барих">
        <Field label="Утас"><TextInput value={form.phone} onChange={(value) => set('phone', value)} /></Field>
        <Field label="Mail"><TextInput type="email" value={form.email} onChange={(value) => set('email', value)} /></Field>
        <Field label="Web"><TextInput value={form.website} onChange={(value) => set('website', value)} /></Field>
        <Field label="Байршил"><TextInput value={form.location} onChange={(value) => set('location', value)} placeholder="Бүс нутаг, хот" /></Field>
        <Field label="Хаяг (албан ёсны)" wide><TextInput value={form.legal_address} onChange={(value) => set('legal_address', value)} /></Field>
        <Field label="Хаяг байршил" wide><TextInput value={form.informal_address} onChange={(value) => set('informal_address', value)} placeholder="Жишээ: Их дэлгүүрийн хойно" /></Field>
        <Field label="Tags" wide hint="Таслалаар тусгаарлана"><TextInput value={form.tags} onChange={(value) => set('tags', value)} /></Field>
      </Section>

      <Section title="Татварын тохиргоо">
        <div className="crm-checks hr-form-wide">
          <CheckField label="НӨАТ суутган төлөгч" checked={form.vat_payer} onChange={(value) => set('vat_payer', value)} />
          <CheckField label="НХАТ суутган төлөгч" checked={form.city_tax_payer} onChange={(value) => set('city_tax_payer', value)} />
        </div>
      </Section>

      <Section title="Тооцоо ба нэмэлт тохиргоо">
        <Field label="Тооцооны данс"><NativeSelect value={form.settlement_account_id} onChange={(value) => set('settlement_account_id', value)} options={options(lookups.settlement_accounts)} /></Field>
        <Field label="Үнийн жагсаалт"><NativeSelect value={form.price_list_id} onChange={(value) => set('price_list_id', value)} options={options(lookups.price_lists)} /></Field>
        <Field label="Тооцооны лимит"><TextInput type="number" min="0" value={form.credit_limit} onChange={(value) => set('credit_limit', value)} /></Field>
        <Field label="Валют"><TextInput value={form.currency} onChange={(value) => set('currency', value.toUpperCase().slice(0, 3))} /></Field>
        <Field label="Төлбөрийн нөхцөл"><NativeSelect value={form.payment_term_id} onChange={(value) => set('payment_term_id', value)} options={options(lookups.payment_terms.filter((row) => row.is_active || String(row.id) === form.payment_term_id))} /></Field>
        <Field label="Тээвэр нөхцөл"><TextInput value={form.delivery_terms} onChange={(value) => set('delivery_terms', value)} /></Field>
        <Field label="Борлуулалт хөнгөлөлт %"><TextInput type="number" min="0" step="0.01" value={form.sales_discount_pct} onChange={(value) => set('sales_discount_pct', value)} /></Field>
        <Field label="Борлуулалт биелэх өдөр"><TextInput type="number" min="0" value={form.sales_lead_days} onChange={(value) => set('sales_lead_days', value)} /></Field>
        <Field label="Борлуулалт тайлбар" wide><TextArea value={form.sales_note} onChange={(value) => set('sales_note', value)} rows={2} /></Field>
        <Field label="Худалдан авалт хөнгөлөлт %"><TextInput type="number" min="0" step="0.01" value={form.purchase_discount_pct} onChange={(value) => set('purchase_discount_pct', value)} /></Field>
        <Field label="Худалдан авалт биелэх өдөр"><TextInput type="number" min="0" value={form.purchase_lead_days} onChange={(value) => set('purchase_lead_days', value)} /></Field>
        <Field label="Худалдан авалт тайлбар" wide><TextArea value={form.purchase_note} onChange={(value) => set('purchase_note', value)} rows={2} /></Field>
      </Section>

      <Section title="Файлын линк">
        <div className="crm-list hr-form-wide">
          {form.links.map((link, index) => <div className="crm-inline" key={index}>
            <TextInput value={link.label} placeholder="Нэр" onChange={(value) => set('links', form.links.map((row, i) => (i === index ? { ...row, label: value } : row)))} />
            <TextInput value={link.url} placeholder="https://… эсвэл \\server\folder" onChange={(value) => set('links', form.links.map((row, i) => (i === index ? { ...row, url: value } : row)))} />
            <Btn onClick={() => set('links', form.links.filter((_, i) => i !== index))}><Trash2 size={14} /></Btn>
          </div>)}
          <div><Btn onClick={() => set('links', [...form.links, { label: '', url: '' }])}><Plus size={14} />Линк нэмэх</Btn></div>
        </div>
      </Section>

      <Section title="Төлөв">
        <div className="crm-checks"><CheckField label="Идэвхтэй" checked={form.is_active} onChange={(value) => set('is_active', value)} /></div>
        {!form.is_active && <Field label="Идэвхгүй болсон"><TextInput type="date" value={form.inactive_since} onChange={(value) => set('inactive_since', value)} /></Field>}
      </Section>

      <div className="crm-actions"><div /><div><Btn onClick={onClose}>Болих</Btn><Btn variant="primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Хадгалж байна…' : 'Хадгалах'}</Btn></div></div>
    </form>
  </Modal>
}
