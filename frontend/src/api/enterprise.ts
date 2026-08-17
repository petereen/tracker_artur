import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import toast from 'react-hot-toast'
import { acceptSession, api, refreshAccessToken } from './client'
import { useAuthStore, Actor } from '../store/auth'

export type WorkflowStatus = 'backlog' | 'to_do' | 'in_progress' | 'review' | 'done' | 'cancelled'
export type SearchEntityType = 'task' | 'worker' | 'file'
export interface GlobalSearchResult {
  id: number
  type: SearchEntityType
  title: string
  subtitle: string | null
  score: number
  metadata: { status?: WorkflowStatus; assignee?: string | null; project?: string | null; avatar_url?: string | null; role?: string | null; presence?: string; kind?: 'file' | 'folder'; size?: number | null; parent_id?: number | null }
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
  estimate_minutes: number | null
  work_location_type: 'office' | 'remote' | 'custom' | null
  work_location: string | null
  sort_position: number
  version: number
  is_archived: boolean
  is_overdue: boolean
  created_by_id: number | null
  creator_name?: string | null
  can_manage_collaboration?: boolean
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

export interface TaskDependency { id: number; predecessor_task_id: number; predecessor_title: string | null; successor_task_id: number; dependency_type: 'blocks' | 'related'; relation_type: 'blocks' | 'related'; direction: 'blocked_by' | 'related'; related_task_id: number; related_task_title: string | null }
export interface TaskCheckItem { id: number; task_id: number; text: string; is_completed: boolean; assignee_id: number | null; position: number; completed_at: string | null }
export interface TaskComment { id: number; task_id: number; author_account_id?: number; author_employee_id?: number; author_name?: string | null; author_avatar_url?: string | null; text: string; mentions: number[]; is_resolved: boolean; edited_at?: string | null; created_at: string }
export interface EnterpriseAttachment { id: number; filename: string; content_type: string; size: number; checksum: string; scan_status: string; created_at: string }
export interface TaskActivity { id: number; action: string; entity_type: string; actor_account_id: number | null; actor_employee_id: number | null; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string }
export interface SavedView { id: number; module: string; name: string; view_type: string; filters: Record<string, unknown>; grouping: Record<string, unknown>; visible_columns: string[]; sort: Record<string, unknown>[]; is_shared: boolean }

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
export interface CalendarConnectionStatus { provider: 'google'; status: string; sync_mode: 'outbound' | 'bidirectional'; configured: boolean; calendar_id?: string; watch_active?: boolean; watch_expires_at?: string | null; last_synced_at?: string | null; last_error?: string | null; sync_failure_count?: number }
export function useGoogleCalendarStatus() { return useQuery<CalendarConnectionStatus>({ queryKey: ['v1', 'integrations', 'google-calendar'], queryFn: () => api.get('/v1/integrations/google-calendar/status').then((r) => r.data) }) }
export function useGoogleCalendarSyncMode() { const qc = useQueryClient(); return useMutation({ mutationFn: (sync_mode: 'outbound' | 'bidirectional') => api.put('/v1/integrations/google-calendar/sync-mode', { sync_mode }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }) }) }
export function useGoogleCalendarDisconnect() { const qc = useQueryClient(); return useMutation({ mutationFn: () => api.post('/v1/integrations/google-calendar/disconnect'), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'integrations', 'google-calendar'] }) }) }

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

const invalidateTaskDetail = (queryClient: ReturnType<typeof useQueryClient>, id: number) => {
  queryClient.invalidateQueries({ queryKey: ['v1', 'tasks', id] })
  queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] })
}

export function useTaskDependencies(id?: number) { return useQuery<TaskDependency[]>({ queryKey: ['v1', 'tasks', id, 'dependencies'], queryFn: () => api.get(`/v1/tasks/${id}/dependencies`).then((r) => r.data), enabled: Boolean(id) }) }
export function useAddTaskDependency() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, predecessor_task_id, dependency_type }: { taskId: number; predecessor_task_id: number; dependency_type: 'blocks' | 'related' }) => api.post(`/v1/tasks/${taskId}/dependencies`, { predecessor_task_id, dependency_type }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Хамаарал хадгалагдсангүй') }) }
export function useDeleteTaskDependency() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/dependencies/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId) }) }

export function useTaskCheckItems(id?: number) { return useQuery<TaskCheckItem[]>({ queryKey: ['v1', 'tasks', id, 'check-items'], queryFn: () => api.get(`/v1/tasks/${id}/check-items`).then((r) => r.data), enabled: Boolean(id) }) }
export function useAddTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, text }: { taskId: number; text: string }) => api.post(`/v1/tasks/${taskId}/check-items`, { text, position: Date.now() }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist хадгалагдсангүй') }) }
export function useUpdateTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id, ...input }: { taskId: number; id: number; text?: string; is_completed?: boolean }) => api.patch(`/v1/tasks/${taskId}/check-items/${id}`, input).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist шинэчлэгдсэнгүй') }) }
export function useDeleteTaskCheckItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/check-items/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Checklist устгагдсангүй') }) }

export function useTaskComments(id?: number) { return useQuery<TaskComment[]>({ queryKey: ['v1', 'tasks', id, 'comments'], queryFn: () => api.get(`/v1/tasks/${id}/comments`).then((r) => r.data), enabled: Boolean(id) }) }
export function useAddTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, text, mentions = [] }: { taskId: number; text: string; mentions?: number[] }) => api.post(`/v1/tasks/${taskId}/comments`, { text, mentions }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Сэтгэгдэл хадгалагдсангүй') }) }
export function useResolveTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id, is_resolved }: { taskId: number; id: number; is_resolved: boolean }) => api.patch(`/v1/tasks/${taskId}/comments/${id}`, { is_resolved }).then((r) => r.data), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId) }) }
export function useDeleteTaskComment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ taskId, id }: { taskId: number; id: number }) => api.delete(`/v1/tasks/${taskId}/comments/${id}`), onSuccess: (_d, v) => invalidateTaskDetail(qc, v.taskId), onError: (e: any) => toast.error(e.response?.data?.detail || 'Сэтгэгдэл устгагдсангүй') }) }

export function useAttachments(objectType: 'task' | 'report', objectId?: number) { return useQuery<EnterpriseAttachment[]>({ queryKey: ['v1', 'attachments', objectType, objectId], queryFn: () => api.get('/v1/attachments', { params: { object_type: objectType, object_id: objectId } }).then((r) => r.data), enabled: Boolean(objectId) }) }
export function useUploadAttachment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ objectType, objectId, file, onProgress }: { objectType: 'task' | 'report'; objectId: number; file: File; onProgress?: (value: number) => void }) => { const form = new FormData(); form.append('file', file); return api.post('/v1/attachments', form, { params: { object_type: objectType, object_id: objectId }, onUploadProgress: (event) => onProgress?.(event.total ? Math.round(event.loaded * 100 / event.total) : 0) }).then((r) => r.data) }, onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ['v1', 'attachments', v.objectType, v.objectId] }); if (v.objectType === 'task') invalidateTaskDetail(qc, v.objectId) }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Файл байршуулсангүй') }) }
export function useDeleteAttachment() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id }: { id: number; objectType: 'task' | 'report'; objectId: number }) => api.delete(`/v1/attachments/${id}`), onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ['v1', 'attachments', v.objectType, v.objectId] }); if (v.objectType === 'task') invalidateTaskDetail(qc, v.objectId) }, onError: (e: any) => toast.error(e.response?.data?.detail || 'Файл устгагдсангүй') }) }
export async function downloadAttachment(id: number, filename: string) { const response = await api.get(`/v1/attachments/${id}/download`, { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url) }

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
export interface ERPMasterRequest { id: number; operation: 'party' | 'item'; definition_version: number; workflow_state: string; payload: Record<string, unknown>; scope: ERPAssignmentScope; version: number; materialized_entity_type?: string | null; materialized_entity_id?: number | null }
export interface ERPDocumentLineInput { item_id?: number; warehouse_id?: number; account_id?: number; description: string; quantity?: string | number; rate?: string | number; tax_rate?: string | number; data?: Record<string, unknown> }
export interface ERPDocument { id: number; public_id: string; document_type: string; number: string; status: string; party_id: number | null; project_id: number | null; source_document_id: number | null; amended_from_id: number | null; currency: string; exchange_rate: string; posting_date: string; due_date: string | null; net_total: string; tax_total: string; grand_total: string; outstanding_amount: string; payload: Record<string, unknown>; custom: Record<string, unknown>; version: number; lines?: ERPDocumentLineInput[] }
export interface ERPDashboard { currency: string; revenue: string; expenses: string; profit: string; cash_collected: string; inventory_value: string; open_customer_queries: number; payroll_total: string; production_cost: string; upcoming_maintenance: number }

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
export function useCreateERPMasterRequest(operation: 'party' | 'item') { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { payload: Record<string, unknown>; custom: Record<string, unknown>; scope?: ERPAssignmentScope }) => api.post(`/v1/erp/master-requests/${operation}`, input).then((r) => r.data as ERPMasterRequest), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useTransitionERPMasterRequest() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, ...input }: { id: number; to_state: string; version: number; comment?: string }) => api.post(`/v1/erp/master-requests/by-id/${id}/transition`, input).then((r) => r.data as ERPMasterRequest), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useUpdateERPModules() { const qc = useQueryClient(); return useMutation({ mutationFn: (modules: Record<ERPModule, boolean>) => api.put('/v1/erp/admin/modules', { modules }).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp'] }) }) }
export function useERPDocuments(documentType: string, enabled = true) { return useQuery<ERPDocument[]>({ queryKey: ['v1', 'erp', 'documents', documentType], queryFn: () => api.get(`/v1/erp/documents/${documentType}`).then((r) => r.data), enabled: enabled && Boolean(documentType), retry: false }) }
export function useCreateERPDocument(documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (input: { party_id?: number; due_date?: string; payload?: Record<string, unknown>; custom?: Record<string, unknown>; lines?: ERPDocumentLineInput[] }) => api.post(`/v1/erp/documents/${documentType}`, input, { headers: { 'Idempotency-Key': crypto.randomUUID() } }).then((r) => r.data as ERPDocument), onSuccess: () => qc.invalidateQueries({ queryKey: ['v1', 'erp', 'documents', documentType] }) }) }
export function useSubmitERPDocument(documentType: string) { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.post(`/v1/erp/documents/by-id/${id}/submit`).then((r) => r.data as ERPDocument), onSuccess: () => { qc.invalidateQueries({ queryKey: ['v1', 'erp'] }); qc.invalidateQueries({ queryKey: ['v1', 'erp', 'documents', documentType] }) } }) }
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
  can_upload: boolean
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
