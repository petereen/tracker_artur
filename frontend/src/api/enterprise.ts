import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { acceptSession, api, refreshAccessToken } from './client'
import { useAuthStore, Actor } from '../store/auth'

export type WorkflowStatus = 'backlog' | 'to_do' | 'in_progress' | 'review' | 'done' | 'cancelled'

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
  assignee_ids: number[]
  assignee_names: string[]
  project_name: string | null
  start_at: string | null
  deadline_at: string | null
  estimate_minutes: number | null
  work_location_type: 'office' | 'remote' | 'custom' | null
  work_location: string | null
  sort_position: number
  version: number
  is_archived: boolean
  is_overdue: boolean
  created_by_id: number | null
  creator_name?: string | null
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
}

export function useEnterpriseLogin() {
  return useMutation({
    mutationFn: (input: { email: string; password: string }) => api.post('/v1/auth/login', input).then((response) => response.data),
    onSuccess: acceptSession,
  })
}

export function useTelegramWidgetLogin() {
  return useMutation({
    mutationFn: (payload: Record<string, string | number>) => api.post('/v1/auth/telegram-widget', payload).then((response) => response.data),
    onSuccess: acceptSession,
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
    mutationFn: () => api.get('/v1/integrations/google-calendar/connect').then((response) => response.data),
  })
}

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
  return useMutation({ mutationFn: () => api.post('/v1/auth/logout'), onSettled: () => logout() })
}

export interface DateRange { date_from: string; date_to: string }

export function useEnterpriseSummary(period?: DateRange, employeeId?: number) {
  return useQuery({ queryKey: ['v1', 'analytics', period, employeeId], queryFn: () => api.get('/v1/analytics/summary', { params: { ...period, ...(employeeId ? { employee_id: employeeId } : {}) } }).then((response) => response.data) })
}

export function useClock(enabled = true) {
  return useQuery<{ active: ClockEntry | null; today_entries: ClockEntry[]; timezone: string; server_time: string }>({ queryKey: ['v1', 'clock'], queryFn: () => api.get('/v1/clock/status').then((response) => response.data), enabled, refetchInterval: enabled ? 30_000 : false })
}

export function useClockAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ action, mode }: { action: 'start' | 'break' | 'resume' | 'stop'; mode?: 'in_person' | 'remote' }) => api.post(`/v1/clock/${action}`, action === 'start' ? { mode } : {}).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'clock'] }),
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Цагийн төлөв өөрчлөгдсөнгүй'),
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

export function useDeadlines(enabled = true) {
  return useQuery<any[]>({ queryKey: ['v1', 'deadlines'], queryFn: () => api.get('/v1/deadlines').then((response) => response.data), enabled })
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
    onSettled: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }) },
  })
}

export function useDeleteEnterpriseTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/v1/tasks/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); toast.success('Даалгавар устгагдлаа') },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Даалгавар устгагдсангүй'),
  })
}

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

export interface PersonalTimeBlock { id: number; title: string; starts_at: string; ends_at: string; task_id: number | null; version: number }

export function useCalendarEvents(scope: 'private' | 'corporate', period: DateRange) {
  return useQuery<any>({ queryKey: ['v1', 'calendar', scope, period], queryFn: () => api.get('/v1/calendar/events', { params: { scope, ...period } }).then((response) => response.data) })
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
  return useMutation({ mutationFn: (input: Record<string, unknown>) => api.post('/v1/calendar/entries', input).then((response) => response.data), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'calendar'] }); queryClient.invalidateQueries({ queryKey: ['v1', 'today'] }); toast.success('Календарийн зүйл хадгалагдлаа') }, onError: (error: any) => toast.error(error.response?.data?.detail || 'Календарийн зүйл хадгалагдсангүй') })
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

export interface WorkerDirectoryItem {
  id: number
  name: string
  job_title: string | null
  telegram_username: string | null
  avatar_url: string | null
  presence: 'offline' | 'in_person' | 'remote' | 'break'
}

export function useWorkerDirectory() {
  return useQuery<WorkerDirectoryItem[]>({ queryKey: ['v1', 'workers'], queryFn: () => api.get('/v1/workers').then((response) => response.data), refetchInterval: 30_000 })
}

export function useWorkerPerformance(employeeId?: number, period?: DateRange, enabled = true) {
  return useQuery<any>({ queryKey: ['v1', 'workers', employeeId, 'performance', period], queryFn: () => api.get(`/v1/workers/${employeeId}/performance`, { params: period }).then((response) => response.data), enabled: Boolean(employeeId) && enabled })
}

export function useWorkerProfile(employeeId?: number) {
  return useQuery<any>({ queryKey: ['v1', 'workers', employeeId, 'profile'], queryFn: () => api.get(`/v1/auth/workers/${employeeId}/profile`).then((response) => response.data), enabled: Boolean(employeeId) })
}

export function useAssistantDraft() {
  return useMutation({ mutationFn: (input: { text: string; kind: 'task' | 'report' }) => api.post('/v1/assistant/drafts', input).then((response) => response.data) })
}

export function useAssistantChat() {
  return useMutation({ mutationFn: (input: { text: string; conversation_id?: number }) => api.post('/v1/assistant/conversations', input).then((response) => response.data) })
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
  can_manage: boolean
  is_search: boolean
  is_trash: boolean
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
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Үйлдэл амжилтгүй боллоо'),
  })
}

export function useCreateCompanyFolder() {
  return useCompanyFilesMutation((input: { name: string; parent_id: number | null }) => api.post('/v1/company-files/folders', input).then((response) => response.data), 'Хавтас үүслээ')
}

export function useUploadCompanyFile() {
  return useCompanyFilesMutation((input: { files: File[]; parent_id: number | null; onProgress?: (percent: number) => void }) => {
    const body = new FormData()
    const totalBytes = input.files.reduce((sum, file) => sum + file.size, 0)
    input.files.forEach((file) => body.append('file', file))
    return api.post('/v1/company-files/upload', body, {
      params: { parent_id: input.parent_id ?? undefined },
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
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = item.name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
