import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AiAgentSettings } from './AiAgentSettings'

const mocks = vi.hoisted(() => ({ update: vi.fn(), test: vi.fn(), settings: null as any }))

vi.mock('../api/aiSettings', () => ({
  useAiAgentSettings: () => ({ data: mocks.settings, isLoading: false, isError: false }),
  useAiModels: () => ({ data: { models: ['gpt-5-mini', 'gpt-5.6-luna'], error: null } }),
  useUpdateAiAgentSettings: () => ({ mutateAsync: mocks.update, mutate: mocks.update, isPending: false }),
  useTestAiConnection: () => ({ mutateAsync: mocks.test, isPending: false }),
}))

function settings(overrides: Record<string, unknown> = {}) {
  return {
    has_key: true, key_last4: 'abcd', key_source: 'organization', env_key_available: false,
    primary_model: 'gpt-5.6-luna', fallback_model: 'gpt-5.6-terra', reasoning_effort: 'low',
    max_output_tokens: 2000, web_search_enabled: true,
    defaults: { primary_model: 'gpt-5.6-luna', fallback_model: 'gpt-5.6-terra', reasoning_effort: 'low', max_output_tokens: 2000 },
    limits: { min_output_tokens: 500, max_output_tokens: 8000 }, updated_at: null,
    ...overrides,
  }
}

// Astryx Selector reads media queries for its adaptive presentation.
vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

describe('AI agent settings', () => {
  beforeEach(() => {
    mocks.update.mockReset().mockResolvedValue(settings())
    mocks.test.mockReset()
    mocks.settings = settings()
  })

  it('never prefills the stored key and shows only its last four characters', () => {
    render(<AiAgentSettings />)
    expect(screen.getByText('sk-…abcd')).toBeInTheDocument()
    expect(screen.getByLabelText(/Шинэ түлхүүрээр солих/)).toHaveValue('')
  })

  it('saves settings without sending a key when the key field is untouched', async () => {
    render(<AiAgentSettings />)
    const save = screen.getByRole('button', { name: 'Хадгалах' })
    expect(save).toBeDisabled()
    fireEvent.click(screen.getByRole('switch', { name: /Вэб хайлт/ }))
    fireEvent.click(save)
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0]).toMatchObject({ api_key: null, primary_model: 'gpt-5.6-luna', fallback_model: 'gpt-5.6-terra', web_search_enabled: false })
  })

  it('sends a newly entered key and reports a failed connection test', async () => {
    mocks.test.mockResolvedValue({ ok: false, error: 'invalid_key', latency_ms: 120, model: 'gpt-5.6-luna' })
    render(<AiAgentSettings />)
    fireEvent.change(screen.getByLabelText(/Шинэ түлхүүрээр солих/), { target: { value: 'sk-proj-newkey0123456789abcdef' } })
    fireEvent.click(screen.getByRole('button', { name: 'Холболт шалгах' }))
    await waitFor(() => expect(screen.getByText('API түлхүүр хүчингүй байна.')).toBeInTheDocument())
    expect(mocks.test).toHaveBeenCalledWith({ api_key: 'sk-proj-newkey0123456789abcdef', model: 'gpt-5.6-luna' })
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0].api_key).toBe('sk-proj-newkey0123456789abcdef')
  })

  it('explains the not-configured state', () => {
    mocks.settings = settings({ has_key: false, key_last4: null, key_source: 'none' })
    render(<AiAgentSettings />)
    expect(screen.getByText('Тохируулаагүй')).toBeInTheDocument()
    expect(screen.getByText(/API түлхүүргүй үед/)).toBeInTheDocument()
  })
})
