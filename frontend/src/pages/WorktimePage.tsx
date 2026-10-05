import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { IScannerControls } from '@zxing/browser'
import { Camera, CheckCircle2, Coffee, Laptop2, MapPin, RefreshCw, ScanLine } from 'lucide-react'
import toast from 'react-hot-toast'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { useClock, useWorktimeMethods, useWorktimeQrClock, type ClockEntry } from '../api/enterprise'
import { AutoWorktimeCard } from '../components/AutoWorktimeCard'
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
  // True once the first camera frame is playing; until then the viewport shows its own loader instead of the browser's grey play placeholder.
  const [cameraReady, setCameraReady] = useState(false)
  const resumeOnVisibleRef = useRef(false)
  const autoStartedRef = useRef(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<ScanResult | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const scanRef = useRef(scan)
  scanRef.current = scan
  const qrEnabled = methods.data?.qr_enabled ?? false

  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(timer) }, [])
  useEffect(() => () => { controlsRef.current?.stop(); controlsRef.current = null }, [])

  const stopScanner = () => {
    controlsRef.current?.stop()
    controlsRef.current = null
    const stream = videoRef.current?.srcObject as MediaStream | null
    stream?.getTracks().forEach((track) => track.stop())
    if (videoRef.current) videoRef.current.srcObject = null
    setCameraReady(false)
    setScanning(false)
  }

  const startScanner = () => {
    setCameraError(null)
    setLastResult(null)
    setCameraReady(false)
    handledRef.current = false
    setScanning(true)
  }

  // The camera opens as soon as the page does: there is nothing else to do here when QR is the method.
  useEffect(() => {
    if (!qrEnabled || autoStartedRef.current) return
    autoStartedRef.current = true
    startScanner()
  }, [qrEnabled])
  // Older links carried ?scan=1 to open the camera; it is on anyway now.
  useEffect(() => {
    if (params.get('scan') !== '1') return
    setParams((current) => { const next = new URLSearchParams(current); next.delete('scan'); return next }, { replace: true })
  }, [params, setParams])
  useEffect(() => { if (!qrEnabled && scanning) stopScanner() }, [qrEnabled, scanning])

  // The phone suspends the camera in the background; release it, and reopen it on return.
  const scanningRef = useRef(scanning)
  scanningRef.current = scanning
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) {
        if (scanningRef.current) { resumeOnVisibleRef.current = true; stopScanner() }
      } else if (resumeOnVisibleRef.current) {
        resumeOnVisibleRef.current = false
        startScanner()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

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
        setCameraReady(false)
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

  const timezone = clock.data?.timezone
  const entries = clock.data?.today_entries ?? []
  const workedMinutes = useMemo(() => entries.filter((entry) => entry.entry_type === 'work').reduce((sum, entry) => sum + entryMinutes(entry, now), 0), [entries, now])

  return <div className="worktime-page">
    <div className={qrEnabled ? 'worktime-grid' : undefined}>
      {qrEnabled && <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} hAlign="between" vAlign="center">
            <VStack gap={0.5}><Heading level={3}>{t('worktime.scanTitle')}</Heading><Text type="supporting">{t('worktime.scanSubtitle')}</Text></VStack>
            {!scanning && lastResult && <Button variant="secondary" label={t('worktime.action.scanAgain')} icon={<ScanLine size={16} />} onClick={startScanner} isDisabled={scan.isPending} isLoading={scan.isPending} />}
          </HStack>
          <div className={`scanner-viewport ${scanning ? 'scanning' : ''} ${scanning && cameraReady ? 'live' : ''} ${lastResult && !scanning ? 'scanned' : ''}`}>
            {/* Mounted for the whole page life and invisible until it plays, so the browser's grey placeholder never shows. */}
            <video ref={videoRef} autoPlay muted playsInline disablePictureInPicture controls={false} onPlaying={() => setCameraReady(true)} onLoadedMetadata={(event) => { void event.currentTarget.play().catch(() => undefined) }} aria-label={t('worktime.cameraLabel')} />
            {scanning && cameraReady && <div className="scanner-frame" aria-hidden="true"><i /></div>}
            {scanning && !cameraReady && <div className="scanner-placeholder" role="status"><span className="scanner-spinner" aria-hidden="true" /><Text color="inherit">{t('worktime.camera.starting')}</Text></div>}
            {!scanning && lastResult && <div className="scanner-placeholder"><CheckCircle2 size={44} /><Heading level={3} color="inherit">{scanMessage(lastResult)}</Heading><Text color="inherit">{formatTime(lastResult.at, timezone)}</Text></div>}
            {!scanning && !lastResult && <div className="scanner-placeholder"><Camera size={36} /><Text color="inherit">{t('worktime.scanInstructions')}</Text></div>}
          </div>
          {scanning && cameraReady && <Text type="supporting" justify="center">{t('worktime.frameHint')}</Text>}
          {cameraError && <Banner status="error" title={t('worktime.scan.notRegisteredShort')} description={cameraError} collapsible={false} endContent={<Button size="sm" label={t('worktime.retry')} icon={<RefreshCw size={14} />} onClick={startScanner} />} />}
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
    <AutoWorktimeCard nativeOnly />
  </div>
}

export default WorktimePage
