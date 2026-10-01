import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../store/auth'
import { ReportPolicySettings } from './ReportPolicySettings'

// Query data is referentially stable between renders, as with react-query.
const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  policy: {
    isLoading: false,
    isError: false,
    data: {
      worker_frequencies: ['daily', 'monthly'],
      custom_periods: [],
      departments: [],
      reminder_days: 3,
      available_frequencies: [],
      department_options: [{ id: 7, name: 'Борлуулалт', manager_employee_id: 2, manager_name: 'Болд' }],
    },
  },
}))

vi.mock('../api/enterprise', () => ({
  useReportPolicy: () => mocks.policy,
  useUpdateReportPolicy: () => ({ mutate: mocks.update, isPending: false }),
}))

describe('ReportPolicySettings', () => {
  afterEach(() => { useAuthStore.setState({ actor: null }); mocks.update.mockReset() })

  it('lets an admin pick worker frequencies, add a custom period and a department report', () => {
    useAuthStore.setState({ actor: { id: 1, email: 'a@test', employee_id: 1, locale: 'mn', roles: ['admin'] } })
    render(<ReportPolicySettings />)
    const company = screen.getByRole('group', { name: 'Компанийн бүх ажилтан' })
    fireEvent.click(within(company).getByLabelText('Өдөр'))
    fireEvent.click(within(company).getByLabelText('Улирал'))
    fireEvent.change(screen.getByLabelText('Нэр'), { target: { value: 'Sprint' } })
    fireEvent.click(screen.getByRole('button', { name: /Нэмэх/ }))
    const department = screen.getByRole('group', { name: 'Хэлтсийн тайлан (даргаар)' })
    expect(within(department).queryByLabelText('Өдөр')).toBeNull()
    fireEvent.click(within(department).getByLabelText('Жил'))
    fireEvent.click(screen.getByRole('button', { name: /Хадгалах/ }))
    const payload = mocks.update.mock.calls[0][0]
    expect(payload.worker_frequencies).toEqual(['monthly', 'quarterly'])
    expect(payload.custom_periods).toEqual([expect.objectContaining({ id: 'sprint', label: 'Sprint', unit: 'week', interval: 2 })])
    expect(payload.departments).toEqual([{ department_id: 7, worker_frequencies: null, department_frequencies: ['yearly'] }])
  })

  it('configures a company month and yearly schedule for the frequencies in use', () => {
    useAuthStore.setState({ actor: { id: 1, email: 'a@test', employee_id: 1, locale: 'mn', roles: ['admin'] } })
    render(<ReportPolicySettings />)
    const company = screen.getByRole('group', { name: 'Компанийн бүх ажилтан' })
    fireEvent.click(within(company).getByLabelText('Жил'))
    // Daily reports follow the evening check-in; only periodic ones get a card.
    expect(screen.queryByRole('article', { name: 'Өдөр хуваарь' })).toBeNull()
    const monthly = screen.getByRole('article', { name: 'Сар хуваарь' })
    fireEvent.change(within(monthly).getByLabelText('Эхлэх өдөр (сарын)'), { target: { value: '26' } })
    const yearly = screen.getByRole('article', { name: 'Жил хуваарь' })
    fireEvent.change(within(yearly).getByLabelText('Санхүүгийн жил эхлэх сар'), { target: { value: '7' } })
    fireEvent.change(within(yearly).getByLabelText('Дуусахаас өмнө сануулах (өдөр)'), { target: { value: '30' } })
    fireEvent.change(within(yearly).getByLabelText('Дууссаны дараа илгээх хугацаа (өдөр)'), { target: { value: '15' } })
    fireEvent.change(within(yearly).getByLabelText('Сануулах цаг'), { target: { value: '17' } })
    fireEvent.click(screen.getByRole('button', { name: /Хадгалах/ }))
    const payload = mocks.update.mock.calls[0][0]
    expect(payload.worker_frequencies).toEqual(['daily', 'monthly', 'yearly'])
    expect(payload.frequency_settings.monthly).toEqual({ reminder_days: null, due_days: 0, reminder_hour: null, start_day: 26 })
    expect(payload.frequency_settings.yearly).toEqual({ reminder_days: 30, due_days: 15, reminder_hour: 17, start_day: 1, start_month: 7 })
  })

  it('is read-only for non-admins', () => {
    useAuthStore.setState({ actor: { id: 2, email: 'm@test', employee_id: 2, locale: 'mn', roles: ['manager'] } })
    render(<ReportPolicySettings />)
    expect(screen.getByText(/Зөвхөн админ өөрчилнө/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Хадгалах/ })).toBeNull()
  })
})
