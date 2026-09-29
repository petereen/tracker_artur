import { describe, expect, it } from 'vitest'
import { encodeWav, speechChunks } from './chimegeCall'

describe('Chimege call helpers', () => {
  it('encodes 48 kHz float frames as 16 kHz mono 16-bit WAV', async () => {
    const frame = new Float32Array(4800).fill(0.5)
    const blob = encodeWav([frame, frame], 48_000)
    const view = new DataView(await blob.arrayBuffer())
    const text = (at: number) => String.fromCharCode(...new Uint8Array(view.buffer, at, 4))
    expect(text(0)).toBe('RIFF')
    expect(text(8)).toBe('WAVE')
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint32(40, true)).toBe(3200 * 2)
    expect(view.getInt16(44, true)).toBe(Math.floor(0.5 * 0x7fff))
  })

  it('splits answers at sentence ends under the chunk limit', () => {
    const chunks = speechChunks('Танд хоёр даалгавар байна. Нэг нь өнөөдөр дуусна! Нөгөө нь маргааш уу?', 40)
    expect(chunks).toEqual(['Танд хоёр даалгавар байна.', 'Нэг нь өнөөдөр дуусна!', 'Нөгөө нь маргааш уу?'])
    expect(speechChunks('Богино. Өгүүлбэр.')).toEqual(['Богино. Өгүүлбэр.'])
    const long = speechChunks('үг '.repeat(200), 50)
    expect(long.every((chunk) => chunk.length <= 50)).toBe(true)
    expect(speechChunks('   ')).toEqual([])
  })
})
