import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ManagerSettingsPage, recipientSubtitle } from './ManagerSettingsPage'

// Astryx Selector reads media queries for its adaptive presentation.
vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

const mocks = vi.hoisted(() => ({
  save: vi.fn(),
  botConnected: true,
  settings: {
    telegram_id: '111111', telegram_username: '@old', telegram_admin_ids: ['111111', '999999'],
    summary_time: '09:00:00', weekly_summary_time: '17:00:00', weekly_summary_day: 5,
    alerts_enabled: true, gamification_enabled: true, soft_mode_weeks: 1, tts_answers_enabled: true, daily_report_reminders_enabled: true,
  },
  options: [
    { employee_id: 1, name: 'Бат', telegram_id: '111111', telegram_username: 'bat', job_title: 'Захирал', department: 'Удирдлага', role: 'Админ' },
    { employee_id: 2, name: 'Саруул', telegram_id: '222222', telegram_username: null, job_title: null, department: null, role: 'Менежер' },
  ],
}))

vi.mock('../api/hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/hooks')>()),
  useManagerSettings: () => ({ data: mocks.settings }),
  useUpdateManagerSettings: () => ({ mutateAsync: mocks.save, isPending: false }),
  useManagerRecipientOptions: () => ({ data: mocks.options }),
}))
vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantContext: () => ({ data: { telegram_bot_connected: mocks.botConnected } }),
}))

describe('ManagerSettingsPage', () => {
  beforeEach(() => { mocks.save.mockReset().mockResolvedValue({}); mocks.botConnected = true })

  it('shows recipients by worker name and position, without a username field', () => {
    render(<ManagerSettingsPage />)
    expect(screen.queryByText(/Username/)).toBeNull()
    expect(screen.getByText('Бат')).toBeInTheDocument()
    expect(screen.getByText(/Захирал · Удирдлага · ID 111111/)).toBeInTheDocument()
    // A configured ID without a worker stays visible and removable.
    expect(screen.getByText('Telegram ID 999999')).toBeInTheDocument()
    expect(recipientSubtitle(mocks.options[1])).toBe('Менежер')
  })

  it('accepts numeric Telegram IDs only and saves the list', async () => {
    render(<ManagerSettingsPage />)
    const manual = screen.getByLabelText('Эсвэл Telegram ID')
    fireEvent.change(manual, { target: { value: '@boss' } })
    expect(screen.getByText('Зөвхөн тоо')).toBeInTheDocument()
    fireEvent.change(manual, { target: { value: '333333' } })
    fireEvent.click(screen.getByRole('button', { name: /^Нэмэх/ }))
    const list = screen.getByRole('list')
    fireEvent.click(within(list).getAllByRole('button', { name: /Хасах/ })[1])
    fireEvent.click(screen.getByRole('button', { name: /Тохиргоо хадгалах/ }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalled())
    expect(mocks.save.mock.calls[0][0].telegram_admin_ids).toEqual(['111111', '333333'])
    expect(mocks.save.mock.calls[0][0]).not.toHaveProperty('telegram_username')
  })

  it('warns when the tenant has no Telegram bot yet', () => {
    mocks.botConnected = false
    render(<ManagerSettingsPage />)
    expect(screen.getByText('Telegram бот холбогдоогүй')).toBeInTheDocument()
  })
})
