import { useEffect, useRef, useState } from 'react'
import { BrowserQRCodeReader, type IScannerControls } from '@zxing/browser'
import { Camera, CheckCircle2, Clock3, Coffee, Laptop2, MapPin, RefreshCw, ScanLine, ShieldAlert } from 'lucide-react'
import toast from 'react-hot-toast'
import { useClock, useWorktimeQrClock } from '../api/enterprise'

function formatTime(value: string | null, timezone = 'Asia/Ulaanbaatar') {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', timeZone: timezone }).format(new Date(value))
}

export function WorktimePage() {
  const clock = useClock()
  const scan = useWorktimeQrClock()
  const videoRef = useRef<HTMLVideoElement>(null)
  const controlsRef = useRef<IScannerControls | null>(null)
  const handledRef = useRef(false)
  const [scanning, setScanning] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<{ action: string; replayed: boolean } | null>(null)

  useEffect(() => () => { controlsRef.current?.stop(); controlsRef.current = null }, [])

  const stopScanner = () => {
    controlsRef.current?.stop()
    controlsRef.current = null
    const stream = videoRef.current?.srcObject as MediaStream | null
    stream?.getTracks().forEach((track) => track.stop())
    if (videoRef.current) videoRef.current.srcObject = null
    setScanning(false)
  }

  const startScanner = async () => {
    setCameraError(null)
    setLastResult(null)
    handledRef.current = false
    setScanning(true)
    try {
      const reader = new BrowserQRCodeReader()
      const controls = await reader.decodeFromConstraints({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } }, videoRef.current!, async (result) => {
        if (!result || handledRef.current) return
        handledRef.current = true
        stopScanner()
        try {
          const value = await scan.mutateAsync({ token: result.getText(), client_timestamp: new Date().toISOString() })
          setLastResult({ action: value.action, replayed: value.replayed })
          toast.success(value.action === 'clock_out' ? 'Оффисын цаг дууслаа' : value.action === 'switched_to_office' ? 'Оффисын цаг эхэллээ' : 'Оффисын цаг бүртгэгдлээ')
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
        } catch (error: any) {
          const detail = error?.response?.data?.detail
          setCameraError(typeof detail === 'object' ? detail.message : detail || 'QR код бүртгэгдсэнгүй')
        }
      })
      controlsRef.current = controls
    } catch (error: any) {
      setScanning(false)
      setCameraError(error?.name === 'NotAllowedError' ? 'Камер ашиглах зөвшөөрөл олгогдоогүй байна.' : 'Камер нээж чадсангүй. HTTPS холболт болон камерын тохиргоог шалгана уу.')
    }
  }

  const active = clock.data?.active
  const timezone = clock.data?.timezone
  return <div className="worktime-page">
    <section className="worktime-hero panel">
      <div><span className="eyebrow">WORKTIME / ATTENDANCE</span><h2>Ажлын цагийн бүртгэл</h2><p>Оффисын дэлгэц дээрх одоогийн QR кодыг уншуулж цаг бүртгэнэ.</p></div>
      <div className={`worktime-state ${active ? 'active' : ''}`}><Clock3 size={17} /><span>{active ? active.mode === 'remote' ? 'Remote ажиллаж байна' : active.entry_type === 'break' ? 'Завсарлага' : 'Оффист ажиллаж байна' : 'Идэвхтэй цаг алга'}</span></div>
    </section>
    <div className="worktime-grid">
      <section className="worktime-scanner panel">
        <div className="panel-heading"><div><span className="eyebrow">QR SCANNER</span><h2>Оффисын QR уншуулах</h2></div><ScanLine size={22} /></div>
        <div className={`scanner-viewport ${scanning ? 'scanning' : ''}`}>
          {scanning ? <><video ref={videoRef} autoPlay muted playsInline aria-label="Оффисын QR камер" /><div className="scanner-frame" aria-hidden="true" /></> : <div className="scanner-placeholder"><Camera size={32} /><span>Камер нээж, дэлгэц дээрх QR код руу чиглүүлнэ үү.</span></div>}
        </div>
        {cameraError && <div className="worktime-alert error" role="alert"><ShieldAlert size={17} />{cameraError}</div>}
        {lastResult && <div className="worktime-alert success" role="status"><CheckCircle2 size={17} /><span>{lastResult.replayed ? 'Давхар хүсэлт баталгаажлаа.' : lastResult.action === 'clock_out' ? 'Оффисын цаг дууслаа.' : lastResult.action === 'switched_to_office' ? 'Remote цаг хаагдаж, оффисын цаг эхэллээ.' : 'Оффисын цаг эхэллээ.'} Дахин бүртгэхийн тулд товчийг дахин дарна уу.</span></div>}
        <div className="scanner-actions">{scanning ? <button className="secondary-action" onClick={stopScanner}><RefreshCw size={16} />Болих</button> : <button className="primary-action" onClick={startScanner} disabled={scan.isPending}><ScanLine size={16} />QR уншуулах</button>}</div>
      </section>
      <section className="worktime-today panel">
        <div className="panel-heading"><div><span className="eyebrow">TODAY</span><h2>Өнөөдрийн интервал</h2></div><Coffee size={21} /></div>
        <div className="worktime-intervals">{clock.isLoading ? <p className="text-muted">Ачаалж байна…</p> : (clock.data?.today_entries ?? []).map((entry) => <div className="worktime-interval" key={entry.id}><span className={`interval-icon ${entry.entry_type}`}><>{entry.entry_type === 'break' ? <Coffee size={15} /> : entry.mode === 'remote' ? <Laptop2 size={15} /> : <MapPin size={15} />}</></span><div><strong>{entry.entry_type === 'break' ? 'Завсарлага' : entry.mode === 'remote' ? 'Remote' : 'Оффис'}</strong><small>{formatTime(entry.started_at, timezone)} – {entry.ended_at ? formatTime(entry.ended_at, timezone) : 'одоо'}</small></div></div>)}{!clock.isLoading && !clock.data?.today_entries.length && <p className="text-muted">Өнөөдөр бүртгэл алга байна.</p>}</div>
      </section>
    </div>
  </div>
}

export default WorktimePage
