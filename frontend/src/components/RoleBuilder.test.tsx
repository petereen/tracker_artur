import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RoleBuilder } from './RoleBuilder'

const mocks = vi.hoisted(() => {
  const catalog = {
    system_roles: [{ key: 'manager', label: 'Менежер', description: '' }, { key: 'hr', label: 'Хүний нөөц', description: '' }],
    modules: [
      { key: 'crm', label: 'CRM', resources: [{ key: 'crm_activity', label: 'Харилцаа холбоо, ажил', actions: [{ key: 'view', label: 'Харах' }, { key: 'edit', label: 'Засах' }] }] },
      { key: 'accounting', label: 'Нягтлан', resources: [{ key: 'accounts', label: 'Дансны төлөвлөгөө', actions: [{ key: 'view', label: 'Харах' }, { key: 'edit', label: 'Засах' }] }] },
    ],
    action_labels: {},
  }
  const roles = [
    { id: 3, name: 'Accountant', code: 'erp_accountant', description: null, is_system: true, is_active: true, system_roles: [], capabilities: [{ resource: 'accounts', action: '*' }, { resource: 'journal_entry', action: '*' }], account_assignments: [], team_assignments: [] },
    { id: 9, name: 'Борлуулалт', code: 'sales', description: null, is_system: false, is_active: true, system_roles: ['manager'], capabilities: [{ resource: 'crm_activity', action: 'view' }], account_assignments: [{ id: 1, account_id: 4, scope: {}, label: 'Болд' }], team_assignments: [] },
  ]
  return {
    create: vi.fn(async (input) => ({ ...input, id: 11 })),
    update: vi.fn(async (input) => input),
    unassign: vi.fn(async () => undefined),
    catalog: { isLoading: false, isError: false, data: catalog },
    roles: { isLoading: false, isError: false, data: roles },
  }
})

// Astryx Selector reads media queries.
vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

const mutation = (fn: any = vi.fn()) => ({ mutate: fn, mutateAsync: fn, isPending: false })
vi.mock('../api/enterprise', () => ({
  useERPRoleCatalog: () => mocks.catalog,
  useERPAccessRoles: () => mocks.roles,
  useCreateERPAccessRole: () => mutation(mocks.create),
  useUpdateERPAccessRole: () => mutation(mocks.update),
  useCloneERPAccessRole: () => mutation(),
  useDeactivateERPAccessRole: () => mutation(),
  useActivateERPAccessRole: () => mutation(),
  useDeleteERPAccessRole: () => mutation(),
  useAssignERPAccountRole: () => mutation(),
  useAssignERPTeamRole: () => mutation(),
  useUnassignERPAccountRole: () => mutation(mocks.unassign),
  useUnassignERPTeamRole: () => mutation(),
  useManagedAccounts: () => ({ data: [{ id: 4, email: 'bold', status: 'active' }, { id: 5, email: 'saraa', status: 'active' }] }),
  useTeams: () => ({ data: [] }),
}))

describe('RoleBuilder', () => {
  afterEach(() => { mocks.create.mockClear(); mocks.update.mockClear(); mocks.unassign.mockClear() })

  it('creates a role from a name, platform access and module permissions (no code needed)', async () => {
    render(<RoleBuilder />)
    fireEvent.change(screen.getByLabelText(/Үүргийн нэр/), { target: { value: 'Нягтлан бодогч' } })
    fireEvent.click(screen.getByLabelText('Хүний нөөц'))
    const accounting = screen.getByRole('region', { name: 'Нягтлан' })
    fireEvent.click(within(accounting).getByLabelText('Дансны төлөвлөгөө'))
    fireEvent.click(screen.getByRole('button', { name: 'Үүрэг үүсгэх' }))
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalled())
    expect(mocks.create.mock.calls[0][0]).toEqual({
      name: 'Нягтлан бодогч', description: undefined, system_roles: ['hr'],
      capabilities: [{ resource: 'accounts', action: 'view' }, { resource: 'accounts', action: 'edit' }],
    })
  })

  it('shows templates read-only with their wildcard grants expanded', () => {
    render(<RoleBuilder />)
    fireEvent.click(screen.getByRole('button', { name: /Accountant/ }))
    expect(screen.getByText(/Загвар үүргийг шууд засах боломжгүй/)).toBeInTheDocument()
    const accounting = screen.getByRole('region', { name: 'Нягтлан' })
    expect(within(accounting).getByLabelText('Засах')).toBeChecked()
    expect(screen.getByText(/journal_entry\.\*/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Хуулж засах' })).toBeInTheDocument()
  })

  it('edits a custom role and removes an assignment', async () => {
    render(<RoleBuilder />)
    fireEvent.click(screen.getByRole('button', { name: /Борлуулалт/ }))
    expect(screen.getByLabelText('Менежер')).toBeChecked()
    const crm = screen.getByRole('region', { name: 'CRM' })
    fireEvent.click(within(crm).getByLabelText('Засах'))
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0]).toMatchObject({ id: 9, system_roles: ['manager'], capabilities: [{ resource: 'crm_activity', action: 'view' }, { resource: 'crm_activity', action: 'edit' }] })
    fireEvent.click(screen.getByRole('button', { name: /Болд/ }))
    await vi.waitFor(() => expect(mocks.unassign).toHaveBeenCalledWith({ roleId: 9, assignmentId: 1 }))
  })
})
