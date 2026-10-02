import { useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { Timestamp } from '@astryxdesign/core/Timestamp'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { useAutoWorktimeSettings, useGeoDevices, useGeoEvents, useMarkGeoEventReviewed, useRevokeGeoDevice, type GeoDevice, type GeoEvent } from '../api/worktimeAuto'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { geoKindKey, geoResultKey } from './AutoWorktimeCard'

type DeviceRow = GeoDevice & Record<string, unknown>
type EventRow = GeoEvent & Record<string, unknown>

function DeviceHealth({ device }: { device: GeoDevice }) {
  const { t } = useTranslation()
  const problems = [
    device.location_permission !== 'always' && t('wta.log.health.permission'),
    device.location_accuracy === 'approximate' && t('wta.log.health.accuracy'),
    device.platform === 'android' && device.battery_unrestricted === false && t('wta.log.health.battery'),
  ].filter(Boolean) as string[]
  if (!problems.length) return <Token size="sm" color="green" label={t('wta.log.health.ok')} />
  return <HStack gap={1} wrap="wrap">{problems.map((problem) => <Token key={problem} size="sm" color="yellow" label={problem} />)}</HStack>
}

/**
 * Enrolled phones and the location event log. Location events are personal
 * data: only administrators and HR may open this, and every read is audited.
 */
export function WorktimeLocationLog() {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const allowed = roles.includes('admin') || roles.includes('hr')
  const isAdmin = roles.includes('admin')
  const [reviewOnly, setReviewOnly] = useState(true)
  const devices = useGeoDevices(allowed)
  const events = useGeoEvents(reviewOnly, allowed)
  const revoke = useRevokeGeoDevice()
  const reviewed = useMarkGeoEventReviewed()
  if (!allowed) return null

  const rows = (events.data?.pages ?? []).flatMap((page) => page.items) as EventRow[]
  const revokeDevice = (device: GeoDevice) => {
    if (!window.confirm(t('wta.log.revokeConfirm', { name: device.employee_name ?? device.email ?? '' }))) return
    revoke.mutate(device.id, { onSuccess: () => toast.success(t('wta.log.revoked')), onError: () => toast.error(t('wta.log.revokeFailed')) })
  }

  return <VStack gap={4}>
    <Banner status="info" title={t('wta.log.privacyTitle')} description={t('wta.log.privacy')} collapsible={false} />

    <VStack gap={2}>
      <Text weight="semibold">{t('wta.log.devices')}</Text>
      {devices.isError && <Banner status="error" title={t('wta.log.loadFailed')} collapsible={false} />}
      {devices.isLoading && <Skeleton height={64} />}
      {devices.data && (devices.data.length === 0
        ? <Text type="supporting">{t('wta.log.noDevices')}</Text>
        : <Table<DeviceRow> data={devices.data as DeviceRow[]} idKey="id" density="compact" columns={[
          { key: 'employee_name', header: t('wta.log.col.employee'), width: proportional(2), renderCell: (record) => <Text>{record.employee_name ?? record.email ?? '—'}</Text> },
          { key: 'platform', header: t('wta.log.col.phone'), width: pixel(110), renderCell: (record) => <Text type="supporting">{record.platform === 'ios' ? 'iPhone' : 'Android'}</Text> },
          { key: 'health', header: t('wta.log.col.health'), width: proportional(2), renderCell: (record) => <DeviceHealth device={record} /> },
          { key: 'last_event_at', header: t('wta.log.col.lastEvent'), width: pixel(170), renderCell: (record) => record.last_event_at ? <Timestamp value={record.last_event_at} format="auto" /> : <Text type="supporting">—</Text> },
          ...(isAdmin ? [{ key: 'actions', header: '', width: pixel(120), renderCell: (record: DeviceRow) => <Button size="sm" variant="ghost" label={t('wta.log.revoke')} isDisabled={revoke.isPending} onClick={() => revokeDevice(record)} /> }] : []),
        ]} />)}
    </VStack>

    <VStack gap={2}>
      <HStack gap={3} vAlign="center" hAlign="between" wrap="wrap">
        <Text weight="semibold">{t('wta.log.events')}</Text>
        <SegmentedControl label={t('wta.log.filter')} size="sm" value={reviewOnly ? 'review' : 'all'} onChange={(value) => setReviewOnly(value === 'review')}>
          <SegmentedControlItem value="review" label={t('wta.log.needsReview')} />
          <SegmentedControlItem value="all" label={t('wta.log.all')} />
        </SegmentedControl>
      </HStack>
      {events.isError && <Banner status="error" title={t('wta.log.loadFailed')} collapsible={false} />}
      {events.isLoading && <Skeleton height={96} />}
      {events.data && (rows.length === 0
        ? <Text type="supporting">{reviewOnly ? t('wta.log.nothingToReview') : t('wta.log.noEvents')}</Text>
        : <Table<EventRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'occurred_at', header: t('wta.log.col.time'), width: pixel(170), renderCell: (record) => <Timestamp value={record.occurred_at} format="date_time" /> },
          { key: 'employee_name', header: t('wta.log.col.employee'), width: proportional(2), renderCell: (record) => <Text>{record.employee_name ?? '—'}</Text> },
          { key: 'kind', header: t('wta.log.col.event'), width: proportional(2), renderCell: (record) => <Text type="supporting">{t(geoKindKey(record.kind))}{record.site_name ? ` · ${record.site_name}` : ''}</Text> },
          { key: 'result', header: t('wta.log.col.result'), width: proportional(3), renderCell: (record) => <HStack gap={1.5} vAlign="center" wrap="wrap">
            <Text>{t(geoResultKey(record.result))}</Text>
            {record.accuracy_meters != null && <Text type="supporting">±{Math.round(record.accuracy_meters)} {t('wta.unit.m')}</Text>}
          </HStack> },
          { key: 'actions', header: '', width: pixel(130), renderCell: (record) => record.needs_review
            ? <Button size="sm" variant="ghost" label={t('wta.log.markReviewed')} isDisabled={reviewed.isPending} onClick={() => reviewed.mutate(record.id, { onError: () => toast.error(t('wta.log.reviewFailed')) })} />
            : null },
        ]} />)}
      {events.hasNextPage && <HStack><Button size="sm" variant="secondary" label={t('wta.log.more')} isLoading={events.isFetchingNextPage} onClick={() => { void events.fetchNextPage() }} /></HStack>}
    </VStack>
  </VStack>
}

/** HR workspace: the same log for HR staff, who have no access to the admin settings. Hidden while the feature is off. */
export function WorktimeLocationLogCard() {
  const { t } = useTranslation()
  const settings = useAutoWorktimeSettings()
  if (!settings.data || settings.data.auto_geofence_mode === 'off') return null
  return <Card padding={5}>
    <VStack gap={4}>
      <Heading level={3}>{t('wta.log.title')}</Heading>
      <WorktimeLocationLog />
    </VStack>
  </Card>
}
