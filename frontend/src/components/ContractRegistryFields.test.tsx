import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ContractRegistryPanel, contractErrorMessage, registryPayload, registryDraftFrom } from './ContractRegistryFields'

const mutate = vi.hoisted(() => vi.fn())
vi.mock('../api/enterprise', () => ({
  useUpdateContractRegistry: () => ({ isPending: false, mutate }),
  useContractPartyOptions: () => ({ data: [] }),
  useCreateContractGroup: () => ({ mutate: vi.fn() }),
  useUpdateContractGroup: () => ({ mutate: vi.fn() }),
  useDeleteContractGroup: () => ({ mutate: vi.fn() }),
}))

const detail = {
  public_id: 'abc', code: 'CT-0001', contract_number: 'ГД-15', group: { id: 2, code: 'SVC', name: 'Үйлчилгээ' }, party: { id: 42, code: '10002', name: 'Салбар ХХК' },
  head_party: { id: 41, code: '10001', name: 'Толгой ХХК' }, signed_on: '2026-09-01', effective_end_on: '2026-09-20', overdue_days: 9, quantity: 120,
  unit: { id: 5, code: 'HR', name: 'Цаг', symbol: 'ц' }, unit_price: 50000, amount: 6000000, currency: 'MNT', penalty_pct: 0.5,
  payment_term: { id: 9, code: 'NET30', name: '30 хоногт' }, note: 'Сар бүр', is_active: true, file_count: 2, files: [],
  links: [{ kind: 'shared', label: 'Скан', url: 'https://drive.example/a.pdf' }, { kind: 'path', label: '', url: 'javascript:alert(1)' }],
  custom_fields: [{ label: 'Хуульч', value: 'Б. Сараа' }],
} as any

describe('ContractRegistryPanel', () => {
  it('shows the d028 registry and only links http(s) URLs', () => {
    render(<ContractRegistryPanel detail={detail} canManage />)
    expect(screen.getByText('CT-0001')).toBeInTheDocument()
    expect(screen.getByText('10001 · Толгой ХХК')).toBeInTheDocument()
    expect(screen.getByText('9')).toHaveClass('contract-overdue')
    expect(screen.getByText('Б. Сараа')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Скан/ })).toHaveAttribute('href', 'https://drive.example/a.pdf')
    expect(screen.getAllByRole('link')).toHaveLength(1)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Идэвхгүй болгох' }))
    expect(mutate).toHaveBeenCalledWith({ publicId: 'abc', is_active: false }, expect.anything())
  })

  it('hides management actions from other viewers', () => {
    render(<ContractRegistryPanel detail={detail} canManage={false} />)
    expect(screen.queryByRole('button', { name: /Бүртгэл засах/ })).not.toBeInTheDocument()
  })
})

describe('registry helpers', () => {
  it('normalizes the draft payload and error details', () => {
    const payload = registryPayload({ ...registryDraftFrom(), code: '  ', amount: '6 000 000', links: [{ kind: 'online', label: ' ', url: ' ' }], custom_fields: [{ label: '', value: 'x' }] })
    expect(payload).toMatchObject({ code: null, amount: '6000000', currency: 'MNT', links: [], custom_fields: [] })
    expect(contractErrorMessage({ response: { data: { detail: { code: 'contract_code_taken', message: 'Код давхардсан' } } } }, 'x')).toBe('Код давхардсан')
    expect(contractErrorMessage({ response: { data: { detail: [{ loc: ['body', 'penalty_pct'], msg: 'too big' }] } } }, 'x')).toBe('penalty_pct: too big')
  })
})
