import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { create } from 'zustand'
import { getApiBaseUrl } from '../platform/runtime'
import type { LicenseState, TenantBranding, TenantFeatureCode } from '../api/tenancy'

/**
 * Operator (superadmin) console client. Operator sessions are separate from
 * tenant sessions: their own token (never the workspace token), kept in
 * sessionStorage so they end with the browser tab, and no refresh flow.
 */
export interface Operator {
  id: number
  email: string
  display_name: string | null
  role: 'superadmin' | 'support'
  status: 'active' | 'disabled'
  last_login_at: string | null
  created_at?: string
}

interface ConsoleSessionState {
  token: string | null
  operator: Operator | null
  expiresAt: number | null
  setSession: (token: string, operator: Operator, expiresIn: number) => void
  logout: () => void
}

const STORAGE_KEY = 'oyuns.console.session'

function loadSession(): Pick<ConsoleSessionState, 'token' | 'operator' | 'expiresAt'> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed.expiresAt && parsed.expiresAt > Date.now()) return parsed
    }
  } catch { /* storage unavailable: start signed out */ }
  return { token: null, operator: null, expiresAt: null }
}

function saveSession(value: Pick<ConsoleSessionState, 'token' | 'operator' | 'expiresAt'> | null) {
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch { /* storage unavailable */ }
}

export const useConsoleSession = create<ConsoleSessionState>((set) => ({
  ...loadSession(),
  setSession: (token, operator, expiresIn) => {
    const value = { token, operator, expiresAt: Date.now() + expiresIn * 1000 }
    saveSession(value)
    set(value)
  },
  logout: () => {
    saveSession(null)
    set({ token: null, operator: null, expiresAt: null })
  },
}))

export const consoleApi = axios.create({ baseURL: getApiBaseUrl(), timeout: 20_000 })

consoleApi.interceptors.request.use((config) => {
  const token = useConsoleSession.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

consoleApi.interceptors.response.use((response) => response, (error) => {
  if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) useConsoleSession.getState().logout()
  return Promise.reject(error)
})

export function consoleError(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => (item as { msg?: string }).msg).filter(Boolean).join('; ') || fallback
  if (detail && typeof detail === 'object') return (detail as { message?: string; code?: string }).message || (detail as { code?: string }).code || fallback
  return fallback
}

// ── types ────────────────────────────────────────────────────────────────
export type TenantStatus = 'pending_activation' | 'active' | 'suspended' | 'terminated'
export type BillingCycle = 'monthly' | 'quarterly' | 'yearly' | 'custom'

export interface ConsoleTenant {
  id: number
  public_id: string
  slug: string
  name: string
  status: TenantStatus
  status_reason: string | null
  is_primary: boolean
  plan_code: string | null
  billing_cycle: BillingCycle
  seat_limit: number | null
  seats_used: number
  features: TenantFeatureCode[]
  license: { required: boolean; state: LicenseState; expires_at: string | null; grace_ends_at: string | null; days_left: number | null }
  license_required: boolean
  contact_email: string | null
  branding: TenantBranding
  hosts: string[]
  created_at: string
  suspended_at: string | null
  terminated_at: string | null
}

export interface ConsoleLicense {
  id: string
  db_id: number
  organization_id: number
  status: 'issued' | 'active' | 'superseded' | 'revoked'
  plan_code: string | null
  seat_limit: number
  features: TenantFeatureCode[]
  billing_cycle: BillingCycle
  valid_from: string
  expires_at: string
  issued_at: string
  activated_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
  supersedes_id: number | null
  key_id: string
  notes: string | null
  token?: string
}

export interface ConsoleAuditEvent {
  id: number
  action: string
  operator_id: number | null
  account_id: number | null
  organization_id: number | null
  target_type: string | null
  target_id: string | null
  details: Record<string, unknown>
  ip_address: string | null
  created_at: string
}

export interface ConsoleTenantDetail {
  tenant: ConsoleTenant
  seats: { used: number; limit: number | null; available: number | null; unlimited: boolean }
  licenses: ConsoleLicense[]
  domains: ConsoleDomain[]
  admins: Array<{ id: number; email: string; status: string; last_login_at: string | null }>
  audit: ConsoleAuditEvent[]
}

export interface ConsolePlan {
  id: number
  code: string
  name: string
  description: string | null
  seat_limit: number | null
  features: TenantFeatureCode[]
  billing_cycle: BillingCycle
  price_amount: number | null
  currency: string
  is_active: boolean
  sort_order: number
}

export interface LicenseIssueInput {
  plan_code?: string | null
  seat_limit?: number | null
  features?: TenantFeatureCode[] | null
  billing_cycle?: BillingCycle | null
  expires_at?: string | null
  duration_months?: number | null
  notes?: string | null
  activate?: boolean
}

export interface TenantCreateInput {
  name: string
  slug: string
  plan_code: string | null
  seat_limit: number | null
  features: TenantFeatureCode[]
  billing_cycle: BillingCycle
  contact_email: string | null
  admin: { email: string; password: string }
  license: LicenseIssueInput | null
}

export interface ConsoleDomain {
  id: number
  hostname: string
  verified_at: string | null
  verification_token: string
  provider: 'cloudflare' | 'manual'
  status: 'pending' | 'active' | 'error'
  ssl_status: string | null
  dns_records: Array<{ type: string; name: string; value: string; purpose: string }>
  last_error: string | null
}

export interface ConsoleSystem {
  rls: { available: boolean; db_role?: string; superuser?: boolean; bypass_rls?: boolean; protected_tables?: number; tenant_tables?: number; strict?: boolean; effective?: boolean }
  license_signing: { available: boolean; key_id: string; public_key_pem: string | null; grace_days: number }
  tenants: Record<string, number>
  routing: {
    root_hosts: string[]; tenant_base_domain: string | null; unknown_host_policy: string; console_hosts: string[]
    custom_domains?: { provider: 'cloudflare' | null; cname_target: string | null; ssl_method: string; limit_per_tenant: number }
  }
}

// ── hooks ────────────────────────────────────────────────────────────────
const get = <T,>(url: string, params?: Record<string, unknown>) => consoleApi.get<T>(url, { params }).then((response) => response.data)

export function useOperatorLogin() {
  const setSession = useConsoleSession((state) => state.setSession)
  return useMutation({
    mutationFn: (input: { email: string; password: string }) => consoleApi.post('/v1/platform/auth/login', input).then((response) => response.data as { access_token: string; expires_in: number; operator: Operator }),
    onSuccess: (data) => setSession(data.access_token, data.operator, data.expires_in),
  })
}

export const useFeatureCatalog = () => useQuery({ queryKey: ['console', 'features'], queryFn: () => get<Array<{ code: TenantFeatureCode; label: string }>>('/v1/platform/features'), staleTime: Infinity })
export const useConsoleTenants = (filters: { status?: string; q?: string }) => useQuery({ queryKey: ['console', 'tenants', filters], queryFn: () => get<ConsoleTenant[]>('/v1/platform/tenants', { status: filters.status || undefined, q: filters.q || undefined }) })
export const useConsoleTenant = (id: number) => useQuery({ queryKey: ['console', 'tenant', id], queryFn: () => get<ConsoleTenantDetail>(`/v1/platform/tenants/${id}`), enabled: Number.isFinite(id) })
export const usePlans = () => useQuery({ queryKey: ['console', 'plans'], queryFn: () => get<ConsolePlan[]>('/v1/platform/plans') })
export const useConsoleSystem = () => useQuery({ queryKey: ['console', 'system'], queryFn: () => get<ConsoleSystem>('/v1/platform/system') })
export const useOperators = (enabled: boolean) => useQuery({ queryKey: ['console', 'operators'], queryFn: () => get<Operator[]>('/v1/platform/operators'), enabled })
export const useConsoleAudit = (tenantId?: number) => useQuery({ queryKey: ['console', 'audit', tenantId ?? 'all'], queryFn: () => get<ConsoleAuditEvent[]>('/v1/platform/audit', { tenant_id: tenantId, limit: 200 }) })

/** Every console mutation refreshes the console's cached lists. */
function useConsoleMutation<TInput, TResult = unknown>(fn: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['console'] }) })
}

const send = <T,>(method: 'post' | 'patch' | 'delete', url: string, body?: unknown, params?: Record<string, unknown>) =>
  consoleApi.request<T>({ method, url, data: body, params }).then((response) => response.data)

export const useCreateTenant = () => useConsoleMutation((input: TenantCreateInput) => send<{ tenant: ConsoleTenant; admin: { id: number; email: string }; license: ConsoleLicense | null }>('post', '/v1/platform/tenants', input))
export const useUpdateTenant = () => useConsoleMutation(({ id, ...input }: { id: number } & Record<string, unknown>) => send<ConsoleTenant>('patch', `/v1/platform/tenants/${id}`, input))
export const useTenantLifecycle = () => useConsoleMutation(({ id, action, reason, confirm_slug }: { id: number; action: 'suspend' | 'reactivate' | 'terminate'; reason?: string; confirm_slug?: string }) =>
  send<ConsoleTenant>('post', `/v1/platform/tenants/${id}/${action}`, { reason: reason || null, confirm_slug }))
export const usePurgeTenant = () => useConsoleMutation(({ id, confirm_slug }: { id: number; confirm_slug: string }) => send('delete', `/v1/platform/tenants/${id}`, undefined, { confirm_slug }))
export const useIssueLicense = () => useConsoleMutation(({ tenantId, ...input }: { tenantId: number } & LicenseIssueInput) => send<ConsoleLicense>('post', `/v1/platform/tenants/${tenantId}/licenses`, input))
export const useRenewLicense = () => useConsoleMutation(({ id, ...input }: { id: string } & LicenseIssueInput) => send<ConsoleLicense>('post', `/v1/platform/licenses/${id}/renew`, input))
export const useRevokeLicense = () => useConsoleMutation(({ id, reason }: { id: string; reason: string }) => send<ConsoleLicense>('post', `/v1/platform/licenses/${id}/revoke`, { reason }))
export const useOperatorActivateLicense = () => useConsoleMutation((id: string) => send<ConsoleLicense>('post', `/v1/platform/licenses/${id}/activate`))
export const fetchLicenseToken = (id: string) => get<ConsoleLicense>(`/v1/platform/licenses/${id}`)
export const useAddDomain = () => useConsoleMutation(({ tenantId, hostname }: { tenantId: number; hostname: string }) => send<{ hostname: string; instructions: string }>('post', `/v1/platform/tenants/${tenantId}/domains`, { hostname }))
export const useVerifyDomain = () => useConsoleMutation(({ tenantId, domainId }: { tenantId: number; domainId: number }) => send('post', `/v1/platform/tenants/${tenantId}/domains/${domainId}/verify`))
export const useRemoveDomain = () => useConsoleMutation(({ tenantId, domainId }: { tenantId: number; domainId: number }) => send('delete', `/v1/platform/tenants/${tenantId}/domains/${domainId}`))
export const useSavePlan = () => useConsoleMutation(({ isNew, ...input }: Partial<ConsolePlan> & { code: string; isNew: boolean }) =>
  (isNew ? send<ConsolePlan>('post', '/v1/platform/plans', input) : send<ConsolePlan>('patch', `/v1/platform/plans/${input.code}`, { ...input, code: undefined })))
export const useCreateOperator = () => useConsoleMutation((input: { email: string; password: string; display_name?: string; role: Operator['role'] }) => send<Operator>('post', '/v1/platform/operators', input))
export const useUpdateOperator = () => useConsoleMutation(({ id, ...input }: { id: number; role?: Operator['role']; status?: Operator['status']; password?: string }) => send<Operator>('patch', `/v1/platform/operators/${id}`, input))
