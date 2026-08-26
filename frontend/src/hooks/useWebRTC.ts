import { useCallback, useEffect, useRef, useState } from 'react'
import { io, Socket } from 'socket.io-client'
import type {
  CallIncomingPayload, CallState, CallType, ClientToServerEvents, ServerToClientEvents,
  SignalingAck,
} from '../../../types/call'
import { useAuthStore } from '../store/auth'
import { setCallAudioRoute, type AudioRoute } from '../platform/audio-route'
import { createIncomingRingtone, createOutgoingRingback, SoundEffect } from '../utils/soundEffects'

export interface CallPeer { userId: string; name: string; avatar?: string | null; conversationId: string }
export interface ActiveCall extends CallPeer { callId: string; callType: CallType; incoming: boolean }

const rtcConfiguration = (): RTCConfiguration => {
  const iceServers: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }]
  const urls = String(import.meta.env.VITE_TURN_URLS || '').split(',').map((value) => value.trim()).filter(Boolean)
  if (urls.length) iceServers.push({ urls, username: import.meta.env.VITE_TURN_USERNAME || undefined, credential: import.meta.env.VITE_TURN_CREDENTIAL || undefined })
  return { iceServers, bundlePolicy: 'max-bundle', iceCandidatePoolSize: 4 }
}

export function mediaErrorMessage(error: unknown) {
  const name = error instanceof DOMException ? error.name : (error as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Камер эсвэл микрофоны зөвшөөрөл хаалттай байна. Browser settings-ээс зөвшөөрнө үү.'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'Камер эсвэл микрофон олдсонгүй. Төхөөрөмжөө холбоод дахин оролдоно уу.'
  if (name === 'NotReadableError' || name === 'TrackStartError') return 'Камер эсвэл микрофоныг өөр програм ашиглаж байна.'
  return 'Дуудлагын медиа эхлүүлж чадсангүй.'
}

export function useWebRTC() {
  const token = useAuthStore((state) => state.token)
  const ownUserId = String(useAuthStore((state) => state.actor?.id || ''))
  const [state, setState] = useState<CallState>('idle')
  const [activeCall, setActiveCall] = useState<ActiveCall | null>(null)
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [audioMuted, setAudioMuted] = useState(false)
  const [audioRoute, setAudioRoute] = useState<AudioRoute>('default')
  const [videoMuted, setVideoMuted] = useState(false)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [signalingConnected, setSignalingConnected] = useState(false)
  const [onlineUsers, setOnlineUsers] = useState<Record<string, boolean>>({})
  const [durationSeconds, setDurationSeconds] = useState(0)
  const socketRef = useRef<Socket<ServerToClientEvents, ClientToServerEvents> | null>(null)
  const peerRef = useRef<RTCPeerConnection | null>(null)
  const localRef = useRef<MediaStream | null>(null)
  const callRef = useRef<ActiveCall | null>(null)
  const candidateQueue = useRef<RTCIceCandidateInit[]>([])
  const toneRef = useRef<SoundEffect | null>(null)
  const reconnectTimer = useRef<number>()
  const resetTimer = useRef<number>()
  const connectedAt = useRef<number>()
  const makingOffer = useRef(false)
  const ignoreOffer = useRef(false)
  const canNegotiate = useRef(false)
  const accepting = useRef(false)

  useEffect(() => { callRef.current = activeCall }, [activeCall])
  const stopTone = useCallback(() => { const tone = toneRef.current; toneRef.current = null; if (tone) void tone.stop() }, [])

  const teardown = useCallback((nextState: CallState = 'ended') => {
    stopTone()
    if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
    if (resetTimer.current) window.clearTimeout(resetTimer.current)
    reconnectTimer.current = undefined
    resetTimer.current = undefined
    candidateQueue.current = []
    canNegotiate.current = false
    makingOffer.current = false
    ignoreOffer.current = false
    accepting.current = false
    const peer = peerRef.current
    peerRef.current = null
    if (peer) {
      peer.onicecandidate = null; peer.ontrack = null; peer.onconnectionstatechange = null; peer.onnegotiationneeded = null
      peer.close()
    }
    localRef.current?.getTracks().forEach((track) => track.stop())
    localRef.current = null
    void setCallAudioRoute('default').catch(() => undefined)
    setLocalStream(null); setRemoteStream(null); setAudioMuted(false); setAudioRoute('default'); setVideoMuted(false); setDurationSeconds(0)
    connectedAt.current = undefined
    setState(nextState)
  }, [stopTone])

  const emitDescription = useCallback(async (type: 'offer' | 'answer', sdp: RTCSessionDescriptionInit) => {
    const call = callRef.current
    if (call) socketRef.current?.emit(`call:${type}`, { callId: call.callId, targetUserId: call.userId, sdp })
  }, [])

  const negotiate = useCallback(async (iceRestart = false) => {
    const peer = peerRef.current
    if (!peer || !canNegotiate.current || makingOffer.current) return
    try {
      makingOffer.current = true
      const offer = await peer.createOffer({ iceRestart })
      if (peer.signalingState !== 'stable') return
      await peer.setLocalDescription(offer)
      await emitDescription('offer', peer.localDescription!)
    } catch { setError('Дуудлагын холболтыг тохируулж чадсангүй.') }
    finally { makingOffer.current = false }
  }, [emitDescription])

  const ensurePeer = useCallback(() => {
    if (peerRef.current) return peerRef.current
    const peer = new RTCPeerConnection(rtcConfiguration())
    peerRef.current = peer
    localRef.current?.getTracks().forEach((track) => peer.addTrack(track, localRef.current!))
    peer.onicecandidate = (event) => {
      const call = callRef.current
      if (event.candidate && call) socketRef.current?.emit('call:ice-candidate', { callId: call.callId, targetUserId: call.userId, candidate: event.candidate.toJSON() })
    }
    peer.ontrack = (event) => setRemoteStream((current) => {
      // Browsers normally provide one shared stream for the audio and video
      // tracks. Clone it on every event: the browser may mutate the same
      // MediaStream object when the second track arrives, which would leave
      // React with the same object identity and prevent the video element
      // from mounting after audio connected first.
      const source = event.streams[0] || current
      const stream = new MediaStream(source?.getTracks() || [])
      if (!stream.getTracks().some((track) => track.id === event.track.id)) stream.addTrack(event.track)
      return stream
    })
    peer.onnegotiationneeded = () => void negotiate()
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === 'connected') {
        if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
        connectedAt.current = connectedAt.current || Date.now()
        setState('connected')
        const call = callRef.current
        if (call) socketRef.current?.emit('call:connected', { callId: call.callId })
      } else if (peer.connectionState === 'disconnected') {
        setState('reconnecting')
        void negotiate(true)
        if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
        reconnectTimer.current = window.setTimeout(() => {
          const call = callRef.current
          if (call) socketRef.current?.emit('call:end', { callId: call.callId, targetUserId: call.userId, durationSeconds: 0, reason: 'ice_timeout' })
          teardown()
        }, 15_000)
      } else if (peer.connectionState === 'failed' || peer.connectionState === 'closed') teardown()
    }
    return peer
  }, [negotiate, teardown])

  const acquireMedia = useCallback(async (callType: CallType) => {
    if (!navigator.mediaDevices?.getUserMedia) throw new DOMException('Media devices are unavailable', 'NotSupportedError')
    await setCallAudioRoute('default')
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: callType === 'video' ? { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' } : false })
    localRef.current = stream
    setLocalStream(stream)
    setDevices(await navigator.mediaDevices.enumerateDevices().catch(() => []))
    return stream
  }, [])

  const finishLocally = useCallback(() => {
    teardown('ended')
    if (resetTimer.current) window.clearTimeout(resetTimer.current)
    resetTimer.current = window.setTimeout(() => { setActiveCall(null); setState('idle'); setError(null) }, 1_500)
  }, [teardown])

  useEffect(() => {
    if (!token) return
    const socket: Socket<ServerToClientEvents, ClientToServerEvents> = io({ path: '/socket.io', auth: { token }, transports: ['websocket', 'polling'], reconnection: true })
    socketRef.current = socket
    socket.on('connect', () => {
      setSignalingConnected(true)
      const call = callRef.current
      if (call) socket.emit('call:resume', { callId: call.callId }, (result) => {
        if (!result.ok) return finishLocally()
        if (peerRef.current?.connectionState === 'connected') setState('connected')
        else if (peerRef.current) setState('connecting')
        else setState(call.incoming ? 'incoming_ring' : 'outgoing_ring')
      })
    })
    socket.on('disconnect', () => { setSignalingConnected(false); if (callRef.current) setState('reconnecting') })
    socket.on('connect_error', () => setSignalingConnected(false))
    socket.on('user:status', ({ userId, isOnline }) => setOnlineUsers((current) => ({ ...current, [userId]: isOnline })))
    socket.on('call:incoming', (payload: CallIncomingPayload) => {
      if (callRef.current) { socket.emit('call:reject', { callId: payload.callId, targetUserId: payload.callerId, reason: 'busy' }); return }
      const call: ActiveCall = { callId: payload.callId, conversationId: payload.conversationId, userId: payload.callerId, name: payload.callerName, avatar: payload.callerAvatar, callType: payload.callType, incoming: true }
      callRef.current = call; setActiveCall(call); setState('incoming_ring'); setError(null)
      const tone = createIncomingRingtone(); toneRef.current = tone; void tone.start()
    })
    socket.on('call:accepted', async ({ callId, acceptedBy }) => {
      const call = callRef.current
      if (!call || call.callId !== callId) return
      if (call.incoming && !accepting.current) { finishLocally(); return }
      stopTone(); setState('connecting')
      if (!call.incoming && acceptedBy === call.userId) { canNegotiate.current = true; ensurePeer(); await negotiate() }
    })
    const receiveDescription = async (description: RTCSessionDescriptionInit) => {
      const call = callRef.current
      if (!call) return
      const peer = ensurePeer()
      const collision = description.type === 'offer' && (makingOffer.current || peer.signalingState !== 'stable')
      const polite = ownUserId.localeCompare(call.userId) > 0
      ignoreOffer.current = !polite && collision
      if (ignoreOffer.current) return
      try {
        if (collision) await peer.setLocalDescription({ type: 'rollback' })
        await peer.setRemoteDescription(description)
        for (const candidate of candidateQueue.current.splice(0)) await peer.addIceCandidate(candidate)
        if (description.type === 'offer') {
          canNegotiate.current = true
          await peer.setLocalDescription(await peer.createAnswer())
          await emitDescription('answer', peer.localDescription!)
        }
      } catch { setError('Нөгөө талын холболтын мэдээллийг боловсруулж чадсангүй.') }
    }
    socket.on('call:offer', ({ sdp }) => void receiveDescription(sdp))
    socket.on('call:answer', ({ sdp }) => void receiveDescription(sdp))
    socket.on('call:ice-candidate', async ({ candidate }) => {
      const peer = peerRef.current
      if (!peer?.remoteDescription) candidateQueue.current.push(candidate)
      else await peer.addIceCandidate(candidate).catch(() => undefined)
    })
    socket.on('call:reject', ({ reason }) => { setError(reason === 'busy' ? 'Хэрэглэгч өөр дуудлагатай байна.' : reason === 'offline' ? 'Хэрэглэгч офлайн байна.' : 'Дуудлагаас татгалзлаа.'); finishLocally() })
    socket.on('call:ended', () => finishLocally())
    socket.on('call:error', ({ message }) => setError(message))
    return () => { socket.removeAllListeners(); socket.disconnect(); socketRef.current = null; setSignalingConnected(false); teardown('idle') }
  }, [emitDescription, ensurePeer, finishLocally, negotiate, ownUserId, stopTone, teardown, token])

  useEffect(() => {
    if (state !== 'connected' || !connectedAt.current) return
    const update = () => setDurationSeconds(Math.max(0, Math.floor((Date.now() - connectedAt.current!) / 1000)))
    update(); const timer = window.setInterval(update, 1_000); return () => window.clearInterval(timer)
  }, [state])

  const initiate = useCallback(async (peer: CallPeer, callType: CallType) => {
    if (!socketRef.current?.connected || callRef.current) return
    setError(null)
    try {
      await acquireMedia(callType)
      setState('outgoing_ring')
      const tone = createOutgoingRingback(); toneRef.current = tone; void tone.start()
      socketRef.current.emit('call:initiate', { recipientId: peer.userId, conversationId: peer.conversationId, callType }, (result) => {
        if (!result.ok) { setError(result.message); finishLocally(); return }
        const call: ActiveCall = { ...peer, callId: result.callId, callType, incoming: false }
        callRef.current = call; setActiveCall(call)
      })
    } catch (reason) { setError(mediaErrorMessage(reason)); teardown('idle') }
  }, [acquireMedia, finishLocally, teardown])

  const accept = useCallback(async () => {
    const call = callRef.current
    if (!call || !call.incoming) return
    accepting.current = true; stopTone(); setState('connecting'); setError(null)
    try {
      await acquireMedia(call.callType); ensurePeer()
      socketRef.current?.emit('call:accept', { callId: call.callId, targetUserId: call.userId }, (result: SignalingAck) => { if (!result.ok) { setError(result.message); finishLocally() } })
    } catch (reason) {
      setError(mediaErrorMessage(reason)); socketRef.current?.emit('call:reject', { callId: call.callId, targetUserId: call.userId, reason: 'declined' }); finishLocally()
    }
  }, [acquireMedia, ensurePeer, finishLocally, stopTone])

  const decline = useCallback(() => { const call = callRef.current; if (call) socketRef.current?.emit('call:reject', { callId: call.callId, targetUserId: call.userId, reason: 'declined' }); finishLocally() }, [finishLocally])
  const end = useCallback((reason = 'ended') => { const call = callRef.current; if (call) socketRef.current?.emit('call:end', { callId: call.callId, targetUserId: call.userId, durationSeconds, reason }); finishLocally() }, [durationSeconds, finishLocally])

  useEffect(() => {
    const leave = () => { const call = callRef.current; if (call) socketRef.current?.emit('call:end', { callId: call.callId, targetUserId: call.userId, durationSeconds: connectedAt.current ? Math.floor((Date.now() - connectedAt.current) / 1000) : 0, reason: 'page_unload' }) }
    window.addEventListener('pagehide', leave); window.addEventListener('beforeunload', leave)
    return () => { window.removeEventListener('pagehide', leave); window.removeEventListener('beforeunload', leave) }
  }, [])

  const toggleMuteAudio = useCallback(() => { const track = localRef.current?.getAudioTracks()[0]; if (track) { track.enabled = !track.enabled; setAudioMuted(!track.enabled) } }, [])
  const switchAudioRoute = useCallback(async () => {
    const nextRoute: AudioRoute = audioRoute === 'speaker' ? 'default' : 'speaker'
    try { await setCallAudioRoute(nextRoute); setAudioRoute(nextRoute) } catch { setError('Дууны гаралтыг өөрчилж чадсангүй.') }
  }, [audioRoute])
  const toggleMuteVideo = useCallback(async () => {
    const current = localRef.current?.getVideoTracks()[0]
    if (current) { current.enabled = !current.enabled; setVideoMuted(!current.enabled); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' } })
      const track = stream.getVideoTracks()[0]; localRef.current?.addTrack(track); setLocalStream(new MediaStream(localRef.current?.getTracks() ?? []))
      peerRef.current?.addTrack(track, localRef.current!); setVideoMuted(false); await negotiate()
    } catch (reason) { setError(mediaErrorMessage(reason)) }
  }, [negotiate])
  const switchMediaDevice = useCallback(async (kind: 'audioinput' | 'videoinput', deviceId: string) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia(kind === 'audioinput' ? { audio: { deviceId: { exact: deviceId } } } : { video: { deviceId: { exact: deviceId } } })
      const replacement = kind === 'audioinput' ? stream.getAudioTracks()[0] : stream.getVideoTracks()[0]
      const sender = peerRef.current?.getSenders().find((item) => item.track?.kind === replacement.kind)
      await sender?.replaceTrack(replacement)
      const old = replacement.kind === 'audio' ? localRef.current?.getAudioTracks()[0] : localRef.current?.getVideoTracks()[0]
      if (old) { localRef.current?.removeTrack(old); old.stop() }
      localRef.current?.addTrack(replacement); setLocalStream(new MediaStream(localRef.current?.getTracks() ?? []))
    } catch (reason) { setError(mediaErrorMessage(reason)) }
  }, [])
  const watchUser = useCallback((peer: Pick<CallPeer, 'userId' | 'conversationId'>) => socketRef.current?.emit('user:watch', peer), [])

  return { state, activeCall, localStream, remoteStream, audioMuted, audioRoute, videoMuted, devices, error, signalingConnected, onlineUsers, durationSeconds, initiate, accept, decline, end, toggleMuteAudio, switchAudioRoute, toggleMuteVideo, switchMediaDevice, watchUser }
}
