import { useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Building2, Layers, LogOut, ScrollText, Server, ShieldCheck, Users } from 'lucide-react'
import { AppShell } from '@astryxdesign/core/AppShell'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Center } from '@astryxdesign/core/Center'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Heading } from '@astryxdesign/core/Heading'
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from '@astryxdesign/core/SideNav'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import { RouterLink } from '../components/budget/shared'
import { type OperatorSession, type TwoFactorChallenge, consoleError, useConsoleSession, useOperatorLogin } from './consoleApi'
import { TwoFactorSetup, TwoFactorVerify } from './ConsoleTwoFactor'
import { TenantDetailPage, TenantsPage } from './ConsoleTenants'
import { AuditPage, OperatorsPage, PlansPage, SystemPage } from './ConsoleCatalog'

function ConsoleLogin() {
  const { t } = useTranslation()
  const login = useOperatorLogin()
  const setSession = useConsoleSession((state) => state.setSession)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  // The password alone opens nothing: the second factor issues the session.
  const [challenge, setChallenge] = useState<TwoFactorChallenge | null>(null)
  const submit = async () => {
    try {
      const result = await login.mutateAsync({ email, password })
      if (result?.mfa_token) {
        setPassword('')
        setChallenge(result)
      }
    } catch (error) {
      toast.error(consoleError(error, t('con.login.failed')))
    }
  }
  const openConsole = (session: OperatorSession) => setSession(session.access_token, session.operator, session.expires_in)
  return <Center minHeight="100dvh" padding={6}>
    <Card padding={6} width="100%" maxWidth={challenge?.two_factor === 'setup' ? 520 : 420}>
      {challenge?.two_factor === 'setup' && <TwoFactorSetup mfaToken={challenge.mfa_token} onSession={openConsole} onRestart={() => setChallenge(null)} />}
      {challenge?.two_factor === 'verify' && <TwoFactorVerify mfaToken={challenge.mfa_token} onSession={openConsole} onRestart={() => setChallenge(null)} />}
      {!challenge && <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <VStack gap={4}>
          <VStack gap={1}>
            <Heading level={1}>{t('con.title')}</Heading>
            <Text type="supporting">{t('con.login.notice')}</Text>
          </VStack>
          <FormLayout>
            <TextInput label={t('con.email')} value={email} onChange={setEmail} type="email" isRequired hasAutoFocus />
            <TextInput label={t('con.password')} value={password} onChange={setPassword} type="password" isRequired />
          </FormLayout>
          <Button label={t('con.signIn')} variant="primary" type="submit" isDisabled={!email || !password || login.isPending} />
        </VStack>
      </form>}
    </Card>
  </Center>
}

function ConsoleShell() {
  const { t } = useTranslation()
  const operator = useConsoleSession((state) => state.operator)
  const logout = useConsoleSession((state) => state.logout)
  const queryClient = useQueryClient()
  const { pathname } = useLocation()
  const items = [
    { to: '/platform', label: t('con.nav.tenants'), icon: Building2, selected: pathname === '/platform' || pathname.startsWith('/platform/tenants') },
    { to: '/platform/plans', label: t('con.nav.plans'), icon: Layers, selected: pathname.startsWith('/platform/plans') },
    { to: '/platform/audit', label: t('con.nav.audit'), icon: ScrollText, selected: pathname.startsWith('/platform/audit') },
    { to: '/platform/system', label: t('con.nav.system'), icon: Server, selected: pathname.startsWith('/platform/system') },
    ...(operator?.role === 'superadmin' ? [{ to: '/platform/operators', label: t('con.nav.operators'), icon: Users, selected: pathname.startsWith('/platform/operators') }] : []),
  ]
  const signOut = () => {
    queryClient.removeQueries({ queryKey: ['console'] })
    logout()
  }
  return <AppShell contentPadding={6} sideNav={
    <SideNav
      header={<SideNavHeading icon={<ShieldCheck size={16} aria-hidden />} heading="OYUNS ERP" subheading={t('con.subtitle')} />}
      footer={<VStack gap={2}>
        <Text type="supporting" maxLines={1}>{`${operator?.email ?? ''} · ${operator?.role === 'superadmin' ? 'Superadmin' : t('con.supportRole')}`}</Text>
        <Button label={t('con.signOut')} variant="ghost" size="sm" icon={<LogOut size={14} />} onClick={signOut} />
      </VStack>}>
      <SideNavSection title={t('con.navSection')} isHeaderHidden>
        {items.map((item) => <SideNavItem key={item.to} label={item.label} icon={<item.icon size={16} aria-hidden />} href={item.to} as={RouterLink} isSelected={item.selected} />)}
      </SideNavSection>
    </SideNav>
  }>
    <Routes>
      <Route index element={<TenantsPage />} />
      <Route path="tenants/:tenantId" element={<TenantDetailPage />} />
      <Route path="plans" element={<PlansPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="system" element={<SystemPage />} />
      <Route path="operators" element={operator?.role === 'superadmin' ? <OperatorsPage /> : <Navigate to="/platform" replace />} />
      <Route path="*" element={<Navigate to="/platform" replace />} />
    </Routes>
  </AppShell>
}

/** `/platform/*` — the isolated superadmin console (separate login and token). */
export default function ConsoleApp() {
  const token = useConsoleSession((state) => state.token)
  return token ? <ConsoleShell /> : <ConsoleLogin />
}
