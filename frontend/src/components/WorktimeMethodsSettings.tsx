import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Switch } from '@astryxdesign/core/Switch'
import { VStack } from '@astryxdesign/core/VStack'
import { useUpdateWorktimeMethods, useWorktimeMethods, type WorktimeMethods } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { useTranslation } from 'react-i18next'

/** Admin on/off switches for QR and location based office check-in. */
export function WorktimeMethodsSettings() {
  const { t } = useTranslation()
  const methods = useWorktimeMethods()
  const update = useUpdateWorktimeMethods()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const serverSeconds = methods.data?.qr_rotation_seconds
  const [seconds, setSeconds] = useState<number | null>(null)
  useEffect(() => { if (serverSeconds != null) setSeconds(serverSeconds) }, [serverSeconds])
  if (methods.isError) return <Banner status="error" title={t('st.wtm.loadFailed')} collapsible={false} />
  if (!methods.data) return <Skeleton height={96} />
  const { qr_enabled: qr, location_enabled: location } = methods.data
  const save = async (input: Partial<WorktimeMethods>) => {
    try { await update.mutateAsync(input); toast.success(t('st.wtm.updated')) } catch { toast.error(t('st.wtm.notSaved')) }
  }
  const disabledMessage = canEdit ? undefined : t('st.wtm.adminOnly')
  return <VStack gap={3}>
    <Switch
      label={t('st.wtm.qr')}
      description={t('st.wtm.qrHint')}
      value={qr}
      changeAction={(checked) => save({ qr_enabled: checked })}
      isDisabled={!canEdit}
      disabledMessage={disabledMessage}
    />
    {qr && <NumberInput
      label={t('st.wtm.rotation')}
      description={t('st.wtm.rotationHint')}
      value={seconds ?? 30}
      onChange={(value) => setSeconds(value)}
      min={15}
      max={300}
      step={5}
      units={t('st.wtm.secUnit')}
      isDisabled={!canEdit}
    />}
    {qr && canEdit && seconds != null && seconds !== methods.data.qr_rotation_seconds && <div><Button label={t('st.wtm.saveRotation')} isDisabled={!Number.isInteger(seconds) || seconds < 15 || seconds > 300 || update.isPending} onClick={() => save({ qr_rotation_seconds: seconds })} /></div>}
    <Switch
      label={t('st.wtm.location')}
      description={t('st.wtm.locationHint')}
      value={location}
      changeAction={(checked) => save({ location_enabled: checked })}
      isDisabled={!canEdit}
      disabledMessage={disabledMessage}
    />
    {!qr && !location && <Banner status="warning" title={t('st.wtm.noVerifyTitle')} description={t('st.wtm.noVerifyDesc')} collapsible={false} />}
    {qr && !location && <Banner status="info" title={t('st.wtm.qrOnlyTitle')} description={t('st.wtm.qrOnlyDesc')} collapsible={false} />}
  </VStack>
}
