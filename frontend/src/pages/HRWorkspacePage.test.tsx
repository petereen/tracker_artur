import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HRWorkspacePage } from './HRWorkspacePage'

const mocks = vi.hoisted(() => ({ updateWorker: vi.fn(), createWorker: vi.fn(), createDepartment: vi.fn(), deleteDepartment: vi.fn(), deleteForever: vi.fn(), downloadWorktime: vi.fn() }))
const tenant = vi.hoisted(() => ({ botConnected: true, seats: undefined as undefined | { used: number; limit: number | null; available: number | null; unlimited: boolean } }))

const worker = {
  id: 5, name: 'Бат Дорж', first_name: 'Бат', last_name: 'Дорж', telegram_id: null, telegram_username: null, photo_url: null, timezone: 'Asia/Ulaanbaatar', is_active: true,
  department_id: 1, department_name: 'Санхүү', manager_id: null, manager_name: null, job_title: 'Нягтлан', employment_role: null, employment_type: 'full_time',
  start_date: '2026-09-01', probation_end_date: null, end_date: null, employment_status: 'active', is_archived: false, telegram_status: 'not_invited', account_id: null,
  registration_number: 'УБ99011512', birthday: '1999-01-15', gender: 'male', phone_number: '99112233', email: null, address: null,
  emergency_contact_name: null, emergency_contact_phone: null, termination_reason: null,
}
const archived = { ...worker, id: 6, name: 'Алдаатай бүртгэл', is_active: false, is_archived: true, employment_status: 'inactive' }
const departments = [
  { id: 1, code: 'FIN', name: 'Санхүү', description: null, manager_employee_id: null, is_active: true, employee_count: 1 },
  { id: 2, code: 'DEPT-2', name: 'Хоосон', description: null, manager_employee_id: null, is_active: true, employee_count: 0 },
]
const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }

vi.mock('../api/enterprise', () => ({
  useActor: () => ({ data: { roles: ['hr'], employee_id: 1 } }),
  useHREmployees: () => ({ data: { items: [worker, archived], page: 1, page_size: 50, total: 2 } }),
  useHRDepartments: () => ({ data: departments }),
  useHRLeaveRequests: () => ({ data: [] }),
  useHRLeaveBalances: () => ({ data: [] }),
  useHRAttendance: () => ({ data: { items: [] } }),
  useUpdateHREmployee: () => ({ ...idle, mutateAsync: mocks.updateWorker }),
  useCreateHREmployee: () => ({ ...idle, mutateAsync: mocks.createWorker }),
  useArchiveHREmployee: () => idle,
  useDeleteHREmployeePermanently: () => ({ ...idle, mutateAsync: mocks.deleteForever }),
  useCreateHRDepartment: () => ({ ...idle, mutateAsync: mocks.createDepartment }),
  useUpdateHRDepartment: () => idle,
  useDeleteHRDepartment: () => ({ ...idle, mutateAsync: mocks.deleteDepartment }),
  useHREmployeeRoles: () => ({ data: undefined }),
  useSetHREmployeeRoles: () => idle,
  useEnterpriseSummary: () => ({ isLoading: false, isError: false, data: { completion_rate: 75 } }),
  useDailyAnalytics: () => ({ isLoading: false, isError: false, data: { days: [
    { date: '2026-09-21', worked_minutes: 480, completed_tasks: 2 },
    { date: '2026-09-22', worked_minutes: 0, completed_tasks: 0 },
    { date: '2026-09-23', worked_minutes: 300, completed_tasks: 1 },
  ] } }),
  downloadWorktimeReport: mocks.downloadWorktime,
  useSubmitHRLeave: () => idle,
  useDecideHRLeave: () => idle,
  useUpdateHRLeave: () => idle,
  useSetHRLeaveBalance: () => idle,
  useUpdateHRAttendance: () => idle,
  useBulkUpdateHRAttendance: () => idle,
  useResetHRAttendance: () => idle,
  saveCompanyBlob: vi.fn(),
}))
vi.mock('../components/MonthlyPayrollProfileDrawer', () => ({ MonthlyPayrollProfileDrawer: () => null }))
vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantContext: () => ({ data: { telegram_bot_connected: tenant.botConnected } }),
  useTenantSeats: () => ({ data: tenant.seats }),
}))

const renderPage = () => render(<MemoryRouter><HRWorkspacePage /></MemoryRouter>)
const choose = (label: string, option: string) => { fireEvent.click(screen.getByRole('button', { name: label })); fireEvent.click(screen.getByRole('option', { name: option })) }

describe('HRWorkspacePage worker and department management', () => {
  beforeEach(() => { tenant.botConnected = true; tenant.seats = undefined; Object.values(mocks).forEach((mock) => mock.mockReset().mockResolvedValue({})); vi.spyOn(window, 'confirm').mockReturnValue(true) })

  it('shows worktime stats in the person panel without the invite section', async () => {
    renderPage()
    fireEvent.click(screen.getByText('Бат Дорж'))
    const panel = screen.getByRole('dialog', { name: 'Бат Дорж profile' })
    expect(within(panel).queryByText('Урилга ба профайл')).not.toBeInTheDocument()
    expect(within(panel).getByRole('heading', { name: 'Ажлын цагийн статистик' })).toBeInTheDocument()
    expect(within(panel).getByText('13ц')).toBeInTheDocument()
    expect(within(panel).getByText('75%')).toBeInTheDocument()
    const headings = [...panel.querySelectorAll('h3')].map((node) => node.textContent)
    expect(headings.indexOf('Ажлын цагийн статистик')).toBeGreaterThan(headings.indexOf('Цалингийн тохиргоо'))
    expect(headings.indexOf('Ажлын цагийн статистик')).toBeLessThan(headings.indexOf('Платформын эрх'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Excel татах' }))
    await waitFor(() => expect(mocks.downloadWorktime).toHaveBeenCalledWith(expect.objectContaining({ worker_id: 5 }), 'xlsx'))
  })

  it('edits a worker status and sends only the changed field', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Бат Дорж үйлдлүүд' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Засах' }))
    choose('Төлөв', 'Урт хугацааны чөлөө')
    expect(screen.getByText(/нэвтрэх эрх хаагдаж/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.updateWorker).toHaveBeenCalledWith({ id: 5, employment_status: 'on_leave' }))
  })

  it('fills birthday and gender from the registration number when adding a worker', async () => {
    mocks.createWorker.mockResolvedValue({ invite: { deep_link: 'https://t.me/bot?start=invite_x' } })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Ажилтан нэмэх/ }))
    const dialog = screen.getByRole('dialog', { name: 'Ажилтан нэмэх' })
    fireEvent.change(within(dialog).getByPlaceholderText('УБ99011512'), { target: { value: 'та01231524' } })
    expect((dialog.querySelector('input[type="date"]') as HTMLInputElement).value).toBe('2001-03-15')
    fireEvent.change(within(dialog).getAllByRole('textbox')[1], { target: { value: 'Сараа' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /Урилгатай үүсгэх/ }))
    await waitFor(() => expect(mocks.createWorker).toHaveBeenCalled())
    expect(mocks.createWorker.mock.calls[0][0]).toMatchObject({ first_name: 'Сараа', registration_number: 'ТА01231524', birthday: '2001-03-15', gender: 'female', employment_status: 'active' })
  })

  it('keeps the Telegram ID field inactive until the tenant connects its bot', async () => {
    tenant.botConnected = false
    mocks.createWorker.mockResolvedValue({ invite: null })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Ажилтан нэмэх/ }))
    const dialog = screen.getByRole('dialog', { name: 'Ажилтан нэмэх' })
    const telegramId = within(dialog).getByLabelText('Telegram ID (заавал биш)') as HTMLInputElement
    expect(telegramId.disabled).toBe(true)
    expect(within(dialog).getByText(/Telegram бот холбогдоогүй/)).toBeTruthy()
    fireEvent.change(within(dialog).getAllByRole('textbox')[1], { target: { value: 'Сараа' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^Үүсгэх/ }))
    await waitFor(() => expect(mocks.createWorker).toHaveBeenCalled())
    expect(mocks.createWorker.mock.calls[0][0]).toMatchObject({ telegram_id: null })
  })

  it('still adds a worker when the seat limit is reached, but warns the admin', async () => {
    tenant.seats = { used: 5, limit: 5, available: 0, unlimited: false }
    mocks.createWorker.mockResolvedValue({ invite: null, seat_warning: 'Лицензийн хэрэглэгчийн эрх дүүрсэн (5/5).' })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Ажилтан нэмэх/ }))
    const dialog = screen.getByRole('dialog', { name: 'Ажилтан нэмэх' })
    expect(within(dialog).getByText('Хэрэглэгчийн эрх дүүрсэн (5 / 5)')).toBeTruthy()
    fireEvent.change(within(dialog).getAllByRole('textbox')[1], { target: { value: 'Сараа' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /Урилгатай үүсгэх/ }))
    await waitFor(() => expect(mocks.createWorker).toHaveBeenCalled())
  })

  it('blocks saving an invalid registration number', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Ажилтан нэмэх/ }))
    const dialog = screen.getByRole('dialog', { name: 'Ажилтан нэмэх' })
    fireEvent.change(within(dialog).getAllByRole('textbox')[1], { target: { value: 'Сараа' } })
    fireEvent.change(within(dialog).getByPlaceholderText('УБ99011512'), { target: { value: 'УБ12' } })
    expect(within(dialog).getByText(/2 кирилл үсэг/)).toBeTruthy()
    expect((within(dialog).getByRole('button', { name: /Урилгатай үүсгэх/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('offers permanent delete only for archived workers', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Бат Дорж үйлдлүүд' }))
    expect(screen.queryByRole('menuitem', { name: 'Бүр мөсөн устгах' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Алдаатай бүртгэл үйлдлүүд' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Бүр мөсөн устгах' }))
    await waitFor(() => expect(mocks.deleteForever).toHaveBeenCalledWith(6))
  })

  it('manages departments and protects ones that still have workers', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Хэлтэс' }))
    expect((screen.getByRole('button', { name: 'Санхүү устгах' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Хоосон устгах' }))
    await waitFor(() => expect(mocks.deleteDepartment).toHaveBeenCalledWith(2))
    fireEvent.click(screen.getByRole('button', { name: /Хэлтэс нэмэх/ }))
    const dialog = screen.getByRole('dialog', { name: 'Хэлтэс нэмэх' })
    fireEvent.change(within(dialog).getByPlaceholderText('Санхүүгийн хэлтэс'), { target: { value: 'Борлуулалт' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.createDepartment).toHaveBeenCalledWith({ name: 'Борлуулалт', description: null, manager_employee_id: null, code: null }))
  })
})
