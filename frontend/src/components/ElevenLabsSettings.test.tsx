import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElevenLabsSettings } from './ElevenLabsSettings'

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

const mocks = vi.hoisted(() => ({ update: vi.fn(), test: vi.fn() }))

vi.mock('../api/aiSettings', () => ({
  useUpdateAiAgentSettings: () => ({ mutateAsync: mocks.update, mutate: mocks.update, isPending: false }),
  useTestElevenLabs: () => ({ mutateAsync: mocks.test, isPending: false }),
  useElevenLabsVoices: () => ({ data: { voices: [{ voice_id: 'EXAVITQu4vr4xnSDxMaL', name: 'Sarah', description: 'female' }, { voice_id: 'JBFqnCBsd6RMkjVDRZzb', name: 'George' }], error: null } }),
}))

function settings(overrides: Record<string, unknown> = {}) {
  return {
    has_key: true,
    key_last4: 'wxyz',
    source: 'organization' as const,
    enabled: true,
    ready: true,
    voice_id: 'EXAVITQu4vr4xnSDxMaL',
    model: 'eleven_flash_v2_5',
    models: ['eleven_flash_v2_5', 'eleven_turbo_v2_5', 'eleven_multilingual_v2'],
    default_voice_id: 'EXAVITQu4vr4xnSDxMaL',
    ...overrides,
  }
}

describe('ElevenLabs settings', () => {
  beforeEach(() => {
    mocks.update.mockReset().mockResolvedValue({})
    mocks.test.mockReset()
  })

  it('shows only the last four key characters and saves a new key with the switch', async () => {
    render(<ElevenLabsSettings settings={settings()} />)
    expect(screen.getByText('…wxyz')).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'ElevenLabs хадгалах' })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/ElevenLabs API түлхүүр: шинээр солих/), { target: { value: 'sk_new_elevenlabs_key_123' } })
    fireEvent.click(screen.getByRole('switch', { name: /ElevenLabs ашиглах/ }))
    fireEvent.click(save)
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0]).toEqual({ elevenlabs_api_key: 'sk_new_elevenlabs_key_123', elevenlabs_enabled: false, elevenlabs_voice_id: 'EXAVITQu4vr4xnSDxMaL', elevenlabs_model: 'eleven_flash_v2_5' })
    await waitFor(() => expect(screen.getByLabelText(/ElevenLabs API түлхүүр: шинээр солих/)).toHaveValue(''))
  })

  it('keeps a voice ID that is not in the account list selectable', () => {
    render(<ElevenLabsSettings settings={settings({ voice_id: 'customVoice1234' })} />)
    expect(screen.getAllByText('customVoice1234').length).toBeGreaterThan(0)
  })

  it('reports the connection test result', async () => {
    mocks.test.mockResolvedValue({ ok: false, error: 'invalid_key', latency_ms: 120, voices: 0 })
    render(<ElevenLabsSettings settings={settings()} />)
    fireEvent.click(screen.getByRole('button', { name: 'ElevenLabs шалгах' }))
    await waitFor(() => expect(screen.getByText('ElevenLabs API түлхүүр хүчингүй байна.')).toBeInTheDocument())
    expect(mocks.test).toHaveBeenCalledWith({ api_key: null })
  })
})
