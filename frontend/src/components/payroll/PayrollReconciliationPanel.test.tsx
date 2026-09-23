import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollReconciliationPanel } from './PayrollReconciliationPanel'

const mocks = vi.hoisted(() => ({
  resolve: vi.fn(),
  report: {
    data: {
      unresolved_errors: 1,
      unresolved_warnings: 0,
      issues: [{ key: 'missing_bank_details:42', code: 'missing_bank_details', severity: 'error', employee_id: 42, message: 'Bank details are missing.', resolved: false }],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  },
}))

vi.mock('../../api/enterprise', () => ({
  usePayrollReconciliation: () => mocks.report,
  useResolvePayrollReconciliation: () => ({ mutateAsync: mocks.resolve, isPending: false }),
}))
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))

describe('payroll review reconciliation', () => {
  beforeEach(() => { mocks.resolve.mockReset().mockResolvedValue({}) })

  it('shows employee errors and a direct setup link to reviewers', () => {
    render(<MemoryRouter><PayrollReconciliationPanel runId={9} canResolve={false} /></MemoryRouter>)
    expect(screen.getByText(/Bank details are missing/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Банкны мэдээлэл засах' })).toHaveAttribute('href', '/erp/payroll/setup?tab=assignments')
    expect(screen.queryByRole('button', { name: 'Тэмдэглэх' })).not.toBeInTheDocument()
  })

  it('requires an issue and explanation before recording a resolution', async () => {
    render(<MemoryRouter><PayrollReconciliationPanel runId={9} canResolve /></MemoryRouter>)
    const submit = screen.getByRole('button', { name: 'Тэмдэглэх' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Шийдсэн' }))
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('Баримт болон засварыг тэмдэглэнэ үү'), { target: { value: 'Verified new primary account' } })
    fireEvent.click(submit)
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith({ id: 9, issue_keys: ['missing_bank_details:42'], note: 'Verified new primary account' }))
  })
})
