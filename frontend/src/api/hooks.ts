import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'

// --- Auth ---
export function useLogin() {
  return useMutation({
    mutationFn: (data: { email: string; password: string }) =>
      api.post<{ access_token: string }>('/auth/login', data).then((r) => r.data),
  })
}

// --- Admin access ---
export interface AdminUser {
  id: number
  email: string
  created_at: string | null
}
export function useAdminUsers() {
  return useQuery<AdminUser[]>({ queryKey: ['admin-users'], queryFn: () => api.get('/auth/admin-users').then((r) => r.data) })
}
export function useCreateAdminUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { email: string; password: string }) => api.post('/auth/admin-users', data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); toast.success('Админ эрх нэмэгдлээ') },
  })
}
export function useDeleteAdminUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/auth/admin-users/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); toast.success('Админ эрх цуцлагдлаа') },
  })
}
export function useChangeOwnPassword() {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) => api.put('/auth/me/password', data),
    onSuccess: () => toast.success('Нууц үг солигдлоо'),
  })
}

// --- Employees ---
export function useEmployees() {
  return useQuery({ queryKey: ['employees'], queryFn: () => api.get('/employees').then((r) => r.data) })
}
export function useCreateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.post('/employees', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Ажилтан нэмэгдлээ') },
    onError: () => toast.error('Нэмэхэд алдаа гарлаа'),
  })
}
export function useUpdateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/employees/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Хадгалагдлаа') },
  })
}
export function useDeleteEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/employees/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Устгагдлаа') },
  })
}

// --- Questions ---
export function useQuestions() {
  return useQuery({ queryKey: ['questions'], queryFn: () => api.get('/questions').then((r) => r.data) })
}
export function useCreateQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.post('/questions', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Асуулт нэмэгдлээ') },
  })
}
export function useUpdateQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/questions/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Хадгалагдлаа') },
  })
}
export function useDeleteQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/questions/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Устгагдлаа') },
  })
}
export function useReorderQuestions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: number[]) => api.put('/questions/reorder', { ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['questions'] }),
  })
}

// --- Schedules ---
export function useSchedules() {
  return useQuery({ queryKey: ['schedules'], queryFn: () => api.get('/schedules').then((r) => r.data) })
}
export function useUpdateSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ employee_id, ...d }: any) => api.put(`/schedules/${employee_id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedules'] }); toast.success('Хуваарь хадгалагдлаа') },
  })
}

// --- Dashboard ---
export function useDashboardSummary(period = 30) {
  return useQuery({ queryKey: ['dashboard', 'summary', period], queryFn: () => api.get(`/dashboard/summary?period=${period}`).then((r) => r.data) })
}
export function useDashboardMetrics(metric: string, period = 30) {
  return useQuery({ queryKey: ['dashboard', 'metrics', metric, period], queryFn: () => api.get(`/dashboard/metrics?metric=${metric}&period=${period}`).then((r) => r.data) })
}
export function useTopEmployees() {
  return useQuery({ queryKey: ['dashboard', 'top'], queryFn: () => api.get('/dashboard/top-employees').then((r) => r.data) })
}

// --- Journal ---
export function useAnswers(filters: { emp_id?: number; date_from?: string; date_to?: string } = {}) {
  const params = new URLSearchParams()
  if (filters.emp_id) params.set('emp_id', String(filters.emp_id))
  if (filters.date_from) params.set('date_from', filters.date_from)
  if (filters.date_to) params.set('date_to', filters.date_to)
  return useQuery({ queryKey: ['answers', filters], queryFn: () => api.get(`/answers?${params}`).then((r) => r.data) })
}

// --- Manager Settings ---
export function useManagerSettings() {
  return useQuery({ queryKey: ['manager-settings'], queryFn: () => api.get('/manager-settings').then((r) => r.data) })
}
export function useUpdateManagerSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.put('/manager-settings', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['manager-settings'] }); toast.success('Тохиргоо хадгалагдлаа') },
  })
}

// --- Onboarding ---
export function useOnboardingTemplate() {
  return useQuery({ queryKey: ['onboarding'], queryFn: () => api.get('/onboarding/template').then((r) => r.data) })
}
export function useUpdateOnboardingTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.put('/onboarding/template', d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); toast.success('Загвар хадгалагдлаа') },
  })
}

// --- Tasks ---
export interface TaskOut {
  id: number
  title: string
  description: string | null
  status: 'open' | 'in_progress' | 'done' | 'overdue' | 'cancelled'
  priority: 1 | 2 | 3
  deadline_at: string | null
  created_at: string | null
  completed_at: string | null
  assignee_id: number | null
  assignee_name: string | null
  created_by_id: number | null
  created_by_tg: string | null
  creator_name: string | null
  reminder_intervals_min: number[]
}

export function useTasks(filters: { status?: string; assignee_id?: number; active?: boolean } = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.assignee_id) params.set('assignee_id', String(filters.assignee_id))
  if (filters.active !== undefined) params.set('active', String(filters.active))
  return useQuery<TaskOut[]>({
    queryKey: ['tasks', filters],
    queryFn: () => api.get(`/tasks?${params}`).then((r) => r.data),
  })
}

export function useTask(id: number) {
  return useQuery<TaskOut>({
    queryKey: ['tasks', id],
    queryFn: () => api.get(`/tasks/${id}`).then((r) => r.data),
  })
}

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: { title: string; description?: string; assignee_id?: number; deadline_at?: string; priority: number }) =>
      api.post('/tasks', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }); toast.success('Даалгавар үүслээ') },
    onError: () => toast.error('Даалгавар үүсгэхэд алдаа гарлаа'),
  })
}

export function useUpdateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: { id: number; title?: string; description?: string; assignee_id?: number; deadline_at?: string; priority?: number; status?: string }) =>
      api.patch(`/tasks/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }); toast.success('Даалгавар шинэчлэгдлээ') },
    onError: () => toast.error('Даалгавар шинэчлэхэд алдаа гарлаа'),
  })
}

export function useTaskComments(taskId: number) {
  return useQuery({
    queryKey: ['tasks', taskId, 'comments'],
    queryFn: () => api.get(`/tasks/${taskId}/comments`).then((r) => r.data),
    enabled: taskId > 0,
  })
}

export function useAddTaskComment(taskId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => api.post(`/tasks/${taskId}/comments`, { text }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks', taskId, 'comments'] }),
  })
}
