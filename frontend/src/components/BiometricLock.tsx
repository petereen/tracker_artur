import { type ReactNode, useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Fingerprint, LogOut } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import { useEnterpriseLogout } from '../api/enterprise'
import { authenticateBiometric, biometricAvailability, isBiometricLockEnabled, setBiometricLockEnabled, type BiometricAvailability } from '../platform/biometric'
import { isNativePlatform } from '../platform/runtime'
import { InitialWorkspaceSkeleton } from './Loading'

/**
 * App lock for the native app: Face ID / fingerprint (or the phone's screen
 * lock) on a cold start only; returning from recent apps never locks it. `active` is false while
 * signed out, so the login screen is never behind the lock. The session
 * itself stays in the Keychain/Keystore; this only gates the screen.
 */
export function BiometricLockGate({ children, active = true }: { children: ReactNode; active?: boolean }) {
  const { t } = useTranslation()
  const logout = useEnterpriseLogout()
  const [locked, setLocked] = useState(() => isNativePlatform() && isBiometricLockEnabled())
  const [prompting, setPrompting] = useState(false)

  const unlock = useCallback(async () => {
    setPrompting(true)
    try {
      // The phone lost its screen lock since the app lock was switched on:
      // there is nothing to verify against, so do not trap the user.
      const availability = await biometricAvailability()
      if (!availability.deviceSecure) {
        setBiometricLockEnabled(false)
        setLocked(false)
        return
      }
      if (await authenticateBiometric(t('wta.lock.reason'), t('wta.lock.title'))) setLocked(false)
    } finally {
      setPrompting(false)
    }
  }, [t])

  // Nothing to protect while signed out (login screen): the lock waits for a session.
  useEffect(() => { if (!active) setLocked(false) }, [active])

  useEffect(() => {
    if (locked && active) void unlock()
    // Prompt once when the lock appears; "Unlock" retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locked, active])

  if (!active || !locked) return children
  return <>
    <InitialWorkspaceSkeleton />
    <Dialog isOpen onOpenChange={() => undefined} purpose="required" width={360}>
      <DialogHeader title={t('wta.lock.title')} subtitle={t('wta.lock.subtitle')} />
      <VStack gap={3} padding={4}>
        <Button label={t('wta.lock.unlock')} variant="primary" icon={<Fingerprint size={16} />} isLoading={prompting} onClick={() => { void unlock() }} />
        <Button label={t('action.logout')} variant="ghost" icon={<LogOut size={14} />} isDisabled={logout.isPending} onClick={() => logout.mutate()} />
      </VStack>
    </Dialog>
  </>
}

/** Profile: switch the app lock on or off for this phone. */
export function BiometricLockCard() {
  const { t } = useTranslation()
  const [availability, setAvailability] = useState<BiometricAvailability | null>(null)
  const [enabled, setEnabled] = useState(isBiometricLockEnabled)

  useEffect(() => {
    let cancelled = false
    void biometricAvailability().then((value) => { if (!cancelled) setAvailability(value) })
    return () => { cancelled = true }
  }, [])

  // Web, or a binary without the biometric plugin.
  if (!isNativePlatform() || !availability || (!availability.available && !availability.deviceSecure && !enabled)) return null

  const change = async (next: boolean) => {
    // Both directions need proof: switching it off is what an intruder would do.
    if (!(await authenticateBiometric(t('wta.lock.reason'), t('wta.lock.title')))) {
      toast.error(t('wta.lock.notConfirmed'))
      return
    }
    setBiometricLockEnabled(next)
    setEnabled(next)
    toast.success(t(next ? 'wta.lock.on' : 'wta.lock.off'))
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center"><Fingerprint size={18} aria-hidden /><Heading level={3}>{t('wta.lock.cardTitle')}</Heading></HStack>
      <Switch label={t('wta.lock.switch')} description={availability.available ? t('wta.lock.switchHint') : t('wta.lock.passcodeOnly')}
        value={enabled} changeAction={change} isDisabled={!availability.deviceSecure} disabledMessage={t('wta.lock.noScreenLock')}
        labelPosition="start" labelSpacing="spread" width="100%" />
      {!availability.deviceSecure && <Text type="supporting">{t('wta.lock.noScreenLock')}</Text>}
    </VStack>
  </Card>
}
