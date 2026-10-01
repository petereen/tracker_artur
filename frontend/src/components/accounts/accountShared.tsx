import { Token } from '@astryxdesign/core/Token'
import type { SelectorSection } from '@astryxdesign/core/Selector'
import type { ERPAccountClassification, ERPAccountOption } from '../../api/enterprise'
import i18n from '../../i18n'

/** Chart of accounts («Данс код», Dayansoft d047) labels shared by the accounts page, payroll and budget pickers. */
export const CLASSIFICATION_ORDER: ERPAccountClassification[] = ['asset', 'liability', 'equity', 'income', 'expense']
/** Getters so each label is resolved in the UI language at render time, not at import. */
export const CLASSIFICATION_LABELS: Record<ERPAccountClassification, string> = {
  get asset() { return i18n.t('accounts.class.asset') },
  get liability() { return i18n.t('accounts.class.liability') },
  get equity() { return i18n.t('accounts.class.equity') },
  get income() { return i18n.t('accounts.class.income') },
  get expense() { return i18n.t('accounts.class.expense') },
}
const CLASSIFICATION_COLORS: Record<ERPAccountClassification, 'blue' | 'orange' | 'purple' | 'green' | 'red'> = { asset: 'blue', liability: 'orange', equity: 'purple', income: 'green', expense: 'red' }
export const CHART_OF_ACCOUNTS_PATH = '/erp/accounts'

export function ClassificationToken({ classification }: { classification?: ERPAccountClassification }) {
  if (!classification) return null
  return <Token size="sm" color={CLASSIFICATION_COLORS[classification]} label={CLASSIFICATION_LABELS[classification]} />
}

export const accountLabel = (account: Pick<ERPAccountOption, 'code' | 'name'>) => `${account.code} · ${account.name}`

/**
 * Selector options for picking a posting account: active, non-group accounts of
 * the allowed classifications, grouped by classification. Accounts whose
 * purpose matches `preferredPurposes` are listed first under «Suggested».
 */
export function accountSelectorOptions(
  accounts: ERPAccountOption[] | undefined,
  { classifications = CLASSIFICATION_ORDER, preferredPurposes = [], keepId }: { classifications?: ERPAccountClassification[]; preferredPurposes?: string[]; keepId?: number | null } = {},
): SelectorSection[] {
  const eligible = (accounts ?? [])
    .filter((account) => (account.is_active !== false && !account.is_group && account.classification && classifications.includes(account.classification)) || account.id === keepId)
    .sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  const option = (account: ERPAccountOption) => ({ value: String(account.id), label: accountLabel(account), description: account.is_active === false ? i18n.t('accounts.inactive') : undefined })
  const preferred = eligible.filter((account) => account.purpose && preferredPurposes.includes(account.purpose))
  const rest = eligible.filter((account) => !preferred.includes(account))
  const sections: SelectorSection[] = []
  if (preferred.length) sections.push({ type: 'section', title: i18n.t('accounts.suggested'), options: preferred.map(option) })
  for (const classification of CLASSIFICATION_ORDER) {
    const rows = rest.filter((account) => account.classification === classification)
    if (rows.length) sections.push({ type: 'section', title: CLASSIFICATION_LABELS[classification], options: rows.map(option) })
  }
  const orphans = rest.filter((account) => !account.classification || !CLASSIFICATION_ORDER.includes(account.classification))
  if (orphans.length) sections.push({ type: 'section', title: i18n.t('accounts.other'), options: orphans.map(option) })
  return sections
}

export function accountErrorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const key = `accounts.error.${String((detail as { code: unknown }).code)}`
    if (i18n.exists(key)) return i18n.t(key)
  }
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '')).filter(Boolean).join('; ') || i18n.t('accounts.error.invalid')
  return i18n.t('accounts.error.failed')
}
