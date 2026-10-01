import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PlansPage } from './PlansPage'
import { useAuthStore } from '../store/auth'

const state = vi.hoisted(() => ({
  reorder: vi.fn(),
  ideas: [
    { id: 1, plan_month: '2026-10-01', title: 'Санал асуулга явуулах', content: 'NPS судалгаа', suggested_due_date: null, status: 'pending', submitted_by_name: 'Болд', merged_into_plan_item_id: null, source_report_id: null, created_at: '', updated_at: '' },
    { id: 2, plan_month: '2026-10-01', title: 'Хуучин санал', content: null, suggested_due_date: null, status: 'merged', submitted_by_name: 'Сараа', merged_into_plan_item_id: 9, source_report_id: null, created_at: '', updated_at: '' },
  ],
  plan: [
    { id: 9, plan_month: '2026-10-01', title: 'Борлуулалтыг өсгөх', content: null, horizon: 'long_term', position: 0, status: 'approved', due_date: null, source_employee_id: null, source_employee_name: null, source_report_id: null, source_idea_ids: [2], approved_at: '', created_at: '', updated_at: '' },
  ],
}))
vi.mock('../api/hooks', () => {
  const mutation = () => ({ isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() })
  return {
  usePlanIdeas: () => ({ data: state.ideas, isLoading: false, isError: false }),
  useCompanyPlan: () => ({ data: state.plan, isLoading: false, isError: false }),
  useReorderCompanyPlan: () => ({ isPending: false, mutate: state.reorder }),
  useCreateCompanyPlanItem: mutation,
  useCreatePlanIdea: mutation,
  useDeleteCompanyPlanItem: mutation,
  useDeletePlanIdea: mutation,
  useMergePlanIdeas: mutation,
  useUpdateCompanyPlanItem: mutation,
  useUpdatePlanIdea: mutation,
  }
})

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

const openIdeas = () => fireEvent.click(screen.getAllByText('Ажилтнуудын санал')[0])
const renderPage = (roles: string[], url = '/plans') => {
  useAuthStore.setState({ actor: { roles } as any })
  return render(<MemoryRouter initialEntries={[url]}><PlansPage /></MemoryRouter>)
}

describe('PlansPage', () => {
  beforeEach(() => {
    state.reorder.mockReset()
    // jsdom has no modal <dialog>; Astryx Dialog calls showModal/close.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
  })

  it('opens on the company plan and keeps employee ideas as the second section', () => {
    renderPage(['member'])
    expect(screen.getByText('Борлуулалтыг өсгөх')).toBeInTheDocument()
    expect(screen.queryByText('Санал асуулга явуулах')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Төлөвлөгөө нэмэх' })).not.toBeInTheDocument()

    openIdeas()
    expect(screen.getByText('Санал асуулга явуулах')).toBeInTheDocument()
    expect(screen.queryByText('Хуучин санал')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Батлах' })).not.toBeInTheDocument()
  })

  it('lets reviewers add plan items and approve pending ideas', () => {
    renderPage(['manager'])
    expect(screen.getByRole('button', { name: 'Төлөвлөгөө нэмэх' })).toBeInTheDocument()

    openIdeas()
    fireEvent.click(screen.getByRole('button', { name: 'Батлах' }))
    expect(screen.getByText('Саналыг батлах')).toBeInTheDocument()
    expect(screen.getByLabelText(/Төлөвлөгөөний гарчиг/)).toHaveValue('Санал асуулга явуулах')
  })

  it('opens the ideas section for a shared idea link', () => {
    renderPage(['member'], '/plans?month=2026-10&idea=2')
    expect(screen.getByText('Хуучин санал')).toBeInTheDocument()
  })
})
