import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChimegeSettings } from './ChimegeSettings'

const mocks = vi.hoisted(() => ({ update: vi.fn(), test: vi.fn() }))

vi.mock('../api/aiSettings', () => ({
  useUpdateAiAgentSettings: () => ({ mutateAsync: mocks.update, mutate: mocks.update, isPending: false }),
  useTestChimege: () => ({ mutateAsync: mocks.test, isPending: false }),
}))

function settings(overrides: Record<string, unknown> = {}) {
  return {
    stt: { has_token: true, token_last4: 'a1b2', source: 'organization' as const, enabled: true },
    tts: { has_token: false, token_last4: null, source: 'none' as const, enabled: true },
    voice_call_enabled: true,
    voice_call_ready: false,
    ...overrides,
  }
}

describe('Chimege settings', () => {
  beforeEach(() => {
    mocks.update.mockReset().mockResolvedValue({})
    mocks.test.mockReset()
  })

  it('shows only the last four characters and warns when the Mongolian call mode cannot run', () => {
    render(<ChimegeSettings settings={settings()} />)
    expect(screen.getByText('…a1b2')).toBeInTheDocument()
    expect(screen.getByLabelText(/Яриа таних \(STT\) token: шинээр солих/)).toHaveValue('')
    expect(screen.getByText('Монгол горим ажиллахгүй')).toBeInTheDocument()
  })

  it('saves a new TTS token with the switches and clears the field', async () => {
    render(<ChimegeSettings settings={settings()} />)
    const save = screen.getByRole('button', { name: 'Chimege хадгалах' })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/^Дуу үүсгэх \(TTS\) token/), { target: { value: 'tts-token-123456' } })
    expect(screen.queryByText('Монгол горим ажиллахгүй')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: /Chimege яриа таних/ }))
    fireEvent.click(save)
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0]).toEqual({ chimege_stt_token: null, chimege_tts_token: 'tts-token-123456', chimege_stt_enabled: false, chimege_tts_enabled: true, chimege_voice_call_enabled: true })
    await waitFor(() => expect(screen.getByLabelText(/^Дуу үүсгэх \(TTS\) token/)).toHaveValue(''))
  })

  it('reports the round-trip test result', async () => {
    mocks.test.mockResolvedValue({ tts: { ok: true, error: null, latency_ms: 800 }, stt: { ok: true, error: null, transcript: 'сайн байна уу', latency_ms: 600 } })
    render(<ChimegeSettings settings={settings({ voice_call_ready: true })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Chimege шалгах' }))
    await waitFor(() => expect(screen.getByText(/сайн байна уу/)).toBeInTheDocument())
    expect(mocks.test).toHaveBeenCalledWith({ stt_token: null, tts_token: null })
  })
})
