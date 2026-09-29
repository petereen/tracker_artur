import { afterEach, describe, expect, it, vi } from 'vitest'
import { ElevenLabsCall, pcm16ToFloat32, speakableText } from './elevenlabsCall'

vi.mock('../api/client', () => ({ api: { post: vi.fn() } }))

function pcmBase64(values: number[]) {
  const bytes = new Uint8Array(values.length * 2)
  const view = new DataView(bytes.buffer)
  values.forEach((value, index) => view.setInt16(index * 2, value, true))
  return btoa(String.fromCharCode(...bytes))
}

class FakeSocket {
  static last: FakeSocket
  static OPEN = 1
  readyState = 0
  sent: any[] = []
  onopen?: () => void
  onmessage?: (event: { data: string }) => void
  onclose?: () => void
  onerror?: () => void
  constructor(public url: string) { FakeSocket.last = this }
  send(data: string) { this.sent.push(JSON.parse(data)) }
  close() { this.readyState = 3; this.onclose?.() }
}

class FakeSource {
  buffer: any
  onended?: () => void
  started: number | null = null
  connect() {}
  start(at: number) { this.started = at }
  stop() { this.onended?.() }
}

function fakeContext(sources: FakeSource[]) {
  return {
    currentTime: 1,
    createBuffer: (_channels: number, length: number, rate: number) => ({ duration: length / rate, copyToChannel: vi.fn() }),
    createBufferSource: () => { const source = new FakeSource(); sources.push(source); return source },
  }
}

describe('ElevenLabs call helpers', () => {
  it('decodes base64 little-endian 16-bit PCM', () => {
    const samples = pcm16ToFloat32(pcmBase64([0, 16384, -32768, 32767]))
    expect(Array.from(samples)).toEqual([0, 0.5, -1, 32767 / 32768])
  })

  it('strips markdown and links before speaking', () => {
    expect(speakableText('**Танд** 2 [даалгавар](https://x.mn/tasks) байна. https://erp.oyuns.mn\n# Дараах')).toBe('Танд 2 даалгавар байна. Дараах')
  })
})

describe('ElevenLabs streamed answers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('streams the answer over the socket, schedules chunks back to back and returns to listening', async () => {
    vi.stubGlobal('WebSocket', FakeSocket)
    const phases: string[] = []
    const lines: [string, string][] = []
    const call = new ElevenLabsCall('s1', {} as MediaStream, {
      onPhase: (phase) => phases.push(phase),
      onLine: (role, text) => lines.push([role, text]),
      onError: vi.fn(),
      onLevel: vi.fn(),
    }, { language: 'en', sampleRate: 24_000, speechUrl: 'wss://api.elevenlabs.io/stream?single_use_token=a' })
    const sources: FakeSource[] = []
    Object.assign(call, { context: fakeContext(sources), analyser: {} })

    const speaking = (call as any).speak('**Hello** there.') as Promise<void>
    await Promise.resolve()
    const socket = FakeSocket.last
    expect(socket.url).toContain('single_use_token=a')
    socket.onopen?.()
    expect(socket.sent[0]).toMatchObject({ text: ' ', generation_config: { chunk_length_schedule: expect.any(Array) } })
    expect(socket.sent[1]).toEqual({ text: 'Hello there. ', flush: true })
    expect(socket.sent[2]).toEqual({ text: '' })

    socket.onmessage?.({ data: JSON.stringify({ audio: pcmBase64(new Array(2400).fill(1000)) }) })
    socket.onmessage?.({ data: JSON.stringify({ audio: pcmBase64(new Array(2400).fill(1000)) }) })
    socket.onmessage?.({ data: JSON.stringify({ isFinal: true }) })
    expect(phases).toEqual(['speaking'])
    expect(sources[0].started).toBeCloseTo(1.03)
    expect(sources[1].started).toBeCloseTo(1.13)
    sources.forEach((source) => source.onended?.())
    await speaking
    expect(phases).toEqual(['speaking', 'listening'])
    expect(lines).toEqual([['assistant', '**Hello** there.']])
  })

  it('keeps the text answer when the stream fails', async () => {
    vi.stubGlobal('WebSocket', FakeSocket)
    const lines: [string, string][] = []
    const call = new ElevenLabsCall('s1', {} as MediaStream, { onPhase: vi.fn(), onLine: (role, text) => lines.push([role, text]), onError: vi.fn(), onLevel: vi.fn() }, { language: 'ru', speechUrl: 'wss://x' })
    Object.assign(call, { context: fakeContext([]), analyser: {} })
    const speaking = (call as any).speak('Привет') as Promise<void>
    await Promise.resolve()
    FakeSocket.last.onerror?.()
    await speaking
    expect(lines[1][0]).toBe('tool')
  })
})
