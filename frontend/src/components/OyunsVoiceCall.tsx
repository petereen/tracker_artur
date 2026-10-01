import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Hand, Mic, MicOff, PhoneOff, X } from 'lucide-react'
import { api } from '../api/client'
import i18n from '../i18n'
import { ChimegeCall } from './chimegeCall'
import { ElevenLabsCall } from './elevenlabsCall'

type CallPhase = 'connecting' | 'listening' | 'thinking' | 'speaking' | 'ended' | 'error'
type TranscriptLine = { id: number; role: 'user' | 'assistant' | 'tool'; text: string }
type VoiceProvider = 'openai' | 'chimege' | 'elevenlabs'

interface VoiceSession {
  /**
   * `realtime`: OpenAI Realtime over WebRTC. `chimege` / `elevenlabs`: turn
   * by turn (server STT + agent), spoken by Chimege or streamed by ElevenLabs.
   */
  mode?: 'realtime' | 'chimege' | 'elevenlabs'
  provider?: VoiceProvider
  /** Engines this call could switch to. */
  providers?: VoiceProvider[]
  session_id: string
  client_secret: string
  calls_url: string
  model: string
  voice: string
  language?: string
  greeting?: string
  greeting_text?: string
  speech_url?: string | null
  sample_rate?: number
  /** Why the picked engine was not used (e.g. `elevenlabs_invalid_key`). */
  notice?: string | null
}

const PROVIDER_LABELS: Record<VoiceProvider, string> = { openai: 'OpenAI', chimege: 'Chimege', elevenlabs: 'ElevenLabs' }
const PROVIDER_KEY = 'oyuns.voiceProvider'

function storedProvider(): VoiceProvider | undefined {
  try {
    const value = window.localStorage.getItem(PROVIDER_KEY)
    return value && value in PROVIDER_LABELS ? value as VoiceProvider : undefined
  } catch {
    return undefined
  }
}

interface FunctionCallItem { type: string; name?: string; arguments?: string; call_id?: string }

// Labels are resolved when shown so they follow the current UI language.
const phaseLabel = (phase: CallPhase) => i18n.t(`assistant.voice.phase.${phase}`)

const ERROR_CODES = [
  'not_configured', 'voice_disabled', 'rate_limited', 'invalid_key', 'model_not_found', 'network', 'microphone', 'unsupported', 'call_ended',
  'elevenlabs_invalid_key', 'elevenlabs_rate_limited', 'elevenlabs_forbidden', 'elevenlabs_network', 'elevenlabs_not_configured',
]

const errorLabel = (code: string | null | undefined) => (code && ERROR_CODES.includes(code) ? i18n.t(`assistant.voice.error.${code}`) : undefined)

// Short spoken-lookup labels for the tool trace in the transcript.
const TOOL_LABELS: [RegExp, string][] = [
  [/task/, 'task'], [/report/, 'report'], [/worktime|attendance/, 'worktime'], [/hr|leave/, 'hr'],
  [/crm/, 'crm'], [/contract/, 'contract'], [/payroll/, 'payroll'], [/knowledge|file/, 'knowledge'],
  [/project|plan/, 'project'], [/calendar/, 'calendar'], [/exchange/, 'exchange'], [/employee|directory|people/, 'employee'],
]

function toolLabel(name: string) {
  return i18n.t(`assistant.voice.tool.${TOOL_LABELS.find(([pattern]) => pattern.test(name))?.[1] ?? 'company'}`)
}

function formatDuration(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/**
 * Live voice call with the OYUNS agent.
 *
 * OpenAI Realtime (WebRTC): the server mints a short-lived client secret with
 * OYUNS' instructions and the caller's read-only tools; tool calls come back
 * over the data channel and are executed by the server with the caller's
 * permissions. Chimege and ElevenLabs calls run turn by turn instead. The
 * caller can switch engines; the call restarts on the chosen one.
 */
export function OyunsVoiceCall({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<CallPhase>('connecting')
  const [error, setError] = useState<string>()
  const [muted, setMuted] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [lines, setLines] = useState<TranscriptLine[]>([])
  const [requested, setRequested] = useState<VoiceProvider | undefined>(storedProvider)
  const [provider, setProvider] = useState<VoiceProvider>()
  const [providers, setProviders] = useState<VoiceProvider[]>([])
  const turnBased = provider === 'chimege' || provider === 'elevenlabs'
  const chimegeRef = useRef<ChimegeCall | null>(null)
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const channelRef = useRef<RTCDataChannel | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const orbRef = useRef<HTMLDivElement>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const frameRef = useRef<number | undefined>(undefined)
  const lineId = useRef(0)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const closedRef = useRef(false)

  const addLine = useCallback((role: TranscriptLine['role'], text: string) => {
    const value = text.trim()
    if (!value) return
    lineId.current += 1
    const id = lineId.current
    setLines((current) => [...current.slice(-40), { id, role, text: value }])
  }, [])

  const send = useCallback((event: Record<string, unknown>) => {
    const channel = channelRef.current
    if (channel?.readyState === 'open') channel.send(JSON.stringify(event))
  }, [])

  const cleanup = useCallback(() => {
    closedRef.current = true
    chimegeRef.current?.stop()
    chimegeRef.current = null
    if (frameRef.current) cancelAnimationFrame(frameRef.current)
    channelRef.current?.close()
    pcRef.current?.getSenders().forEach((sender) => sender.track?.stop())
    pcRef.current?.close()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    if (audioRef.current) { audioRef.current.srcObject = null; audioRef.current.remove() }
    void audioContextRef.current?.close().catch(() => undefined)
    channelRef.current = null
    pcRef.current = null
    streamRef.current = null
  }, [])

  const runTools = useCallback(async (calls: FunctionCallItem[]) => {
    setPhase('thinking')
    await Promise.all(calls.map(async (call) => {
      addLine('tool', i18n.t('assistant.voice.checking', { tool: toolLabel(call.name || '') }))
      let output: string
      try {
        const { data } = await api.post('/v1/assistant/voice/tool', { name: call.name, arguments: call.arguments ?? '{}', call_id: call.call_id })
        output = data.output
      } catch {
        output = JSON.stringify({ status: 'unavailable', summary: 'The lookup failed.' })
      }
      send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: call.call_id, output } })
    }))
    if (!closedRef.current) send({ type: 'response.create' })
  }, [addLine, send])

  const onServerEvent = useCallback((event: any) => {
    switch (event.type) {
      case 'input_audio_buffer.speech_started':
        setPhase('listening')
        break
      case 'input_audio_buffer.speech_stopped':
      case 'response.created':
        setPhase('thinking')
        break
      case 'output_audio_buffer.started':
        setPhase('speaking')
        break
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared':
        setPhase('listening')
        break
      case 'conversation.item.input_audio_transcription.completed':
        addLine('user', event.transcript || '')
        break
      case 'response.output_audio_transcript.done':
      case 'response.audio_transcript.done':
        addLine('assistant', event.transcript || '')
        break
      case 'response.done': {
        const calls = ((event.response?.output ?? []) as FunctionCallItem[]).filter((item) => item.type === 'function_call' && item.call_id)
        if (calls.length) void runTools(calls)
        break
      }
      case 'error':
        // Non-fatal protocol errors (e.g. a cancelled response) keep the call alive.
        if (event.error?.code !== 'response_cancel_not_active') console.warn('OYUNS voice error', event.error)
        break
      default:
        break
    }
  }, [addLine, runTools])

  const watchLevel = useCallback((stream: MediaStream) => {
    try {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
      if (!AudioContextClass) return
      const context: AudioContext = new AudioContextClass()
      audioContextRef.current = context
      const analyser = context.createAnalyser()
      analyser.fftSize = 256
      context.createMediaStreamSource(stream).connect(analyser)
      const samples = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        analyser.getByteFrequencyData(samples)
        const level = samples.reduce((sum, value) => sum + value, 0) / (samples.length * 255)
        orbRef.current?.style.setProperty('--voice-level', String(1 + Math.min(0.35, level * 1.6)))
        frameRef.current = requestAnimationFrame(tick)
      }
      tick()
    } catch {
      // The orb animation is decorative.
    }
  }, [])

  useEffect(() => {
    // Each mount owns its own attempt; a StrictMode remount or a fast close
    // cancels the earlier attempt before it can publish any resources.
    let cancelled = false
    closedRef.current = false
    const start = async () => {
      if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === 'undefined') throw new Error('unsupported')
      let stream: MediaStream
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      } catch {
        throw new Error('microphone')
      }
      if (cancelled) { stream.getTracks().forEach((track) => track.stop()); return }
      streamRef.current = stream
      const { data: session } = await api.post<VoiceSession>('/v1/assistant/voice/session', { language: i18n.language, provider: requested })
      if (cancelled) { stream.getTracks().forEach((track) => track.stop()); return }
      setProviders(session.providers ?? [])
      setProvider(session.provider ?? (session.mode === 'chimege' ? 'chimege' : 'openai'))
      if (session.notice) addLine('tool', `${errorLabel(session.notice) ?? i18n.t('assistant.voice.engineFallback')} ${i18n.t('assistant.voice.usedProvider', { provider: PROVIDER_LABELS[session.provider ?? 'openai'] })}`)
      if (session.mode === 'chimege' || session.mode === 'elevenlabs') {
        const callbacks = {
          onPhase: setPhase,
          onLine: addLine,
          onError: (code: string) => { setError(code); setPhase('error'); cleanup() },
          onLevel: (level: number) => orbRef.current?.style.setProperty('--voice-level', String(1 + Math.min(0.35, level * 3))),
        }
        const call = session.mode === 'elevenlabs'
          ? new ElevenLabsCall(session.session_id, stream, callbacks, { language: session.language || 'mn', sampleRate: session.sample_rate, speechUrl: session.speech_url })
          : new ChimegeCall(session.session_id, stream, callbacks)
        chimegeRef.current = call
        setPhase('listening')
        await call.start(session.greeting_text || i18n.t('assistant.voice.greeting', { lng: session.language ?? i18n.language }))
        return
      }
      const pc = new RTCPeerConnection()
      pcRef.current = pc
      const audio = document.createElement('audio')
      audio.autoplay = true
      audioRef.current = audio
      pc.ontrack = (event) => {
        audio.srcObject = event.streams[0]
        watchLevel(event.streams[0])
      }
      pc.onconnectionstatechange = () => {
        if (['failed', 'disconnected'].includes(pc.connectionState) && !closedRef.current) {
          setError('network')
          setPhase('error')
        }
      }
      stream.getTracks().forEach((track) => pc.addTrack(track, stream))
      const channel = pc.createDataChannel('oai-events')
      channelRef.current = channel
      channel.onmessage = (message) => {
        try { onServerEvent(JSON.parse(message.data)) } catch { /* ignore malformed events */ }
      }
      channel.onopen = () => {
        setPhase('listening')
        // Open the call in the interface language. The greeting goes in as a
        // system item: `response.instructions` would replace the session
        // instructions (language rules and context) for this response.
        send({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [{ type: 'input_text', text: session.greeting || 'Greet the caller briefly and ask how you can help. One short sentence.' }] } })
        send({ type: 'response.create' })
      }
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      const answer = await fetch(session.calls_url, {
        method: 'POST',
        body: offer.sdp,
        headers: { Authorization: `Bearer ${session.client_secret}`, 'Content-Type': 'application/sdp' },
      })
      if (!answer.ok) throw new Error('network')
      const sdp = await answer.text()
      if (cancelled) { pc.close(); return }
      await pc.setRemoteDescription({ type: 'answer', sdp })
    }
    start().catch((failure: any) => {
      if (cancelled || closedRef.current) return
      const detail = failure?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : failure?.message || 'network')
      setPhase('error')
      cleanup()
    })
    return () => {
      cancelled = true
      cleanup()
    }
  }, [cleanup, onServerEvent, send, watchLevel, requested])

  const switchProvider = (next: VoiceProvider) => {
    if (next === provider) return
    try { window.localStorage.setItem(PROVIDER_KEY, next) } catch { /* the pick just is not remembered */ }
    // Changing `requested` restarts the call effect on the new engine.
    setLines([])
    setElapsed(0)
    setError(undefined)
    setPhase('connecting')
    setRequested(next)
  }

  const running = phase === 'listening' || phase === 'thinking' || phase === 'speaking'
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = !muted })
  }, [muted])

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight })
  }, [lines])

  const hangUp = () => {
    cleanup()
    setPhase('ended')
    onClose()
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') hangUp() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return createPortal(<div className="oyuns-voice-overlay" role="dialog" aria-modal="true" aria-label={t('assistant.call.agentAria')}>
    <section className="oyuns-voice-card">
      <header>
        <div><strong>OYUNS Agent</strong><small>{phase === 'error' ? phaseLabel('error') : `${t('assistant.voice.title')}${provider ? ` · ${PROVIDER_LABELS[provider]}` : ''}${provider === 'chimege' ? ` · ${t('assistant.voice.mongolianMode')}` : ''} · ${formatDuration(elapsed)}`}</small></div>
        <button type="button" className="chat-icon-button" onClick={hangUp} aria-label={t('chat.close')}><X /></button>
      </header>
      {providers.length > 1 && <div className="oyuns-voice-engines" role="radiogroup" aria-label={t('assistant.voice.engine')}>
        {providers.map((item) => <button key={item} type="button" role="radio" aria-checked={item === provider} disabled={phase === 'connecting'} onClick={() => switchProvider(item)}>{PROVIDER_LABELS[item]}</button>)}
      </div>}
      <div ref={orbRef} className={`oyuns-voice-orb ${phase}`} aria-hidden="true" />
      <p className="oyuns-voice-status" aria-live="polite">{muted && phase !== 'error' ? t('assistant.voice.muted') : phaseLabel(phase)}</p>
      {error && <p className="oyuns-voice-error" role="alert">{errorLabel(error) ?? t('assistant.voice.error.default')}</p>}
      {lines.length > 0 && <div ref={transcriptRef} className="oyuns-voice-transcript" aria-label={t('assistant.voice.transcript')}>{lines.map((line) => <p key={line.id} className={line.role}>{line.role === 'user' ? t('assistant.voice.you') : line.role === 'assistant' ? 'OYUNS: ' : ''}{line.text}</p>)}</div>}
      <div className="oyuns-voice-controls">
        <button type="button" className={`mute ${muted ? 'active' : ''}`} onClick={() => setMuted((value) => !value)} disabled={phase === 'error'} aria-pressed={muted} aria-label={muted ? t('assistant.voice.unmute') : t('assistant.voice.mute')}>{muted ? <MicOff /> : <Mic />}</button>
        {turnBased && phase === 'speaking' && <button type="button" className="mute" onClick={() => chimegeRef.current?.interrupt()} aria-label={t('assistant.voice.interrupt')} title={t('assistant.voice.interrupt')}><Hand /></button>}
        <button type="button" className="hangup" onClick={hangUp} aria-label={t('assistant.voice.hangup')}><PhoneOff /></button>
      </div>
    </section>
  </div>, document.body)
}
