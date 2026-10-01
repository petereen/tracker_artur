import { Fragment, useEffect, useState } from 'react'
import { Pencil } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { useContractRegistryOptions, useUpdateContractArchiveEntryRegistry, type ContractArchiveEntry } from '../api/enterprise'
import { intlLocale } from '../utils/locale'
import { LinkItem, contractErrorMessage, formatContractMoney, registryDraftFrom, registryPayload, ContractRegistryForm } from './ContractRegistryFields'

/**
 * «Гэрээний бүртгэл» of an archived contract: the same contract data that contracts created through the
 * workflow carry (code, number, group, counterparty, date, amounts, penalty, payment term, links, meta).
 * Archive managers can add or correct it after the fact.
 */
export function ContractArchiveRegistry({ entry }: { entry: ContractArchiveEntry }) {
  const { t } = useTranslation()
  const registry = entry.registry
  const options = useContractRegistryOptions()
  const save = useUpdateContractArchiveEntryRegistry()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(() => registryDraftFrom(registry ?? undefined))
  useEffect(() => { if (!editing) setDraft(registryDraftFrom(registry ?? undefined)) }, [registry, editing])
  if (!registry) return null
  const isActive = registry.is_active ?? true
  const quantity = registry.quantity !== null && registry.quantity !== undefined
    ? `${new Intl.NumberFormat(intlLocale()).format(registry.quantity)} ${registry.unit?.symbol || registry.unit?.name || ''}`.trim() : '—'
  const submit = (input: Parameters<typeof save.mutate>[0], success: string) => save.mutate(input, {
    onSuccess: () => { toast.success(success); setEditing(false) },
    onError: (error) => toast.error(contractErrorMessage(error, t('contracts.registry.saveFailed'))),
  })
  const partyLabel = registry.party ? `${registry.party.code} · ${registry.party.name}` : undefined
  return <section className="archive-registry" aria-label={t('contracts.registry.heading')}>
    <header className="archive-registry-header">
      <h3>{t('contracts.registry.heading')}</h3>
      <span className={`contract-active-pill ${isActive ? 'is-active' : 'is-inactive'}`}>{isActive ? t('contracts.registry.active') : t('contracts.registry.inactive')}</span>
    </header>
    {editing ? <>
      <ContractRegistryForm draft={draft} onChange={setDraft} options={options.data} disabled={save.isPending} partyLabel={partyLabel} />
      <div className="contract-registry-actions">
        <button type="button" className="secondary-action" onClick={() => setEditing(false)}>{t('contracts.registry.cancel')}</button>
        <button type="button" className="primary-action" disabled={save.isPending} onClick={() => submit({ id: entry.id, ...registryPayload(draft) }, t('contracts.registry.archiveSaved'))}>{t('contracts.registry.save')}</button>
      </div>
    </> : <>
      <dl className="contract-registry-list">
        <dt>{t('contracts.registry.code')}</dt><dd>{registry.code || '—'}</dd>
        <dt>{t('contracts.registry.dtNumber')}</dt><dd>{registry.contract_number || '—'}</dd>
        <dt>{t('crm.common.group')}</dt><dd>{registry.group ? `${registry.group.code} · ${registry.group.name}` : '—'}</dd>
        <dt>{t('contracts.registry.dtParty')}</dt><dd>{partyLabel || '—'}</dd>
        <dt>{t('crm.party.parent')}</dt><dd>{registry.head_party ? `${registry.head_party.code} · ${registry.head_party.name}` : '—'}</dd>
        <dt>{t('contracts.registry.archiveDate')}</dt><dd>{registry.signed_on || '—'}</dd>
        <dt>{t('contracts.registry.quantity')}</dt><dd>{quantity}</dd>
        <dt>{t('contracts.registry.unitPrice')}</dt><dd>{formatContractMoney(registry.unit_price, registry.currency)}</dd>
        <dt>{t('contracts.registry.amount')}</dt><dd><strong>{formatContractMoney(registry.amount, registry.currency)}</strong></dd>
        <dt>{t('contracts.registry.dtPenalty')}</dt><dd>{registry.penalty_pct !== null && registry.penalty_pct !== undefined ? `${registry.penalty_pct}%` : '—'}</dd>
        <dt>{t('contracts.registry.paymentTerm')}</dt><dd>{registry.payment_term ? registry.payment_term.name : '—'}</dd>
        {registry.custom_fields?.map((field, index) => <Fragment key={index}><dt>{field.label}</dt><dd>{field.value || '—'}</dd></Fragment>)}
      </dl>
      {registry.note && <p className="contract-registry-note">{registry.note}</p>}
      {!!registry.links?.length && <ul className="contract-registry-links">{registry.links.map((link, index) => <LinkItem key={index} link={link} />)}</ul>}
      {entry.can_edit && <div className="contract-registry-actions">
        <button type="button" className="secondary-action" onClick={() => { setDraft(registryDraftFrom(registry)); setEditing(true) }}><Pencil size={14} />{t('contracts.registry.edit')}</button>
        <button type="button" className="secondary-action" disabled={save.isPending} onClick={() => {
          if (isActive && !window.confirm(t('contracts.registry.archiveConfirm'))) return
          submit({ id: entry.id, is_active: !isActive }, isActive ? t('contracts.registry.deactivated') : t('contracts.registry.activated'))
        }}>{isActive ? t('contracts.registry.deactivate') : t('contracts.registry.activate')}</button>
      </div>}
      {entry.can_edit && !registry.code && !registry.party && registry.amount === null && <p className="archive-registry-hint">{t('contracts.registry.archiveHint')}</p>}
    </>}
  </section>
}
