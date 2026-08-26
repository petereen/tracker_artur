import { InfiniteData, useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import toast from 'react-hot-toast'
import { acceptSession, api, clearSessionCredentials, publicApi, refreshAccessToken } from './client'
import { notificationService } from '../platform/notifications'
import { getNativeRefreshToken } from '../platform/secure-session'
import { isNativePlatform, requireWebCapability } from '../platform/runtime'
import { useAuthStore, Actor } from '../store/auth'

export type WorkflowStatus = 'backlog' | 'to_do' | 'in_progress' | 'review' | 'done' | 'cancelled'
export type SearchEntityType = 'task' | 'worker' | 'file'
export interface GlobalSearchResult {
  id: number
  type: SearchEntityType
  title: string
  subtitle: string | null
  score: number
  metadata: { status?: WorkflowStatus; assignee?: string | null; project?: string | null; avatar_url?: string | null; role?: string | null; presence?: string; kind?: 'file' | 'folder'; size?: number | null; parent_id?: number | null; content_state?: string }
}
export interface GlobalSearchResponse { query: string; groups: { tasks: GlobalSearchResult[]; workers: GlobalSearchResult[]; files: GlobalSearchResult[] } }

export interface EnterpriseTask {
  id: number
  public_id: string
  project_id: number | null
  parent_task_id: number | null
  title: string
  description: string | null
  workflow_status: WorkflowStatus
  priority: number
  primary_owner_id: number | null
  primary_owner_name: string | null
  reviewer_id: number | null
  reviewer_name: string | null
  reviewer_ids: number[]
  reviewer_names: string[]
  assignee_ids: number[]
  assignee_names: string[]
  project_name: string | null
  start_at: string | null
  deadline_at: string | null
  is_all_day: boolean
  estimate_minutes: number | null
  work_location_type: 'office' | 'remote' | 'custom' | null
  work_location: string | null
  sort_position: number
  version: number
  is_archived: boolean
  is_overdue: boolean
  created_at: string
  created_by_id: number | null
  creator_name?: string | null
  creator_avatar_url?: string | null
  can_manage_collaboration?: boolean
}

export interface DeadlineItem {
  id: string
  entity_id: number
  type: 'project' | 'plan' | 'task' | 'subtask'
  title: string
  due_date: string | null
  status: string
  owner: string | null
  project_id: number | null
  project_name: string | null
  bucket: 'overdue' | 'soon' | 'later' | 'none'
  version?: number
}

export interface Project {
  id: number
  public_id: string
  client_id: number | null
  manager_id: number | null
  manager_name: string | null
  member_ids: number[]
  code: string
  name: string
  description: string | null
  status: string
  starts_on: string | null
  ends_on: string | null
  budget_minutes: number | null
  budget_amount: number | null
  currency: string
  default_billable: boolean
  version: number
  archived_at?: string | null
  can_archive?: boolean
}

export interface ClockEntry {
  id: number
  employee_id: number
  local_work_date: string
  project_id: number | null
  task_id: number | null
  entry_type: 'work' | 'break'
  mode: 'in_person' | 'remote' | null
  started_at: string
  ended_at: string | null
  source_channel?: string
  source_kiosk_id?: number | null
  work_location_id?: string | null
}

export interface WorktimeReportOptions {
  departments: Array<{ value: string; label: string }>
  workers: Array<{ id: number; name: string; department: string }>
}

export interface WorktimeReportSummary {
  total_minutes: number
  average_minutes_per_worker: number
  average_daily_minutes_per_worker: number
  average_weekly_minutes_per_worker: number
  active_worker_count: number
}

export interface WorktimeReportRow {
  worker_id: number
  worker_name: string
  department: string
  date: string
  clock_in: string | null
  clock_out: string | null
  total_minutes: number | null
  status: 'complete' | 'in_progress'
}

export interface WorktimeReportPreview {
  range: { from: string; to: string }
  summary: WorktimeReportSummary
  items: WorktimeReportRow[]
  page: number
  page_size: number
  total: number
}

export interface WorktimeReportQuery {
  from: string
  to: string
  department?: string
  worker_id?: number
  page?: number
  page_size?: number
}

export interface WorktimeQrKiosk {
  id: number
  public_id: string
  label: string
  location_id: string
  display_name: string
  status: 'active' | 'revoked'
  paired_at: string | null
  last_seen_at: string | null
  revoked_at: string | null
  pairing_code?: string
  pairing_expires_at?: string
}

export interface WorktimeQrDisplayToken {
  token: string
  issued_at: string
  expires_at: string
  server_time: string
  location_id: string
  display_name: string
}

export interface WorktimeQrClockResult {
  action: 'clock_in' | 'switched_to_office' | 'clock_out'
  replayed: boolean
  location_id: string
  server_time: string
  timezone: string
  affected_entries: ClockEntry[]
  shift_summary: { active: ClockEntry | null; today_entries: ClockEntry[] }
}

const worktimeQrKeys = ['v1', 'worktime-qr'] as const
const worktimeReportKeys = ['v1', 'worktime-reports'] as const

export function useWorktimeReportOptions(enabled = true) {
  return useQuery<WorktimeReportOptions>({
    queryKey: [...worktimeReportKeys, 'options'],
    queryFn: () => api.get('/v1/worktime-reports/options').then((response) => response.data),
    enabled,
  })
}

export function useWorktimeReportPreview(query: WorktimeReportQuery, enabled = true) {
  return useQuery<WorktimeReportPreview>({
    queryKey: [...worktimeReportKeys, 'preview', query],
    queryFn: () => api.get('/v1/worktime-reports/preview', { params: query }).then((response) => response.data),
    enabled: enabled && Boolean(query.from && query.to),
    placeholderData: (previous) => previous,
  })
}

export async function downloadWorktimeReport(query: WorktimeReportQuery, format: 'csv' | 'xlsx') {
  const response = await api.get('/v1/worktime-reports/export', {
    params: { ...query, format },
    responseType: 'blob',
    timeout: 10 * 60 * 1000,
  })
  const disposition = response.headers['content-disposition'] as string | undefined
  const filename = disposition?.match(/filename="?([^";]+)"?/i)?.[1]
    || `worktime-report_${query.from}_${query.to}.${format}`
  saveCompanyBlob(response.data as Blob, filename)
}

export function useWorktimeQrKiosks(enabled = true) {
  return useQuery<WorktimeQrKiosk[]>({ queryKey: [...worktimeQrKeys, 'kiosks'], queryFn: () => api.get('/v1/worktime-qr/kiosks').then((response) => response.data), enabled })
}

export function useCreateWorktimeQrKiosk() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: { label: string; location_id: string; display_name: string }) => api.post('/v1/worktime-qr/kiosks', input).then((response) => response.data as WorktimeQrKiosk), onSuccess: () => queryClient.invalidateQueries({ queryKey: worktimeQrKeys }) })
}

export function useRenewWorktimeQrPairingCode() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (id: number) => api.post(`/v1/worktime-qr/kiosks/${id}/pairing-code`).then((response) => response.data as WorktimeQrKiosk), onSuccess: () => queryClient.invalidateQueries({ queryKey: worktimeQrKeys }) })
}

export function useRevokeWorktimeQrKiosk() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (id: number) => api.post(`/v1/worktime-qr/kiosks/${id}/revoke`).then((response) => response.data as WorktimeQrKiosk), onSuccess: () => queryClient.invalidateQueries({ queryKey: worktimeQrKeys }) })
}

export function usePairWorktimeQrKiosk() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (code: string) => publicApi.post('/v1/worktime-qr/pair', { code }).then((response) => response.data), onSuccess: () => queryClient.invalidateQueries({ queryKey: [...worktimeQrKeys, 'display-token'] }) })
}

export function useWorktimeQrDisplayToken(enabled = true) {
  return useQuery<WorktimeQrDisplayToken>({ queryKey: [...worktimeQrKeys, 'display-token'], queryFn: () => publicApi.get('/v1/worktime-qr/display-token', { headers: { 'Cache-Control': 'no-cache' } }).then((response) => response.data), enabled, refetchInterval: (query) => {
    const expiresAt = query.state.data?.expires_at
    if (query.state.error) return expiresAt ? 5_000 : false
    if (expiresAt) return Math.max(1_000, new Date(expiresAt).getTime() - Date.now() - 4_000)
    return 30_000
  }, refetchOnWindowFocus: false, refetchOnReconnect: false, refetchIntervalInBackground: true, retry: false })
}

export function useWorktimeQrClock() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: { token: string; client_timestamp: string }) => api.post('/v1/worktime-qr/clock', input).then((response) => response.data as WorktimeQrClockResult), onSuccess: (result) => { queryClient.setQueryData(clockQueryKey, { active: result.shift_summary.active, today_entries: result.shift_summary.today_entries, timezone: result.timezone, server_time: result.server_time }); queryClient.invalidateQueries({ queryKey: clockQueryKey }) } })
}

export interface TaskDependency { id: number; predecessor_task_id: number; predecessor_title: string | null; successor_task_id: number; dependency_type: 'blocks' | 'related'; relation_type: 'blocks' | 'related'; direction: 'blocked_by' | 'related'; related_task_id: number; related_task_title: string | null }
export interface TaskCheckItem { id: number; task_id: number; text: string; is_completed: boolean; assignee_id: number | null; position: number; completed_at: string | null }
export interface TaskComment { id: number; task_id: number; author_account_id?: number; author_employee_id?: number; author_name?: string | null; author_avatar_url?: string | null; text: string; mentions: number[]; is_resolved: boolean; edited_at?: string | null; created_at: string }
export interface EnterpriseAttachment { id: number; filename: string; content_type: string; size: number; checksum: string; scan_status: string; created_at: string }
export interface TaskActivity { id: number; action: string; entity_type: string; actor_account_id: number | null; actor_employee_id: number | null; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string }
export interface SavedView { id: number; module: string; name: string; view_type: string; filters: Record<string, unknown>; grouping: Record<string, unknown>; visible_columns: string[]; sort: Record<string, unknown>[]; is_shared: boolean }

export type ContractStatus = 'DRAFT' | 'PENDING_REVIEW' | 'CHANGES_REQUESTED' | 'APPROVED' | 'REJECTED' | 'SIGNED_AND_STAMPED'
export type ContractDocumentType = 'contract' | 'agreement' | 'official_letter' | 'other'
export interface ContractSummary {
  id: number; public_id: string; title: string; document_type: ContractDocumentType; status: ContractStatus
  author_account_id: number; author_name?: string | null; project_id: number | null; task_id: number | null
  effective_start_on?: string | null; effective_end_on?: string | null; submission_round: number; version: number
  current_revision_id: number | null; approved_revision_id: number | null; approved_at?: string | null; signed_at?: string | null
  excerpt?: string; created_at: string; updated_at: string
}
export interface ContractReview { id: number; round_number: number; reviewer_account_id: number; reviewer_employee_id: number | null; reviewer_name: string; decision: 'pending' | 'approved' | 'changes_requested' | 'rejected'; remark: string | null; acted_at: string | null }
export interface ContractRevision { id: number; revision_number: number; title: string; body_json: Record<string, unknown>; plain_text: string; checksum: string; created_at: string; author_account_id: number | null }
export interface ContractComment { id: number; revision_id: number; parent_id: number | null; author_account_id: number | null; body: string; anchor: { from?: number; to?: number; quote?: string } | null; is_resolved: boolean; created_at: string }
export interface ContractFile { id: number; purpose: 'supporting' | 'signed_final'; filename: string; content_type: string; size: number; checksum: string; scan_status: string; confirmed_at: string | null; created_at: string }
export interface ContractDetail extends ContractSummary { body_json: Record<string, unknown> | null; approved_body_json: Record<string, unknown> | null; reviewer_account_ids: number[]; revisions: ContractRevision[]; reviews: ContractReview[]; comments: ContractComment[]; files: ContractFile[]; timeline: Array<{ id: number; operation: string; actor_account_id: number | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; created_at: string }> }
export interface ContractListResponse { items: ContractSummary[]; counts: Record<'all' | 'drafts' | 'pending_my_approval' | 'submitted_by_me' | 'approved' | 'signed' | 'returned', number> }
export interface ContractReviewerCandidate { account_id: number; employee_id: number; name: string; job_title: string | null }

const contractKeys = ['v1', 'contracts'] as const
export function useContractList(view: string) { return useQuery<ContractListResponse>({ queryKey: [...contractKeys, view], queryFn: () => api.get('/v1/contracts', { params: { view } }).then((r) => r.data) }) }
export function useContractDetail(publicId?: string) { return useQuery<ContractDetail>({ queryKey: [...contractKeys, 'detail', publicId], queryFn: () => api.get(`/v1/contracts/${publicId}`).then((r) => r.data), enabled: Boolean(publicId) }) }
export function useContractReviewerCandidates() { return useQuery<ContractReviewerCandidate[]>({ queryKey: [...contractKeys, 'reviewer-candidates'], queryFn: () => api.get('/v1/contracts/reviewer-candidates').then((r) => r.data) }) }
export function useCreateContract() { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { title: string; document_type: ContractDocumentType; body_json: Record<string, unknown>; reviewer_account_ids: number[]; project_id?: number | null; task_id?: number | null; effective_start_on?: string | null; effective_end_on?: string | null }) => api.post('/v1/contracts', input).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: contractKeys }) }) }
export function useUpdateContract() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ publicId, version, ...input }: { publicId: string; version: number; title?: string; document_type?: ContractDocumentType; body_json?: Record<string, unknown>; reviewer_account_ids?: number[]; project_id?: number | null; task_id?: number | null; effective_start_on?: string | null; effective_end_on?: string | null }) => api.patch(`/v1/contracts/${publicId}`, input, { headers: { 'If-Match': String(version) } }).then((r) => r.data), onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', v.publicId] }) }) }
function contractAction(path: string) { const qc = useQueryClient(); return useMutation({ mutationFn: ({ publicId, remark }: { publicId: string; remark?: string }) => api.post(`/v1/contracts/${publicId}/${path}`, remark === undefined ? {} : { remark }).then((r) => r.data), onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: contractKeys }); qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', v.publicId] }) }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Үйлдэл амжилтгүй боллоо') }) }
export function useSubmitContract() { return contractAction('submit') }
export function useResubmitContract() { return contractAction('resubmit') }
export function useRecallContract() { return contractAction('recall') }
export function useApproveContract() { return contractAction('approve') }
export function useRequestContractChanges() { return contractAction('request-changes') }
export function useRejectContract() { return contractAction('reject') }
export function useDuplicateContract() { const qc = useQueryClient(); return useMutation({ mutationFn: (publicId: string) => api.post(`/v1/contracts/${publicId}/duplicate`).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: contractKeys }) }) }
export function useAddContractComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ publicId, ...input }: { publicId: string; revision_id: number; body: string; parent_id?: number | null; anchor?: Record<string, unknown> | null }) => api.post(`/v1/contracts/${publicId}/comments`, input).then((r) => r.data), onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', v.publicId] }) }) }
export function useResolveContractComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ publicId, id, is_resolved }: { publicId: string; id: number; is_resolved: boolean }) => api.patch(`/v1/contracts/${publicId}/comments/${id}`, null, { params: { is_resolved } }).then((r) => r.data), onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', v.publicId] }) }) }
export function useUploadContractFile() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ publicId, purpose, file }: { publicId: string; purpose: 'supporting' | 'signed_final'; file: File }) => { const form = new FormData(); form.append('file', file); return api.post(`/v1/contracts/${publicId}/files`, form, { params: { purpose } }).then((r) => r.data) }, onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', v.publicId] }) }) }
export function useConfirmContractFinal() { const qc = useQueryClient(); return useMutation({ mutationFn: (publicId: string) => api.post(`/v1/contracts/${publicId}/confirm-final`).then((r) => r.data), onSuccess: (_d, publicId) => { qc.invalidateQueries({ queryKey: contractKeys }); qc.invalidateQueries({ queryKey: [...contractKeys, 'detail', publicId] }) } }) }
export function useMarkContractPrinted() { return useMutation({ mutationFn: (publicId: string) => api.post(`/v1/contracts/${publicId}/mark-printed`).then((r) => r.data) }) }
export async function downloadContractFile(publicId: string, id: number, filename: string) { requireWebCapability('File downloads'); const response = await api.get(`/v1/contracts/${publicId}/files/${id}/download`, { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url) }

export function useEnterpriseLogin() {
  return useMutation({
    mutationFn: (input: { email: string; password: string }) => api.post('/v1/auth/login', input).then((response) => response.data),
    onSuccess: acceptSession,
  })
}

export interface AuthCapabilities { telegram_native: boolean }

export function useAuthCapabilities(enabled = true) {
  return useQuery<AuthCapabilities>({
    queryKey: ['v1', 'auth', 'capabilities'],
    queryFn: () => publicApi.get('/v1/auth/capabilities').then((response) => response.data),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function usePasswordResetRequest() {
  return useMutation({
    mutationFn: (email: string) => api.post('/v1/auth/password-reset/request', { email }).then((response) => response.data),
  })
}

export function usePasswordResetConfirm() {
  return useMutation({
    mutationFn: (input: { token: string; new_password: string }) => api.post('/v1/auth/password-reset/confirm', input),
  })
}

export function useGoogleCalendarConnect() {
  return useMutation({
    mutationFn: () => api.get('/v1/integrations/google-calendar/auth-url').then((response) => response.data),
  })
}
export interface CalendarConnectionStatus { provider: 'google'; status: string; sync_mode: 'outbound' | 'bidirectional'; configured: boolean; calendar_id?: string; calendar_name?: string | null; calendar_timezone?: string | null; account_email?: string | null; watch_active?: boolean; watch_expires_at?: string | null; last_synced_at?: string | null; last_error?: string | null; sync_failure_count?: number }
export function useGoogleCalendarStatus() { return useQuery<CalendarConnectionStatus>({ queryKey: ['v1', 'integrations', 'google-calendar'], queryFn: () => api.get('/v1/integrations/google-calendar/status').then((r) => r.data) }) }
export function useGoogleCalendarSyncMode() { const qc = useQueryClient(); return useMutation({ mutationFn: (sync_mode: 'outbound' | 'bidirectional') => api.put('/v1/integrations/google-calendar/sync-mode', { sync_mode }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }) }) }
export interface GoogleCalendarOption { id: string; name: string; time_zone?: string | null; primary?: boolean }
export function useGoogleCalendarList(enabled = true) { return useQuery<{ items: GoogleCalendarOption[]; selected_id?: string }>({ queryKey: ['v1', 'integrations', 'google-calendar', 'calendars'], queryFn: () => api.get('/v1/integrations/google-calendar/calendars').then((r) => r.data), enabled }) }
export function useGoogleCalendarSelect() { const qc = useQueryClient(); return useMutation({ mutationFn: (calendar_id: string) => api.put('/v1/integrations/google-calendar/calendar', { calendar_id }).then((r) => r.data), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }); qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar', 'calendars'] }) } }) }
export function useGoogleCalendarSync() { const qc = useQueryClient(); return useMutation({ mutationFn: () => api.post('/v1/integrations/google-calendar/sync').then((r) => r.data), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }); qc.invalidateQueries({ queryKey: ['v1', 'calendar'] }) } }) }
export function useGoogleCalendarDisconnect() { const qc = useQueryClient(); return useMutation({ mutationFn: () => api.delete('/v1/integrations/google-calendar/disconnect'), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }) }) }

export interface ManagedAccount {
  id: number
  email: string
  employee_id: number | null
  telegram_id: string | null
  locale: string
  roles: string[]
  status: 'active' | 'invited' | 'locked' | 'disabled'
}

export function useManagedAccounts() {
  return useQuery<ManagedAccount[]>({ queryKey: ['v1', 'accounts'], queryFn: () => api.get('/v1/auth/accounts').then((response) => response.data) })
}

export function useCreateManagedAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { email: string; password: string; roles: string[]; locale: string; employee_id?: number }) => api.post('/v1/auth/accounts', input).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'accounts'] }),
  })
}

export function useUpdateManagedAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: { id: number; username?: string; password?: string; roles?: string[]; status?: 'active' | 'disabled' }) => api.patch(`/v1/auth/accounts/${id}`, input).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'accounts'] }),
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Хэрэглэгчийн эрх шинэчлэгдсэнгүй'),
  })
}

export function useInviteAccount() {
  return useMutation({
    mutationFn: (input: { email: string; employee_id?: number; locale: string; roles: string[] }) => api.post('/v1/auth/accounts/invite', input).then((response) => response.data),
  })
}

export async function bootstrapSession() {
  const store = useAuthStore.getState()
  try {
    await refreshAccessToken()
  } catch {
    store.setToken(null)
  } finally {
    store.setInitialized(true)
  }
}

export function useActor(enabled = true) {
  return useQuery<Actor>({
    queryKey: ['v1', 'actor'],
    queryFn: () => api.get('/v1/auth/me').then((response) => response.data),
    enabled,
  })
}

export function useEnterpriseLogout() {
  const logout = useAuthStore((state) => state.logout)
  return useMutation({
    mutationFn: async () => {
      if (isNativePlatform()) await notificationService.unregister()
      const refreshToken = isNativePlatform() ? await getNativeRefreshToken() : null
      try {
        return await api.post('/v1/auth/logout', refreshToken ? { refresh_token: refreshToken } : undefined)
      } finally {
        await clearSessionCredentials()
      }
    },
    onSettled: () => logout(),
  })
}

export interface DateRange { date_from: string; date_to: string }

function localCalendarDate(year: number, month: number, day: number) {
  return `${year.toString().padStart(4, '0')}-${(month + 1).toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`
}

function calendarMonthPeriod(anchor: Date, offset: number): DateRange {
  const month = new Date(anchor.getFullYear(), anchor.getMonth() + offset, 1)
  const lastDay = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  return {
    date_from: localCalendarDate(month.getFullYear(), month.getMonth(), 1),
    date_to: localCalendarDate(month.getFullYear(), month.getMonth(), lastDay),
  }
}

export function useEnterpriseSummary(period?: DateRange, employeeId?: number) {
  return useQuery({ queryKey: ['v1', 'analytics', period, employeeId], queryFn: () => api.get('/v1/analytics/summary', { params: { ...period, ...(employeeId ? { employee_id: employeeId } : {}) } }).then((response) => response.data) })
}

export interface ClockStatus {
  active: ClockEntry | null
  today_entries: ClockEntry[]
  timezone: string
  server_time: string
}

const clockQueryKey = ['v1', 'clock'] as const

export function useClock(enabled = true) {
  return useQuery<ClockStatus>({
    queryKey: clockQueryKey,
    queryFn: () => api.get('/v1/clock/status').then((response) => response.data),
    enabled,
    refetchInterval: enabled ? 30_000 : false,
    refetchOnWindowFocus: enabled,
  })
}

type ClockAction = 'start' | 'break' | 'resume' | 'stop'
interface ClockActionInput { action: ClockAction; mode?: 'in_person' | 'remote' }

export function useClockAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ action, mode }: ClockActionInput) => api.post(`/v1/clock/${action}`, action === 'start' ? { mode } : {}).then((response) => response.data),
    onMutate: async ({ action, mode }: ClockActionInput) => {
      await queryClient.cancelQueries({ queryKey: clockQueryKey })
      const previous = queryClient.getQueryData<ClockStatus>(clockQueryKey)
      if (!previous) return { previous }

      const now = new Date().toISOString()
      const active = previous.active
      const entries = previous.today_entries.slice()
      const closeActive = (items: ClockEntry[]) => active
        ? items.map((entry) => entry.id === active.id ? { ...entry, ended_at: now } : entry)
        : items
      const employeeId = active?.employee_id ?? entries[entries.length - 1]?.employee_id ?? 0
      const localWorkDate = active?.local_work_date ?? entries[entries.length - 1]?.local_work_date ?? now.slice(0, 10)
      const previousWork = [...entries].reverse().find((entry) => entry.entry_type === 'work')
      const optimisticEntry = (entryType: ClockEntry['entry_type'], entryMode: ClockEntry['mode']): ClockEntry => ({
        id: -Date.now(),
        employee_id: employeeId,
        local_work_date: localWorkDate,
        project_id: previousWork?.project_id ?? null,
        task_id: previousWork?.task_id ?? null,
        entry_type: entryType,
        mode: entryMode,
        started_at: now,
        ended_at: null,
      })

      if (action === 'stop') {
        queryClient.setQueryData<ClockStatus>(clockQueryKey, {
          ...previous,
          active: null,
          today_entries: closeActive(entries),
          server_time: now,
        })
      } else if (action === 'break' && active?.entry_type === 'work') {
        const next = optimisticEntry('break', null)
        queryClient.setQueryData<ClockStatus>(clockQueryKey, {
          ...previous,
          active: next,
          today_entries: [...closeActive(entries), next],
          server_time: now,
        })
      } else if (action === 'resume' && active?.entry_type === 'break') {
        const next = optimisticEntry('work', previousWork?.mode ?? 'in_person')
        queryClient.setQueryData<ClockStatus>(clockQueryKey, {
          ...previous,
          active: next,
          today_entries: [...closeActive(entries), next],
          server_time: now,
        })
      } else if (action === 'start' && !(active?.entry_type === 'work' && active.mode === mode)) {
        const next = optimisticEntry('work', mode ?? 'in_person')
        queryClient.setQueryData<ClockStatus>(clockQueryKey, {
          ...previous,
          active: next,
          today_entries: [...closeActive(entries), next],
          server_time: now,
        })
      }

      return { previous }
    },
    onError: (error: any, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(clockQueryKey, context.previous)
      toast.error(error.response?.data?.detail || 'Цагийн төлөв өөрчлөгдсөнгүй')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: clockQueryKey }),
  })
}

export function useProjects() {
  return useQuery<Project[]>({ queryKey: ['v1', 'projects'], queryFn: () => api.get('/v1/projects').then((response) => response.data) })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Record<string, unknown>) => api.post('/v1/projects', input).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'projects'] }); toast.success('Төсөл үүслээ') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Төсөл үүссэнгүй'),
  })
}

export function useProject(id?: number) {
  return useQuery<Project>({ queryKey: ['v1', 'projects', id], queryFn: () => api.get(`/v1/projects/${id}`).then((response) => response.data), enabled: Boolean(id) })
}

export function useUpdateProject() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: ({ id, ...input }: { id: number } & Record<string, unknown>) => api.patch(`/v1/projects/${id}`, input).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'projects'] }); toast.success('Төсөл хадгалагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Төсөл хадгалагдсангүй') })
}

export function useArchiveProject() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (id: number) => api.delete(`/v1/projects/${id}`), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'projects'] }); toast.success('Төсөл архивлагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Төсөл архивлагдсангүй') })
}

export interface TaskFilters { kind?: 'all' | 'standalone' | 'project' | 'subtask'; workflow_status?: string; priority?: 1 | 2 | 3; overdue?: boolean; scope?: 'mine' | 'organization' | 'project' | 'delegated' }
export function useEnterpriseTasks(projectId?: number, period?: Partial<DateRange>, filters: TaskFilters = {}) {
  return useQuery<EnterpriseTask[]>({ queryKey: ['v1', 'tasks', projectId, period, filters], queryFn: () => api.get('/v1/tasks', { params: { ...(projectId ? { project_id: projectId } : {}), ...period, ...filters } }).then((response) => response.data) })
}
export function useEnterpriseTask(id?: number) {
  return useQuery<EnterpriseTask>({ queryKey: ['v1', 'tasks', id], queryFn: () => api.get(`/v1/tasks/${id}`).then((response) => response.data), enabled: Boolean(id) })
}
export function useGlobalSearch(query: string) {
  return useQuery<GlobalSearchResponse>({ queryKey: ['v1', 'search', query], queryFn: () => api.get('/v1/search', { params: { q: query, limit_per_group: 5 } }).then((response) => response.data), enabled: query.trim().length > 0, staleTime: 30_000 })
}

export function useDeadlines(enabled = true) {
  return useQuery<DeadlineItem[]>({ queryKey: ['v1', 'deadlines'], queryFn: () => api.get('/v1/deadlines').then((response) => response.data), enabled })
}

export function useCreateEnterpriseTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Record<string, unknown>) => api.post('/v1/tasks', input, { headers: { 'Idempotency-Key': crypto.randomUUID() } }).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); toast.success('Даалгавар үүслээ') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Даалгавар үүссэнгүй'),
  })
}

export function useUpdateEnterpriseTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, version, ...input }: Partial<EnterpriseTask> & { id: number; version: number }) => api.patch(`/v1/tasks/${id}`, input, { headers: { 'If-Match': String(version) } }).then((response) => response.data),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey: ['v1', 'tasks'] })
      const snapshots = queryClient.getQueriesData<EnterpriseTask[]>({ queryKey: ['v1', 'tasks'] })
      snapshots.forEach(([key, tasks]) => queryClient.setQueryData(key, tasks?.map((task) => task.id === change.id ? { ...task, ...change } : task)))
      return { snapshots }
    },
    onError: (error: any, _change, context) => {
      context?.snapshots.forEach(([key, tasks]) => queryClient.setQueryData(key, tasks))
      toast.error(error.response?.status === 409 ? 'Даалгаврыг өөр хүн шинэчилсэн. Хамгийн сүүлийн хувилбарыг авлаа.' : 'Шинэчлэлт хадгалагдсангүй')
    },
    onSettled: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'deadlines'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }) },
  })
}

export function useDeleteEnterpriseTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/v1/tasks/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'deadlines'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); toast.success('Даалгавар устгагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Даалгавар устгагдсангүй'),
  })
}

const invalidateTaskDetail = (queryClient: ReturnType<typeof useQueryClient>, id: number) => {
  queryClient.invalidateQueries({ queryKey: ['v1', 'tasks', id] })
  queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] })
}

export function useTaskDependencies(id?: number) { return useQuery<TaskDependency[]>({ queryKey: ['v1', 'tasks', id, 'dependencies'], queryFn: () => api.get(`/v1/tasks/${id}/dependencies`).then((r) => r.data), enabled: Boolean(id) }) }
export function useAddTaskDependency() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, predecessor_task_id, dependency_type }: { taskId: number; predecessor_task_id: number; dependency_type: 'blocks' | 'related' }) => api.post(`/v1/tasks/${taskId}/dependencies`, { predecessor_task_id, dependency_type }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Хамаарал хадгалагдсангүй') }) }
export function useDeleteTaskDependency() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/dependencies/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId) }) }

export function useTaskCheckItems(id?: number) { return useQuery<TaskCheckItem[]>({ queryKey: ['v1', 'tasks', id, 'check-items'], queryFn: () => api.get(`/v1/tasks/${id}/check-items`).then((r) => r.data), enabled: Boolean(id) }) }
export function checklistPosition(now = Date.now()) { return Math.floor(now / 1000) }
export function useAddTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, text }: { taskId: number; text: string }) => api.post(`/v1/tasks/${taskId}/check-items`, { text, position: checklistPosition() }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist хадгалагдсангүй') }) }
export function useUpdateTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id, ...input }: { taskId: number; id: number; text?: string; is_completed?: boolean }) => api.patch(`/v1/tasks/${taskId}/check-items/${id}`, input).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist шинэчлэгдсэнгүй') }) }
export function useDeleteTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/check-items/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist устгагдсангүй') }) }

export function useTaskComments(id?: number) { return useQuery<TaskComment[]>({ queryKey: ['v1', 'tasks', id, 'comments'], queryFn: () => api.get(`/v1/tasks/${id}/comments`).then((r) => r.data), enabled: Boolean(id) }) }
export function useAddTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, text, mentions = [] }: { taskId: number; text: string; mentions?: number[] }) => api.post(`/v1/tasks/${taskId}/comments`, { text, mentions }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Сэтгэгдэл хадгалагдсангүй') }) }
export function useResolveTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id, is_resolved }: { taskId: number; id: number; is_resolved: boolean }) => api.patch(`/v1/tasks/${taskId}/comments/${id}`, { is_resolved }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId) }) }
export function useDeleteTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/comments/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Сэтгэгдэл устгагдсангүй') }) }

export function useAttachments(objectType: 'task' | 'report', objectId?: number) { return useQuery<EnterpriseAttachment[]>({ queryKey: ['v1', 'attachments', objectType, objectId], queryFn: () => api.get('/v1/attachments', { params: { object_type: objectType, object_id: objectId } }).then((r) => r.data), enabled: Boolean(objectId) }) }
export function useUploadAttachment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ objectType, objectId, file, onProgress }: { objectType: 'task' | 'report'; objectId: number; file: File; onProgress?: (value: number) => void }) => { const form = new FormData(); form.append('file', file); return api.post('/v1/attachments', form, { params: { object_type: objectType, object_id: objectId }, onUploadProgress: (event) => onProgress?.(event.total ? Math.round(event.loaded * 100 / event.total) : 0) }).then((r) => r.data) }, onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ['v1', 'attachments', v.objectType, v.objectId] }); if (v.objectType === 'task') invalidateTaskDetail(qc, v.objectId) }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Файл байршуулсангүй') }) }
export function useDeleteAttachment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id }: { id: number; objectType: 'task' | 'report'; objectId: number }) => api.delete(`/v1/attachments/${id}`), onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ['v1', 'attachments', v.objectType, v.objectId] }); if (v.objectType === 'task') invalidateTaskDetail(qc, v.objectId) }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Файл устгагдсангүй') }) }
export async function downloadAttachment(id: number, filename: string) { requireWebCapability('File downloads'); const response = await api.get(`/v1/attachments/${id}/download`, { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url) }

export function useTaskActivity(id?: number) { return useQuery<TaskActivity[]>({ queryKey: ['v1', 'tasks', id, 'activity'], queryFn: () => api.get(`/v1/tasks/${id}/activity`).then((r) => r.data), enabled: Boolean(id) }) }
export function useSavedViews(module: string) { return useQuery<SavedView[]>({ queryKey: ['v1', 'saved-views', module], queryFn: () => api.get('/v1/saved-views', { params: { module } }).then((r) => r.data) }) }
export function useCreateSavedView() { const qc = useQueryClient(); return useMutation({ mutationFn: (input: Omit<SavedView, 'id'>) => api.post('/v1/saved-views', input).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'saved-views'] }) }) }
export function useDeleteSavedView() { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.delete(`/v1/saved-views/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'saved-views'] }) }) }

export function useCapacity(period?: DateRange) {
  return useQuery<any[]>({ queryKey: ['v1', 'capacity', period], queryFn: () => api.get('/v1/capacity', { params: period }).then((response) => response.data) })
}

export function useObjectives() {
  return useQuery<any[]>({ queryKey: ['v1', 'objectives'], queryFn: () => api.get('/v1/objectives').then((response) => response.data) })
}

export function useEnterpriseReports(status?: string, period?: DateRange) {
  return useQuery<any[]>({ queryKey: ['v1', 'reports', status, period], queryFn: () => api.get('/v1/reports', { params: { ...(status ? { status } : {}), ...period } }).then((response) => response.data) })
}

export function useCreateReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { report_type: 'daily' | 'monthly'; period_date: string }) => api.post('/v1/reports', input).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'reports'] }); toast.success('Тайлан үүслээ') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Тайлан үүссэнгүй'),
  })
}

export interface PermissionSettings { task_assignment_roles: string[]; available_roles: string[] }
export function usePermissionSettings() {
  return useQuery<PermissionSettings>({ queryKey: ['v1', 'settings', 'permissions'], queryFn: () => api.get('/v1/settings/permissions').then((response) => response.data) })
}
export function useUpdatePermissionSettings() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (task_assignment_roles: string[]) => api.put('/v1/settings/permissions', { task_assignment_roles }).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'settings', 'permissions'] }); toast.success('Даалгаврын эрх хадгалагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Эрх хадгалагдсангүй') })
}

export interface BrandingSettings {
  light_logo: string
  dark_logo: string
  light_source: string
  dark_source: string
  legacy_options: { value: 'legacy-aio' | 'legacy-icon'; label: string; url: string }[]
}

export function useBrandingSettings() {
  return useQuery<BrandingSettings>({ queryKey: ['v1', 'settings', 'branding'], queryFn: () => api.get('/v1/settings/branding').then((response) => response.data) })
}

export function useUpdateBrandingSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { theme: 'light' | 'dark'; source: 'legacy-aio' | 'legacy-icon' | 'default' }) => api.put('/v1/settings/branding', input).then((response) => response.data),
    onSuccess: (data) => { queryClient.setQueryData(['v1', 'settings', 'branding'], data); toast.success('Лого хадгалагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Лого хадгалагдсангүй'),
  })
}

export function useUploadBrandingLogo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ theme, file }: { theme: 'light' | 'dark'; file: File }) => { const form = new FormData(); form.append('file', file); return api.post('/v1/settings/branding/logo', form, { params: { theme } }).then((response) => response.data) },
    onSuccess: (data) => { queryClient.setQueryData(['v1', 'settings', 'branding'], data); toast.success('Лого байршууллаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Лого байршуулсангүй'),
  })
}

export function useTodayCheckin() {
  return useQuery<any>({ queryKey: ['v1', 'checkins', 'today'], queryFn: () => api.get('/v1/checkins/today').then((response) => response.data) })
}

export function useStartCheckin() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (template_id: number) => api.post('/v1/checkins', { template_id }).then((response) => response.data), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'checkins'] }) })
}

export function useSubmitCheckin() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: ({ id, answers }: { id: number; answers: any[] }) => api.post(`/v1/checkins/${id}/submit`, { answers }).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'checkins'] }); toast.success('Өдрийн check-in хадгалагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Check-in хадгалагдсангүй') })
}

export function useDailyAnalytics(period: DateRange, employeeId?: number) {
  return useQuery<any>({ queryKey: ['v1', 'analytics', 'daily', period, employeeId], queryFn: () => api.get('/v1/analytics/daily', { params: { ...period, ...(employeeId ? { employee_id: employeeId } : {}) } }).then((response) => response.data), refetchOnMount: 'always', refetchOnWindowFocus: false })
}

export interface WorkHoursAnalytics {
  date_from: string
  date_to: string
  employee_id: number | null
  remote_minutes: number
  office_minutes: number
  total_minutes: number
  scope: 'organization' | 'worker'
}

function dateOnly(value: Date) {
  return `${value.getFullYear().toString().padStart(4, '0')}-${(value.getMonth() + 1).toString().padStart(2, '0')}-${value.getDate().toString().padStart(2, '0')}`
}

export function previousDateRange(period: DateRange): DateRange {
  const start = new Date(`${period.date_from}T12:00:00`)
  const end = new Date(`${period.date_to}T12:00:00`)
  const dayCount = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1)
  const previousEnd = new Date(start)
  previousEnd.setDate(previousEnd.getDate() - 1)
  const previousStart = new Date(previousEnd)
  previousStart.setDate(previousStart.getDate() - dayCount + 1)
  return { date_from: dateOnly(previousStart), date_to: dateOnly(previousEnd) }
}

function workHoursQuery(period: DateRange, employeeId?: number) {
  return {
    queryKey: ['v1', 'analytics', 'work-hours', period, employeeId],
    queryFn: () => api.get<WorkHoursAnalytics>('/v1/analytics/work-hours', { params: { ...period, ...(employeeId ? { employee_id: employeeId } : {}) } }).then((response) => response.data),
    refetchOnMount: 'always' as const,
    refetchOnWindowFocus: false as const,
  }
}

export function useWorkHoursAnalytics(period: DateRange, employeeId?: number) {
  const previous = previousDateRange(period)
  const currentQuery = useQuery<WorkHoursAnalytics>(workHoursQuery(period, employeeId))
  const previousQuery = useQuery<WorkHoursAnalytics>(workHoursQuery(previous, employeeId))
  return {
    data: currentQuery.data,
    previousData: previousQuery.data,
    isLoading: currentQuery.isLoading,
    isFetching: currentQuery.isFetching,
    trendPending: previousQuery.isLoading || previousQuery.isFetching,
    isError: currentQuery.isError,
    refetch: currentQuery.refetch,
  }
}

export type AnalyticsMetric = 'utilization' | 'billable_ratio' | 'budget_burn' | 'task_completion' | 'deadline_health' | 'report_compliance'
export interface AnalyticsDrilldown { metric: AnalyticsMetric; scope: string; date_from: string; date_to: string; items: Array<Record<string, any>>; totals: { count: number; average_value: number | null; unpriced_minutes: number }; page: number; page_size: number; total: number }
export function useAnalyticsDrilldown(metric: AnalyticsMetric | undefined, period: DateRange, employeeId?: number) { return useQuery<AnalyticsDrilldown>({ queryKey: ['v1', 'analytics', 'drilldown', metric, period, employeeId], queryFn: () => api.get('/v1/analytics/drilldown', { params: { metric, ...period, ...(employeeId ? { employee_id: employeeId } : {}) } }).then((r) => r.data), enabled: Boolean(metric) }) }

export interface PersonalTimeBlock { id: number; title: string; starts_at: string; ends_at: string; task_id: number | null; version: number }

export function useCalendarEvents(scope: 'private' | 'corporate', anchor: Date) {
  const months = [-1, 0, 1].map((offset) => {
    const month = new Date(anchor.getFullYear(), anchor.getMonth() + offset, 1)
    return { month, period: calendarMonthPeriod(anchor, offset) }
  })
  const queries = useQueries({
    queries: months.map(({ month, period }) => ({
      queryKey: ['v1', 'calendar', scope, 'month', month.getFullYear(), month.getMonth()],
      queryFn: () => api.get('/v1/calendar/events', { params: { scope, ...period } }).then((response) => response.data),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const data = queries.reduce((combined, query) => {
    const monthData = query.data
    if (!monthData) return combined
    for (const key of ['tasks', 'projects', 'plans', 'entries', 'holidays', 'time_blocks']) {
      combined[key] = [...combined[key], ...(monthData[key] ?? [])]
    }
    return combined
  }, { tasks: [], projects: [], plans: [], entries: [], holidays: [], time_blocks: [] } as Record<string, any[]>)
  return {
    data,
    isLoading: queries.some((query) => query.isLoading),
    isFetching: queries.some((query) => query.isFetching),
    isError: queries.some((query) => query.isError),
  }
}

export function useHolidaySettings() {
  return useQuery<{ country: string; countries: { countryCode: string; name: string }[] }>({ queryKey: ['v1', 'calendar', 'holiday-settings'], queryFn: () => api.get('/v1/calendar/holiday-settings').then((response) => response.data) })
}

export function useSetHolidayCountry() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: async (country_code: string) => { await api.put('/v1/calendar/holiday-country', { country_code }); const year = new Date().getFullYear(); await Promise.all([api.post('/v1/calendar/holidays/sync', null, { params: { year } }), api.post('/v1/calendar/holidays/sync', null, { params: { year: year + 1 } })]) }, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); toast.success('Амралтын өдрийн улс шинэчлэгдлээ') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Улс шинэчлэгдсэнгүй') })
}

export function useCreateCalendarEntry() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: Record<string, unknown>) => api.post('/v1/calendar/entries', input).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'today'] }); toast.success('Календарийн item хадгалагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Календарийн item хадгалагдсангүй') })
}

export function useTodayAgenda() {
  return useQuery<any>({ queryKey: ['v1', 'today', 'agenda'], queryFn: () => api.get('/v1/today/agenda').then((response) => response.data) })
}

export function useCreateTimeBlock() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: Record<string, unknown>) => api.post('/v1/calendar/time-blocks', input).then((response) => response.data), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }), onError: (error: any) => toast.error(error.response?.data?.detail || 'Хувийн төлөвлөгөө хадгалагдсангүй') })
}

export function useDeleteTimeBlock() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (id: number) => api.delete(`/v1/calendar/time-blocks/${id}`), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }) })
}

export function useReportReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'approve' | 'request-revision' | 'submit' | 'reopen' }) => api.post(`/v1/reports/${id}/${action}`).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'reports'] }),
  })
}

export function useReportDetail(id?: number) {
  return useQuery<any>({ queryKey: ['v1', 'reports', 'detail', id], queryFn: () => api.get(`/v1/reports/${id}`).then((response) => response.data), enabled: Boolean(id) })
}

export function useSaveReportDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, version, title, markdown }: { id: number; version: number; title?: string; markdown: string }) => api.put(`/v1/reports/${id}/draft`, { title, markdown }, { headers: { 'If-Match': String(version) } }).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'reports'] }),
  })
}

export function useAddReportComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ reportId, revision_id, text, range_metadata }: { reportId: number; revision_id?: number; text: string; range_metadata?: { start: number; end: number; quote: string } }) => api.post(`/v1/reports/${reportId}/comments`, { revision_id, text, range_metadata }).then((r) => r.data), onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: ['v1', 'reports', 'detail', v.reportId] }), onError: (e: any) => toast.error(e.response?.data?.detail || 'Сэтгэгдэл хадгалагдсангүй') }) }
export function useResolveReportComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ reportId, id, is_resolved }: { reportId: number; id: number; is_resolved: boolean }) => api.patch(`/v1/reports/${reportId}/comments/${id}`, null, { params: { is_resolved } }).then((r) => r.data), onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: ['v1', 'reports', 'detail', v.reportId] }) }) }
export function useBatchApproveReports() { const qc = useQueryClient(); return useMutation({ mutationFn: (report_ids: number[]) => api.post('/v1/reports/batch-approve', { report_ids }).then((r) => r.data), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'reports'] }); toast.success('Сонгосон тайлангууд батлагдлаа') }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Багц батлалт амжилтгүй') }) }

export interface WorkerDirectoryItem {
  id: number
  name: string
  job_title: string | null
  telegram_username: string | null
  avatar_url: string | null
  presence: 'offline' | 'in_person' | 'remote' | 'break'
}

export interface ChatIdentity {
  account_id: number
  employee_id: number | null
  name: string
  email: string
  avatar_url: string | null
  is_online: boolean
  last_seen_at: string | null
  role?: 'owner' | 'member'
  is_agent?: boolean
}

export interface ChatMessageSummary {
  id: number
  body: string | null
  attachment_count: number
  sender_account_id: number | null
  sender_name: string | null
  created_at: string
}

export interface ChatConversation {
  id: number
  public_id: string
  kind: 'direct' | 'group'
  title: string
  avatar_urls: string[]
  presence: 'online' | 'offline' | null
  members: ChatIdentity[]
  member_count: number
  can_manage: boolean
  last_message: ChatMessageSummary | null
  unread_count: number
  is_pinned: boolean
  pinned_at: string | null
  is_archived: boolean
  archived_at: string | null
  is_muted: boolean
  muted_until: string | null
  pinned_message_count: number
  created_at: string
  updated_at: string
}

export interface ChatAttachment {
  id: number
  public_id: string
  filename: string
  content_type: string
  media_kind: 'image' | 'video' | 'audio' | 'document'
  size: number
  duration_seconds: number | null
  scan_status: string
  download_url: string
}

export interface CompanyFileChatAttachment {
  item_id: number
  filename: string
  content_type: string
  size: number | null
  download_url: string
}

export interface ChatMessage {
  id: number
  conversation_id: number
  sender: ChatIdentity | null
  sender_account_id: number | null
  client_nonce: string
  body: string | null
  kind: 'text' | 'call'
  call: { call_id: string; call_type: 'audio' | 'video'; outcome: 'completed' | 'missed' | 'declined' | 'canceled' | 'failed'; duration_seconds: number; direction: 'incoming' | 'outgoing'; caller_name: string | null; callee_name: string | null; started_at: string; ended_at: string | null } | null
  attachments: ChatAttachment[]
  company_file_attachments: CompanyFileChatAttachment[]
  reply_to_message_id: number | null
  thread_root_message_id: number | null
  reply_preview: { id: number; body: string | null; sender_name: string | null; is_deleted: boolean } | null
  thread_reply_count: number
  forwarded_from_message_id: number | null
  forwarded_sender_name: string | null
  reactions: Array<{ emoji: string; count: number; reacted: boolean }>
  is_starred: boolean
  is_pinned: boolean
  is_deleted: boolean
  edited_at: string | null
  deleted_at: string | null
  created_at: string
  is_mine: boolean
  status: 'sending' | 'failed' | 'sent' | 'delivered' | 'read' | null
  receipts: { total: number; delivered: number; read: number }
  capabilities: { can_edit: boolean; can_delete_everyone: boolean; can_delete_self: boolean; can_forward: boolean; can_react: boolean; can_pin: boolean }
}

export interface ChatMessagePage { items: ChatMessage[]; next_before_id: number | null }
export interface ChatConversationPage { items: ChatConversation[]; next_cursor: number | null }
export interface ChatReceiptDetail {
  message_id: number
  counts: { total: number; delivered: number; read: number }
  items: Array<{ account: ChatIdentity; status: 'sent' | 'delivered' | 'read'; delivered_at: string | null; read_at: string | null }>
}

export function useChatContacts(search = '', enabled = true) {
  return useQuery<ChatIdentity[]>({
    queryKey: ['v1', 'chat', 'contacts', search],
    queryFn: () => api.get('/v1/chat/contacts', { params: { q: search || undefined, limit: 100 } }).then((response) => response.data),
    enabled,
    refetchInterval: 20_000,
  })
}

export type ChatConversationFilter = 'all' | 'unread' | 'groups' | 'direct' | 'archived'

export function useChatConversations(search = '', filter: ChatConversationFilter = 'all') {
  return useQuery<ChatConversationPage>({
    queryKey: ['v1', 'chat', 'conversations', search, filter],
    queryFn: () => api.get('/v1/chat/conversations', { params: { q: search || undefined, filter, limit: 50 } }).then((response) => response.data),
    refetchInterval: 20_000,
  })
}

export function useChatUnreadCount(enabled = true) {
  return useQuery<{ unread_count: number }>({
    queryKey: ['v1', 'chat', 'unread-count'],
    queryFn: () => api.get('/v1/chat/unread-count').then((response) => response.data),
    enabled,
  })
}

export function useChatConversation(publicId?: string) {
  return useQuery<ChatConversation>({
    queryKey: ['v1', 'chat', 'conversation', publicId],
    queryFn: () => api.get(`/v1/chat/conversations/${publicId}`).then((response) => response.data),
    enabled: Boolean(publicId),
    refetchInterval: 20_000,
  })
}

export function useChatMessages(publicId?: string) {
  return useInfiniteQuery<ChatMessagePage>({
    queryKey: ['v1', 'chat', 'messages', publicId],
    queryFn: ({ pageParam }) => api.get(`/v1/chat/conversations/${publicId}/messages`, { params: { before_id: pageParam || undefined, limit: 50 } }).then((response) => response.data),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_before_id || undefined,
    enabled: Boolean(publicId),
  })
}

export function useChatMessageContext(publicId?: string, aroundId?: number) {
  return useQuery<ChatMessagePage & { anchor_message_id?: number }>({
    queryKey: ['v1', 'chat', 'message-context', publicId, aroundId],
    queryFn: () => api.get(`/v1/chat/conversations/${publicId}/messages`, { params: { around_id: aroundId, limit: 50 } }).then((response) => response.data),
    enabled: Boolean(publicId && aroundId),
  })
}

function invalidateChat(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversations'] })
  queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'unread-count'] })
}

export function useOpenDirectConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { account_id?: number; employee_id?: number; agent?: boolean }) => api.post('/v1/chat/conversations/direct', input).then((response) => response.data as ChatConversation),
    onSuccess: () => invalidateChat(queryClient),
  })
}

export function useCreateChatGroup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { title: string; member_account_ids: number[] }) => api.post('/v1/chat/conversations/groups', input).then((response) => response.data as ChatConversation),
    onSuccess: () => invalidateChat(queryClient),
  })
}

export function useRenameChatGroup(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (title: string) => api.patch(`/v1/chat/conversations/${publicId}`, { title }).then((response) => response.data as ChatConversation), onSuccess: () => { invalidateChat(queryClient); queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversation', publicId] }) } })
}

export function useAddChatMembers(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (account_ids: number[]) => api.post(`/v1/chat/conversations/${publicId}/members`, { account_ids }).then((response) => response.data as ChatConversation), onSuccess: () => { invalidateChat(queryClient); queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversation', publicId] }) } })
}

export function useRemoveChatMember(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (accountId: number) => api.delete(`/v1/chat/conversations/${publicId}/members/${accountId}`), onSuccess: () => { invalidateChat(queryClient); queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversation', publicId] }) } })
}

export function useLeaveChatGroup(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: () => api.post(`/v1/chat/conversations/${publicId}/leave`).then((response) => response.data), onSuccess: () => invalidateChat(queryClient) })
}

export function useSendChatMessage(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation<ChatMessage, any, { body?: string | null; client_nonce: string; upload_ids?: string[]; reply_to_message_id?: number | null }, { previous?: InfiniteData<ChatMessagePage>; nonce: string }>({
    mutationFn: (input) => api.post(`/v1/chat/conversations/${publicId}/messages`, input).then((response) => response.data),
    onMutate: async (input) => {
      const key = ['v1', 'chat', 'messages', publicId]
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<InfiniteData<ChatMessagePage>>(key)
      const actor = useAuthStore.getState().actor
      const optimistic: ChatMessage = {
        id: -Date.now(), conversation_id: 0, sender: actor ? { account_id: actor.id, employee_id: actor.employee_id, name: actor.name || actor.email, email: actor.email, avatar_url: actor.avatar_url || null, is_online: true, last_seen_at: new Date().toISOString() } : null,
        sender_account_id: actor?.id ?? null, client_nonce: input.client_nonce, body: input.body || null, kind: 'text', call: null, attachments: [], company_file_attachments: [], reply_to_message_id: input.reply_to_message_id || null, thread_root_message_id: null, reply_preview: null, thread_reply_count: 0, forwarded_from_message_id: null, forwarded_sender_name: null, reactions: [], is_starred: false, is_pinned: false, is_deleted: false, edited_at: null, deleted_at: null, created_at: new Date().toISOString(), is_mine: true, status: 'sending', receipts: { total: 0, delivered: 0, read: 0 }, capabilities: { can_edit: false, can_delete_everyone: false, can_delete_self: false, can_forward: false, can_react: false, can_pin: false },
      }
      queryClient.setQueryData<InfiniteData<ChatMessagePage>>(key, (current) => current ? ({ ...current, pages: current.pages.map((page, index) => index === 0 ? { ...page, items: [...page.items.filter((message) => message.client_nonce !== input.client_nonce), optimistic] } : page) }) : { pages: [{ items: [optimistic], next_before_id: null }], pageParams: [undefined] })
      return { previous, nonce: input.client_nonce }
    },
    onError: (_error, _input, context) => {
      const key = ['v1', 'chat', 'messages', publicId]
      queryClient.setQueryData<InfiniteData<ChatMessagePage>>(key, (current) => current ? ({ ...current, pages: current.pages.map((page) => ({ ...page, items: page.items.map((message) => message.client_nonce === context?.nonce ? { ...message, status: 'failed' } : message) })) }) : context?.previous)
    },
    onSuccess: (message) => {
      const key = ['v1', 'chat', 'messages', publicId]
      queryClient.setQueryData<InfiniteData<ChatMessagePage>>(key, (current) => current ? ({ ...current, pages: current.pages.map((page) => ({ ...page, items: page.items.map((item) => item.client_nonce === message.client_nonce ? message : item) })) }) : current)
      invalidateChat(queryClient)
    },
  })
}

export async function uploadChatAttachment(publicId: string, file: File, onProgress?: (value: number) => void, signal?: AbortSignal) {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/v1/chat/conversations/${publicId}/uploads`, form, {
    signal,
    onUploadProgress: (event) => onProgress?.(event.total ? Math.round(event.loaded * 100 / event.total) : 0),
  }).then((response) => response.data as ChatAttachment)
}

export function cancelChatUpload(publicId: string, uploadId: string) {
  return api.delete(`/v1/chat/conversations/${publicId}/uploads/${uploadId}`)
}

export async function downloadChatAttachment(publicId: string, attachment: ChatAttachment) {
  const response = await api.get(`/v1/chat/conversations/${publicId}/attachments/${attachment.public_id}`, { responseType: 'blob' })
  return URL.createObjectURL(response.data)
}

export async function downloadCompanyFileChatAttachment(attachment: CompanyFileChatAttachment) {
  const response = await api.get(`/v1/company-files/${attachment.item_id}/download`, { responseType: 'blob' })
  return URL.createObjectURL(response.data)
}

function useChatMessageMutation(publicId?: string) {
  const queryClient = useQueryClient()
  return (message?: ChatMessage) => {
    invalidateChat(queryClient)
    queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'messages', publicId] })
    queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'conversation', publicId] })
    return message
  }
}

export function useEditChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, body }: { messageId: number; body: string }) => api.patch(`/v1/chat/conversations/${publicId}/messages/${messageId}`, { body }).then((r) => r.data as ChatMessage), onSuccess: done }) }
export function useDeleteChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, scope }: { messageId: number; scope: 'self' | 'everyone' }) => api.delete(`/v1/chat/conversations/${publicId}/messages/${messageId}`, { params: { scope } }).then((r) => r.data), onSuccess: () => done() }) }
export function useReactChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, emoji, remove }: { messageId: number; emoji: string; remove?: boolean }) => api.request({ url: `/v1/chat/conversations/${publicId}/messages/${messageId}/reaction`, method: remove ? 'DELETE' : 'PUT', data: { emoji } }).then((r) => r.data as ChatMessage), onSuccess: done }) }
export function useStarChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, starred }: { messageId: number; starred: boolean }) => api.request({ url: `/v1/chat/conversations/${publicId}/messages/${messageId}/star`, method: starred ? 'PUT' : 'DELETE' }).then((r) => r.data as ChatMessage), onSuccess: done }) }
export function usePinChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, pinned }: { messageId: number; pinned: boolean }) => api.request({ url: `/v1/chat/conversations/${publicId}/messages/${messageId}/pin`, method: pinned ? 'PUT' : 'DELETE' }).then((r) => r.data as ChatMessage), onSuccess: done }) }
export function useChatThread(publicId?: string, messageId?: number) { return useQuery<{ root: ChatMessage; items: ChatMessage[] }>({ queryKey: ['v1', 'chat', 'thread', publicId, messageId], queryFn: () => api.get(`/v1/chat/conversations/${publicId}/messages/${messageId}/thread`).then((r) => r.data), enabled: Boolean(publicId && messageId) }) }
export function useForwardChatMessage(publicId?: string) { const done = useChatMessageMutation(publicId); return useMutation({ mutationFn: ({ messageId, destinations }: { messageId: number; destinations: Array<{ conversation_public_id: string; client_nonce: string }> }) => api.post(`/v1/chat/conversations/${publicId}/messages/${messageId}/forward`, { destinations }).then((r) => r.data), onSuccess: () => done() }) }
export function useChatSearch(search: string, conversationPublicId?: string, enabled = true) { return useQuery<{ items: Array<{ conversation: { public_id: string; title: string }; message: ChatMessage }>; next_before_id: number | null }>({ queryKey: ['v1', 'chat', 'search', search, conversationPublicId], queryFn: () => api.get('/v1/chat/search', { params: { q: search, conversation_public_id: conversationPublicId || undefined } }).then((r) => r.data), enabled: enabled && Boolean(search.trim()) }) }
export function useUpdateChatConversationPreferences(publicId?: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { pinned?: boolean; archived?: boolean; mute_for?: '1h' | '8h' | '1w' | 'forever' | 'off' }) => api.patch(`/v1/chat/conversations/${publicId}/preferences`, input).then((r) => r.data as ChatConversation), onSuccess: () => { invalidateChat(qc); qc.invalidateQueries({ queryKey: ['v1', 'chat', 'conversation', publicId] }) } }) }

export function useAcknowledgeChat(publicId?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { message_id: number; status: 'delivered' | 'read' }) => acknowledgeChatReceipt(publicId!, input.message_id, input.status),
    onSuccess: () => { invalidateChat(queryClient); queryClient.invalidateQueries({ queryKey: ['v1', 'chat', 'messages', publicId] }) },
  })
}

export function acknowledgeChatReceipt(publicId: string, messageId: number, status: 'delivered' | 'read') {
  return api.post(`/v1/chat/conversations/${publicId}/receipts`, { message_id: messageId, status })
}

export function useChatReceiptDetails(publicId?: string, messageId?: number) {
  return useQuery<ChatReceiptDetail>({ queryKey: ['v1', 'chat', 'receipts', publicId, messageId], queryFn: () => api.get(`/v1/chat/conversations/${publicId}/messages/${messageId}/receipts`).then((response) => response.data), enabled: Boolean(publicId && messageId) })
}

export function useWorkerDirectory() {
  return useQuery<WorkerDirectoryItem[]>({ queryKey: ['v1', 'workers'], queryFn: () => api.get('/v1/workers').then((response) => response.data), refetchInterval: 30_000 })
}

export function useWorkerPerformance(employeeId?: number, period?: DateRange, enabled = true) {
  return useQuery<any>({ queryKey: ['v1', 'workers', employeeId, 'performance', period], queryFn: () => api.get(`/v1/workers/${employeeId}/performance`, { params: period }).then((response) => response.data), enabled: Boolean(employeeId) && enabled })
}

export type ERPModule = 'accounting' | 'selling' | 'buying' | 'stock' | 'crm' | 'support' | 'payroll' | 'manufacturing' | 'assets_maintenance'
export interface ERPMetadata {
  modules: Record<ERPModule, boolean>
  module_labels: Record<ERPModule, string>
  document_modules: Record<string, ERPModule>
  actions: string[]
  currency: string
  custom_fields: Array<{ resource: string; key: string; label: string; field_type: string; options: Record<string, unknown>; required: boolean; posting_relevant: boolean }>
  roles: Array<{ id: number; name: string; code: string; description: string | null }>
  module_visibility_is_not_authorization: boolean
}
export type ERPFieldType = 'text' | 'long_text' | 'number' | 'money' | 'date' | 'datetime' | 'boolean' | 'select' | 'multi_select' | 'reference'
export interface ERPFormField { key: string; label: string; help_text?: string | null; field_type: ERPFieldType; section: 'header' | 'line' | 'master'; required: boolean; default?: unknown; options: Record<string, any>; validation: Record<string, any>; position: number }
export interface ERPWorkflow { initial_state: string; states: Array<{ key: string; label?: string; terminal?: boolean }>; transitions: Array<{ from: string; to: string; label: string; role_ids: number[]; requester_allowed: boolean }> }
export interface ERPFormDefinition { id: number; operation: string; version: number; status: 'draft' | 'published' | 'archived'; fields: ERPFormField[]; workflow: ERPWorkflow; published_at?: string | null; archived_at?: string | null; updated_at?: string }
export interface ERPOperationCatalog { operations: Record<string, { key: string; label: string; kind: 'document' | 'master_request'; module: ERPModule | null; sections: Array<'header' | 'line' | 'master'>; posting_capable: boolean }>; actions: string[]; field_types: ERPFieldType[]; sections: string[]; reference_targets: string[]; scope_dimensions: string[] }
export interface ERPAccessRole { id: number; name: string; code: string; description: string | null; is_system: boolean; is_active: boolean; capabilities: Array<{ resource: string; action: string }>; account_assignments: Array<{ id: number; account_id: number; scope: ERPAssignmentScope }>; team_assignments: Array<{ id: number; team_id: number; scope: ERPAssignmentScope }> }
export interface ERPAssignmentScope { warehouse_ids?: number[]; project_ids?: number[]; branch_codes?: string[] }
export interface ERPMasterRequest { id: number; operation: string; definition_version: number; workflow_state: string; status?: string; payload: Record<string, unknown>; payload_json?: Record<string, unknown>; scope: ERPAssignmentScope; version: number; requested_by?: number; approved_by?: number | null; approved_at?: string | null; materialized_entity_type?: string | null; materialized_entity_id?: number | null }
export interface ERPDocumentLineInput { id?: number; item_id?: number; warehouse_id?: number; account_id?: number; description: string; quantity?: string | number; rate?: string | number; discount_percent?: string | number; discount_amount?: string | number; tax_rate?: string | number; data?: Record<string, unknown> }
export interface ERPDocument { id: number; public_id: string; document_type: string; number: string; status: string; party_id: number | null; project_id: number | null; source_document_id: number | null; amended_from_id: number | null; currency: string; exchange_rate: string; posting_date: string; due_date: string | null; net_total: string; tax_total: string; grand_total: string; outstanding_amount: string; payload: Record<string, unknown>; custom: Record<string, unknown>; version: number; workflow_state?: string; archived_at?: string | null; lines?: ERPDocumentLineInput[] }
export interface ERPDashboard { currency: string; revenue: string; expenses: string; profit: string; cash_collected: string; inventory_value: string; open_customer_queries: number; open_queries?: number; open_queries_breakdown?: { support_tickets: number; pending_approvals: number }; payroll_total: string; production_cost: string; upcoming_maintenance: number }

export function useERPMetadata(enabled = true) { return useQuery<ERPMetadata>({ queryKey: ['v1', 'erp', 'meta'], queryFn: () => api.get('/v1/erp/meta').then((r) => r.data), enabled, retry: false }) }
export function useERPCatalog(enabled = true) { return useQuery<ERPOperationCatalog>({ queryKey: ['v1', 'erp', 'catalog'], queryFn: () => api.get('/v1/erp/catalog').then((r) => r.data), enabled, retry: false }) }
export function useERPForm(operation: string, admin = false, history = false) { return useQuery<ERPFormDefinition & { history?: ERPFormDefinition[] }>({ queryKey: ['v1', 'erp', 'form', operation, admin, history], queryFn: () => api.get(admin ? `/v1/erp/admin/forms/${operation}` : `/v1/erp/forms/${operation}`, { params: admin && history ? { include_history: true } : undefined }).then((r) => r.data), enabled: Boolean(operation), retry: false }) }
export function useSaveERPFormDraft(operation: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (input: Pick<ERPFormDefinition, 'fields' | 'workflow'>) => api.put(`/v1/erp/admin/forms/${operation}`, input).then((r) => r.data as ERPFormDefinition), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'form', operation] }) }) }
export function usePublishERPForm(operation: string) { const qc = useQueryClient(); return useMutation({ mutationFn: () => api.post(`/v1/erp/admin/forms/${operation}/publish`).then((r) => r.data as ERPFormDefinition), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useERPAccessRoles() { return useQuery<ERPAccessRole[]>({ queryKey: ['v1', 'erp', 'roles'], queryFn: () => api.get('/v1/erp/admin/roles').then((r) => r.data), retry: false }) }
export function useCreateERPAccessRole() { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { name: string; code: string; description?: string; capabilities: Array<{ resource: string; action: string }> }) => api.post('/v1/erp/admin/roles', input).then((r) => r.data as ERPAccessRole), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useUpdateERPAccessRole() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, ...input }: { id: number; name?: string; description?: string; capabilities?: Array<{ resource: string; action: string }> }) => api.patch(`/v1/erp/admin/roles/${id}`, input).then((r) => r.data as ERPAccessRole), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useCloneERPAccessRole() { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.post(`/v1/erp/admin/roles/${id}/clone`).then((r) => r.data as ERPAccessRole), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useDeactivateERPAccessRole() { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.post(`/v1/erp/admin/roles/${id}/deactivate`).then((r) => r.data as ERPAccessRole), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useAssignERPAccountRole() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ roleId, account_id, scope = {} }: { roleId: number; account_id: number; scope?: ERPAssignmentScope }) => api.post(`/v1/erp/admin/roles/${roleId}/accounts`, { account_id, scope }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useAssignERPTeamRole() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ roleId, team_id, scope = {} }: { roleId: number; team_id: number; scope?: ERPAssignmentScope }) => api.post(`/v1/erp/admin/roles/${roleId}/teams`, { team_id, scope }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'roles'] }) }) }
export function useTeams() { return useQuery<Array<{ id: number; name: string; code: string }>>({ queryKey: ['v1', 'teams'], queryFn: () => api.get('/v1/teams').then((r) => r.data) }) }
export function useCreateERPMasterRequest(operation: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { payload: Record<string, unknown>; custom: Record<string, unknown>; scope?: ERPAssignmentScope }) => api.post(`/v1/erp/master-requests/${operation}`, input).then((r) => r.data as ERPMasterRequest), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useTransitionERPMasterRequest() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, ...input }: { id: number; to_state: string; version: number; comment?: string }) => api.post(`/v1/erp/master-requests/by-id/${id}/transition`, input).then((r) => r.data as ERPMasterRequest), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useUpdateERPModules() { const qc = useQueryClient(); return useMutation({ mutationFn: (modules: Record<ERPModule, boolean>) => api.put('/v1/erp/admin/modules', { modules }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export type ERPDocumentView = 'all' | 'drafts' | 'pending_approval' | 'approved' | 'archived'
export function useERPDocuments(documentType: string, enabled = true, view: ERPDocumentView = 'all', search = '') { return useQuery<ERPDocument[]>({ queryKey: ['v1', 'erp', 'documents', documentType, view, search], queryFn: () => api.get(`/v1/erp/documents/${documentType}`, { params: { view, search: search || undefined } }).then((r) => r.data), enabled: enabled && Boolean(documentType), retry: false }) }
export function useCreateERPDocument(documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { party_id?: number; due_date?: string; payload?: Record<string, unknown>; custom?: Record<string, unknown>; lines?: ERPDocumentLineInput[] }) => api.post(`/v1/erp/documents/${documentType}`, input, { headers: { 'Idempotency-Key': crypto.randomUUID() } }).then((r) => r.data as ERPDocument), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useSubmitERPDocument(documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.post(`/v1/erp/documents/by-id/${id}/submit`).then((r) => r.data as ERPDocument), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'erp'] }); qc.invalidateQueries({ queryKey: ['v1', 'erp', 'documents', documentType] }) } }) }
export function useERPDocumentAction(action: 'archive' | 'restore' | 'approve', documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.post(`/v1/erp/documents/by-id/${id}/${action}`).then((r) => r.data as ERPDocument), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'erp'] }); qc.invalidateQueries({ queryKey: ['v1', 'erp', 'documents', documentType] }) } }) }
export function useConvertERPDocument(documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, targetType }: { id: number; targetType: string }) => api.post(`/v1/erp/documents/by-id/${id}/convert/${targetType}`).then((r) => r.data as ERPDocument), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useERPDashboard(enabled = true) { return useQuery<ERPDashboard>({ queryKey: ['v1', 'erp', 'dashboard'], queryFn: () => api.get('/v1/erp/reports/dashboard').then((r) => r.data), enabled, retry: false }) }

export function useWorkerProfile(employeeId?: number) {
  return useQuery<any>({ queryKey: ['v1', 'workers', employeeId, 'profile'], queryFn: () => api.get(`/v1/auth/workers/${employeeId}/profile`).then((response) => response.data), enabled: Boolean(employeeId) })
}

export function useAssistantDraft() {
  return useMutation({ mutationFn: (input: { text: string; kind: 'task' | 'report' }) => api.post('/v1/assistant/drafts', input).then((response) => response.data) })
}

export function useAssistantChat() {
  return useMutation({ mutationFn: (input: { text: string; conversation_id?: number; voice_mode?: boolean }) => api.post('/v1/assistant/conversations', input).then((response) => response.data) })
}

export interface AssistantFileAttachment {
  item_id: number
  filename: string
  content_type: string
  size: number | null
  download_url: string
}

export async function downloadAssistantAttachment(attachment: AssistantFileAttachment) {
  const response = await api.get(attachment.download_url, { responseType: 'blob' })
  saveCompanyBlob(response.data, attachment.filename)
}

export function useConfirmAssistantAction() {
  return useMutation({ mutationFn: (token: string) => api.post('/v1/assistant/actions/confirm', { token }).then((response) => response.data) })
}

export async function transcribeAssistantVoice(recording: Blob) {
  const form = new FormData()
  form.append('file', recording, 'oyuns-question.webm')
  return api.post('/v1/voice/transcriptions', form).then((response) => response.data as { transcript: string })
}

export async function synthesizeAssistantSpeech(text: string): Promise<string | undefined> {
  const response = await api.post('/v1/assistant/speech', { text }, { responseType: 'blob', validateStatus: (status) => status === 200 || status === 204 })
  if (response.status === 204 || !response.data?.size) return undefined
  return URL.createObjectURL(response.data)
}

export interface UserProfile {
  username: string
  name: string
  employee_id: number | null
  telegram_username: string | null
  avatar_url: string | null
  locale: 'mn' | 'en' | 'ru'
  roles: string[]
  phone_number: string | null
  birthday: string | null
  work_direction: string | null
  work_branch: string | null
  telegram_connected: boolean
  requires_password_setup: boolean
}

export function useProfile() {
  return useQuery<UserProfile>({ queryKey: ['v1', 'profile'], queryFn: () => api.get('/v1/auth/profile').then((response) => response.data) })
}

export interface WorldClockPreferences {
  clocks: string[]
  display_mode: 'digital' | 'analog'
  hour_format: '12' | '24'
}

export function useWorldClockPreferences() {
  return useQuery<WorldClockPreferences>({
    queryKey: ['v1', 'auth', 'preferences', 'world-clock'],
    queryFn: () => api.get('/v1/auth/preferences/world-clock').then((response) => response.data),
  })
}

export type WorkspaceMode = 'member' | 'manager'
export interface WorkspaceModePreferences { mode: WorkspaceMode }
export const workspaceModeQueryKey = (accountId?: number | null) => ['v1', 'auth', 'preferences', 'workspace-mode', accountId ?? 'anonymous'] as const

export function useWorkspaceModePreferences(enabled = true) {
  const accountId = useAuthStore((state) => state.actor?.id)
  return useQuery<WorkspaceModePreferences>({
    queryKey: workspaceModeQueryKey(accountId),
    queryFn: () => api.get('/v1/auth/preferences/workspace-mode').then((response) => response.data),
    enabled,
  })
}

export function useUpdateWorkspaceModePreferences() {
  const queryClient = useQueryClient()
  const accountId = useAuthStore((state) => state.actor?.id)
  return useMutation({
    mutationFn: (input: WorkspaceModePreferences) => api.put('/v1/auth/preferences/workspace-mode', input).then((response) => response.data as WorkspaceModePreferences),
    onSuccess: (data) => queryClient.setQueryData(workspaceModeQueryKey(accountId), data),
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Ажлын горим хадгалагдсангүй'),
  })
}

export function useUpdateWorldClockPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: WorldClockPreferences) => api.put('/v1/auth/preferences/world-clock', input).then((response) => response.data as WorldClockPreferences),
    onSuccess: (data) => {
      queryClient.setQueryData(['v1', 'auth', 'preferences', 'world-clock'], data)
      toast.success('Цагийн тохиргоо хадгалагдлаа')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Цагийн тохиргоо хадгалагдсангүй'),
  })
}

export interface ChatNotificationPreferences { desktop_alerts_enabled: boolean; sound_enabled: boolean }
export function useChatNotificationPreferences(enabled = true) { return useQuery<ChatNotificationPreferences>({ queryKey: ['v1', 'auth', 'preferences', 'chat-notifications'], queryFn: () => api.get('/v1/auth/preferences/chat-notifications').then((response) => response.data), enabled }) }
export function useUpdateChatNotificationPreferences() { const qc = useQueryClient(); return useMutation({ mutationFn: (input: ChatNotificationPreferences) => api.put('/v1/auth/preferences/chat-notifications', input).then((response) => response.data as ChatNotificationPreferences), onSuccess: (data) => qc.setQueryData(['v1', 'auth', 'preferences', 'chat-notifications'], data), onError: (error: any) => toast.error(error.response?.data?.detail || 'Чатын мэдэгдлийн тохиргоо хадгалагдсангүй') }) }

export function useUpdateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { username?: string; avatar_url?: string | null; locale?: string; phone_number?: string | null; birthday?: string | null; work_direction?: string | null; work_branch?: string | null; current_password?: string }) => api.patch('/v1/auth/profile', input).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'profile'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'actor'] }); toast.success('Профайл хадгалагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Профайл хадгалагдсангүй'),
  })
}

export function useChangeProfilePassword() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { current_password?: string; new_password: string }) => api.patch('/v1/auth/profile/password', input).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'profile'] }); toast.success('Нууц үг хадгалагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Нууц үг хадгалагдсангүй'),
  })
}

export function useTelegramProfileLink() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (init_data: string) => api.post('/v1/auth/profile/telegram-link', null, { params: { init_data } }).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'profile'] }); toast.success('Telegram холбогдлоо') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Telegram холбогдсонгүй') })
}

export interface UserNotification {
  id: number
  kind: string
  title: string
  body: string
  target_url: string | null
  payload: Record<string, unknown>
  created_at: string
  read_at: string | null
  telegram_status: 'queued' | 'sent' | 'failed' | 'unavailable'
  is_priority: boolean
}

export interface NotificationPage {
  items: UserNotification[]
  unread_count: number
  next_cursor: number | null
}

export function useNotifications() {
  return useQuery<NotificationPage>({ queryKey: ['v1', 'notifications'], queryFn: () => api.get('/v1/notifications').then((response) => response.data) })
}

export function useReadNotification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post(`/v1/notifications/${id}/read`).then((response) => response.data),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['v1', 'notifications'] })
      const previous = queryClient.getQueryData<NotificationPage>(['v1', 'notifications'])
      queryClient.setQueryData<NotificationPage>(['v1', 'notifications'], (page) => !page ? page : { ...page, unread_count: Math.max(0, page.unread_count - (page.items.some((item) => item.id === id && !item.read_at) ? 1 : 0)), items: page.items.map((item) => item.id === id ? { ...item, read_at: item.read_at ?? new Date().toISOString() } : item) })
      return { previous }
    },
    onError: (_error, _id, context) => queryClient.setQueryData(['v1', 'notifications'], context?.previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['v1', 'notifications'] }),
  })
}

export function useReadAllNotifications() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/v1/notifications/read-all').then((response) => response.data),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['v1', 'notifications'] })
      const previous = queryClient.getQueryData<NotificationPage>(['v1', 'notifications'])
      queryClient.setQueryData<NotificationPage>(['v1', 'notifications'], (page) => !page ? page : { ...page, unread_count: 0, items: page.items.map((item) => ({ ...item, read_at: item.read_at ?? new Date().toISOString() })) })
      return { previous }
    },
    onError: (_error, _variables, context) => queryClient.setQueryData(['v1', 'notifications'], context?.previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['v1', 'notifications'] }),
  })
}

export function useToggleNotificationPriority() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, is_priority }: { id: number; is_priority: boolean }) => api.post(`/v1/notifications/${id}/priority`, { is_priority }).then((response) => response.data),
    onMutate: async ({ id, is_priority }) => {
      await queryClient.cancelQueries({ queryKey: ['v1', 'notifications'] })
      const previous = queryClient.getQueryData<NotificationPage>(['v1', 'notifications'])
      queryClient.setQueryData<NotificationPage>(['v1', 'notifications'], (page) => !page ? page : { ...page, items: page.items.map((item) => item.id === id ? { ...item, is_priority } : item) })
      return { previous }
    },
    onError: (_error, _variables, context) => queryClient.setQueryData(['v1', 'notifications'], context?.previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['v1', 'notifications'] }),
  })
}

export function useUploadAvatar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => { const body = new FormData(); body.append('file', file); return api.post('/v1/auth/profile/avatar', body).then((response) => response.data) },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'profile'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'actor'] }); toast.success('Профайл зураг хадгалагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Зураг хадгалагдсангүй'),
  })
}

export interface CompanyLibraryItem {
  id: number
  parent_id: number | null
  kind: 'folder' | 'file'
  name: string
  title: string
  extension: string | null
  searchable_metadata: Record<string, unknown>
  content_type: string | null
  size: number | null
  checksum: string | null
  uploaded_by_account_id: number | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface CompanyFilesPageData {
  current_folder: CompanyLibraryItem | null
  breadcrumbs: { id: number; name: string }[]
  items: CompanyLibraryItem[]
  folders: { id: number; parent_id: number | null; name: string }[]
  can_upload: boolean
  can_manage: boolean
  is_search: boolean
  is_trash: boolean
  search_status?: 'ok' | 'empty' | 'indexing' | 'partial' | 'denied' | 'unavailable' | null
  search_diagnostics?: Array<Record<string, unknown>>
  search_warnings?: string[]
}

export function useCompanyFiles(input: { parentId?: number; search?: string; sort?: string; trash?: boolean }) {
  return useQuery<CompanyFilesPageData>({
    queryKey: ['v1', 'company-files', input],
    queryFn: () => api.get('/v1/company-files', { params: { parent_id: input.parentId, q: input.search || undefined, sort: input.sort || 'name', trash: input.trash || undefined } }).then((response) => response.data),
  })
}

function useCompanyFilesMutation<T>(mutationFn: (input: T) => Promise<unknown>, successMessage: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'company-files'] }); toast.success(successMessage) },
    onError: (error: any) => {
      if (axios.isCancel(error)) return
      const detail = error?.response?.data?.detail
      const message = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : 'Үйлдэл амжилтгүй боллоо'
      toast.error(message)
    },
  })
}

export function useCreateCompanyFolder() {
  return useCompanyFilesMutation((input: { name: string; parent_id: number | null }) => api.post('/v1/company-files/folders', input).then((response) => response.data), 'Хавтас үүслээ')
}

export function useUploadCompanyFile() {
  return useCompanyFilesMutation((input: { files: File[]; parent_id: number | null; onProgress?: (percent: number) => void; signal?: AbortSignal }) => {
    const body = new FormData()
    const totalBytes = input.files.reduce((sum, file) => sum + file.size, 0)
    input.files.forEach((file) => body.append('files', file))
    return api.post('/v1/company-files/upload', body, {
      params: { parent_id: input.parent_id ?? undefined },
      signal: input.signal,
      timeout: 5 * 60 * 1000,
      onUploadProgress: (event) => {
        const total = event.total || totalBytes || 1
        const percent = Math.min(100, Math.round((event.loaded / total) * 100))
        input.onProgress?.(percent)
      },
    }).then((response) => response.data)
  }, 'Файл байршлаа')
}

export function useUpdateCompanyItem() {
  return useCompanyFilesMutation((input: { id: number; name?: string; parent_id?: number; move_to_root?: boolean }) => api.patch(`/v1/company-files/${input.id}`, { name: input.name, parent_id: input.parent_id, move_to_root: input.move_to_root || false }).then((response) => response.data), 'Файл сан шинэчлэгдлээ')
}

export function useTrashCompanyItem() {
  return useCompanyFilesMutation((id: number) => api.delete(`/v1/company-files/${id}`), 'Хогийн сав руу зөөлөө')
}

export function useRestoreCompanyItem() {
  return useCompanyFilesMutation((id: number) => api.post(`/v1/company-files/${id}/restore`).then((response) => response.data), 'Сэргээлээ')
}

export function useDeleteCompanyItemPermanently() {
  return useCompanyFilesMutation((id: number) => api.delete(`/v1/company-files/${id}/permanent`), 'Бүрмөсөн устгалаа')
}

export async function downloadCompanyFile(item: CompanyLibraryItem) {
  const response = await api.get(`/v1/company-files/${item.id}/download`, { responseType: 'blob' })
  saveCompanyBlob(response.data, item.name)
}

export function saveCompanyBlob(blob: Blob, name: string) {
  requireWebCapability('File downloads')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function downloadCompanyFolder(folder: CompanyLibraryItem, onProgress?: () => void) {
  const response = await api.get(`/v1/company-files/${folder.id}/archive`, { responseType: 'blob', timeout: 10 * 60 * 1000, onDownloadProgress: () => onProgress?.() })
  saveCompanyBlob(response.data, `${folder.name}.zip`)
}

export async function getCompanyFileBlob(item: CompanyLibraryItem) {
  return (await api.get(`/v1/company-files/${item.id}/download`, { responseType: 'blob' })).data as Blob
}

export async function getCompanyFilePreview(item: CompanyLibraryItem) {
  const response = await api.get(`/v1/company-files/${item.id}/preview`, { responseType: 'blob' })
  return { blob: response.data as Blob, truncated: response.headers['x-preview-truncated'] === 'true' }
}
