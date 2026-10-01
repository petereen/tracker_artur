import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotificationSettings } from './NotificationSettings'
import { NotificationPreferencesCard } from './NotificationPreferencesCard'

const mocks = vi.hoisted(() => ({
  updateTenant: vi.fn(),
  updatePersonal: vi.fn(),
  tenant: {
    isLoading: false,
    isError: false,
    data: { categories: [
      { key: 'tasks', label: 'Даалгавар', description: 'Шинэ даалгавар', legacy: false, enabled: true, web: true, telegram: true, user_editable: true },
      { key: 'checkin', label: 'Check-in', description: 'Хуучин асуулга', legacy: true, enabled: false, web: false, telegram: false, user_editable: true },
    ] },
  },
  personal: {
    isLoading: false,
    isError: false,
    data: {
      telegram_linked: true,
      telegram_bot_connected: true,
      categories: [
        { key: 'tasks', label: 'Даалгавар', description: '', available: true, editable: true, web: true, telegram: true, default_web: true, default_telegram: true },
        { key: 'crm', label: 'CRM', description: '', available: true, editable: false, web: true, telegram: true, default_web: true, default_telegram: true },
      ],
    },
  },
}))

vi.mock('../api/notificationSettings', () => ({
  useTenantNotificationSettings: () => mocks.tenant,
  useUpdateTenantNotificationSettings: () => ({ mutate: mocks.updateTenant, isPending: false }),
  usePersonalNotificationPreferences: () => mocks.personal,
  useUpdatePersonalNotificationPreferences: () => ({ mutate: mocks.updatePersonal, isPending: false }),
}))

describe('NotificationSettings (admin)', () => {
  afterEach(() => { mocks.updateTenant.mockReset() })

  it('turns a category off for everyone and locks personal changes', () => {
    render(<NotificationSettings />)
    // Channels of a disabled category cannot be edited.
    expect(screen.getByRole('switch', { name: 'Check-in: Telegram' })).toBeDisabled()
    fireEvent.click(screen.getByRole('switch', { name: 'Даалгавар: Telegram' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Даалгавар: ажилтан өөрчилнө' }))
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    expect(mocks.updateTenant).toHaveBeenCalledWith({ categories: {
      tasks: { enabled: true, web: true, telegram: false, user_editable: false },
      checkin: { enabled: false, web: false, telegram: false, user_editable: true },
    } })
  })
})

describe('NotificationPreferencesCard (profile)', () => {
  afterEach(() => { mocks.updatePersonal.mockReset() })

  it('saves a personal channel choice and keeps admin-locked categories read-only', () => {
    render(<NotificationPreferencesCard />)
    const tasks = screen.getByRole('group', { name: 'Даалгавар мэдэгдэл' })
    fireEvent.click(tasks.querySelectorAll('[role="switch"]')[1])
    expect(mocks.updatePersonal).toHaveBeenCalledWith({ categories: { tasks: { telegram: false } } })
    const crm = screen.getByRole('group', { name: 'CRM мэдэгдэл' })
    expect(crm).toHaveTextContent('Админ тогтоосон')
    crm.querySelectorAll('[role="switch"]').forEach((item) => expect(item).toBeDisabled())
  })
})
