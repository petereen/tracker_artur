import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Divider } from '@astryxdesign/core/Divider'
import { Grid } from '@astryxdesign/core/Grid'
import { HStack } from '@astryxdesign/core/HStack'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Switch } from '@astryxdesign/core/Switch'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Timestamp } from '@astryxdesign/core/Timestamp'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  autoWorktimeErrorCode,
  useAutoWorktimeSettings,
  useDeleteWorktimeSite,
  useSaveWorktimeSite,
  useUpdateAutoWorktimeSettings,
  useWorktimeSites,
  type AutoWorktimeMode,
  type AutoWorktimeSettings,
  type WorktimeSite,
  type WorktimeSiteInput,
} from '../api/worktimeAuto'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { DialogScrollBody } from './DialogScrollBody'
import { WorktimeLocationLog } from './WorktimeLocationLog'
import { WorktimeMapPicker } from './WorktimeMapPicker'

type SiteRow = WorktimeSite & Record<string, unknown>
type Numbers = Pick<AutoWorktimeSettings, 'exit_grace_minutes' | 'min_accuracy_meters' | 'geo_retention_days'>
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/
const NEW_SITE: WorktimeSiteInput = { name: '', latitude: 47.9184, longitude: 106.9177, radius_meters: 150, is_active: true, schedule_start: null, schedule_end: null }

/** The employer's own acknowledgement: tracking location is the organization's decision and duty. */
function EmployerDisclaimerDialog({ mode, onClose, onConfirm, isSaving }: { mode: AutoWorktimeMode; onClose: () => void; onConfirm: () => void; isSaving: boolean }) {
  const { t } = useTranslation()
  const [accepted, setAccepted] = useState(false)
  return <Dialog isOpen onOpenChange={(open) => { if (!open && !isSaving) onClose() }} purpose="form" width={560}>
    <DialogHeader title={t('wta.adm.employerTitle')} subtitle={t(`wta.adm.mode.${mode}`)} />
    <DialogScrollBody label={t('wta.adm.employerTitle')} actions={<>
      <Button label={t('wta.adm.cancel')} variant="ghost" onClick={onClose} isDisabled={isSaving} />
      <Button label={t('wta.adm.employerConfirm')} variant="primary" isDisabled={!accepted} isLoading={isSaving} onClick={onConfirm} />
    </>}>
      <Text>{t('wta.adm.employerIntro')}</Text>
      {(['notice', 'voluntary', 'access', 'retention', 'law'] as const).map((item) => <Text key={item}>• {t(`wta.adm.employer.${item}`)}</Text>)}
      <CheckboxInput label={t('wta.adm.employerAccept')} value={accepted} onChange={setAccepted} />
    </DialogScrollBody>
  </Dialog>
}

function SiteDialog({ site, onClose }: { site: WorktimeSite | null; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveWorktimeSite()
  const [draft, setDraft] = useState<WorktimeSiteInput>(() => site ? { ...site } : NEW_SITE)
  const [scheduled, setScheduled] = useState(Boolean(site?.schedule_start && site?.schedule_end))
  const [start, setStart] = useState(site?.schedule_start ?? '07:00')
  const [end, setEnd] = useState(site?.schedule_end ?? '20:00')
  const timesValid = !scheduled || (TIME.test(start) && TIME.test(end))
  const valid = draft.name.trim().length > 0 && Number.isFinite(draft.latitude) && Number.isFinite(draft.longitude) && draft.radius_meters >= 25 && draft.radius_meters <= 5000 && timesValid

  const submit = async () => {
    try {
      await save.mutateAsync({ ...draft, id: site?.id, name: draft.name.trim(), schedule_start: scheduled ? start : null, schedule_end: scheduled ? end : null })
      toast.success(t('wta.adm.siteSaved'))
      onClose()
    } catch (error) {
      toast.error(autoWorktimeErrorCode(error) === 'worktime_site_limit' ? t('wta.adm.siteLimit') : t('wta.adm.siteNotSaved'))
    }
  }

  return <Dialog isOpen onOpenChange={(open) => { if (!open && !save.isPending) onClose() }} purpose="form" width={640}>
    <DialogHeader title={site ? t('wta.adm.editSite') : t('wta.adm.addSite')} />
    <DialogScrollBody label={site ? t('wta.adm.editSite') : t('wta.adm.addSite')} actions={<>
      <Button label={t('wta.adm.cancel')} variant="ghost" onClick={onClose} isDisabled={save.isPending} />
      <Button label={t('wta.adm.saveSite')} variant="primary" isDisabled={!valid} isLoading={save.isPending} onClick={() => { void submit() }} />
    </>}>
      <TextInput label={t('wta.adm.siteName')} value={draft.name} onChange={(name) => setDraft({ ...draft, name })} placeholder={t('wta.adm.siteNamePlaceholder')} isRequired />
      <WorktimeMapPicker latitude={draft.latitude} longitude={draft.longitude} radiusMeters={draft.radius_meters} disabled={save.isPending}
        onChange={({ latitude, longitude }) => setDraft({ ...draft, latitude: Number(latitude.toFixed(6)), longitude: Number(longitude.toFixed(6)) })} />
      <Grid columns={{ minWidth: 180 }} gap={3}>
        <NumberInput label={t('wta.adm.latitude')} value={draft.latitude} min={-90} max={90} step={0.0001} onChange={(latitude) => setDraft({ ...draft, latitude })} />
        <NumberInput label={t('wta.adm.longitude')} value={draft.longitude} min={-180} max={180} step={0.0001} onChange={(longitude) => setDraft({ ...draft, longitude })} />
        <NumberInput label={t('wta.adm.radius')} value={draft.radius_meters} min={25} max={5000} step={25} units={t('wta.unit.m')} onChange={(radius_meters) => setDraft({ ...draft, radius_meters })} />
      </Grid>
      <Text type="supporting">{t('wta.adm.radiusHint')}</Text>
      <Switch label={t('wta.adm.schedule')} description={t('wta.adm.scheduleHint')} value={scheduled} onChange={setScheduled} />
      {scheduled && <Grid columns={2} gap={3}>
        <TextInput label={t('wta.adm.scheduleStart')} value={start} onChange={setStart} placeholder="07:00" status={TIME.test(start) ? undefined : { type: 'error', message: t('wta.adm.timeFormat') }} />
        <TextInput label={t('wta.adm.scheduleEnd')} value={end} onChange={setEnd} placeholder="20:00" status={TIME.test(end) ? undefined : { type: 'error', message: t('wta.adm.timeFormat') }} />
      </Grid>}
      <Switch label={t('wta.adm.siteActive')} value={draft.is_active} onChange={(is_active) => setDraft({ ...draft, is_active })} />
    </DialogScrollBody>
  </Dialog>
}

function SitesPanel({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation()
  const sites = useWorktimeSites()
  const remove = useDeleteWorktimeSite()
  const [editing, setEditing] = useState<WorktimeSite | 'new' | null>(null)
  const removeSite = (site: WorktimeSite) => {
    if (!window.confirm(t('wta.adm.deleteSiteConfirm', { name: site.name }))) return
    remove.mutate(site.id, { onSuccess: () => toast.success(t('wta.adm.siteDeleted')), onError: () => toast.error(t('wta.adm.siteNotDeleted')) })
  }
  return <VStack gap={2}>
    <HStack gap={3} vAlign="center" hAlign="between" wrap="wrap">
      <VStack gap={0.5}>
        <Text weight="semibold">{t('wta.adm.sites')}</Text>
        <Text type="supporting">{t('wta.adm.sitesHint')}</Text>
      </VStack>
      {canEdit && <Button size="sm" label={t('wta.adm.addSite')} icon={<Plus size={15} />} onClick={() => setEditing('new')} />}
    </HStack>
    {sites.isError && <Banner status="error" title={t('wta.adm.sitesLoadFailed')} collapsible={false} />}
    {sites.isLoading && <Skeleton height={64} />}
    {sites.data && (sites.data.length === 0
      ? <Banner status="warning" title={t('wta.adm.noSitesTitle')} description={t('wta.adm.noSites')} collapsible={false} />
      : <Table<SiteRow> data={sites.data as SiteRow[]} idKey="id" density="compact" columns={[
        { key: 'name', header: t('wta.adm.siteName'), width: proportional(3), renderCell: (record) => <Text weight="medium">{record.name}</Text> },
        { key: 'radius_meters', header: t('wta.adm.radius'), width: pixel(110), renderCell: (record) => <Text type="supporting">{record.radius_meters} {t('wta.unit.m')}</Text> },
        { key: 'schedule', header: t('wta.adm.schedule'), width: pixel(150), renderCell: (record) => <Text type="supporting">{record.schedule_start && record.schedule_end ? `${record.schedule_start}–${record.schedule_end}` : t('wta.adm.anyTime')}</Text> },
        { key: 'is_active', header: t('wta.adm.status'), width: pixel(120), renderCell: (record) => <Token size="sm" color={record.is_active ? 'green' : 'gray'} label={record.is_active ? t('wta.adm.active') : t('wta.adm.inactive')} /> },
        ...(canEdit ? [{ key: 'actions', header: '', width: pixel(96), renderCell: (record: SiteRow) => <HStack gap={1}>
          <Button size="sm" variant="ghost" isIconOnly label={t('wta.adm.editSiteAria', { name: record.name })} icon={<Pencil size={14} />} onClick={() => setEditing(record)} />
          <Button size="sm" variant="ghost" isIconOnly label={t('wta.adm.deleteSiteAria', { name: record.name })} icon={<Trash2 size={14} />} isDisabled={remove.isPending} onClick={() => removeSite(record)} />
        </HStack> }] : []),
      ]} />)}
    {editing && <SiteDialog site={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </VStack>
}

/** Admin: automatic (geofence) work time — mode, rules, office sites, phones and the event log. */
export function WorktimeAutoSettings() {
  const { t } = useTranslation()
  const settings = useAutoWorktimeSettings()
  const update = useUpdateAutoWorktimeSettings()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const [numbers, setNumbers] = useState<Numbers | null>(null)
  const [pendingMode, setPendingMode] = useState<AutoWorktimeMode | null>(null)
  const data = settings.data
  useEffect(() => {
    if (data) setNumbers({ exit_grace_minutes: data.exit_grace_minutes, min_accuracy_meters: data.min_accuracy_meters, geo_retention_days: data.geo_retention_days })
  }, [data])

  if (settings.isError) return <Banner status="error" title={t('wta.adm.loadFailed')} collapsible={false} />
  if (!data || !numbers) return <Skeleton height={160} />

  const enabled = data.auto_geofence_mode !== 'off'
  const acknowledged = data.employer_disclaimer_ack?.policy_version === data.policy_version
  const dirty = numbers.exit_grace_minutes !== data.exit_grace_minutes || numbers.min_accuracy_meters !== data.min_accuracy_meters || numbers.geo_retention_days !== data.geo_retention_days
  const numbersValid = Object.values(numbers).every((value) => Number.isInteger(value))

  const saveMode = async (mode: AutoWorktimeMode, acknowledge: boolean) => {
    try {
      await update.mutateAsync({ auto_geofence_mode: mode, acknowledge_employer_disclaimer: acknowledge || undefined })
      toast.success(t(`wta.adm.modeSaved.${mode}`))
      setPendingMode(null)
    } catch (error) {
      if (autoWorktimeErrorCode(error) === 'employer_disclaimer_required') setPendingMode(mode)
      else toast.error(t('wta.adm.notSaved'))
    }
  }
  const changeMode = (mode: AutoWorktimeMode) => {
    if (mode === data.auto_geofence_mode) return
    if (mode !== 'off' && !acknowledged) setPendingMode(mode)
    else void saveMode(mode, false)
  }
  const saveNumbers = async () => {
    try { await update.mutateAsync(numbers); toast.success(t('wta.adm.saved')) } catch { toast.error(t('wta.adm.notSaved')) }
  }

  return <VStack gap={4}>
    <Text type="supporting">{t('wta.adm.intro')}</Text>
    <VStack gap={1.5}>
      <Switch label={t('wta.adm.switchLabel')} description={t('wta.adm.switchHint')} value={enabled} isDisabled={!canEdit || update.isPending} onChange={(next) => changeMode(next ? 'on' : 'off')} />
      {enabled && <SegmentedControl label={t('wta.adm.modeLabel')} value={data.auto_geofence_mode} isDisabled={!canEdit || update.isPending} onChange={(value) => changeMode(value as AutoWorktimeMode)}>
        <SegmentedControlItem value="shadow" label={t('wta.adm.mode.shadow')} />
        <SegmentedControlItem value="on" label={t('wta.adm.mode.on')} />
      </SegmentedControl>}
      <Text type="supporting">{t(`wta.adm.modeHint.${data.auto_geofence_mode}`)}</Text>
      {!canEdit && <Text type="supporting">{t('wta.adm.adminOnly')}</Text>}
    </VStack>
    {data.employer_disclaimer_ack && <Text type="supporting">
      {t('wta.adm.ackBy', { email: data.employer_disclaimer_ack.email })} <Timestamp value={data.employer_disclaimer_ack.acknowledged_at} format="date_time" />
    </Text>}
    {data.auto_geofence_mode !== 'off' && !acknowledged && <Banner status="warning" title={t('wta.adm.reackTitle')} description={t('wta.adm.reack')} collapsible={false} />}

    <Grid columns={{ minWidth: 180 }} gap={3}>
      <NumberInput label={t('wta.adm.grace')} description={t('wta.adm.graceHint')} value={numbers.exit_grace_minutes} min={0} max={120} step={1} units={t('wta.unit.min')} isDisabled={!canEdit} onChange={(exit_grace_minutes) => setNumbers({ ...numbers, exit_grace_minutes })} />
      <NumberInput label={t('wta.adm.accuracy')} description={t('wta.adm.accuracyHint')} value={numbers.min_accuracy_meters} min={10} max={1000} step={10} units={t('wta.unit.m')} isDisabled={!canEdit} onChange={(min_accuracy_meters) => setNumbers({ ...numbers, min_accuracy_meters })} />
      <NumberInput label={t('wta.adm.retention')} description={t('wta.adm.retentionHint')} value={numbers.geo_retention_days} min={7} max={730} step={1} units={t('wta.unit.day')} isDisabled={!canEdit} onChange={(geo_retention_days) => setNumbers({ ...numbers, geo_retention_days })} />
    </Grid>
    {canEdit && dirty && <HStack><Button label={t('wta.adm.save')} variant="primary" isDisabled={!numbersValid} isLoading={update.isPending} onClick={() => { void saveNumbers() }} /></HStack>}

    <Divider />
    <SitesPanel canEdit={canEdit} />
    <Divider />
    <WorktimeLocationLog />

    {pendingMode && <EmployerDisclaimerDialog mode={pendingMode} isSaving={update.isPending} onClose={() => setPendingMode(null)} onConfirm={() => { void saveMode(pendingMode, true) }} />}
  </VStack>
}
