import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationCenter } from './NotificationCenter'

const readOne = vi.fn(() => Promise.resolve())
const readAll = vi.fn()

vi.mock('../api/enterprise', () => ({
  useNotifications: () => ({ isLoading: false, isError: false, data: { unread_count: 1, next_cursor: null, items: [{ id: 7, kind: 'task_assigned', title: 'Шинэ даалгавар', body: 'Танд ажил оноолоо.', target_url: '/tasks?task=7', payload: {}, created_at: new Date().toISOString(), read_at: null, telegram_status: 'queued' }] } }),
  useReadNotification: () => ({ mutateAsync: readOne }),
  useReadAllNotifications: () => ({ mutate: readAll, isPending: false }),
}))

describe('NotificationCenter', () => {
  beforeEach(() => { readOne.mockClear(); readAll.mockClear() })

  it('shows unread state and exposes read actions in the dropdown', () => {
    render(<MemoryRouter><NotificationCenter /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Мэдэгдэл, 1 уншаагүй/ }))
    expect(screen.getByRole('dialog', { name: 'Мэдэгдлүүд' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Бүгдийг унших/ }))
    expect(readAll).toHaveBeenCalledOnce()
  })
})
