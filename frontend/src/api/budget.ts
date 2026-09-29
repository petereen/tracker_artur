import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { saveCompanyBlob } from './enterprise'

const BASE = '/v1/erp/budget'
export const budgetKeys = ['v1', 'erp', 'budget'] as const

export type BudgetKind = 'income' | 'cogs' | 'expense' | 'other'
export type BudgetScenario = 'base' | 'optimistic' | 'conservative' | 'other'
export type BudgetPeriodType = 'month' | 'quarter' | 'year' | 'custom'
export type BudgetStatus = 'draft' | 'approved' | 'archived'
export type VarianceStatus = 'favorable' | 'on_track' | 'unfavorable' | 'unplanned' | 'no_activity'
export type AnalysisDimension = 'account' | 'group' | 'kind' | 'project' | 'party_group' | 'month' | 'quarter' | 'year'

export interface BudgetCapabilities {
  module_enabled: boolean
  budgets: Record<'view' | 'create' | 'edit' | 'approve' | 'archive' | 'export', boolean>
  settings: Record<'view' | 'create' | 'edit' | 'archive', boolean>
}

export interface BudgetGroup { id: number; code: string; name: string; kind: BudgetKind; parent_id: number | null; sort: number; is_active: boolean }
export interface LedgerAccountRef { id: number; code: string; name: string; classification: string }
export interface BudgetAccount {
  id: number; code: string; name: string; kind: BudgetKind; group_id: number | null; group_name: string | null
  note: string | null; sort: number; is_active: boolean; erp_accounts: LedgerAccountRef[]; in_use: boolean
}
export interface BudgetLookups {
  currency: string
  groups: BudgetGroup[]
  accounts: BudgetAccount[]
  erp_accounts: Array<LedgerAccountRef & { is_active: boolean; budget_account_id: number | null }>
  projects: Array<{ id: number; code: string; name: string }>
  party_groups: Array<{ id: number; code: string; name: string }>
}

export type BudgetTotals = Record<BudgetKind | 'profit', string>
export interface Budget {
  id: number; public_id: string; number: string; name: string; purpose: string | null
  scenario: BudgetScenario; period_type: BudgetPeriodType; start_date: string; end_date: string
  project_id: number | null; project_name: string | null; currency: string; status: BudgetStatus; is_primary: boolean
  copied_from_id: number | null; approved_at: string | null; approved_by: string | null; created_by: string | null
  totals: BudgetTotals | null; version: number; created_at: string | null; updated_at: string | null
}
export interface BudgetColumn { start: string; end: string; label: string }
export interface BudgetGridRow {
  budget_account_id: number; account_code: string; account_name: string; kind: BudgetKind
  project_id: number | null; party_group_id: number | null; note: string | null; amounts: Record<string, string>; total: string
}
export interface BudgetDetail extends Budget { columns: BudgetColumn[]; rows: BudgetGridRow[] }

export interface BudgetInput { name: string; purpose?: string | null; scenario: BudgetScenario; period_type: BudgetPeriodType; start_date: string; end_date: string; project_id?: number | null }
export interface BudgetLineInput { budget_account_id: number; project_id: number | null; party_group_id: number | null; note: string | null; amounts: Record<string, string> }

export interface Measures {
  budgeted: string; expected: string; actual: string; variance: string; remaining: string
  performance_pct: string | null; status: VarianceStatus
}
export interface AnalysisRow extends Measures { key: Partial<Record<AnalysisDimension, number | string>>; labels: Partial<Record<AnalysisDimension, string>>; kind: BudgetKind | null }
export interface BudgetAnalysis {
  budget: Budget
  window: { date_from: string; date_to: string; as_of: string; elapsed_pct: string }
  group_by: AnalysisDimension[]
  dimension_labels: Partial<Record<AnalysisDimension, string>>
  rows: AnalysisRow[]
  totals: Record<BudgetKind | 'profit', Measures>
  unmapped: Array<{ erp_account_id: number; code: string; name: string; classification: string; actual: string }>
}
export interface AnalysisFilters {
  budget_id?: number; date_from?: string; date_to?: string; as_of?: string; group_by?: string
  project_id?: number; party_group_id?: number; budget_group_id?: number; kind?: BudgetKind
}
export type LedgerLine = {
  id: number; posting_date: string; document_id: number; document_type: string; document_number: string
  account_code: string; account_name: string; budget_account_code: string; budget_account_name: string
  party_name: string | null; project_name: string | null; memo: string | null; debit: string; credit: string; amount: string
}
export interface DrillFilters extends AnalysisFilters { budget_account_id?: number; period_start?: string; period_end?: string }
export interface DrillResult { total_count: number; total_amount: string; items: LedgerLine[]; window: { date_from: string; as_of: string } }

const clean = <T extends object>(params: T) => Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== '' && value !== null))

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: budgetKeys })
}

export function useBudgetCapabilities(enabled = true) {
  return useQuery<BudgetCapabilities>({ queryKey: [...budgetKeys, 'capabilities'], queryFn: () => api.get(`${BASE}/capabilities`).then((r) => r.data), enabled, retry: false, staleTime: 60_000 })
}
export function useBudgetLookups(enabled = true) {
  return useQuery<BudgetLookups>({ queryKey: [...budgetKeys, 'lookups'], queryFn: () => api.get(`${BASE}/lookups`).then((r) => r.data), enabled, staleTime: 60_000 })
}

// ─── Budget accounts & groups ─────────────────────────────────────────────────
export function useSaveBudgetGroup() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: Partial<BudgetGroup> & { id?: number }) => (id ? api.patch(`${BASE}/groups/${id}`, input) : api.post(`${BASE}/groups`, input)).then((r) => r.data as BudgetGroup), onSuccess: invalidate })
}
export function useDeleteBudgetGroup() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/groups/${id}`), onSuccess: invalidate })
}
export type BudgetAccountInput = Partial<Omit<BudgetAccount, 'id' | 'group_name' | 'erp_accounts' | 'in_use'>> & { erp_account_ids?: number[] }
export function useSaveBudgetAccount() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: BudgetAccountInput & { id?: number }) => (id ? api.patch(`${BASE}/accounts/${id}`, input) : api.post(`${BASE}/accounts`, input)).then((r) => r.data as BudgetAccount), onSuccess: invalidate })
}
export function useDeleteBudgetAccount() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/accounts/${id}`), onSuccess: invalidate })
}
export function useGenerateBudgetAccounts() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (erpAccountIds?: number[]) => api.post(`${BASE}/accounts/generate`, { erp_account_ids: erpAccountIds ?? null }).then((r) => r.data as { created: number; accounts: BudgetAccount[] }), onSuccess: invalidate })
}

// ─── Budgets ──────────────────────────────────────────────────────────────────
export interface BudgetListFilters { status?: 'active' | 'draft' | 'approved' | 'archived' | 'all'; scenario?: BudgetScenario; project_id?: number; search?: string; year?: number }
export function useBudgets(filters: BudgetListFilters, enabled = true) {
  return useQuery<{ items: Budget[] }>({ queryKey: [...budgetKeys, 'budgets', filters], queryFn: () => api.get(`${BASE}/budgets`, { params: clean(filters) }).then((r) => r.data), enabled, placeholderData: keepPreviousData })
}
export function useBudget(budgetId?: number) {
  return useQuery<BudgetDetail>({ queryKey: [...budgetKeys, 'budget', budgetId], queryFn: () => api.get(`${BASE}/budgets/${budgetId}`).then((r) => r.data), enabled: Boolean(budgetId) })
}
export function useCreateBudget() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (input: BudgetInput) => api.post(`${BASE}/budgets`, input).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export function useUpdateBudget(budgetId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (input: Partial<BudgetInput> & { version: number }) => api.patch(`${BASE}/budgets/${budgetId}`, input).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export function useSaveBudgetLines(budgetId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (input: { version: number; rows: BudgetLineInput[] }) => api.put(`${BASE}/budgets/${budgetId}/lines`, input).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export type BudgetAction = 'approve' | 'reopen' | 'archive' | 'restore'
export function useBudgetAction() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, action, version }: { id: number; action: BudgetAction; version?: number }) => api.post(`${BASE}/budgets/${id}/${action}`, { version }).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export function useSetPrimaryBudget() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, isPrimary }: { id: number; isPrimary: boolean }) => api.post(`${BASE}/budgets/${id}/primary`, { is_primary: isPrimary }).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export function useCopyBudget() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: { id: number; name: string; purpose?: string | null; scenario: BudgetScenario; shift_years: number; adjust_pct: string }) => api.post(`${BASE}/budgets/${id}/copy`, input).then((r) => r.data as BudgetDetail), onSuccess: invalidate })
}
export function useDeleteBudget() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/budgets/${id}`), onSuccess: invalidate })
}
export function useImportBudget(budgetId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (file: File) => { const body = new FormData(); body.append('file', file); return api.post(`${BASE}/budgets/${budgetId}/import`, body).then((r) => r.data as { imported_rows: number; budget: BudgetDetail }) }, onSuccess: invalidate })
}
export async function downloadBudgetWorkbook(budget: Pick<Budget, 'id' | 'number'>) {
  const response = await api.get(`${BASE}/budgets/${budget.id}/export`, { responseType: 'blob' })
  saveCompanyBlob(response.data, `${budget.number}.xlsx`)
}

// ─── Analysis ─────────────────────────────────────────────────────────────────
export function useBudgetAnalysis(filters: AnalysisFilters, enabled = true) {
  return useQuery<BudgetAnalysis>({ queryKey: [...budgetKeys, 'analysis', filters], queryFn: () => api.get(`${BASE}/analysis`, { params: clean(filters) }).then((r) => r.data), enabled, placeholderData: keepPreviousData, retry: false })
}
export function useBudgetTransactions(filters: DrillFilters | null) {
  return useQuery<DrillResult>({ queryKey: [...budgetKeys, 'transactions', filters], queryFn: () => api.get(`${BASE}/analysis/transactions`, { params: clean(filters ?? {}) }).then((r) => r.data), enabled: Boolean(filters) })
}
export async function downloadBudgetAnalysis(filters: AnalysisFilters, name: string) {
  const response = await api.get(`${BASE}/analysis/export`, { params: clean(filters), responseType: 'blob' })
  saveCompanyBlob(response.data, `${name}.xlsx`)
}
