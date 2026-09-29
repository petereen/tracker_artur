import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ContractArchiveEntry } from '../api/enterprise'
import { ContractArchiveRegistry } from './ContractArchiveRegistry'

const mocks = vi.hoisted(() => ({ mutate: vi.fn() }))

vi.mock('../api/enterprise', () => ({
  useContractRegistryOptions: () => ({ data: { next_code: 'CT-0002', groups: [], can_manage_groups: false, units: [], payment_terms: [] } }),
  useContractPartyOptions: () => ({ data: [], isFetching: false }),
  useCreateContractGroup: () => ({ mutateAsync: vi.fn() }),
  useUpdateContractGroup: () => ({ mutateAsync: vi.fn() }),
  useDeleteContractGroup: () => ({ mutateAsync: vi.fn() }),
  useUpdateContractRegistry: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateContractArchiveEntryRegistry: () => ({ mutate: mocks.mutate, isPending: false }),
}))

const registry = {
  code: null, contract_number: null, group_id: null, group: null, party_id: null, party: null, head_party: null, signed_on: null, quantity: null, unit_id: null, unit: null,
  unit_price: null, amount: null, currency: 'MNT', penalty_pct: null, payment_term_id: null, payment_term: null, note: null, is_active: true, links: [], custom_fields: [],
  overdue_days: 0, file_count: 0, holder: 'entry' as const, contract_public_id: null,
}
const entry = (patch: Partial<ContractArchiveEntry> = {}) => ({ id: 7, name: 'Хуучин гэрээ.pdf', can_edit: true, registry, ...patch }) as ContractArchiveEntry

describe('ContractArchiveRegistry', () => {
  beforeEach(() => mocks.mutate.mockReset())

  it('lets an archive manager add the contract data of an archived contract', () => {
    render(<ContractArchiveRegistry entry={entry()} />)
    expect(screen.getByText('Гэрээний мэдээлэл бөглөгдөөгүй байна — «Бүртгэл засах»-аар нэмнэ үү.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Бүртгэл засах/ }))
    fireEvent.change(screen.getByLabelText('Гэрээний дугаар'), { target: { value: 'ГД-1/2024' } })
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    expect(mocks.mutate).toHaveBeenCalledWith(expect.objectContaining({ id: 7, contract_number: 'ГД-1/2024', currency: 'MNT' }), expect.anything())
  })

  it('shows the data read-only without the edit right', () => {
    render(<ContractArchiveRegistry entry={entry({ can_edit: false, registry: { ...registry, code: 'ГЭ-2024/001', amount: 10000, currency: 'USD' } })} />)
    expect(screen.getByText('ГЭ-2024/001')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Бүртгэл засах/ })).not.toBeInTheDocument()
  })
})
