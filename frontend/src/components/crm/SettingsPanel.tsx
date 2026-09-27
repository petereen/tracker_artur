import { useState, type ReactNode } from 'react'
import toast from 'react-hot-toast'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useDeleteCRMSetting, useSaveCRMSetting, type CRMLookups, type CRMSettingKind } from '../../api/crm'
import { Badge, Btn, Card, Modal } from '../ui'
import { CATEGORY_LABELS, CheckField, Field, NativeSelect, StatusChip, TextInput, crmErrorText } from './shared'

type FieldSpec =
  | { key: string; label: string; type: 'text' | 'number' | 'color' }
  | { key: string; label: string; type: 'select'; options: Array<{ value: string; label: string }> }
  | { key: string; label: string; type: 'check' }

type Row = Record<string, unknown> & { id: number; name: string; is_active: boolean }

function SettingModal({ kind, title, fields, row, defaults, onClose }: { kind: CRMSettingKind; title: string; fields: FieldSpec[]; row: Row | null; defaults: Record<string, unknown>; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, unknown>>(() => ({ ...defaults, ...(row ?? {}) }))
  const save = useSaveCRMSetting(kind)
  const submit = async () => {
    const payload: Record<string, unknown> = {}
    for (const field of fields) {
      const value = values[field.key]
      if (field.type === 'number') payload[field.key] = value === '' || value === null || value === undefined ? undefined : Number(value)
      else if (field.type === 'check') payload[field.key] = Boolean(value)
      else if (field.type === 'select' && field.key.endsWith('_id')) payload[field.key] = value ? Number(value) : null
      else payload[field.key] = value === '' ? null : value
    }
    try { await save.mutateAsync(row ? { id: row.id, ...payload } : payload); toast.success('Хадгаллаа'); onClose() } catch (error) { toast.error(crmErrorText(error)) }
  }
  return <Modal title={title} onClose={onClose}>
    <div className="hr-form-grid">
      {fields.map((field) => field.type === 'check'
        ? <div className="crm-checks" key={field.key}><CheckField label={field.label} checked={Boolean(values[field.key])} onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))} /></div>
        : <Field label={field.label} key={field.key}>
          {field.type === 'select'
            ? <NativeSelect value={values[field.key] == null ? '' : String(values[field.key])} onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))} options={field.options} />
            : <TextInput type={field.type} value={values[field.key] == null ? '' : String(values[field.key])} onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))} />}
        </Field>)}
    </div>
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>Болих</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>Хадгалах</Btn></div></div>
  </Modal>
}

function SettingList({ kind, title, rows, fields, defaults, canEdit, describe }: { kind: CRMSettingKind; title: string; rows: Row[]; fields: FieldSpec[]; defaults: Record<string, unknown>; canEdit: boolean; describe: (row: Row) => ReactNode }) {
  const [editing, setEditing] = useState<Row | 'new' | null>(null)
  const remove = useDeleteCRMSetting(kind)
  return <Card>
    <h2>{title}</h2>
    <div className="crm-list">
      {rows.map((row) => <article key={row.id}>
        <div>{describe(row)}</div>
        <div className="crm-checks">
          {!row.is_active && <Badge color="muted">Идэвхгүй</Badge>}
          {canEdit && <div className="crm-row-actions">
            <button onClick={() => setEditing(row)} aria-label="Засах"><Pencil size={13} /></button>
            <button aria-label="Устгах" onClick={() => { if (window.confirm(`“${row.name}”-ийг устгах уу?`)) void remove.mutateAsync(row.id).then(() => toast.success('Устгалаа')).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button>
          </div>}
        </div>
      </article>)}
      {!rows.length && <div className="hr-empty">Бүртгэл алга</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />Нэмэх</Btn></div>}
    {editing && <SettingModal kind={kind} title={title} fields={fields} row={editing === 'new' ? null : editing} defaults={defaults} onClose={() => setEditing(null)} />}
  </Card>
}

export function SettingsPanel({ lookups, canEdit }: { lookups: CRMLookups; canEdit: boolean }) {
  const categoryOptions = Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label }))
  const groupOptions = lookups.party_groups.map((row) => ({ value: String(row.id), label: row.name }))
  return <div className="crm-settings">
    <SettingList kind="statuses" title="Төлөв (Харилцаа холбоо)" canEdit={canEdit} rows={lookups.statuses as unknown as Row[]}
      defaults={{ color: '#2D62EC', category: 'open', sort: (lookups.statuses.length + 1) * 10, is_active: true }}
      fields={[{ key: 'name', label: 'Нэр', type: 'text' }, { key: 'code', label: 'Код', type: 'text' }, { key: 'category', label: 'Утга (систем)', type: 'select', options: categoryOptions }, { key: 'color', label: 'Өнгө', type: 'color' }, { key: 'sort', label: 'Дараалал', type: 'number' }, { key: 'is_active', label: 'Идэвхтэй', type: 'check' }]}
      describe={(row) => <><StatusChip name={row.name} color={String(row.color)} /><small>{row.code as string} · {CATEGORY_LABELS[row.category as keyof typeof CATEGORY_LABELS]} · {row.sort as number}</small></>} />
    <SettingList kind="activity-types" title="Харилцаа холбооны төрөл" canEdit={canEdit} rows={lookups.activity_types as unknown as Row[]}
      defaults={{ sort: (lookups.activity_types.length + 1) * 10, is_active: true }}
      fields={[{ key: 'name', label: 'Нэр', type: 'text' }, { key: 'code', label: 'Код', type: 'text' }, { key: 'sort', label: 'Дараалал', type: 'number' }, { key: 'is_active', label: 'Идэвхтэй', type: 'check' }]}
      describe={(row) => <><strong>{row.name}</strong><small>{row.code as string}</small></>} />
    <SettingList kind="party-groups" title="Харилцагчийн бүлэг" canEdit={canEdit} rows={lookups.party_groups as unknown as Row[]}
      defaults={{ is_active: true }}
      fields={[{ key: 'name', label: 'Нэр', type: 'text' }, { key: 'code', label: 'Код', type: 'text' }, { key: 'parent_id', label: 'Харьяа бүлэг', type: 'select', options: groupOptions },
        { key: 'default_settlement_account_id', label: 'Тооцооны данс (Default)', type: 'select', options: lookups.settlement_accounts.map((row) => ({ value: String(row.id), label: `${row.code} ${row.name}` })) },
        { key: 'default_price_list_id', label: 'Үнийн жагсаалт (Default)', type: 'select', options: lookups.price_lists.map((row) => ({ value: String(row.id), label: row.name })) },
        { key: 'is_default', label: 'Default бүлэг', type: 'check' }, { key: 'is_foreign', label: 'Гадаад', type: 'check' }, { key: 'is_active', label: 'Идэвхтэй', type: 'check' }]}
      describe={(row) => <><strong>{row.name} {row.is_default ? <Badge color="blue">Default</Badge> : null}</strong><small>{row.code as string}{row.parent_id ? ` · ↳ ${lookups.party_groups.find((group) => group.id === row.parent_id)?.name ?? ''}` : ''}{row.is_foreign ? ' · Гадаад' : ''}</small></>} />
    <SettingList kind="payment-terms" title="Төлбөрийн нөхцөл" canEdit={canEdit} rows={lookups.payment_terms as unknown as Row[]}
      defaults={{ days: 0, period_unit: 'day', period_value: 0, is_active: true }}
      fields={[{ key: 'name', label: 'Нэр', type: 'text' }, { key: 'code', label: 'Код', type: 'text' }, { key: 'days', label: 'Төлөх хоног', type: 'number' },
        { key: 'period_unit', label: 'Хугацаа төрөл', type: 'select', options: [{ value: 'day', label: 'Хоног' }, { value: 'month', label: 'Month' }] }, { key: 'period_value', label: 'Хугацаа утга', type: 'number' }, { key: 'is_active', label: 'Идэвхтэй', type: 'check' }]}
      describe={(row) => <><strong>{row.name}</strong><small>{row.code as string} · {row.period_unit === 'month' ? `${row.period_value as number} сар` : `${row.days as number} хоног`}</small></>} />
  </div>
}
