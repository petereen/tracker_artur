import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { saveCompanyBlob } from './enterprise'

const BASE = '/v1/erp/crm'
export const crmKeys = ['v1', 'erp', 'crm'] as const

export type CRMAction = 'view' | 'create' | 'edit' | 'archive'
export type CRMStatusCategory = 'open' | 'in_progress' | 'waiting' | 'done' | 'cancelled'

export interface CRMCapabilities {
  module_enabled: boolean
  employee_id: number | null
  parties: Record<CRMAction, boolean>
  activities: Record<CRMAction, boolean>
  settings: Record<CRMAction, boolean>
}

export interface CRMStatus { id: number; register: string; code: string; name: string; sort: number; color: string; category: CRMStatusCategory; is_active: boolean }
export interface CRMActivityType { id: number; code: string; name: string; sort: number; is_active: boolean }
export interface CRMPartyGroup { id: number; code: string; name: string; parent_id: number | null; is_default: boolean; is_foreign: boolean; default_settlement_account_id: number | null; default_price_list_id: number | null; is_active: boolean }
export interface CRMPaymentTerm { id: number; code: string; name: string; days: number; period_unit: 'day' | 'month'; period_value: number; is_active: boolean }

export interface CRMLookups {
  employees: Array<{ id: number; name: string; job_title: string | null }>
  statuses: CRMStatus[]
  activity_types: CRMActivityType[]
  party_groups: CRMPartyGroup[]
  payment_terms: CRMPaymentTerm[]
  contracts: Array<{ id: number; title: string; status: string }>
  projects: Array<{ id: number; code: string; name: string }>
  price_lists: Array<{ id: number; code: string; name: string }>
  settlement_accounts: Array<{ id: number; code: string; name: string }>
}

export interface CRMPartyLink { label: string; url: string }

export interface CRMParty {
  id: number; public_id: string; code: string; name: string; name_en: string | null; business_name: string | null
  party_type: 'customer' | 'supplier' | 'prospect' | 'contact'
  registry_no: string | null; tax_id: string | null
  is_customer: boolean; is_supplier: boolean; is_individual: boolean; is_foreign: boolean
  vat_payer: boolean; city_tax_payer: boolean; tax_status_checked_at: string | null
  email: string | null; phone: string | null; website: string | null; legal_address: string | null; location: string | null; informal_address: string | null
  tags: string[]
  group_id: number | null; group_name: string | null
  responsible_employee_id: number | null; responsible_name: string | null
  parent_party_id: number | null; parent_name: string | null; settle_via_parent: boolean
  customer_since: string | null; inactive_since: string | null
  payment_term_id: number | null; payment_term_name: string | null
  price_list_id: number | null; price_list_name: string | null
  settlement_account_id: number | null; settlement_account_name: string | null
  credit_limit: string | null; currency: string
  sales_discount_pct: string | null; sales_note: string | null; sales_lead_days: number | null
  purchase_discount_pct: string | null; purchase_note: string | null; purchase_lead_days: number | null
  delivery_terms: string | null; links: CRMPartyLink[]; custom: Record<string, unknown>
  is_active: boolean; status: string; version: number; created_at: string | null; updated_at: string | null
  duplicate_tax_id?: boolean; duplicate_name?: boolean
}

export interface CRMContact { id: number; party_id: number; name: string; nickname: string | null; position: string | null; phone: string | null; email: string | null; address: string | null; note: string | null; is_default: boolean; is_active: boolean }
export interface CRMBankAccount { id: number; party_id: number; bank_name: string; currency: string; iban_prefix: string | null; account_no: string; account_name: string | null; note: string | null; is_default: boolean; is_active: boolean }
export interface CRMPartyStats { activities_total: number; activities_open: number; activities_overdue: number; expected_revenue_open: string | null; last_activity_at: string | null; documents_total: number }

export interface CRMPartyDetail extends CRMParty {
  contacts: CRMContact[]
  bank_accounts: CRMBankAccount[]
  children: Array<{ id: number; code: string; name: string; is_active: boolean }>
  stats: CRMPartyStats
  group_stats: CRMPartyStats | null
}

export interface CRMActivity {
  id: number; public_id: string; number: string
  party_id: number | null; party_code: string | null; party_name: string | null
  contact_id: number | null; contact_name: string | null; contact_phone: string | null; contact_email: string | null
  activity_at: string | null; subject: string; body: string | null
  type_id: number | null; type_name: string | null; is_important: boolean
  due_at: string | null; duration_minutes: number | null
  responsible_employee_id: number | null; responsible_name: string | null
  status_id: number | null; status: { id: number; name: string; color: string; category: CRMStatusCategory } | null
  completed_at: string | null; completion_note: string | null
  reference: string | null; contract_id: number | null; contract_title: string | null
  project_id: number | null; project_name: string | null; task_id: number | null; task_title: string | null
  is_closed: boolean; closed_at: string | null
  reviewed_by_employee_id: number | null; reviewed_by_name: string | null; reviewed_at: string | null
  expected_revenue: string | null; currency: string
  overdue_days: number; is_open: boolean; is_overdue: boolean; is_active: boolean; custom: Record<string, unknown>
  created_by_employee_id: number | null; created_by_name: string | null
  version: number; created_at: string | null; updated_at: string | null
}

export interface CRMSummary {
  open: number; overdue: number; due_today: number; due_this_week: number; important: number
  expected_revenue: Array<{ currency: string; amount: string }>
  by_status: Array<{ status_id: number; name: string; color: string; count: number }>
  by_responsible: Array<{ employee_id: number; name: string; open: number; overdue: number }>
}

export interface CRMHistoryEntry { id: number; action: string; actor_name: string | null; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string | null }
export interface CRMPartyDocument { id: number; number: string; document_type: string; status: string; posting_date: string | null; due_date: string | null; grand_total: string | null; outstanding_amount: string | null; currency: string; party_id: number }
export interface CRMAttachment { id: number; filename: string; content_type: string; size: number; checksum: string; scan_status: string; created_at: string | null }
export interface CRMTaxpayer { registry_no: string | null; tin: string; name: string | null; vat_payer: boolean; city_tax_payer: boolean; found: boolean; duplicates: Array<{ party_id: number; code: string; name: string; reason: string }> }
export interface CRMImportResult { dry_run: boolean; total_rows: number; valid_rows: number; created: number; errors: Array<{ row: number; code: string; message: string }>; warnings: Array<{ row: number; code: string; message: string }> }

export interface Paged<T> { items: T[]; total: number; page: number; page_size: number }

export interface CRMPartyFilters { search?: string; kind?: 'all' | 'customer' | 'supplier' | 'prospect'; group_id?: number; responsible_employee_id?: number; parent_party_id?: number; is_active?: boolean; duplicates_only?: boolean; page?: number; page_size?: number }
export interface CRMActivityFilters {
  search?: string; party_id?: number; include_children?: boolean; type_id?: number; status_id?: number; responsible_employee_id?: number
  mine?: boolean; state?: 'open' | 'closed' | 'all'; overdue?: boolean; important?: boolean; is_active?: boolean
  date_from?: string; date_to?: string; due_from?: string; due_to?: string; sort?: 'activity_at' | 'due_at' | 'number'; page?: number; page_size?: number
}

export type CRMPartyInput = Partial<Omit<CRMParty, 'id' | 'public_id' | 'group_name' | 'responsible_name' | 'parent_name' | 'payment_term_name' | 'price_list_name' | 'settlement_account_name' | 'status' | 'created_at' | 'updated_at' | 'tax_status_checked_at' | 'duplicate_tax_id' | 'duplicate_name'>> & { confirm_duplicate_tin?: boolean }
export type CRMActivityInput = Partial<Pick<CRMActivity,
  'party_id' | 'contact_id' | 'contact_name' | 'contact_phone' | 'contact_email' | 'activity_at' | 'subject' | 'body' | 'type_id' | 'is_important' |
  'due_at' | 'duration_minutes' | 'responsible_employee_id' | 'status_id' | 'completed_at' | 'completion_note' | 'reference' | 'contract_id' |
  'project_id' | 'is_closed' | 'expected_revenue' | 'currency' | 'is_active' | 'version'>> & { type_name?: string | null }

const clean = <T extends object>(params: T) => Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== '' && value !== null))

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: crmKeys })
}

export function useCRMCapabilities(enabled = true) {
  return useQuery<CRMCapabilities>({ queryKey: [...crmKeys, 'capabilities'], queryFn: () => api.get(`${BASE}/capabilities`).then((r) => r.data), enabled, retry: false, staleTime: 60_000 })
}
export function useCRMLookups(enabled = true) {
  return useQuery<CRMLookups>({ queryKey: [...crmKeys, 'lookups'], queryFn: () => api.get(`${BASE}/lookups`).then((r) => r.data), enabled, staleTime: 60_000 })
}
export function useCRMSummary(mine: boolean, enabled = true) {
  return useQuery<CRMSummary>({ queryKey: [...crmKeys, 'summary', mine], queryFn: () => api.get(`${BASE}/summary`, { params: { mine } }).then((r) => r.data), enabled })
}

// ─── Parties ──────────────────────────────────────────────────────────────────
export function useCRMParties(filters: CRMPartyFilters, enabled = true) {
  return useQuery<Paged<CRMParty>>({ queryKey: [...crmKeys, 'parties', filters], queryFn: () => api.get(`${BASE}/parties`, { params: clean(filters) }).then((r) => r.data), enabled, placeholderData: keepPreviousData })
}
export function useCRMParty(partyId?: number) {
  return useQuery<CRMPartyDetail>({ queryKey: [...crmKeys, 'party', partyId], queryFn: () => api.get(`${BASE}/parties/${partyId}`).then((r) => r.data), enabled: Boolean(partyId) })
}
export function useCRMPartyHistory(partyId?: number, enabled = true) {
  return useQuery<CRMHistoryEntry[]>({ queryKey: [...crmKeys, 'party', partyId, 'history'], queryFn: () => api.get(`${BASE}/parties/${partyId}/history`).then((r) => r.data), enabled: Boolean(partyId) && enabled })
}
export function useCRMPartyDocuments(partyId?: number, includeChildren = false, enabled = true) {
  return useQuery<CRMPartyDocument[]>({ queryKey: [...crmKeys, 'party', partyId, 'documents', includeChildren], queryFn: () => api.get(`${BASE}/parties/${partyId}/documents`, { params: { include_children: includeChildren } }).then((r) => r.data), enabled: Boolean(partyId) && enabled })
}
export function useCRMFiles(kind: 'parties' | 'activities', id?: number, enabled = true) {
  return useQuery<CRMAttachment[]>({ queryKey: [...crmKeys, kind, id, 'files'], queryFn: () => api.get(`${BASE}/${kind}/${id}/files`).then((r) => r.data), enabled: Boolean(id) && enabled })
}
export function useSaveCRMParty() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...input }: CRMPartyInput & { id?: number }) => (id ? api.patch(`${BASE}/parties/${id}`, input) : api.post(`${BASE}/parties`, input)).then((r) => r.data as CRMParty & { duplicates?: CRMTaxpayer['duplicates'] }),
    onSuccess: invalidate,
  })
}
export function useDeleteCRMParty() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/parties/${id}`), onSuccess: invalidate })
}
export function useRefreshCRMTaxStatus() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.post(`${BASE}/parties/${id}/refresh-tax-status`).then((r) => r.data as CRMParty & { official_name: string | null; changed: string[] }), onSuccess: invalidate })
}
export async function lookupCRMTaxpayer(params: { registry_no?: string; tin?: string }) {
  return api.get(`${BASE}/parties/lookup-taxpayer`, { params: clean(params) }).then((r) => r.data as CRMTaxpayer)
}
export function useSaveCRMContact(partyId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: Partial<CRMContact> & { id?: number }) => (id ? api.patch(`${BASE}/parties/${partyId}/contacts/${id}`, input) : api.post(`${BASE}/parties/${partyId}/contacts`, input)).then((r) => r.data as CRMContact), onSuccess: invalidate })
}
export function useDeleteCRMContact(partyId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/parties/${partyId}/contacts/${id}`), onSuccess: invalidate })
}
export function useSaveCRMBankAccount(partyId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: Partial<CRMBankAccount> & { id?: number }) => (id ? api.patch(`${BASE}/parties/${partyId}/bank-accounts/${id}`, input) : api.post(`${BASE}/parties/${partyId}/bank-accounts`, input)).then((r) => r.data as CRMBankAccount), onSuccess: invalidate })
}
export function useDeleteCRMBankAccount(partyId: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/parties/${partyId}/bank-accounts/${id}`), onSuccess: invalidate })
}
export function useUploadCRMFile(kind: 'parties' | 'activities', id: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (file: File) => { const body = new FormData(); body.append('file', file); return api.post(`${BASE}/${kind}/${id}/files`, body).then((r) => r.data as CRMAttachment) }, onSuccess: invalidate })
}
export function useDeleteCRMFile() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/files/${id}`), onSuccess: invalidate })
}
export async function downloadCRMFile(file: CRMAttachment) {
  const response = await api.get(`${BASE}/files/${file.id}/download`, { responseType: 'blob' })
  saveCompanyBlob(response.data, file.filename)
}
export async function downloadCRMPartiesCsv(filters: CRMPartyFilters) {
  const response = await api.get(`${BASE}/parties/export.csv`, { params: clean({ ...filters, page: undefined, page_size: undefined, duplicates_only: undefined }), responseType: 'blob' })
  saveCompanyBlob(response.data, `customers-${new Date().toISOString().slice(0, 10)}.csv`)
}
export async function downloadCRMImportTemplate() {
  const response = await api.get(`${BASE}/parties/import-template.csv`, { responseType: 'blob' })
  saveCompanyBlob(response.data, 'customer-import-template.csv')
}
export function useImportCRMParties() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) => { const body = new FormData(); body.append('file', file); return api.post(`${BASE}/parties/import`, body, { params: { dry_run: dryRun } }).then((r) => r.data as CRMImportResult) },
    onSuccess: (result) => { if (!result.dry_run) void invalidate() },
  })
}

// ─── Activities ───────────────────────────────────────────────────────────────
export function useCRMActivities(filters: CRMActivityFilters, enabled = true) {
  return useQuery<Paged<CRMActivity>>({ queryKey: [...crmKeys, 'activities', filters], queryFn: () => api.get(`${BASE}/activities`, { params: clean(filters) }).then((r) => r.data), enabled, placeholderData: keepPreviousData })
}
export function useCRMActivity(activityId?: number) {
  return useQuery<CRMActivity>({ queryKey: [...crmKeys, 'activity', activityId], queryFn: () => api.get(`${BASE}/activities/${activityId}`).then((r) => r.data), enabled: Boolean(activityId) })
}
export function useSaveCRMActivity() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: CRMActivityInput & { id?: number }) => (id ? api.patch(`${BASE}/activities/${id}`, input) : api.post(`${BASE}/activities`, input)).then((r) => r.data as CRMActivity), onSuccess: invalidate })
}
export function useBulkCRMActivities() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (input: { party_ids: number[]; template: CRMActivityInput }) => api.post(`${BASE}/activities/bulk`, input).then((r) => r.data as { created: number; items: CRMActivity[] }), onSuccess: invalidate })
}
export function useCRMActivityAction(action: 'clone' | 'close' | 'reopen' | 'review') {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, completion_note }: { id: number; completion_note?: string }) => api.post(`${BASE}/activities/${id}/${action}`, action === 'close' ? { completion_note } : undefined).then((r) => r.data as CRMActivity), onSuccess: invalidate })
}
export function useCreateCRMActivityTask() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: { id: number; title?: string; deadline_at?: string | null; assignee_employee_id?: number | null }) => api.post(`${BASE}/activities/${id}/task`, input).then((r) => r.data as { task_id: number; activity: CRMActivity }), onSuccess: invalidate })
}
export function useDeleteCRMActivity() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/activities/${id}`), onSuccess: invalidate })
}

// ─── Settings ─────────────────────────────────────────────────────────────────
export type CRMSettingKind = 'statuses' | 'activity-types' | 'party-groups' | 'payment-terms'
export function useSaveCRMSetting(kind: CRMSettingKind) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: ({ id, ...input }: Record<string, unknown> & { id?: number }) => (id ? api.patch(`${BASE}/settings/${kind}/${id}`, input) : api.post(`${BASE}/settings/${kind}`, input)).then((r) => r.data), onSuccess: invalidate })
}
export function useDeleteCRMSetting(kind: CRMSettingKind) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (id: number) => api.delete(`${BASE}/settings/${kind}/${id}`), onSuccess: invalidate })
}
