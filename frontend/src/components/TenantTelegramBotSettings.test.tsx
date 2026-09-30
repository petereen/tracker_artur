import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TenantTelegramBotSettings } from './TenantTelegramBotSettings'

const mocks = vi.hoisted(() => ({
  connect: vi.fn(),
  renew: vi.fn(),
  disconnect: vi.fn(),
  bot: { isLoading: false, isError: false, data: { connected: false, source: null, status: 'not_connected' } as Record<string, unknown> },
}))

vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantTelegramBot: () => mocks.bot,
  useConnectTelegramBot: () => ({ mutateAsync: mocks.connect, isPending: false }),
  useRenewTelegramHandshake: () => ({ mutateAsync: mocks.renew, isPending: false }),
  useDisconnectTelegramBot: () => ({ mutateAsync: mocks.disconnect, isPending: false }),
}))

const TOKEN = `123456789:${'A'.repeat(35)}`

describe('TenantTelegramBotSettings', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => { if (typeof mock === 'function') (mock as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue({}) })
    mocks.bot.data = { connected: false, source: null, status: 'not_connected' }
  })

  it('starts the handshake with a BotFather token', async () => {
    render(<TenantTelegramBotSettings />)
    expect(screen.getAllByText('Холбогдоогүй').length).toBeGreaterThan(0)
    const input = screen.getByLabelText('BotFather токен')
    fireEvent.change(input, { target: { value: 'not-a-token' } })
    expect(screen.getByText('Токены хэлбэр буруу байна')).toBeInTheDocument()
    fireEvent.change(input, { target: { value: `  ${TOKEN}  ` } })
    fireEvent.click(screen.getByRole('button', { name: /Холбох/ }))
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledWith(TOKEN))
  })

  it('shows the one-time /start link while the handshake is pending', () => {
    mocks.bot.data = {
      connected: false, source: 'tenant', status: 'pending', bot_id: 123456789, bot_username: 'acme_bot', bot_name: 'Acme',
      handshake_url: 'https://t.me/acme_bot?start=oyuns-abc', handshake_expires_at: '2026-10-01T00:00:00Z',
    }
    render(<TenantTelegramBotSettings />)
    expect(screen.getByText('Сүүлийн алхам: ботоо баталгаажуулна уу')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Telegram-аар нээх/ })).toHaveAttribute('href', 'https://t.me/acme_bot?start=oyuns-abc')
    fireEvent.click(screen.getByRole('button', { name: /Шинэ холбоос/ }))
    expect(mocks.renew).toHaveBeenCalled()
    // No token form while waiting for the handshake.
    expect(screen.queryByLabelText('BotFather токен')).toBeNull()
  })

  it('shows a connected bot and lets the admin disconnect it', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mocks.bot.data = {
      connected: true, source: 'tenant', status: 'active', bot_id: 123456789, bot_username: 'acme_bot', bot_name: 'Acme',
      online: true, last_seen_at: '2026-09-30T10:00:00Z', handshake_completed_at: '2026-09-30T09:00:00Z',
    }
    render(<TenantTelegramBotSettings />)
    expect(screen.getAllByText('Холбогдсон').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /@acme_bot/ })).toBeInTheDocument()
    expect(screen.getByText('Одоо ажиллаж байна')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Салгах/ }))
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalled())
  })

  it('explains a revoked token and offers to replace it', () => {
    mocks.bot.data = { connected: false, source: 'tenant', status: 'error', bot_username: 'acme_bot', last_error: 'Telegram токеныг хүчингүй болгосон байна.' }
    render(<TenantTelegramBotSettings />)
    expect(screen.getByText('Telegram токеныг хүчингүй болгосон байна.')).toBeInTheDocument()
    expect(screen.getByLabelText('BotFather токен')).toBeInTheDocument()
  })
})
