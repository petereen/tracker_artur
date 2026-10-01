import { api } from '../api/client'
import i18n from '../i18n'

/**
 * Turn-based voice call: the browser detects the end of each utterance, sends
 * it as 16 kHz WAV to the server (STT + the OYUNS agent), and speaks the
 * answer. `ChimegeCall` plays Chimege TTS sentence by sentence (the next part
 * is synthesized while the current one plays); `ElevenLabsCall` overrides
 * `speak` to stream the answer from ElevenLabs.
 */

export type ChimegePhase = 'listening' | 'thinking' | 'speaking'

export interface ChimegeCallCallbacks {
  onPhase: (phase: ChimegePhase) => void
  onLine: (role: 'user' | 'assistant' | 'tool', text: string) => void
  onError: (code: string) => void
  onLevel: (level: number) => void
}

const TARGET_RATE = 16_000
const FRAME_SIZE = 4096
const PREROLL_MS = 400
const END_SILENCE_MS = 900
const MIN_SPEECH_MS = 350
const MAX_UTTERANCE_MS = 30_000
const MIN_THRESHOLD = 0.012
const SPEECH_CHUNK_CHARS = 220

export interface TurnResult {
  transcript: string
  answer: string
  error: string | null
  language?: string
  /** ElevenLabs calls: a single-use stream URL for speaking this answer. */
  speech_url?: string | null
}

function rms(samples: Float32Array) {
  let sum = 0
  for (let index = 0; index < samples.length; index += 1) sum += samples[index] * samples[index]
  return Math.sqrt(sum / samples.length)
}

/** Mono float frames → 16 kHz 16-bit PCM WAV. */
export function encodeWav(frames: Float32Array[], sampleRate: number): Blob {
  const total = frames.reduce((sum, frame) => sum + frame.length, 0)
  const input = new Float32Array(total)
  let offset = 0
  for (const frame of frames) { input.set(frame, offset); offset += frame.length }
  const ratio = sampleRate / TARGET_RATE
  const length = Math.floor(total / ratio)
  const buffer = new ArrayBuffer(44 + length * 2)
  const view = new DataView(buffer)
  const text = (at: number, value: string) => { for (let index = 0; index < value.length; index += 1) view.setUint8(at + index, value.charCodeAt(index)) }
  text(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); text(8, 'WAVE')
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  text(36, 'data'); view.setUint32(40, length * 2, true)
  for (let index = 0; index < length; index += 1) {
    // Average the source samples that fall into each output sample.
    const start = Math.floor(index * ratio)
    const end = Math.min(total, Math.floor((index + 1) * ratio))
    let sum = 0
    for (let source = start; source < end; source += 1) sum += input[source]
    const sample = Math.max(-1, Math.min(1, end > start ? sum / (end - start) : input[start] ?? 0))
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

/** Split an answer at sentence ends into parts Chimege synthesizes quickly. */
export function speechChunks(text: string, limit = SPEECH_CHUNK_CHARS): string[] {
  const sentences = text.replace(/\s+/g, ' ').trim().match(/[^.!?…]+[.!?…]*/g) ?? []
  const chunks: string[] = []
  let current = ''
  for (const raw of sentences) {
    const sentence = raw.trim()
    if (!sentence) continue
    if (current && (current.length + sentence.length + 1) > limit) { chunks.push(current); current = '' }
    if (sentence.length > limit) {
      // An overlong sentence is split at word boundaries.
      for (const word of sentence.split(' ')) {
        if (current && current.length + word.length + 1 > limit) { chunks.push(current); current = '' }
        current = current ? `${current} ${word}` : word
      }
    } else {
      current = current ? `${current} ${sentence}` : sentence
    }
  }
  if (current) chunks.push(current)
  return chunks
}

export class ChimegeCall {
  protected context: AudioContext | null = null
  private processor: ScriptProcessorNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  protected analyser: AnalyserNode | null = null
  private playing: AudioBufferSourceNode | null = null
  protected controller = new AbortController()
  private phase: ChimegePhase = 'listening'
  protected stopped = false
  protected speechToken = 0
  private noiseFloor = 0.005
  private preroll: Float32Array[] = []
  private frames: Float32Array[] = []
  private speaking = false
  private speechStartedAt = 0
  private lastVoiceAt = 0

  constructor(
    protected readonly sessionId: string,
    private readonly stream: MediaStream,
    protected readonly callbacks: ChimegeCallCallbacks,
    protected readonly language = 'mn',
  ) {}

  async start(greeting: string) {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioContextClass) throw new Error('unsupported')
    const context: AudioContext = new AudioContextClass()
    this.context = context
    await context.resume().catch(() => undefined)
    this.analyser = context.createAnalyser()
    this.analyser.fftSize = 512
    this.analyser.connect(context.destination)
    this.source = context.createMediaStreamSource(this.stream)
    this.processor = context.createScriptProcessor(FRAME_SIZE, 1, 1)
    // A muted sink keeps the processor running without echoing the mic.
    const sink = context.createGain()
    sink.gain.value = 0
    this.source.connect(this.processor)
    this.processor.connect(sink)
    sink.connect(context.destination)
    this.processor.onaudioprocess = (event) => this.onFrame(new Float32Array(event.inputBuffer.getChannelData(0)))
    await this.speak(greeting)
  }

  /** Stop the current answer and listen again. */
  interrupt() {
    if (this.phase !== 'speaking') return
    this.speechToken += 1
    this.stopPlayback()
    this.setPhase('listening')
  }

  stop() {
    this.stopped = true
    this.speechToken += 1
    this.controller.abort()
    this.stopPlayback()
    if (this.processor) this.processor.onaudioprocess = null
    this.processor?.disconnect()
    this.source?.disconnect()
    void this.context?.close().catch(() => undefined)
    this.context = null
  }

  protected setPhase(phase: ChimegePhase) {
    this.phase = phase
    if (!this.stopped) this.callbacks.onPhase(phase)
  }

  protected stopPlayback() {
    try { this.playing?.stop() } catch { /* already stopped */ }
    this.playing = null
  }

  private onFrame(frame: Float32Array) {
    if (this.stopped || !this.context) return
    if (this.phase === 'speaking' && this.analyser) {
      const samples = new Float32Array(this.analyser.fftSize)
      this.analyser.getFloatTimeDomainData(samples)
      this.callbacks.onLevel(rms(samples))
    }
    if (this.phase !== 'listening') { this.preroll = []; return }
    const level = rms(frame)
    this.callbacks.onLevel(level)
    const now = performance.now()
    const threshold = Math.max(MIN_THRESHOLD, this.noiseFloor * 3)
    const frameMs = (frame.length / this.context.sampleRate) * 1000
    if (!this.speaking) {
      this.noiseFloor = this.noiseFloor * 0.95 + level * 0.05
      this.preroll.push(frame)
      if (this.preroll.length * frameMs > PREROLL_MS) this.preroll.shift()
      if (level > threshold) {
        this.speaking = true
        this.speechStartedAt = now
        this.lastVoiceAt = now
        this.frames = [...this.preroll]
        this.preroll = []
      }
      return
    }
    this.frames.push(frame)
    if (level > threshold * 0.7) this.lastVoiceAt = now
    const silentFor = now - this.lastVoiceAt
    if (silentFor >= END_SILENCE_MS || now - this.speechStartedAt >= MAX_UTTERANCE_MS) {
      const voicedMs = this.lastVoiceAt - this.speechStartedAt
      const frames = this.frames
      this.speaking = false
      this.frames = []
      if (voicedMs >= MIN_SPEECH_MS) void this.turn(encodeWav(frames, this.context.sampleRate))
    }
  }

  private async turn(wav: Blob) {
    this.setPhase('thinking')
    const form = new FormData()
    form.append('session_id', this.sessionId)
    form.append('file', wav, 'speech.wav')
    let data: TurnResult
    try {
      ({ data } = await api.post('/v1/assistant/voice/turn', form, { signal: this.controller.signal, timeout: 90_000 }))
    } catch (failure: any) {
      if (this.stopped) return
      const detail = failure?.response?.data?.detail
      if (failure?.response?.status === 404) { this.callbacks.onError(typeof detail === 'string' ? detail : 'call_ended'); return }
      this.callbacks.onLine('tool', i18n.t('assistant.call.connectionLost'))
      this.setPhase('listening')
      return
    }
    if (this.stopped) return
    if (data.transcript) this.callbacks.onLine('user', data.transcript)
    const language = data.language || this.language
    const speechUrl = data.speech_url ?? undefined
    if (!data.transcript) { await this.speak(i18n.t('assistant.call.notUnderstood', { lng: language }), speechUrl); return }
    if (!data.answer) { await this.speak(i18n.t('assistant.call.agentUnavailable', { lng: language }), speechUrl); return }
    await this.speak(data.answer, speechUrl)
  }

  private fetchSpeech(text: string): Promise<ArrayBuffer | null> {
    return api.post('/v1/assistant/voice/chimege/speech', { session_id: this.sessionId, text }, { responseType: 'arraybuffer', signal: this.controller.signal, timeout: 60_000 })
      .then((response) => response.data as ArrayBuffer)
      .catch(() => null)
  }

  private play(buffer: AudioBuffer, token: number): Promise<void> {
    return new Promise((resolve) => {
      if (!this.context || !this.analyser || token !== this.speechToken) { resolve(); return }
      const node = this.context.createBufferSource()
      node.buffer = buffer
      node.connect(this.analyser)
      node.onended = () => resolve()
      this.playing = node
      node.start()
    })
  }

  /** Show the text and speak it; the next part is fetched while one plays. */
  protected async speak(text: string, _speechUrl?: string) {
    this.callbacks.onLine('assistant', text)
    const token = ++this.speechToken
    const chunks = speechChunks(text)
    let next = chunks.length ? this.fetchSpeech(chunks[0]) : null
    let spoke = false
    for (let index = 0; index < chunks.length && next; index += 1) {
      const audio = await next
      next = index + 1 < chunks.length ? this.fetchSpeech(chunks[index + 1]) : null
      if (this.stopped || token !== this.speechToken || !this.context) return
      if (!audio) continue
      try {
        const buffer = await this.context.decodeAudioData(audio.slice(0))
        if (token !== this.speechToken) return
        if (this.phase !== 'speaking') this.setPhase('speaking')
        spoke = true
        await this.play(buffer, token)
      } catch {
        // An undecodable part is skipped; the text stays in the transcript.
      }
    }
    if (this.stopped || token !== this.speechToken) return
    if (!spoke && chunks.length) this.callbacks.onLine('tool', i18n.t('assistant.call.ttsFailed'))
    this.stopPlayback()
    this.setPhase('listening')
  }
}
