import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiAccessSettings } from './AiAccessSettings'

// Query data is referentially stable between renders, as with react-query.
const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  access: {
    isLoading: false,
    isError: false,
    data: {
      configured: false,
      updated_at: null,
      groups: [
        { key: 'work', label: 'Ажил ба төлөвлөлт', sections: [
          { key: 'tasks', label: 'Даалгавар', description: '', has_write: true },
          { key: 'reports', label: 'Ажлын тайлан', description: '', has_write: false },
        ] },
        { key: 'people', label: 'Хүний нөөц', sections: [{ key: 'payroll', label: 'Цалин', description: '', has_write: false }] },
      ],
      sections: {
        tasks: { read: true, write: true },
        reports: { read: true, write: false },
        payroll: { read: true, write: false },
      },
    },
  },
}))

vi.mock('../api/aiSettings', () => ({
  useAiAccessSettings: () => mocks.access,
  useUpdateAiAccessSettings: () => ({ mutate: mocks.update, isPending: false }),
}))

describe('AiAccessSettings', () => {
  afterEach(() => mocks.update.mockReset())

  it('counts checkboxes and keeps write dependent on read', () => {
    render(<AiAccessSettings />)
    expect(screen.getByText('4 / 4')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Даалгавар: унших'))
    expect((screen.getByLabelText('Даалгавар: үүсгэх ба засах') as HTMLInputElement).checked).toBe(false)
    fireEvent.click(screen.getByLabelText('Даалгавар: үүсгэх ба засах'))
    expect((screen.getByLabelText('Даалгавар: унших') as HTMLInputElement).checked).toBe(true)
  })

  it('toggles a whole group and saves the matrix', () => {
    render(<AiAccessSettings />)
    fireEvent.click(screen.getByLabelText('ХҮНИЙ НӨӨЦ'))
    expect(screen.getByText('3 / 4')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    expect(mocks.update).toHaveBeenCalledWith({
      tasks: { read: true, write: true },
      reports: { read: true, write: false },
      payroll: { read: false, write: false },
    })
  })

  it('clears everything and warns', () => {
    render(<AiAccessSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'Бүгдийг цуцлах' }))
    expect(screen.getByText('0 / 4')).toBeTruthy()
    expect(screen.getByText('AI туслах компанийн өгөгдөл уншихгүй')).toBeTruthy()
  })
})
