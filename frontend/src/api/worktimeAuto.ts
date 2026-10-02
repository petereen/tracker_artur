import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

/** Automatic geofence worktime: employee consent and device, admin sites, settings and event log. */
export type AutoWorktimeMode = 'off' | 'shadow' | 'on'

export interface AutoWorktimeSettings {
  auto_geofence_mode: AutoWorktimeMode
  exit_grace_minutes: number
  min_accuracy_meters: number
  geo_retention_days: number
  employer_disclaimer_ack: { account_id: number; email: string; acknowledged_at: string; policy_version: string } | null
  policy_version: string
}

export interface WorktimeSite {
  id: string
  name: string
  latitude: number
  longitude: number
  radius_meters: number
  is_active: boolean
  schedule_start: string | null
  schedule_end: string | null
}
export type WorktimeSiteInput = Omit<WorktimeSite, 'id'>

export interface GeoDevice {
  id: string
  platform: 'ios' | 'android'
  label: string | null
  geofence_enabled: boolean
  location_permission: 'always' | 'when_in_use' | 'denied' | null
  location_accuracy: 'precise' | 'approximate' | null
  battery_unrestricted: boolean | null
  app_version: string | null
  native_version: number | null
  last_event_at: string | null
  last_state_at: string | null
  revoked_at: string | null
  created_at: string
  email?: string
  employee_name?: string | null
}

export interface GeoEvent {
  id: number
  kind: 'enter' | 'exit' | 'state_inside' | 'state_outside' | 'sweep'
  occurred_at: string
  received_at: string
  accuracy_meters: number | null
  is_mock: boolean
  result: string
  needs_review: boolean
  time_entry_id: number | null
  site_name: string | null
  employee_id: number | null
  employee_name: string | null
}

export interface AutoWorktimeStatus {
  mode: AutoWorktimeMode
  available: boolean
  employee_linked: boolean
  policy_version: string
  consent: { id: number; policy_version: string; accepted_at: string; locale: string } | null
  device: GeoDevice | null
  site_count: number
  geo_retention_days: number
  recent_events: GeoEvent[]
}

export interface ConsentText { policy_version: string; locale: string; text: string; text_sha256: string }
export interface DeviceEnrollment { device: GeoDevice; credential: string; sites: WorktimeSite[]; config: { mode: AutoWorktimeMode; min_accuracy_meters: number } }
export type DeviceStateInput = Partial<Pick<GeoDevice, 'location_permission' | 'location_accuracy' | 'battery_unrestricted' | 'app_version' | 'native_version'>>

const keys = {
  status: ['v1', 'worktime-auto', 'status'] as const,
  settings: ['v1', 'settings', 'worktime-auto'] as const,
  sites: ['v1', 'worktime-auto', 'sites'] as const,
  devices: ['v1', 'worktime-auto', 'devices'] as const,
  events: (needsReview: boolean) => ['v1', 'worktime-auto', 'events', needsReview] as const,
}

export function autoWorktimeErrorCode(error: unknown): string | undefined {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return detail && typeof detail === 'object' ? (detail as { code?: string }).code : undefined
}

// ── Employee ────────────────────────────────────────────────────────────────
export function useAutoWorktimeStatus(enabled = true) {
  return useQuery<AutoWorktimeStatus>({ queryKey: keys.status, queryFn: () => api.get('/v1/worktime/auto/status').then((response) => response.data), enabled, staleTime: 30_000 })
}

export const fetchAutoWorktimeStatus = () => api.get('/v1/worktime/auto/status').then((response) => response.data as AutoWorktimeStatus)

export function useConsentText(locale: string, enabled: boolean) {
  return useQuery<ConsentText>({
    queryKey: ['v1', 'worktime-auto', 'consent-text', locale],
    queryFn: () => api.get('/v1/worktime/auto/consent-text', { params: { locale } }).then((response) => response.data),
    enabled,
    staleTime: Infinity,
  })
}

export function useAcceptConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { text: ConsentText; app_platform: 'ios' | 'android' | 'web' }) => api.post('/v1/worktime/auto/consent', {
      policy_version: input.text.policy_version, text_sha256: input.text.text_sha256, locale: input.text.locale, app_platform: input.app_platform,
    }).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.status }),
  })
}

export function useRevokeConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete('/v1/worktime/auto/consent').then((response) => response.data as { revoked: number; devices_revoked: number }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.status }),
  })
}

export function useEnrollDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { platform: 'ios' | 'android' } & DeviceStateInput) => api.post('/v1/mobile/devices', input).then((response) => response.data as DeviceEnrollment),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.status }),
  })
}

export const updateDeviceState = (deviceId: string, state: DeviceStateInput) => api.put(`/v1/mobile/devices/${deviceId}/state`, state).then((response) => response.data as GeoDevice)
export const revokeOwnDevice = (deviceId: string) => api.delete(`/v1/mobile/devices/${deviceId}`).then((response) => response.data as GeoDevice)

// ── Administration ─────────────────────────────────────────────────────────
export function useAutoWorktimeSettings(enabled = true) {
  return useQuery<AutoWorktimeSettings>({ queryKey: keys.settings, queryFn: () => api.get('/v1/settings/worktime-auto').then((response) => response.data), enabled })
}

export function useUpdateAutoWorktimeSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<Pick<AutoWorktimeSettings, 'auto_geofence_mode' | 'exit_grace_minutes' | 'min_accuracy_meters' | 'geo_retention_days'>> & { acknowledge_employer_disclaimer?: boolean }) =>
      api.put('/v1/settings/worktime-auto', input).then((response) => response.data as AutoWorktimeSettings),
    onSuccess: (data) => queryClient.setQueryData(keys.settings, data),
  })
}

export function useWorktimeSites(enabled = true) {
  return useQuery<WorktimeSite[]>({ queryKey: keys.sites, queryFn: () => api.get('/v1/worktime/sites').then((response) => response.data), enabled })
}

export function useSaveWorktimeSite() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: WorktimeSiteInput & { id?: string }) => (id ? api.put(`/v1/worktime/sites/${id}`, input) : api.post('/v1/worktime/sites', input)).then((response) => response.data as WorktimeSite),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.sites }),
      // The first site is also the office used for the manual location start.
      queryClient.invalidateQueries({ queryKey: ['v1', 'settings', 'worktime-geofence'] }),
    ]),
  })
}

export function useDeleteWorktimeSite() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/v1/worktime/sites/${id}`),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.sites }),
      queryClient.invalidateQueries({ queryKey: ['v1', 'settings', 'worktime-geofence'] }),
    ]),
  })
}

export function useGeoDevices(enabled = true) {
  return useQuery<GeoDevice[]>({ queryKey: keys.devices, queryFn: () => api.get('/v1/worktime/auto/devices').then((response) => response.data), enabled })
}

export function useRevokeGeoDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/v1/worktime/auto/devices/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

export function useGeoEvents(needsReview: boolean, enabled = true) {
  return useInfiniteQuery({
    queryKey: keys.events(needsReview),
    queryFn: ({ pageParam }) => api.get('/v1/worktime/auto/events', { params: { limit: 50, cursor: pageParam ?? undefined, needs_review: needsReview ? true : undefined } })
      .then((response) => response.data as { items: GeoEvent[]; next_cursor: number | null }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  })
}

export function useMarkGeoEventReviewed() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post(`/v1/worktime/auto/events/${id}/reviewed`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'worktime-auto', 'events'] }),
  })
}
