import { forwardRef, memo, useEffect, useRef, useState } from 'react'
import { Maximize2, MonitorUp, ShieldAlert, Wifi, WifiOff } from 'lucide-react'
import { QRCodeCanvas } from 'qrcode.react'
import { usePairWorktimeQrKiosk, useWorktimeQrDisplayToken, type WorktimeQrDisplayToken } from '../api/enterprise'

const qrSizeFor = () => Math.min(480, Math.max(240, Math.round(Math.min(window.innerWidth * 0.62, window.innerHeight * 0.5))))

// Redraws only when the token or size changes, never on timer ticks.
const KioskQr = memo(forwardRef<HTMLCanvasElement, { value: string; size: number }>(function KioskQr({ value, size }, ref) {
  return <QRCodeCanvas ref={ref} value={value} size={size} level="M" marginSize={2} bgColor="#ffffff" fgColor="#0B172A" />
}))

// Owns the 1s tick so the QR and the rest of the page stay untouched.
function KioskCountdown({ expiresAt, issuedAt, offset, active }: { expiresAt?: string; issuedAt?: string; offset: number; active: boolean }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  const end = expiresAt ? new Date(expiresAt).getTime() : 0
  const total = expiresAt && issuedAt ? Math.max(1, end - new Date(issuedAt).getTime()) : 30_000
  const remaining = active ? Math.max(0, end - (Date.now() + offset)) : 0
  return <div className="kiosk-countdown"><strong>{active ? `${Math.ceil(remaining / 1000)}s` : '—'}</strong><span>Дараагийн код хүртэл</span><div className="kiosk-progress">{active && <i style={{ transform: `scaleX(${Math.max(0, Math.min(1, (remaining - 1000) / total))})` }} />}</div></div>
}

export function WorktimeQrPage() {
  const display = useWorktimeQrDisplayToken()
  const pair = usePairWorktimeQrKiosk()
  const [code, setCode] = useState('')
  const [serverOffset, setServerOffset] = useState(0)
  const [pipAvailable, setPipAvailable] = useState(false)
  const [qrSize, setQrSize] = useState(qrSizeFor)
  const [, setExpiryTick] = useState(0)
  const qrRef = useRef<HTMLCanvasElement>(null)
  const pipVideoRef = useRef<HTMLVideoElement>(null)
  const fetched = display.data
  // The next code is fetched a few seconds early and held back; the displayed
  // code only swaps at the instant the current one expires.
  const [shown, setShown] = useState<WorktimeQrDisplayToken | undefined>()
  const [next, setNext] = useState<WorktimeQrDisplayToken | undefined>()
  const data = shown

  useEffect(() => {
    if (!fetched || fetched.token === shown?.token || fetched.token === next?.token) return
    const shownLive = shown && new Date(shown.expires_at).getTime() - (Date.now() + serverOffset) > 0
    if (shownLive) setNext(fetched)
    else { setShown(fetched); setNext(undefined) }
  }, [fetched?.token])

  useEffect(() => {
    setPipAvailable(Boolean(document.pictureInPictureEnabled && HTMLVideoElement.prototype.requestPictureInPicture))
    let timer: number | undefined
    const onResize = () => { window.clearTimeout(timer); timer = window.setTimeout(() => setQrSize(qrSizeFor()), 300) }
    window.addEventListener('resize', onResize)
    return () => { window.clearTimeout(timer); window.removeEventListener('resize', onResize) }
  }, [])

  useEffect(() => {
    if (fetched?.token) setServerOffset(new Date(fetched.server_time).getTime() - Date.now())
  }, [fetched?.token, fetched?.server_time])

  // One re-render exactly when the current code expires.
  useEffect(() => {
    if (!data) return
    const delay = new Date(data.expires_at).getTime() - (Date.now() + serverOffset)
    const timer = window.setTimeout(() => {
      if (next) { setShown(next); setNext(undefined) }
      setExpiryTick((value) => value + 1)
    }, Math.max(0, delay))
    return () => window.clearTimeout(timer)
  }, [data?.token, data?.expires_at, next, serverOffset])

  const remaining = data ? Math.max(0, new Date(data.expires_at).getTime() - (Date.now() + serverOffset)) : 0
  const displayError = display.error as any
  const detail = displayError?.response?.data?.detail
  const pairingRequired = detail?.code === 'kiosk_pairing_required' || detail?.code === 'kiosk_revoked'
  const hasUsableToken = Boolean(data && remaining > 0 && !pairingRequired)

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

  if (detail?.code === 'worktime_qr_disabled') return <main className="worktime-kiosk-stage"><section className="kiosk-pair-card panel"><div className="kiosk-brand"><img src="/favicon.png" alt="OYUNS" /></div><span className="eyebrow">OYUNS WORKTIME DISPLAY</span><h1>QR бүртгэл түр хаалттай</h1><p>Администратор QR-аар цаг бүртгэх боломжийг хаасан байна. Тохиргоонд дахин нээгдэхэд энэ дэлгэц автоматаар QR харуулна.</p></section></main>
  if (pairingRequired) return <main className="worktime-kiosk-stage"><section className="kiosk-pair-card panel"><div className="kiosk-brand"><img src="/favicon.png" alt="OYUNS" /></div><span className="eyebrow">OYUNS WORKTIME DISPLAY</span><h1>Дэлгэц холбох</h1><p>Администраторын үүсгэсэн 8 тэмдэгттэй pairing кодыг оруулна уу.</p><form onSubmit={pairDisplay}><input value={code} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8))} autoComplete="one-time-code" inputMode="text" placeholder="ABCD2345" aria-label="Pairing код" /><button className="primary-action" disabled={pair.isPending || code.length !== 8}>{pair.isPending ? 'Холбож байна…' : 'Дэлгэц холбох'}</button></form>{pair.isError && <div className="worktime-alert error" role="alert"><ShieldAlert size={17} />{(pair.error as any)?.response?.data?.detail?.message || 'Код буруу эсвэл хугацаа дууссан байна.'}</div>}</section></main>

  return <main className="worktime-kiosk-stage"><section className="worktime-kiosk-display"><header><div><span className="eyebrow">OYUNS WORKTIME</span><h1>{data?.display_name || 'Оффисын цаг'}</h1><p>{data?.location_id || 'main_office'}</p></div><span className={`kiosk-connectivity ${display.isError ? 'offline' : ''}`}>{display.isError ? <><WifiOff size={16} />Offline</> : <><Wifi size={16} />Live</>}</span></header><div className="kiosk-qr-shell" style={{ width: qrSize, height: qrSize }}>{hasUsableToken ? <KioskQr ref={qrRef} value={data!.token} size={qrSize} /> : <div className="kiosk-qr-placeholder"><ShieldAlert size={40} /><span>{display.isFetching ? 'Шинэ QR код ачаалж байна…' : display.isError ? 'Сүлжээг шалгаж байна…' : 'Холболтыг шалгаж байна…'}</span></div>}</div><KioskCountdown expiresAt={data?.expires_at} issuedAt={data?.issued_at} offset={serverOffset} active={hasUsableToken} /><p className="kiosk-hint">{hasUsableToken ? 'Энэ QR кодыг ажилтны OYUNS Worktime scanner-аар уншуулна уу.' : 'Хугацаа дууссан кодыг уншуулах боломжгүй.'}</p><footer><button className="kiosk-control" onClick={fullscreen}><Maximize2 size={17} />Fullscreen</button>{pipAvailable && hasUsableToken && <button className="kiosk-control" onClick={pictureInPicture}><MonitorUp size={17} />PiP</button>}<span>{display.isFetching ? 'Шинэчилж байна…' : display.isError ? 'Холболтыг шалгаж байна…' : 'Идэвхтэй'}</span></footer><video ref={pipVideoRef} muted playsInline className="pip-video" aria-hidden="true" /></section></main>
}

export default WorktimeQrPage
