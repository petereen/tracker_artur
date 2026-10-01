import { useState, type ReactNode } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
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
    try { await save.mutateAsync(row ? { id: row.id, ...payload } : payload); toast.success(t('crm.common.saved')); onClose() } catch (error) { toast.error(crmErrorText(error)) }
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
    <div className="crm-actions"><div /><div><Btn onClick={onClose}>{t('crm.common.cancel')}</Btn><Btn variant="primary" onClick={() => void submit()} disabled={save.isPending}>{t('crm.common.save')}</Btn></div></div>
  </Modal>
}

function SettingList({ kind, title, rows, fields, defaults, canEdit, describe }: { kind: CRMSettingKind; title: string; rows: Row[]; fields: FieldSpec[]; defaults: Record<string, unknown>; canEdit: boolean; describe: (row: Row) => ReactNode }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<Row | 'new' | null>(null)
  const remove = useDeleteCRMSetting(kind)
  return <Card>
    <h2>{title}</h2>
    <div className="crm-list">
      {rows.map((row) => <article key={row.id}>
        <div>{describe(row)}</div>
        <div className="crm-checks">
          {!row.is_active && <Badge color="muted">{t('crm.common.inactive')}</Badge>}
          {canEdit && <div className="crm-row-actions">
            <button onClick={() => setEditing(row)} aria-label={t('crm.common.edit')}><Pencil size={13} /></button>
            <button aria-label={t('crm.common.delete')} onClick={() => { if (window.confirm(t('crm.settings.confirmDelete', { name: row.name }))) void remove.mutateAsync(row.id).then(() => toast.success(t('crm.common.deleted'))).catch((error) => toast.error(crmErrorText(error))) }}><Trash2 size={13} /></button>
          </div>}
        </div>
      </article>)}
      {!rows.length && <div className="hr-empty">{t('crm.settings.empty')}</div>}
    </div>
    {canEdit && <div style={{ marginTop: 10 }}><Btn onClick={() => setEditing('new')}><Plus size={14} />{t('crm.common.add')}</Btn></div>}
    {editing && <SettingModal kind={kind} title={title} fields={fields} row={editing === 'new' ? null : editing} defaults={defaults} onClose={() => setEditing(null)} />}
  </Card>
}

export function SettingsPanel({ lookups, canEdit }: { lookups: CRMLookups; canEdit: boolean }) {
  const { t } = useTranslation()
  const categoryOptions = Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label }))
  const groupOptions = lookups.party_groups.map((row) => ({ value: String(row.id), label: row.name }))
  return <div className="crm-settings">
    <SettingList kind="statuses" title={t('crm.settings.statuses')} canEdit={canEdit} rows={lookups.statuses as unknown as Row[]}
      defaults={{ color: '#2D62EC', category: 'open', sort: (lookups.statuses.length + 1) * 10, is_active: true }}
      fields={[{ key: 'name', label: t('crm.common.name'), type: 'text' }, { key: 'code', label: t('crm.common.code'), type: 'text' }, { key: 'category', label: t('crm.settings.meaning'), type: 'select', options: categoryOptions }, { key: 'color', label: t('crm.settings.color'), type: 'color' }, { key: 'sort', label: t('crm.settings.sort'), type: 'number' }, { key: 'is_active', label: t('crm.common.active'), type: 'check' }]}
      describe={(row) => <><StatusChip name={row.name} color={String(row.color)} /><small>{row.code as string} · {CATEGORY_LABELS[row.category as keyof typeof CATEGORY_LABELS]} · {row.sort as number}</small></>} />
    <SettingList kind="activity-types" title={t('crm.settings.activityTypes')} canEdit={canEdit} rows={lookups.activity_types as unknown as Row[]}
      defaults={{ sort: (lookups.activity_types.length + 1) * 10, is_active: true }}
      fields={[{ key: 'name', label: t('crm.common.name'), type: 'text' }, { key: 'code', label: t('crm.common.code'), type: 'text' }, { key: 'sort', label: t('crm.settings.sort'), type: 'number' }, { key: 'is_active', label: t('crm.common.active'), type: 'check' }]}
      describe={(row) => <><strong>{row.name}</strong><small>{row.code as string}</small></>} />
    <SettingList kind="party-groups" title={t('crm.settings.partyGroups')} canEdit={canEdit} rows={lookups.party_groups as unknown as Row[]}
      defaults={{ is_active: true }}
      fields={[{ key: 'name', label: t('crm.common.name'), type: 'text' }, { key: 'code', label: t('crm.common.code'), type: 'text' }, { key: 'parent_id', label: t('crm.settings.parentGroup'), type: 'select', options: groupOptions },
        { key: 'default_settlement_account_id', label: t('crm.settings.settlementAccount'), type: 'select', options: lookups.settlement_accounts.map((row) => ({ value: String(row.id), label: `${row.code} ${row.name}` })) },
        { key: 'default_price_list_id', label: t('crm.settings.priceList'), type: 'select', options: lookups.price_lists.map((row) => ({ value: String(row.id), label: row.name })) },
        { key: 'is_default', label: t('crm.settings.defaultGroup'), type: 'check' }, { key: 'is_foreign', label: t('crm.common.foreign'), type: 'check' }, { key: 'is_active', label: t('crm.common.active'), type: 'check' }]}
      describe={(row) => <><strong>{row.name} {row.is_default ? <Badge color="blue">{t('crm.settings.default')}</Badge> : null}</strong><small>{row.code as string}{row.parent_id ? ` · ↳ ${lookups.party_groups.find((group) => group.id === row.parent_id)?.name ?? ''}` : ''}{row.is_foreign ? ` · ${t('crm.common.foreign')}` : ''}</small></>} />
    <SettingList kind="payment-terms" title={t('crm.settings.paymentTerms')} canEdit={canEdit} rows={lookups.payment_terms as unknown as Row[]}
      defaults={{ days: 0, period_unit: 'day', period_value: 0, is_active: true }}
      fields={[{ key: 'name', label: t('crm.common.name'), type: 'text' }, { key: 'code', label: t('crm.common.code'), type: 'text' }, { key: 'days', label: t('crm.settings.days'), type: 'number' },
        { key: 'period_unit', label: t('crm.settings.periodUnit'), type: 'select', options: [{ value: 'day', label: t('crm.settings.unitDay') }, { value: 'month', label: t('crm.settings.unitMonth') }] }, { key: 'period_value', label: t('crm.settings.periodValue'), type: 'number' }, { key: 'is_active', label: t('crm.common.active'), type: 'check' }]}
      describe={(row) => <><strong>{row.name}</strong><small>{row.code as string} · {row.period_unit === 'month' ? t('crm.settings.months', { n: row.period_value as number }) : t('crm.settings.daysN', { n: row.days as number })}</small></>} />
  </div>
}
