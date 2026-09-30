import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, publicApi } from './client'
import { useAuthStore } from '../store/auth'

/** Licensed feature modules (backend `TENANT_FEATURES`). */
export type TenantFeatureCode = 'crm' | 'budget' | 'payroll' | 'contracts' | 'ai_assistant' | 'legacy_workspace'
export type LicenseState = 'not_required' | 'valid' | 'grace' | 'expired' | 'missing'

export interface TenantBranding {
  slug: string | null
  name: string
  logo_url: string
  dark_logo_url: string
  favicon_url: string
  primary_color: string | null
  secondary_color: string | null
}

export interface SeatUsage { used: number; limit: number | null; available: number | null; unlimited: boolean }
export interface TenantFeature { code: TenantFeatureCode; label: string; enabled: boolean; primary_only: boolean }
export interface TenantLicenseStatus { required: boolean; state: LicenseState; expires_at: string | null; grace_ends_at: string | null; days_left: number | null }

export interface TenantContext {
  slug: string
  name: string
  status: 'pending_activation' | 'active' | 'suspended' | 'terminated'
  is_primary: boolean
  plan_code: string | null
  billing_cycle: string
  features: TenantFeature[]
  license: TenantLicenseStatus
  branding: TenantBranding
  seats?: SeatUsage
}

export interface LicenseRecord {
  id: string
  status: 'issued' | 'active' | 'superseded' | 'revoked'
  plan_code: string | null
  seat_limit: number
  features: TenantFeatureCode[]
  billing_cycle: string
  valid_from: string
  expires_at: string
  issued_at: string
  activated_at: string | null
  revoked_at: string | null
  key_id: string
}

export interface TenantLicenseOverview {
  tenant: { slug: string; name: string; status: string; public_id: string }
  license: TenantLicenseStatus
  active: LicenseRecord | null
  history: LicenseRecord[]
  seats: SeatUsage
  features: TenantFeature[]
  plan_code: string | null
  billing_cycle: string
}

export interface LicenseClaims {
  license_id: string
  tenant_public_id: string
  tenant_slug: string | null
  seats: number
  features: TenantFeatureCode[]
  plan: string | null
  billing_cycle: string
  issued_at: string
  valid_from: string
  expires_at: string
  key_id: string
}

export interface LicenseVerification { valid: boolean; claims: LicenseClaims; seats: SeatUsage; fits_current_usage: boolean; feature_labels: Record<string, string> }

export interface EditableBranding { display_name: string | null; logo_url: string | null; favicon_url: string | null; primary_color: string | null; secondary_color: string | null }

export const DEFAULT_BRANDING: TenantBranding = {
  slug: null, name: 'OYUNS ERP', logo_url: '/favicon.png', dark_logo_url: '/oyuns-aio-logo.png', favicon_url: '/favicon.png', primary_color: null, secondary_color: null,
}

/** `{detail: {code, message}}` from the tenancy layer, or null. */
export function tenancyError(error: unknown): { status?: number; code?: string; message?: string; used?: number; limit?: number } | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (!response) return null
  if (detail && typeof detail === 'object') return { status: response.status, ...(detail as Record<string, unknown>) } as ReturnType<typeof tenancyError>
  return { status: response.status, message: typeof detail === 'string' ? detail : undefined }
}

export function tenancyErrorMessage(error: unknown, fallback: string) {
  const parsed = tenancyError(error)
  return parsed?.message || parsed?.code || fallback
}

/** Public branding of the tenant this host (or session) resolves to. */
export function useTenantBranding() {
  const token = useAuthStore((state) => state.token)
  return useQuery<TenantBranding>({
    queryKey: ['tenant', 'branding', Boolean(token)],
    queryFn: () => (token ? api : publicApi).get('/v1/tenant/branding').then((response) => response.data),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useTenantContext(enabled = true) {
  return useQuery<TenantContext>({
    queryKey: ['tenant', 'context'],
    queryFn: () => api.get('/v1/tenant/context').then((response) => response.data),
    enabled,
    staleTime: 60_000,
    retry: false,
  })
}

export function useTenantLicense(enabled = true) {
  return useQuery<TenantLicenseOverview>({
    queryKey: ['tenant', 'license'],
    queryFn: () => api.get('/v1/tenant/license').then((response) => response.data),
    enabled,
  })
}

export function useTenantSeats(enabled = true) {
  return useQuery<SeatUsage>({
    queryKey: ['tenant', 'seats'],
    queryFn: () => api.get('/v1/tenant/seats').then((response) => response.data),
    enabled,
  })
}

export function useVerifyLicense() {
  return useMutation({ mutationFn: (token: string) => api.post('/v1/tenant/license/verify', { token }).then((response) => response.data as LicenseVerification) })
}

export function useActivateLicense() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => api.post('/v1/tenant/license/activate', { token }).then((response) => response.data),
    // New modules, seats and gates change what every screen may load.
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useTenantBrandingSettings(enabled = true) {
  return useQuery<{ branding: EditableBranding; preview: TenantBranding }>({
    queryKey: ['tenant', 'branding-settings'],
    queryFn: () => api.get('/v1/tenant/branding/settings').then((response) => response.data),
    enabled,
  })
}

export function useUpdateTenantBranding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<EditableBranding>) => api.put('/v1/tenant/branding/settings', input).then((response) => response.data as { branding: EditableBranding; preview: TenantBranding }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tenant'] }),
  })
}

export function isFeatureEnabled(context: TenantContext | undefined, feature: TenantFeatureCode): boolean {
  // Before the context loads (or on older servers) keep the UI permissive:
  // the API is the authority and answers 403 for unlicensed modules.
  if (!context) return true
  return context.features.some((item) => item.code === feature && item.enabled)
}
