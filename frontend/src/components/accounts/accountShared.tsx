import { Token } from '@astryxdesign/core/Token'
import type { SelectorSection } from '@astryxdesign/core/Selector'
import type { ERPAccountClassification, ERPAccountOption } from '../../api/enterprise'

/** Chart of accounts («Данс код», Dayansoft d047) labels shared by the accounts page, payroll and budget pickers. */
export const CLASSIFICATION_ORDER: ERPAccountClassification[] = ['asset', 'liability', 'equity', 'income', 'expense']
export const CLASSIFICATION_LABELS: Record<ERPAccountClassification, string> = { asset: 'Хөрөнгө', liability: 'Өр төлбөр', equity: 'Эздийн өмч', income: 'Орлого', expense: 'Зардал' }
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
 * purpose matches `preferredPurposes` are listed first under «Санал болгох».
 */
export function accountSelectorOptions(
  accounts: ERPAccountOption[] | undefined,
  { classifications = CLASSIFICATION_ORDER, preferredPurposes = [], keepId }: { classifications?: ERPAccountClassification[]; preferredPurposes?: string[]; keepId?: number | null } = {},
): SelectorSection[] {
  const eligible = (accounts ?? [])
    .filter((account) => (account.is_active !== false && !account.is_group && account.classification && classifications.includes(account.classification)) || account.id === keepId)
    .sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  const option = (account: ERPAccountOption) => ({ value: String(account.id), label: accountLabel(account), description: account.is_active === false ? 'Идэвхгүй' : undefined })
  const preferred = eligible.filter((account) => account.purpose && preferredPurposes.includes(account.purpose))
  const rest = eligible.filter((account) => !preferred.includes(account))
  const sections: SelectorSection[] = []
  if (preferred.length) sections.push({ type: 'section', title: 'Санал болгох', options: preferred.map(option) })
  for (const classification of CLASSIFICATION_ORDER) {
    const rows = rest.filter((account) => account.classification === classification)
    if (rows.length) sections.push({ type: 'section', title: CLASSIFICATION_LABELS[classification], options: rows.map(option) })
  }
  const orphans = rest.filter((account) => !account.classification || !CLASSIFICATION_ORDER.includes(account.classification))
  if (orphans.length) sections.push({ type: 'section', title: 'Бусад', options: orphans.map(option) })
  return sections
}

const ERROR_MESSAGES: Record<string, string> = {
  erp_account_code_duplicate: 'Ийм кодтой данс аль хэдийн бүртгэлтэй байна.',
  erp_account_code_name_required: 'Дансны код, нэрийг оруулна уу.',
  erp_account_purpose_invalid: 'Дансны зориулалт буруу байна.',
  erp_account_classification_invalid: 'Сонгосон зориулалт энэ ангилалд тохирохгүй байна.',
  payroll_account_classification_invalid: 'Цалингийн зориулалттай данс тохирох ангилалд (зардал / өр төлбөр / хөрөнгө) байх ёстой.',
  erp_account_parent_invalid: 'Хураангуй данс олдсонгүй.',
  erp_account_parent_must_be_group: 'Хураангуй данс нь идэвхтэй «бүлэг данс» байх ёстой.',
  erp_account_parent_classification_mismatch: 'Хураангуй данс ижил ангилалтай байх ёстой.',
  erp_account_parent_cycle: 'Дансыг өөрийн дэд дансны доор оруулах боломжгүй.',
  erp_account_group_has_children: 'Дэд данстай бүлэг дансыг энгийн данс болгох боломжгүй.',
  erp_account_referenced_fields_locked: 'Гүйлгээ эсвэл тохиргоонд ашиглагдсан тул код, ангилал, зориулалт, валютыг өөрчлөх боломжгүй. Шинэ данс нээж, хуучныг идэвхгүй болгоно уу.',
  erp_account_not_found: 'Данс олдсонгүй.',
}

export function accountErrorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = String((detail as { code: unknown }).code)
    if (ERROR_MESSAGES[code]) return ERROR_MESSAGES[code]
  }
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '')).filter(Boolean).join('; ') || 'Мэдээлэл буруу байна'
  return 'Үйлдэл амжилтгүй боллоо'
}
