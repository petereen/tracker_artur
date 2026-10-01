import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { IScannerControls } from '@zxing/browser'
import { Camera, CheckCircle2, Coffee, Laptop2, LocateFixed, LogIn, LogOut, MapPin, RefreshCw, ScanLine, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { useClock, useWorktimeMethods, useWorktimeQrClock, type ClockEntry } from '../api/enterprise'
import { WorkdayStartButton } from '../components/WorkdayStartButton'
import i18n from '../i18n'

type ScanResult = { action: string; replayed: boolean; at: string }

function formatTime(value: string | null, timezone = 'Asia/Ulaanbaatar') {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', timeZone: timezone }).format(new Date(value))
}

function formatDuration(minutes: number) {
  const whole = Math.max(0, Math.floor(minutes))
  const hours = Math.floor(whole / 60)
  return hours ? `${hours}${i18n.t('worktime.unit.hour')} ${String(whole % 60).padStart(2, '0')}${i18n.t('worktime.unit.minute')}` : `${whole}${i18n.t('worktime.unit.minute')}`
}

const entryMinutes = (entry: ClockEntry, now: number) => ((entry.ended_at ? new Date(entry.ended_at).getTime() : now) - new Date(entry.started_at).getTime()) / 60_000
const entryLabel = (entry: ClockEntry) => entry.entry_type === 'break' ? i18n.t('worktime.break') : entry.mode === 'remote' ? i18n.t('worktime.remote') : i18n.t('worktime.office')
const scanMessage = (result: ScanResult) => result.replayed ? i18n.t('worktime.scan.alreadyUsed') : result.action === 'clock_out' ? i18n.t('worktime.scan.officeEnded') : result.action === 'switched_to_office' ? i18n.t('worktime.scan.remoteToOffice') : i18n.t('worktime.scan.officeStarted')

function playScanTone() {
  if (navigator.vibrate) navigator.vibrate(80)
  try {
    const audio = new AudioContext()
    const oscillator = audio.createOscillator()
    const gain = audio.createGain()
    oscillator.frequency.value = 880
    gain.gain.value = 0.05
    oscillator.connect(gain).connect(audio.destination)
    oscillator.start()
    oscillator.stop(audio.currentTime + 0.12)
  } catch { /* audio feedback is optional */ }
}

export function WorktimePage() {
  const { t } = useTranslation()
  const clock = useClock()
  const methods = useWorktimeMethods()
  const scan = useWorktimeQrClock()
  const [params, setParams] = useSearchParams()
  const videoRef = useRef<HTMLVideoElement>(null)
  const controlsRef = useRef<IScannerControls | null>(null)
  const handledRef = useRef(false)
  const [scanning, setScanning] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<ScanResult | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const scanRef = useRef(scan)
  scanRef.current = scan
  const qrEnabled = methods.data?.qr_enabled ?? false
  const locationEnabled = methods.data?.location_enabled ?? false

  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(timer) }, [])
  useEffect(() => () => { controlsRef.current?.stop(); controlsRef.current = null }, [])

  const stopScanner = () => {
    controlsRef.current?.stop()
    controlsRef.current = null
    const stream = videoRef.current?.srcObject as MediaStream | null
    stream?.getTracks().forEach((track) => track.stop())
    if (videoRef.current) videoRef.current.srcObject = null
    setScanning(false)
  }

  const startScanner = () => {
    setCameraError(null)
    setLastResult(null)
    handledRef.current = false
    setScanning(true)
  }

  // Dashboard «Оффис эхлэх» lands here with ?scan=1 when QR is the office method.
  useEffect(() => {
    if (params.get('scan') !== '1' || !qrEnabled) return
    startScanner()
    setParams((current) => { const next = new URLSearchParams(current); next.delete('scan'); return next }, { replace: true })
  }, [params, qrEnabled, setParams])
  useEffect(() => { if (!qrEnabled && scanning) stopScanner() }, [qrEnabled, scanning])

  useEffect(() => {
    if (!scanning || !videoRef.current) return
    let cancelled = false
    const video = videoRef.current
    const start = async () => {
      try {
        const { BrowserQRCodeReader } = await import('@zxing/browser')
        if (cancelled) return
        const reader = new BrowserQRCodeReader()
        const controls = await reader.decodeFromConstraints({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } }, video, async (result) => {
          if (!result || handledRef.current) return
          handledRef.current = true
          stopScanner()
          try {
            const value = await scanRef.current.mutateAsync({ token: result.getText(), client_timestamp: new Date().toISOString() })
            const next = { action: value.action, replayed: value.replayed, at: new Date().toISOString() }
            setLastResult(next)
            toast.success(scanMessage(next))
            playScanTone()
          } catch (error: any) {
            const detail = error?.response?.data?.detail
            setCameraError(typeof detail === 'object' ? detail.message : detail || t('worktime.scan.notRegistered'))
          }
        })
        if (cancelled) controls.stop()
        else controlsRef.current = controls
      } catch (error: any) {
        if (cancelled) return
        setScanning(false)
        setCameraError(error?.name === 'NotAllowedError' ? t('worktime.camera.denied') : t('worktime.camera.failed'))
      }
    }
    void start()
    return () => {
      cancelled = true
      controlsRef.current?.stop()
      controlsRef.current = null
      const stream = video.srcObject as MediaStream | null
      stream?.getTracks().forEach((track) => track.stop())
      video.srcObject = null
    }
  }, [scanning])

  const active = clock.data?.active
  const timezone = clock.data?.timezone
  const entries = clock.data?.today_entries ?? []
  const workedMinutes = useMemo(() => entries.filter((entry) => entry.entry_type === 'work').reduce((sum, entry) => sum + entryMinutes(entry, now), 0), [entries, now])
  const officeActive = active?.entry_type === 'work' && active.mode === 'in_person'
  const state = !active ? { label: t('worktime.status.notStarted'), variant: 'neutral' as const } : active.entry_type === 'break' ? { label: t('worktime.break'), variant: 'warning' as const } : active.mode === 'remote' ? { label: t('worktime.status.remote'), variant: 'accent' as const } : { label: t('worktime.status.office'), variant: 'success' as const }
  const plainStart = methods.isSuccess && !qrEnabled && !locationEnabled

  return <div className="worktime-page">
    <Card padding={5}>
      <VStack gap={4}>
        <HStack gap={4} hAlign="between" vAlign="center" wrap="wrap">
          <VStack gap={1}>
            <HStack gap={2} vAlign="center"><StatusDot variant={state.variant} label={state.label} isPulsing={Boolean(active && active.entry_type === 'work')} /><Text type="label" weight="semibold">{state.label}</Text></HStack>
            <Heading level={2}>{active ? t('worktime.activeSince', { time: formatTime(active.started_at, timezone), duration: formatDuration(entryMinutes(active, now)) }) : t('worktime.startDay')}</Heading>
            <Text type="supporting">{active ? t('worktime.hint.scanAgainToEnd') : qrEnabled && locationEnabled ? t('worktime.hint.qrOrLocation') : qrEnabled ? t('worktime.hint.qrOnly') : locationEnabled ? t('worktime.hint.locationOnly') : t('worktime.hint.pressToStart')}</Text>
          </VStack>
          <HStack gap={2} wrap="wrap" vAlign="center">
            {qrEnabled && !scanning && <Button variant={active && !officeActive ? 'secondary' : 'primary'} label={officeActive ? t('worktime.action.scanToEnd') : t('worktime.action.scan')} icon={officeActive ? <LogOut size={16} /> : <ScanLine size={16} />} onClick={startScanner} isDisabled={scan.isPending || active?.entry_type === 'break'} tooltip={active?.entry_type === 'break' ? t('worktime.action.endBreakFirst') : undefined} />}
            {(locationEnabled || plainStart) && !active && <WorkdayStartButton className={qrEnabled ? 'secondary-action' : 'primary-action'}>{plainStart ? <><LogIn size={16} />{t('worktime.action.start')}</> : <><LocateFixed size={16} />{t('worktime.action.startByLocation')}</>}</WorkdayStartButton>}
          </HStack>
        </HStack>
        <Grid columns={{ minWidth: 140 }} gap={3}>
          <VStack gap={0.5}><Text type="supporting">{t('worktime.workedToday')}</Text><Text type="large" weight="semibold" hasTabularNumbers>{formatDuration(workedMinutes)}</Text></VStack>
          <VStack gap={0.5}><Text type="supporting">{t('worktime.entries')}</Text><Text type="large" weight="semibold" hasTabularNumbers>{entries.length}</Text></VStack>
          <VStack gap={0.5}><Text type="supporting">{t('worktime.method')}</Text><HStack gap={1} wrap="wrap">{methods.isLoading ? <Skeleton width={90} height={22} /> : <>{qrEnabled && <Token size="sm" color="blue" label="QR" />}{locationEnabled && <Token size="sm" color="green" label={t('worktime.method.location')} />}{plainStart && <Token size="sm" label={t('worktime.method.simple')} />}</>}</HStack></VStack>
        </Grid>
      </VStack>
    </Card>
    <div className={qrEnabled ? 'worktime-grid' : undefined}>
      {qrEnabled && <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} hAlign="between" vAlign="center">
            <VStack gap={0.5}><Heading level={3}>{t('worktime.scanTitle')}</Heading><Text type="supporting">{t('worktime.scanSubtitle')}</Text></VStack>
            {scanning && <Button variant="ghost" label={t('worktime.cancel')} icon={<X size={16} />} onClick={stopScanner} />}
          </HStack>
          <div className={`scanner-viewport ${scanning ? 'scanning' : ''} ${lastResult && !scanning ? 'scanned' : ''}`}>
            {scanning ? <><video ref={videoRef} autoPlay muted playsInline onLoadedMetadata={(event) => { void event.currentTarget.play().catch(() => undefined) }} aria-label={t('worktime.cameraLabel')} /><div className="scanner-frame" aria-hidden="true"><i /></div></>
              : lastResult ? <div className="scanner-placeholder"><CheckCircle2 size={44} /><Heading level={3} color="inherit">{scanMessage(lastResult)}</Heading><Text color="inherit">{formatTime(lastResult.at, timezone)}</Text></div>
              : <div className="scanner-placeholder"><Camera size={36} /><Text color="inherit">{t('worktime.scanInstructions')}</Text></div>}
          </div>
          {scanning && <Text type="supporting" justify="center">{t('worktime.frameHint')}</Text>}
          {cameraError && <Banner status="error" title={t('worktime.scan.notRegisteredShort')} description={cameraError} collapsible={false} endContent={<Button size="sm" label={t('worktime.retry')} icon={<RefreshCw size={14} />} onClick={startScanner} />} />}
          {!scanning && <HStack gap={2} hAlign="between" vAlign="center" wrap="wrap">
            <List listStyle="decimal" density="compact">
              <ListItem label={t('worktime.step.aim')} />
              <ListItem label={t('worktime.step.frame')} />
              <ListItem label={t('worktime.step.auto')} />
            </List>
            <Button variant="primary" label={lastResult ? t('worktime.action.scanAgain') : t('worktime.action.openCamera')} icon={<ScanLine size={16} />} onClick={startScanner} isDisabled={scan.isPending} isLoading={scan.isPending} />
          </HStack>}
        </VStack>
      </Card>}
      <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} hAlign="between" vAlign="center"><Heading level={3}>{t('worktime.todayEntries')}</Heading><Text type="supporting" hasTabularNumbers>{formatDuration(workedMinutes)}</Text></HStack>
          {clock.isLoading ? <Skeleton height={120} /> : entries.length ? <List hasDividers density="compact">
            {[...entries].reverse().map((entry) => <ListItem
              key={entry.id}
              label={entryLabel(entry)}
              description={`${formatTime(entry.started_at, timezone)} – ${entry.ended_at ? formatTime(entry.ended_at, timezone) : t('worktime.now')}`}
              startContent={entry.entry_type === 'break' ? <Coffee size={16} /> : entry.mode === 'remote' ? <Laptop2 size={16} /> : <MapPin size={16} />}
              endContent={entry.ended_at ? <Text type="supporting" hasTabularNumbers>{formatDuration(entryMinutes(entry, now))}</Text> : <Token size="sm" color="green" label={t('worktime.qr.active')} />}
            />)}
          </List> : <EmptyState isCompact title={t('worktime.noEntries')} description={qrEnabled ? t('worktime.noEntriesQr') : t('worktime.noEntriesStart')} icon={<Coffee size={24} />} />}
        </VStack>
      </Card>
    </div>
  </div>
}

export default WorktimePage
