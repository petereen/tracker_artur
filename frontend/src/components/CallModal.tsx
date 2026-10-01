import { useTranslation } from 'react-i18next'
import { useEffect, useRef } from 'react'
import { Camera, CameraOff, Mic, MicOff, Phone, PhoneOff, Volume2, VolumeX } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import type { useWebRTC } from '../hooks/useWebRTC'
import { resolvePublicAssetUrl } from '../platform/runtime'

type CallController = ReturnType<typeof useWebRTC>

function formatDuration(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function CallAvatar({ name, avatar }: { name: string; avatar?: string | null }) {
  return <div className="call-avatar">{avatar ? <img src={resolvePublicAssetUrl(avatar) || undefined} alt="" /> : <span>{name.slice(0, 2).toUpperCase()}</span>}</div>
}

export function CallModal({ call, onOpenConversation }: { call: CallController; onOpenConversation: () => void }) {
  const { t } = useTranslation()
  const remoteVideo = useRef<HTMLVideoElement>(null)
  const remoteAudio = useRef<HTMLAudioElement>(null)
  const localVideo = useRef<HTMLVideoElement>(null)
  const dialog = useRef<HTMLElement>(null)
  useEffect(() => {
    if (remoteVideo.current) remoteVideo.current.srcObject = call.remoteStream
    if (remoteAudio.current) {
      remoteAudio.current.srcObject = call.remoteStream
      void remoteAudio.current.play().catch(() => undefined)
    }
    return () => {
      if (remoteVideo.current) remoteVideo.current.srcObject = null
      if (remoteAudio.current) remoteAudio.current.srcObject = null
    }
  }, [call.remoteStream])
  useEffect(() => {
    if (localVideo.current) {
      localVideo.current.srcObject = call.localStream
      void localVideo.current.play().catch(() => undefined)
    }
    return () => { if (localVideo.current) localVideo.current.srcObject = null }
  }, [call.localStream, call.videoMuted])
  useEffect(() => {
    if (!call.activeCall || call.state === 'idle') return
    const previous = document.activeElement as HTMLElement | null
    dialog.current?.querySelector<HTMLElement>('button')?.focus()
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled)') || [])]
      if (!items.length) return event.preventDefault()
      const first = items[0]; const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', trap)
    return () => { document.removeEventListener('keydown', trap); previous?.focus?.() }
  }, [call.activeCall, call.state])
  const active = call.activeCall
  const visible = Boolean(active && call.state !== 'idle')
  if (!active) return null
  const connected = ['connecting', 'connected', 'reconnecting'].includes(call.state)
  const status = call.state === 'incoming_ring' ? t(active.callType === 'video' ? 'chat.call.video' : 'chat.call.audio') : call.state === 'outgoing_ring' ? t('chat.call.ringing') : call.state === 'connecting' ? t('chat.call.connecting') : call.state === 'reconnecting' ? t('chat.call.reconnecting') : call.state === 'connected' ? formatDuration(call.durationSeconds) : t('chat.call.finished')
  const hasRemoteVideo = Boolean(call.remoteStream?.getVideoTracks().some((track) => track.enabled))
  const hasLocalVideo = Boolean(call.localStream?.getVideoTracks().some((track) => track.enabled))
  return <AnimatePresence>{visible && <motion.div className="call-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
    <motion.section ref={dialog} onPointerDown={() => { void remoteAudio.current?.play().catch(() => undefined) }} className={`call-modal ${connected ? 'active' : 'ringing'}`} role="dialog" aria-modal="true" aria-label={t('chat.call.withName', { name: active.name })} initial={{ opacity: 0, scale: .96, y: 14 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .98 }} transition={{ type: 'spring', stiffness: 420, damping: 34 }}>
      {connected ? <div className="call-stage">
        <audio ref={remoteAudio} data-call-audio autoPlay />
        {hasRemoteVideo ? <video ref={remoteVideo} autoPlay muted playsInline className="call-remote-video" /> : <div className="call-audio-stage"><CallAvatar name={active.name} avatar={active.avatar} /></div>}
        <button className="call-identity" onClick={onOpenConversation}><strong>{active.name}</strong><span>{status}</span></button>
        {hasLocalVideo && <video ref={localVideo} autoPlay muted playsInline className="call-local-video" />}
      </div> : <div className="call-ringing-content">
        <button className="call-avatar-pulse" onClick={onOpenConversation}><i /><CallAvatar name={active.name} avatar={active.avatar} /></button>
        <h2>{active.name}</h2><p>{status}</p> 
      </div>}
      {call.error && <p className="call-error" role="alert">{call.error}</p>}
      <div className="call-controls">
        {call.state === 'incoming_ring' ? <><button className="call-control accept" onClick={call.accept}><Phone /><span>{t('chat.call.accept')}</span></button><button className="call-control end" onClick={call.decline}><PhoneOff /><span>{t('chat.call.decline')}</span></button></> : call.state === 'outgoing_ring' ? <button className="call-control end" onClick={() => call.end('canceled')}><PhoneOff /><span>{t('chat.call.cancel')}</span></button> : connected ? <>
          <button className={`call-control ${call.audioMuted ? 'off' : ''}`} onClick={call.toggleMuteAudio}>{call.audioMuted ? <MicOff /> : <Mic />}<span>{call.audioMuted ? t('chat.call.unmute') : t('chat.call.mute')}</span></button>
          <button className={`call-control ${call.audioRoute === 'speaker' ? 'active' : ''}`} onClick={call.switchAudioRoute}>{call.audioRoute === 'speaker' ? <VolumeX /> : <Volume2 />}<span>{call.audioRoute === 'speaker' ? t('chat.call.earpiece') : t('chat.call.speaker')}</span></button>
          <button className={`call-control ${call.videoMuted ? 'off' : ''}`} onClick={call.toggleMuteVideo}>{call.videoMuted ? <CameraOff /> : <Camera />}<span>{hasLocalVideo ? t('chat.call.cameraOff') : t('chat.call.cameraOn')}</span></button>
          <button className="call-control end" onClick={() => call.end()}><PhoneOff /><span>{t('chat.call.end')}</span></button>
        </> : null}
      </div>
      {connected && call.devices.length > 0 && <div className="call-device-controls">
        <select aria-label={t('chat.call.pickMic')} onChange={(event) => call.switchMediaDevice('audioinput', event.target.value)} defaultValue=""><option value="" disabled>{t('chat.call.mic')}</option>{call.devices.filter((item) => item.kind === 'audioinput').map((item) => <option key={item.deviceId} value={item.deviceId}>{item.label || t('chat.call.mic')}</option>)}</select>
        <select aria-label={t('chat.call.pickCamera')} onChange={(event) => call.switchMediaDevice('videoinput', event.target.value)} defaultValue=""><option value="" disabled>{t('chat.call.camera')}</option>{call.devices.filter((item) => item.kind === 'videoinput').map((item) => <option key={item.deviceId} value={item.deviceId}>{item.label || t('chat.call.camera')}</option>)}</select>
      </div>}
    </motion.section>
  </motion.div>}</AnimatePresence>
}
