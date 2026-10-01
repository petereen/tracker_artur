import { useEffect } from 'react'
import toast from 'react-hot-toast'
import { LogOut } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Center } from '@astryxdesign/core/Center'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import { useEnterpriseLogout } from '../api/enterprise'
import type { TenantContext } from '../api/tenancy'
import i18n from '../i18n'
import { TenantLicenseSettings, formatDate } from './TenantLicenseSettings'

const UNAVAILABLE_CODES = ['tenant_suspended', 'tenant_terminated', 'tenant_mismatch', 'tenant_not_found'] as const
type UnavailableCode = (typeof UNAVAILABLE_CODES)[number]

export function isWorkspaceUnavailable(code: string | undefined): code is UnavailableCode {
  return Boolean(code && (UNAVAILABLE_CODES as readonly string[]).includes(code))
}

function LogoutButton() {
  const { t } = useTranslation()
  const logout = useEnterpriseLogout()
  return <Button label={t('action.logout')} variant="secondary" icon={<LogOut size={15} />} onClick={() => logout.mutate()} isDisabled={logout.isPending} />
}

/** Suspended/terminated tenant or a session opened on another tenant's domain. */
export function WorkspaceUnavailableScreen({ code }: { code: string }) {
  const { t } = useTranslation()
  const key = isWorkspaceUnavailable(code) ? code : 'tenant_suspended'
  const copy = { title: t(`tenant.unavailable.${key}.title`), description: t(`tenant.unavailable.${key}.description`) }
  return <Center minHeight="100dvh" padding={6}>
    <Card padding={6} maxWidth={520}>
      <VStack gap={4}>
        <Heading level={2}>{copy.title}</Heading>
        <Text type="supporting">{copy.description}</Text>
        <HStack><LogoutButton /></HStack>
      </VStack>
    </Card>
  </Center>
}

/** No valid license: admins activate a key here, everyone else waits for them. */
export function LicenseRequiredScreen({ context, isAdmin }: { context: TenantContext; isAdmin: boolean }) {
  const { t } = useTranslation()
  const expired = context.license.state === 'expired'
  return <Center minHeight="100dvh" padding={6}>
    <VStack gap={4} width="100%" maxWidth={960}>
      <VStack gap={1}>
        <Heading level={1}>{context.branding.name}</Heading>
        <Text type="supporting">{expired
          ? t('tenant.licenseExpired', { date: formatDate(context.license.expires_at) })
          : t('tenant.licenseActivate')}</Text>
      </VStack>
      {isAdmin
        ? <TenantLicenseSettings />
        : <Card padding={6}><Text>{t('tenant.licenseWaitAdmin')}</Text></Card>}
      <HStack><LogoutButton /></HStack>
    </VStack>
  </Center>
}

/** One reminder per session while an expired license runs on its grace period. */
export function useLicenseGraceNotice(context: TenantContext | undefined, isAdmin: boolean) {
  const state = context?.license.state
  const graceEnds = context?.license.grace_ends_at
  useEffect(() => {
    if (state !== 'grace') return
    const key = `oyuns.license-grace-notice.${graceEnds}`
    try {
      if (sessionStorage.getItem(key)) return
      sessionStorage.setItem(key, '1')
    } catch { /* private mode: remind every load */ }
    toast(i18n.t(isAdmin ? 'tenant.graceAdmin' : 'tenant.graceMember', { date: formatDate(graceEnds) }), { icon: '⚠️', duration: 8000 })
  }, [graceEnds, isAdmin, state])
}
