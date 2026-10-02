import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { HStack } from '@astryxdesign/core/HStack'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import { useManagedAccounts } from '../api/enterprise'
import { useResetAccountTwoFactor, useTwoFactorSettings, useUpdateTwoFactorSettings } from '../api/twoFactor'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

/** Admin switch that makes two-factor sign-in mandatory for the tenant, plus per-account reset. */
export function TwoFactorSettings() {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const settings = useTwoFactorSettings(canEdit)
  const update = useUpdateTwoFactorSettings()
  const accounts = useManagedAccounts()
  const reset = useResetAccountTwoFactor()
  if (!canEdit) return <Banner status="info" title={t('tfa.set.adminOnly')} collapsible={false} />
  if (settings.isError) return <Banner status="error" title={t('tfa.set.loadFailed')} collapsible={false} />
  if (!settings.data) return <Skeleton height={96} />
  const { required, enrolled, accounts: total } = settings.data
  const save = async (checked: boolean) => {
    try { await update.mutateAsync(checked); toast.success(t(checked ? 'tfa.set.on' : 'tfa.set.off')) } catch { toast.error(t('tfa.set.notSaved')) }
  }
  const resetAccount = (id: number, email: string) => {
    if (!window.confirm(t('tfa.set.resetConfirm', { email }))) return
    reset.mutate(id, { onSuccess: () => toast.success(t('tfa.set.resetDone')), onError: () => toast.error(t('tfa.set.resetFailed')) })
  }
  const enrolledAccounts = (accounts.data ?? []).filter((account) => account.two_factor_enabled)
  return <VStack gap={3}>
    <Switch label={t('tfa.set.switch')} description={t('tfa.set.switchHint')} value={required} changeAction={save} isDisabled={update.isPending} />
    <Text type="supporting">{t('tfa.set.progress', { enrolled, total })}</Text>
    {!required && enrolled > 0 && <Banner status="info" title={t('tfa.set.offNoteTitle')} description={t('tfa.set.offNote')} collapsible={false} />}
    <VStack gap={2}>
      <Text weight="semibold">{t('tfa.set.accounts')}</Text>
      {enrolledAccounts.length === 0
        ? <Text type="supporting">{t('tfa.set.noneEnrolled')}</Text>
        : enrolledAccounts.map((account) => <HStack key={account.id} gap={3} hAlign="between" vAlign="center">
          <Text>{account.email}</Text>
          <Button label={t('tfa.set.reset')} aria-label={t('tfa.set.resetAria', { email: account.email })} variant="secondary" size="sm" isDisabled={reset.isPending} onClick={() => resetAccount(account.id, account.email)} />
        </HStack>)}
    </VStack>
  </VStack>
}
