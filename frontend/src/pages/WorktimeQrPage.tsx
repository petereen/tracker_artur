import { useEffect, useRef, useState } from 'react'
import { Maximize2, MonitorUp, RefreshCw, ShieldAlert, Wifi, WifiOff } from 'lucide-react'
import { QRCodeCanvas } from 'qrcode.react'
import { usePairWorktimeQrKiosk, useWorktimeQrDisplayToken } from '../api/enterprise'

export function WorktimeQrPage() {
  const display = useWorktimeQrDisplayToken()
  const pair = usePairWorktimeQrKiosk()
  const [code, setCode] = useState('')
  const [now, setNow] = useState(Date.now())
  const [pipAvailable, setPipAvailable] = useState(false)
  const qrRef = useRef<HTMLCanvasElement>(null)
  const pipVideoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    setPipAvailable(Boolean(document.pictureInPictureEnabled && HTMLVideoElement.prototype.requestPictureInPicture))
    return () => window.clearInterval(timer)
  }, [])

  const data = display.data
  const offset = data ? new Date(data.server_time).getTime() - Date.now() : 0
  const remaining = data ? Math.max(0, new Date(data.expires_at).getTime() - (now + offset)) : 0
  const total = data ? Math.max(1, new Date(data.expires_at).getTime() - new Date(data.issued_at).getTime()) : 30_000
  const progress = Math.min(100, Math.max(0, remaining / total * 100))
  const hasUsableToken = Boolean(data && remaining > 0)
  const displayError = display.error as any
  const detail = displayError?.response?.data?.detail
  const pairingRequired = !data && (display.isError || detail?.code === 'kiosk_pairing_required' || detail?.code === 'kiosk_revoked')

  const pairDisplay = async (event: React.FormEvent) => {
    event.preventDefault()
    await pair.mutateAsync(code.trim().toUpperCase())
    setCode('')
  }

  const fullscreen = () => document.documentElement.requestFullscreen?.().catch(() => undefined)
  const pictureInPicture = async () => {
    const canvas = qrRef.current
    const video = pipVideoRef.current
    if (!canvas || !video || !video.requestPictureInPicture) return
    const stream = canvas.captureStream?.(5)
    if (!stream) return
    video.srcObject = stream
    await video.play()
    await video.requestPictureInPicture()
  }

  if (pairingRequired) return <main className="worktime-kiosk-stage"><section className="kiosk-pair-card panel"><div className="kiosk-brand"><img src="/favicon.png" alt="OYUNS" /></div><span className="eyebrow">OYUNS WORKTIME DISPLAY</span><h1>Дэлгэц холбох</h1><p>Администраторын үүсгэсэн 8 тэмдэгттэй pairing кодыг оруулна уу.</p><form onSubmit={pairDisplay}><input value={code} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8))} autoComplete="one-time-code" inputMode="text" placeholder="ABCD2345" aria-label="Pairing код" /><button className="primary-action" disabled={pair.isPending || code.length !== 8}>{pair.isPending ? 'Холбож байна…' : 'Дэлгэц холбох'}</button></form>{pair.isError && <div className="worktime-alert error" role="alert"><ShieldAlert size={17} />{(pair.error as any)?.response?.data?.detail?.message || 'Код буруу эсвэл хугацаа дууссан байна.'}</div>}</section></main>

  return <main className="worktime-kiosk-stage"><section className="worktime-kiosk-display"><header><div><span className="eyebrow">OYUNS WORKTIME</span><h1>{data?.display_name || 'Оффисын цаг'}</h1><p>{data?.location_id || 'main_office'}</p></div><span className={`kiosk-connectivity ${display.isError ? 'offline' : ''}`}>{display.isError ? <><WifiOff size={16} />Offline</> : <><Wifi size={16} />Live</>}</span></header><div className="kiosk-qr-shell">{hasUsableToken ? <QRCodeCanvas ref={qrRef} value={data!.token} size={Math.min(560, Math.max(260, Math.round(window.innerWidth * 0.38)))} level="H" includeMargin bgColor="#ffffff" fgColor="#0B172A" /> : <><ShieldAlert size={48} /><span>{display.isFetching ? 'Шинэ QR код ачаалж байна…' : 'QR кодын хугацаа дууссан. Холболтыг шалгаж байна…'}</span></>}</div><div className="kiosk-countdown"><strong>{hasUsableToken ? `${Math.ceil(remaining / 1000)}s` : '—'}</strong><span>Дараагийн код хүртэл</span><div className="kiosk-progress"><i style={{ width: `${progress}%` }} /></div></div><p className="kiosk-hint">{hasUsableToken ? 'Энэ QR кодыг ажилтны OYUNS Worktime scanner-аар уншуулна уу.' : 'Хугацаа дууссан кодыг уншуулах боломжгүй.'}</p><footer><button className="kiosk-control" onClick={fullscreen}><Maximize2 size={17} />Fullscreen</button>{pipAvailable && hasUsableToken && <button className="kiosk-control" onClick={pictureInPicture}><MonitorUp size={17} />PiP</button>}<span>{display.isFetching ? 'Шинэчилж байна…' : display.isError ? 'Холболтыг шалгаж байна…' : 'Динамик хамгаалалт идэвхтэй'}</span></footer><video ref={pipVideoRef} muted playsInline className="pip-video" aria-hidden="true" /></section></main>
}

export default WorktimeQrPage
