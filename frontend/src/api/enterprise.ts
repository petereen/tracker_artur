import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'
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
  start_at: string | null
  deadline_at: string | null
  estimate_minutes: number | null
  sort_position: number
  version: number
  is_archived: boolean
  is_overdue: boolean
}

export interface Project {
  id: number
  public_id: string
  client_id: number | null
  manager_id: number | null
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
}

export interface ClockEntry {
  id: number
  employee_id: number
  project_id: number | null
  task_id: number | null
  entry_type: 'work' | 'break'
  mode: 'in_person' | 'remote' | null
  started_at: string
  ended_at: string | null
}

export function useEnterpriseLogin() {
  const setToken = useAuthStore((state) => state.setToken)
  return useMutation({
    mutationFn: (input: { email: string; password: string }) => api.post('/v1/auth/login', input).then((response) => response.data),
    onSuccess: (data) => setToken(data.access_token),
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
    mutationFn: (input: { email: string; password: string; roles: string[]; locale: string }) => api.post('/v1/auth/accounts', input).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'accounts'] }),
  })
}

export function useUpdateManagedAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: { id: number; username?: string; password?: string; roles?: string[]; status?: 'active' | 'disabled' }) => api.patch(`/v1/auth/accounts/${id}`, input).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'accounts'] }),
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
    const { data } = await api.post('/v1/auth/refresh')
    store.setToken(data.access_token)
  } catch {
    store.setToken(null)
  } finally {
    store.setInitialized(true)
  }
}

export function useActor(enabled = true) {
  const setActor = useAuthStore((state) => state.setActor)
  return useQuery<Actor>({
    queryKey: ['v1', 'actor'],
    queryFn: () => api.get('/v1/auth/me').then((response) => {
      setActor(response.data)
      return response.data
    }),
    enabled,
  })
}

export function useEnterpriseLogout() {
  const logout = useAuthStore((state) => state.logout)
  return useMutation({ mutationFn: () => api.post('/v1/auth/logout'), onSettled: () => logout() })
}

export function useEnterpriseSummary() {
  return useQuery({ queryKey: ['v1', 'analytics'], queryFn: () => api.get('/v1/analytics/summary').then((response) => response.data) })
}

export function useClock() {
  return useQuery<{ active: ClockEntry | null; server_time: string }>({ queryKey: ['v1', 'clock'], queryFn: () => api.get('/v1/clock/status').then((response) => response.data), refetchInterval: 30_000 })
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
  })
}

export function useEnterpriseTasks(projectId?: number) {
  return useQuery<EnterpriseTask[]>({ queryKey: ['v1', 'tasks', projectId], queryFn: () => api.get('/v1/tasks', { params: projectId ? { project_id: projectId } : {} }).then((response) => response.data) })
}

export function useCreateEnterpriseTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Record<string, unknown>) => api.post('/v1/tasks', input, { headers: { 'Idempotency-Key': crypto.randomUUID() } }).then((response) => response.data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }); toast.success('Даалгавар үүслээ') },
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
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['v1', 'tasks'] }),
  })
}

export function useCapacity() {
  return useQuery<any[]>({ queryKey: ['v1', 'capacity'], queryFn: () => api.get('/v1/capacity').then((response) => response.data) })
}

export function useObjectives() {
  return useQuery<any[]>({ queryKey: ['v1', 'objectives'], queryFn: () => api.get('/v1/objectives').then((response) => response.data) })
}

export function useEnterpriseReports(status?: string) {
  return useQuery<any[]>({ queryKey: ['v1', 'reports', status], queryFn: () => api.get('/v1/reports', { params: status ? { status } : {} }).then((response) => response.data) })
}

export function useReportReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'approve' | 'request-revision' | 'submit' }) => api.post(`/v1/reports/${id}/${action}`).then((response) => response.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['v1', 'reports'] }),
  })
}
