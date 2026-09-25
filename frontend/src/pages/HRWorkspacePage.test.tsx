import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HRWorkspacePage } from './HRWorkspacePage'

const mocks = vi.hoisted(() => ({ updateWorker: vi.fn(), createWorker: vi.fn(), createDepartment: vi.fn(), deleteDepartment: vi.fn(), deleteForever: vi.fn() }))

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
  useRegenerateHRInvite: () => idle,
  useRevokeHRInvite: () => idle,
  useSubmitHRLeave: () => idle,
  useDecideHRLeave: () => idle,
  useUpdateHRLeave: () => idle,
  useSetHRLeaveBalance: () => idle,
  useUpdateHRAttendance: () => idle,
  useBulkUpdateHRAttendance: () => idle,
  downloadHRAttendanceCsv: vi.fn(),
}))
vi.mock('../components/MonthlyPayrollProfileDrawer', () => ({ MonthlyPayrollProfileDrawer: () => null }))

const renderPage = () => render(<MemoryRouter><HRWorkspacePage /></MemoryRouter>)
const choose = (label: string, option: string) => { fireEvent.click(screen.getByRole('button', { name: label })); fireEvent.click(screen.getByRole('option', { name: option })) }

describe('HRWorkspacePage worker and department management', () => {
  beforeEach(() => { Object.values(mocks).forEach((mock) => mock.mockReset().mockResolvedValue({})); vi.spyOn(window, 'confirm').mockReturnValue(true) })

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
