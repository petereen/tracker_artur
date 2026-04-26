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

// --- Employees ---
export function useEmployees() {
  return useQuery({ queryKey: ['employees'], queryFn: () => api.get('/employees').then((r) => r.data) })
}
export function useCreateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.post('/employees', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Сотрудник добавлен') },
    onError: () => toast.error('Ошибка при добавлении'),
  })
}
export function useUpdateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/employees/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Сохранено') },
  })
}
export function useDeleteEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/employees/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['employees'] }); toast.success('Удалено') },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Вопрос добавлен') },
  })
}
export function useUpdateQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/questions/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Сохранено') },
  })
}
export function useDeleteQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/questions/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success('Удалено') },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedules'] }); toast.success('Расписание сохранено') },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['manager-settings'] }); toast.success('Настройки сохранены') },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); toast.success('Шаблон сохранён') },
  })
}
