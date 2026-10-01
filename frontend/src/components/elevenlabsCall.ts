import { api } from '../api/client'
import i18n from '../i18n'
import { ChimegeCall, type ChimegeCallCallbacks } from './chimegeCall'

/**
 * Turn-based call spoken by ElevenLabs: utterance detection and the agent
 * turn are shared with `ChimegeCall`; each answer streams from the ElevenLabs
 * `stream-input` WebSocket as raw PCM and is scheduled gaplessly as chunks
 * arrive. Each answer uses a fresh single-use URL minted by the server, so
 * the organization key never reaches the browser.
 */

const DEFAULT_SAMPLE_RATE = 24_000
// Smaller first chunks start the audio sooner; later ones sound smoother.
const CHUNK_LENGTH_SCHEDULE = [80, 120, 200, 260]
const VOICE_SETTINGS = { stability: 0.5, similarity_boost: 0.8, use_speaker_boost: false, speed: 1.05 }

/** Base64 little-endian 16-bit mono PCM → float samples. */
export function pcm16ToFloat32(base64: string): Float32Array<ArrayBuffer> {
  const binary = atob(base64)
  const length = binary.length >> 1
  const samples = new Float32Array(length)
  for (let index = 0; index < length; index += 1) {
    const value = binary.charCodeAt(index * 2) | (binary.charCodeAt(index * 2 + 1) << 8)
    samples[index] = (value >= 0x8000 ? value - 0x10000 : value) / 0x8000
  }
  return samples
}

/** Markdown and links read badly aloud; the transcript keeps the original. */
export function speakableText(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[*_#`>|~]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export interface ElevenLabsCallOptions {
  language: string
  sampleRate?: number
  /** The session's stream URL, used for the greeting. */
  speechUrl?: string | null
}

export class ElevenLabsCall extends ChimegeCall {
  private socket: WebSocket | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private readonly sampleRate: number
  private pendingUrl: string | null

  constructor(sessionId: string, stream: MediaStream, callbacks: ChimegeCallCallbacks, options: ElevenLabsCallOptions) {
    super(sessionId, stream, callbacks, options.language)
    this.sampleRate = options.sampleRate || DEFAULT_SAMPLE_RATE
    this.pendingUrl = options.speechUrl ?? null
  }

  protected override stopPlayback() {
    const socket = this.socket
    this.socket = null
    if (socket && socket.readyState <= WebSocket.OPEN) socket.close()
    for (const node of this.sources) {
      try { node.stop() } catch { /* already stopped */ }
    }
    this.sources.clear()
    super.stopPlayback()
  }

  private async streamUrl(): Promise<string | null> {
    if (this.pendingUrl) {
      const url = this.pendingUrl
      this.pendingUrl = null
      return url
    }
    try {
      const { data } = await api.post<{ speech_url: string }>('/v1/assistant/voice/elevenlabs/stream', { session_id: this.sessionId }, { signal: this.controller.signal })
      return data.speech_url
    } catch (failure: any) {
      if (failure?.response?.status === 404 && !this.stopped) this.callbacks.onError('call_ended')
      return null
    }
  }

  protected override async speak(text: string, speechUrl?: string) {
    this.callbacks.onLine('assistant', text)
    const token = ++this.speechToken
    const spoken = speakableText(text)
    const url = spoken ? speechUrl ?? await this.streamUrl() : null
    if (this.stopped || token !== this.speechToken) return
    const spoke = url ? await this.streamAnswer(url, spoken, token) : false
    if (this.stopped || token !== this.speechToken) return
    if (!spoke && spoken) this.callbacks.onLine('tool', i18n.t('assistant.call.ttsFailed'))
    this.stopPlayback()
    this.setPhase('listening')
  }

  /** Stream one answer; resolves after the last chunk finished playing. */
  private streamAnswer(url: string, text: string, token: number): Promise<boolean> {
    return new Promise((resolve) => {
      const context = this.context
      const analyser = this.analyser
      if (!context || !analyser) { resolve(false); return }
      let nextAt = 0
      let pending = 0
      let finished = false
      let spoke = false
      let settled = false
      const settle = () => {
        if (settled || !finished || pending > 0) return
        settled = true
        resolve(spoke)
      }
      const socket = new WebSocket(url)
      this.socket = socket
      socket.onopen = () => {
        socket.send(JSON.stringify({ text: ' ', voice_settings: VOICE_SETTINGS, generation_config: { chunk_length_schedule: CHUNK_LENGTH_SCHEDULE } }))
        socket.send(JSON.stringify({ text: `${text} `, flush: true }))
        // An empty text closes the input; the server sends the rest, then isFinal.
        socket.send(JSON.stringify({ text: '' }))
      }
      socket.onmessage = (message) => {
        if (token !== this.speechToken || this.stopped) return
        let data: { audio?: string | null; isFinal?: boolean; error?: string; message?: string }
        try { data = JSON.parse(String(message.data)) } catch { return }
        if (data.audio) {
          const samples = pcm16ToFloat32(data.audio)
          if (samples.length) {
            const buffer = context.createBuffer(1, samples.length, this.sampleRate)
            buffer.copyToChannel(samples, 0)
            const node = context.createBufferSource()
            node.buffer = buffer
            node.connect(analyser)
            const startAt = Math.max(context.currentTime + 0.03, nextAt)
            nextAt = startAt + buffer.duration
            pending += 1
            this.sources.add(node)
            node.onended = () => {
              this.sources.delete(node)
              pending -= 1
              settle()
            }
            node.start(startAt)
            if (!spoke) {
              spoke = true
              this.setPhase('speaking')
            }
          }
        } else if (data.error || data.message) {
          console.warn('ElevenLabs stream error', data.error || data.message)
        }
        if (data.isFinal) {
          finished = true
          settle()
        }
      }
      socket.onerror = () => { finished = true; settle() }
      socket.onclose = () => { finished = true; settle() }
    })
  }
}
