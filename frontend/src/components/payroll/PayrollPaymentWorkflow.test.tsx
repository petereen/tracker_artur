import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { PayrollPaymentWorkflow } from './PayrollPaymentWorkflow'

const mocks = vi.hoisted(() => ({
  batchId: vi.fn(),
  details: vi.fn(),
  mutation: { mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false },
}))

vi.mock('../../api/enterprise', () => ({
  usePayrollPaymentBatches: () => ({ data: [{ id: 7 }] }),
  usePayrollPaymentBatch: (id: number) => {
    mocks.batchId(id)
    return { data: mocks.details() }
  },
  usePayrollPaymentAllocations: () => ({ data: [] }),
  usePreparePayrollPayments: () => mocks.mutation,
  useSubmitPayrollPaymentBatch: () => mocks.mutation,
  useSettlePayrollPayment: () => mocks.mutation,
  useRejectPayrollPayment: () => mocks.mutation,
  useReversePayrollPayment: () => mocks.mutation,
  usePublishPayrollPayslips: () => mocks.mutation,
  usePayrollBankExportProfiles: () => ({ data: [] }),
  useCreatePayrollBankExport: () => mocks.mutation,
  usePayrollStatementImports: () => ({ data: [] }),
  usePayrollStatementImport: () => ({ data: undefined }),
  useImportPayrollStatement: () => mocks.mutation,
  useMatchPayrollStatementLine: () => mocks.mutation,
}))
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))

describe('payroll payment resume', () => {
  it('fetches allocation detail for a listed batch and gates settlement on submission', () => {
    mocks.details.mockReturnValue({
      id: 7,
      batch_reference: 'PB-7',
      payment_account_id: 11,
      total_amount: '250.00',
      status: 'prepared',
      allocations: [{ id: 17, employee_id: 42, amount: '250.00', status: 'pending' }],
    })
    render(<MemoryRouter><PayrollPaymentWorkflow runId={3} status="payment_prepared" canPay canRelease released={false} /></MemoryRouter>)
    expect(mocks.batchId).toHaveBeenCalledWith(7)
    expect(screen.getByText('Ажилтан #42')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Төлөгдсөн' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Цалингийн хуудас гаргах' })).toBeDisabled()
  })

  it('shows release after settled payment resumes', () => {
    mocks.details.mockReturnValue({
      id: 7,
      batch_reference: 'PB-7',
      payment_account_id: 11,
      total_amount: '250.00',
      status: 'settled',
      allocations: [{ id: 17, employee_id: 42, amount: '250.00', status: 'settled', transaction_reference: 'BANK-123' }],
    })
    render(<MemoryRouter><PayrollPaymentWorkflow runId={3} status="settled" canPay={false} canRelease released={false} /></MemoryRouter>)
    expect(screen.getByText(/BANK-123/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Цалингийн хуудас гаргах' })).toBeEnabled()
  })

  it('offers a new batch for the unpaid remainder of a partial run', async () => {
    mocks.mutation.mutateAsync.mockReset().mockResolvedValue({})
    mocks.details.mockReturnValue({
      id: 7,
      batch_reference: 'PB-7',
      payment_account_id: 11,
      total_amount: '100.00',
      status: 'settled',
      allocations: [{ id: 17, employee_id: 42, amount: '100.00', status: 'settled', transaction_reference: 'BANK-123' }],
    })
    render(<MemoryRouter><PayrollPaymentWorkflow runId={3} status="partially_settled" canPay canRelease released={false} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'Үлдэгдэл төлбөр бэлтгэх' }))
    await waitFor(() => expect(mocks.mutation.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ id: 3, idempotency_key: expect.any(String) })))
  })
})
