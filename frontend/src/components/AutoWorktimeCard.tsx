import { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { MapPinned } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Heading } from '@astryxdesign/core/Heading'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { Timestamp } from '@astryxdesign/core/Timestamp'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  autoWorktimeErrorCode,
  updateDeviceState,
  useAcceptConsent,
  useAutoWorktimeStatus,
  useConsentText,
  useEnrollDevice,
  useRevokeConsent,
  type GeoEvent,
} from '../api/worktimeAuto'
import { authenticateBiometric, biometricAvailability } from '../platform/biometric'
import {
  deviceState,
  disableGeofence,
  enrollGeofence,
  geofencePlatform,
  geofenceSupported,
  getGeofenceStatus,
  openBackgroundSettings,
  openLocationSettings,
  requestBatteryExemption,
  requestGeofencePermissions,
  type GeofenceStatus,
} from '../platform/geofence'
import { isNativePlatform } from '../platform/runtime'
import { DialogScrollBody } from './DialogScrollBody'

const RESULT_KEYS: Record<string, string> = {
  started: 'wta.result.started',
  stopped: 'wta.result.stopped',
  pending_stop: 'wta.result.pendingStop',
  'shadow:start': 'wta.result.shadowStart',
  'shadow:stop': 'wta.result.shadowStop',
  'ignored:mock_location': 'wta.result.mock',
  'ignored:low_accuracy': 'wta.result.lowAccuracy',
  'ignored:position_mismatch': 'wta.result.mismatch',
  'ignored:stale': 'wta.result.stale',
  'ignored:manual_stop': 'wta.result.manualStop',
  'ignored:remote_session': 'wta.result.remote',
  'ignored:outside_schedule': 'wta.result.outsideSchedule',
  'ignored:returned': 'wta.result.returned',
}

/** Text for what the rules did with one reported transition. */
export function geoResultKey(result: string) {
  return RESULT_KEYS[result] ?? 'wta.result.ignored'
}

export function geoKindKey(kind: GeoEvent['kind']) {
  return `wta.kind.${kind}`
}

function StatusRow({ label, ok, okLabel, problem, action }: { label: string; ok: boolean; okLabel: string; problem: string; action?: React.ReactNode }) {
  const { t } = useTranslation()
  return <div className={ok ? 'wta-status-row' : 'wta-status-row is-problem'}>
    <div className="wta-status-main">
      <Text weight="semibold">{label}</Text>
      <Token size="sm" color={ok ? 'green' : 'yellow'} label={ok ? okLabel : t('wta.status.attention')} />
    </div>
    {!ok && <Text>{problem}</Text>}
    {!ok && action && <div className="wta-status-action">{action}</div>}
  </div>
}

function ConsentDialog({ onClose, onAccepted }: { onClose: () => void; onAccepted: () => Promise<void> }) {
  const { t, i18n } = useTranslation()
  const text = useConsentText((i18n.resolvedLanguage ?? i18n.language).split('-')[0], true)
  const accept = useAcceptConsent()
  const [read, setRead] = useState(false)
  const [working, setWorking] = useState(false)

  const agree = async () => {
    if (!text.data) return
    setWorking(true)
    try {
      // Whoever holds the unlocked phone must not be able to consent for its owner.
      if ((await biometricAvailability()).deviceSecure && !(await authenticateBiometric(t('wta.consent.confirmReason'), t('wta.title')))) {
        toast.error(t('wta.consent.notConfirmed'))
        return
      }
      await accept.mutateAsync({ text: text.data, app_platform: geofencePlatform() ?? 'web' })
      await onAccepted()
    } catch (error) {
      toast.error(autoWorktimeErrorCode(error) === 'consent_text_changed' ? t('wta.consent.changed') : t('wta.consent.failed'))
    } finally {
      setWorking(false)
    }
  }

  return <Dialog isOpen onOpenChange={(open) => { if (!open && !working) onClose() }} purpose="form" width={560}>
    <DialogHeader title={t('wta.consent.title')} subtitle={t('wta.consent.subtitle')} />
    <DialogScrollBody label={t('wta.consent.title')} actions={<>
      <Button label={t('wta.consent.decline')} variant="ghost" onClick={onClose} isDisabled={working} />
      <Button label={t('wta.consent.agree')} variant="primary" isDisabled={!read || !text.data} isLoading={working} onClick={() => { void agree() }} />
    </>}>
      {text.isError && <Banner status="error" title={t('wta.consent.loadFailed')} collapsible={false} />}
      {text.isLoading && <Skeleton height={240} />}
      {text.data && text.data.text.split('\n\n').map((paragraph, index) => index === 0
        ? <Heading key={index} level={4}>{paragraph}</Heading>
        : <Text key={index}>{paragraph.split('\n').map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}{line}</span>)}</Text>)}
      <Banner status="info" title={t('wta.consent.optionalTitle')} description={t('wta.consent.optional')} collapsible={false} />
      <CheckboxInput label={t('wta.consent.read')} value={read} onChange={setRead} isDisabled={!text.data} />
    </DialogScrollBody>
  </Dialog>
}

/** Worktime (app only) and Profile: the employee's own switch for automatic (geofence) work time on this phone. */
export function AutoWorktimeCard({ nativeOnly = false }: { nativeOnly?: boolean }) {
  const { t } = useTranslation()
  const status = useAutoWorktimeStatus()
  const enroll = useEnrollDevice()
  const revoke = useRevokeConsent()
  const [supported, setSupported] = useState<boolean | null>(null)
  const [native, setNative] = useState<GeofenceStatus | null>(null)
  const [consentOpen, setConsentOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const readNative = useCallback(async () => {
    const value = await getGeofenceStatus().catch(() => null)
    setNative(value)
    return value
  }, [])

  useEffect(() => {
    let cancelled = false
    void geofenceSupported().then((value) => { if (!cancelled) setSupported(value) })
    void readNative()
    return () => { cancelled = true }
  }, [readNative])

  const data = status.data
  // Only people without an employee record have nothing to switch.
  // Live location only exists in the mobile/tablet app; on the web the worktime page has nothing to offer.
  if (!data || !data.employee_linked || (nativeOnly && !isNativePlatform())) return null

  const deviceId = data.device?.id
  const report = async (value: GeofenceStatus | null) => {
    if (value && deviceId) await updateDeviceState(deviceId, deviceState(value)).catch(() => undefined)
    await status.refetch()
  }

  /** Permissions → device credential → native monitoring. */
  const turnOnThisPhone = async () => {
    setBusy(true)
    try {
      const permitted = await requestGeofencePermissions()
      setNative(permitted)
      if (permitted.permission !== 'always') {
        toast.error(t('wta.permission.alwaysNeeded'))
        return
      }
      const platform = geofencePlatform()
      if (!platform) return
      const enrollment = await enroll.mutateAsync({ platform, ...deviceState(permitted) })
      const configured = await enrollGeofence(enrollment.credential)
      setNative(configured)
      toast.success(t('wta.enabled'))
      if (!configured.batteryUnrestricted) setNative(await requestBatteryExemption())
      await status.refetch()
    } catch (error) {
      const code = autoWorktimeErrorCode(error)
      toast.error(code === 'worktime_auto_disabled' ? t('wta.disabledByOrg') : t('wta.enableFailed'))
    } finally {
      setBusy(false)
    }
  }

  const turnOff = async () => {
    if (!window.confirm(t('wta.offConfirm'))) return
    setBusy(true)
    try {
      await revoke.mutateAsync()
      await disableGeofence().catch(() => undefined)
      await readNative()
      toast.success(t('wta.disabled'))
    } catch {
      toast.error(t('wta.disableFailed'))
    } finally {
      setBusy(false)
    }
  }

  const fix = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      await report(await readNative())
    } finally {
      setBusy(false)
    }
  }

  const onThisPhone = Boolean(native?.enrolled && data.device)
  const android = geofencePlatform() === 'android'
  const consented = Boolean(data.consent)
  // Turning on needs the organization's switch and a phone that can run the geofence; withdrawing is always possible.
  const switchDisabled = busy || (!consented && (data.mode === 'off' || supported !== true))
  const changeSwitch = (next: boolean) => {
    if (next) setConsentOpen(true)
    else void turnOff()
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <div className="wta-head">
        <MapPinned size={20} aria-hidden />
        <Heading level={3}>{t('wta.title')}</Heading>
        {data.mode === 'shadow' && <Token size="sm" color="yellow" label={t('wta.mode.shadow')} />}
        {onThisPhone && data.mode === 'on' && <Token size="sm" color="green" label={t('wta.active')} />}
      </div>
      <Text>{t('wta.intro')}</Text>

      <div className="wta-panel wta-switch-panel">
        <Switch label={t('wta.switch.label')} description={t('wta.switch.hint')} value={consented} onChange={changeSwitch} isDisabled={switchDisabled} />
      </div>

      {data.mode === 'off' && (consented
        ? <Banner status="info" title={t('wta.offByOrgTitle')} description={t('wta.offByOrg')} collapsible={false} />
        : <Banner status="info" title={t('wta.offByOrgNoConsentTitle')} description={t('wta.offByOrgNoConsent')} collapsible={false} />)}
      {data.mode === 'shadow' && <Banner status="info" title={t('wta.shadowTitle')} description={t('wta.shadowHint')} collapsible={false} />}

      {supported === false && <Banner status="info" collapsible={false}
        title={isNativePlatform() ? t('wta.updateAppTitle') : t('wta.mobileOnlyTitle')}
        description={isNativePlatform() ? t('wta.updateApp') : t('wta.mobileOnly')} />}

      {supported && data.mode !== 'off' && consented && !onThisPhone && <VStack gap={3}>
        {data.device && <Banner status="warning" title={t('wta.otherPhoneTitle')} description={t('wta.otherPhone')} collapsible={false} />}
        <Button label={data.device ? t('wta.useThisPhone') : t('wta.turnOn')} variant="primary" isLoading={busy}
          onClick={() => { void turnOnThisPhone() }} />
      </VStack>}

      {supported && onThisPhone && native && <section className="wta-section" aria-labelledby="wta-phone-title">
        <Heading level={4} id="wta-phone-title">{t('wta.phone.title')}</Heading>
        <div className="wta-panel">
          <StatusRow label={t('wta.permission.label')} ok={native.permission === 'always'} okLabel={t('wta.permission.always')} problem={t('wta.permission.alwaysNeeded')}
            action={<Button size="sm" label={t('wta.permission.fix')} isLoading={busy} onClick={() => { void fix(async () => { const next = await requestGeofencePermissions(); if (next.permission !== 'always') await openLocationSettings() }) }} />} />
          <StatusRow label={t('wta.accuracy.label')} ok={native.accuracy === 'precise'} okLabel={t('wta.accuracy.precise')} problem={t('wta.accuracy.needed')}
            action={<Button size="sm" label={t('wta.openSettings')} onClick={() => { void fix(openLocationSettings) }} />} />
          {android && <StatusRow label={t('wta.battery.label')} ok={native.batteryUnrestricted} okLabel={t('wta.battery.unrestricted')} problem={t('wta.battery.needed')}
            action={<Button size="sm" label={t('wta.battery.allow')} isLoading={busy} onClick={() => { void fix(requestBatteryExemption) }} />} />}
          {android && <div className="wta-status-row">
            <Text type="supporting">{t('wta.battery.vendorHint')}</Text>
            <div className="wta-status-action"><Button size="sm" variant="secondary" label={t('wta.battery.vendor')} onClick={() => { void openBackgroundSettings() }} /></div>
          </div>}
        </div>
        {native.lastError === 'device_revoked' && <Banner status="warning" title={t('wta.revokedTitle')} description={t('wta.revoked')} collapsible={false} />}
      </section>}

      {data.recent_events.length > 0 && <section className="wta-section" aria-labelledby="wta-recent-title">
        <Heading level={4} id="wta-recent-title">{t('wta.recent')}</Heading>
        <ul className="wta-events">
          {data.recent_events.slice(0, 5).map((event) => <li key={event.id}>
            <Text weight="medium">{t(geoResultKey(event.result))}</Text>
            <Text type="supporting">{t(geoKindKey(event.kind))}{event.site_name ? ` · ${event.site_name}` : ''} · <Timestamp value={event.occurred_at} format="date_time" /></Text>
          </li>)}
        </ul>
      </section>}

      {data.consent && <Text type="supporting">{t('wta.consentGiven', { days: data.geo_retention_days })} <Timestamp value={data.consent.accepted_at} format="date" /></Text>}
    </VStack>
    {consentOpen && <ConsentDialog onClose={() => setConsentOpen(false)} onAccepted={async () => { setConsentOpen(false); await turnOnThisPhone() }} />}
  </Card>
}
