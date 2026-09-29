import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ERPModuleSettings } from './ERPModuleSettings'

const mocks = vi.hoisted(() => ({ update: vi.fn(), modules: { crm: true, budget: false, payroll: false } as Record<string, boolean> }))

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../api/enterprise', () => ({
  useERPMetadata: () => ({ data: { modules: mocks.modules, module_labels: {}, document_modules: {}, actions: [], currency: 'MNT', custom_fields: [], roles: [], module_visibility_is_not_authorization: true }, isLoading: false, isError: false }),
  useUpdateERPModules: () => ({ mutate: mocks.update, isPending: false }),
}))

describe('ERP module settings', () => {
  beforeEach(() => {
    mocks.update.mockReset()
    mocks.modules = { crm: true, budget: false, payroll: false }
  })

  it('lists only modules that have a workspace, plus the always-on chart of accounts', () => {
    render(<MemoryRouter><ERPModuleSettings /></MemoryRouter>)
    expect(screen.getByText('CRM · Харилцагч')).toBeInTheDocument()
    expect(screen.getByText('Төсөв, гүйцэтгэл')).toBeInTheDocument()
    expect(screen.getByText('Цалин')).toBeInTheDocument()
    expect(screen.getByText('Дансны төлөвлөгөө')).toBeInTheDocument()
    for (const retired of ['Accounting', 'Selling', 'Buying', 'Stock', 'Manufacturing', 'Assets & maintenance', 'Support']) {
      expect(screen.queryByText(retired)).not.toBeInTheDocument()
    }
    // Enabled CRM and the chart of accounts get an open link; disabled modules do not.
    expect(screen.getAllByRole('link', { name: 'Нээх' }).map((link) => link.getAttribute('href'))).toEqual(['/erp/crm', '/erp/accounts'])
  })

  it('sends the full module map when a switch is toggled', () => {
    render(<MemoryRouter><ERPModuleSettings /></MemoryRouter>)
    fireEvent.click(screen.getByLabelText('Цалин идэвхжүүлэх'))
    expect(mocks.update).toHaveBeenCalledWith({ crm: true, budget: false, payroll: true }, expect.anything())
  })
})
