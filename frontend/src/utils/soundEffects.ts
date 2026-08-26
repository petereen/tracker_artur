type ToneMode = 'ringback' | 'ringtone'

class SynthesizedTone {
  private context: AudioContext | null = null
  private oscillators: OscillatorNode[] = []
  private gain: GainNode | null = null
  private timer: number | null = null
  private stopped = false

  constructor(private readonly mode: ToneMode) {}

  async start() {
    if (this.context || typeof AudioContext === 'undefined') return
    this.stopped = false
    try {
      const context = new AudioContext()
      this.context = context
      await context.resume()
      if (this.stopped) return void this.stop()
      const gain = context.createGain()
      gain.gain.value = 0
      gain.connect(context.destination)
      this.gain = gain
      const frequencies = this.mode === 'ringback' ? [425] : [440, 480]
      this.oscillators = frequencies.map((frequency) => {
        const oscillator = context.createOscillator()
        oscillator.type = 'sine'
        oscillator.frequency.value = frequency
        oscillator.connect(gain)
        oscillator.start()
        return oscillator
      })
      const pulse = () => {
        if (!this.context || !this.gain) return
        const now = this.context.currentTime
        this.gain.gain.cancelScheduledValues(now)
        this.gain.gain.setValueAtTime(0, now)
        this.gain.gain.linearRampToValueAtTime(this.mode === 'ringback' ? 0.08 : 0.055, now + 0.025)
        this.gain.gain.setValueAtTime(this.mode === 'ringback' ? 0.08 : 0.055, now + (this.mode === 'ringback' ? 0.65 : 0.45))
        this.gain.gain.linearRampToValueAtTime(0, now + (this.mode === 'ringback' ? 0.72 : 0.52))
      }
      pulse()
      this.timer = window.setInterval(pulse, this.mode === 'ringback' ? 2_000 : 1_450)
    } catch {
      await this.stop()
    }
  }

  async stop() {
    this.stopped = true
    if (this.timer !== null) window.clearInterval(this.timer)
    this.timer = null
    for (const oscillator of this.oscillators) {
      try { oscillator.stop() } catch { /* already stopped */ }
      oscillator.disconnect()
    }
    this.oscillators = []
    this.gain?.disconnect()
    this.gain = null
    const context = this.context
    this.context = null
    if (context && context.state !== 'closed') await context.close().catch(() => undefined)
  }
}

export const createOutgoingRingback = () => new SynthesizedTone('ringback')
export const createIncomingRingtone = () => new SynthesizedTone('ringtone')
export type SoundEffect = ReturnType<typeof createOutgoingRingback>
