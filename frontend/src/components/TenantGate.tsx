import { useEffect } from 'react'
import toast from 'react-hot-toast'
import { LogOut } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Center } from '@astryxdesign/core/Center'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import { useEnterpriseLogout } from '../api/enterprise'
import type { TenantContext } from '../api/tenancy'
import { TenantLicenseSettings, formatDate } from './TenantLicenseSettings'

const UNAVAILABLE: Record<string, { title: string; description: string }> = {
  tenant_suspended: { title: 'Ажлын орон зай түр түдгэлзсэн', description: 'Байгууллагын эрх үйлчилгээ үзүүлэгчийн шийдвэрээр түр зогссон байна. Админ эсвэл OYUNS ERP-тэй холбогдоно уу.' },
  tenant_terminated: { title: 'Ажлын орон зай хаагдсан', description: 'Энэ байгууллагын гэрээ дууссан тул нэвтрэх боломжгүй.' },
  tenant_mismatch: { title: 'Өөр байгууллагын холбоос', description: 'Энэ хаяг таны байгууллагынх биш байна. Өөрийн байгууллагын хаягаар нэвтэрнэ үү.' },
  tenant_not_found: { title: 'Ажлын орон зай олдсонгүй', description: 'Хаягаа шалгаад дахин оролдоно уу.' },
}

export function isWorkspaceUnavailable(code: string | undefined): code is keyof typeof UNAVAILABLE {
  return Boolean(code && code in UNAVAILABLE)
}

function LogoutButton() {
  const logout = useEnterpriseLogout()
  return <Button label="Гарах" variant="secondary" icon={<LogOut size={15} />} onClick={() => logout.mutate()} isDisabled={logout.isPending} />
}

/** Suspended/terminated tenant or a session opened on another tenant's domain. */
export function WorkspaceUnavailableScreen({ code }: { code: string }) {
  const copy = UNAVAILABLE[code] ?? UNAVAILABLE.tenant_suspended
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
  const expired = context.license.state === 'expired'
  return <Center minHeight="100dvh" padding={6}>
    <VStack gap={4} width="100%" maxWidth={960}>
      <VStack gap={1}>
        <Heading level={1}>{context.branding.name}</Heading>
        <Text type="supporting">{expired
          ? `Лицензийн хугацаа ${formatDate(context.license.expires_at)}-нд дууссан.`
          : 'Ажлын орон зайг ашиглахын тулд лицензийн түлхүүр идэвхжүүлнэ үү.'}</Text>
      </VStack>
      {isAdmin
        ? <TenantLicenseSettings />
        : <Card padding={6}><Text>Байгууллагын админ лицензийг идэвхжүүлсний дараа ажлын орон зай нээгдэнэ.</Text></Card>}
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
    toast(isAdmin
      ? `Лицензийн хугацаа дууссан. ${formatDate(graceEnds)} хүртэл сунгалтын түлхүүрээ идэвхжүүлнэ үү (Тохиргоо → Лиценз).`
      : `Байгууллагын лицензийн хугацаа дууссан. ${formatDate(graceEnds)}-наас хойш хандалт хаагдана.`, { icon: '⚠️', duration: 8000 })
  }, [graceEnds, isAdmin, state])
}
