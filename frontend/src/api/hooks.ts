import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'
import i18n from '../i18n'

// --- Auth ---
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); toast.success(i18n.t('api.admin.added')) },
  })
}
export function useDeleteAdminUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/auth/admin-users/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); toast.success(i18n.t('api.admin.revoked')) },
  })
}
export function useChangeOwnPassword() {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) => api.put('/auth/me/password', data),
    onSuccess: () => toast.success(i18n.t('api.password.changed')),
  })
}

// --- Employees ---
export function useEmployees(includeArchived = false) {
  return useQuery({ queryKey: ['employees', { includeArchived }], queryFn: () => api.get('/employees', { params: { include_archived: includeArchived } }).then((r) => r.data) })
}
export function useEmployeePerformance(employeeId: number | null, filters: DateRangeFilters = {}) {
  const params = dashboardParams(filters)
  return useQuery({
    queryKey: ['employees', employeeId, 'performance', filters],
    queryFn: () => api.get(`/employees/${employeeId}/performance?${params}`).then((r) => r.data),
    enabled: employeeId !== null,
  })
}
export function useCreateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.post('/employees', d).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees'] })
      qc.invalidateQueries({ queryKey: ['v1', 'hr'] })
      qc.invalidateQueries({ queryKey: ['v1', 'workers'] })
      toast.success(i18n.t('api.employee.added'))
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      toast.error((typeof detail === 'object' ? detail?.message : detail) || i18n.t('api.addFailed'))
    },
  })
}
export function useUpdateEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/employees/${id}`, d).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees'] })
      qc.invalidateQueries({ queryKey: ['v1', 'hr'] })
      qc.invalidateQueries({ queryKey: ['v1', 'workers'] })
      toast.success(i18n.t('api.saved'))
    },
  })
}
export function useDeleteEmployee() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/employees/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees'] })
      qc.invalidateQueries({ queryKey: ['v1', 'hr'] })
      qc.invalidateQueries({ queryKey: ['v1', 'workers'] })
      toast.success(i18n.t('api.deleted'))
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || i18n.t('api.employee.notDeleted')),
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success(i18n.t('api.question.added')) },
  })
}
export function useUpdateQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: any) => api.put(`/questions/${id}`, d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success(i18n.t('api.saved')) },
  })
}
export function useDeleteQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/questions/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['questions'] }); toast.success(i18n.t('api.deleted')) },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['schedules'] }); toast.success(i18n.t('api.schedule.saved')) },
  })
}

// --- Dashboard ---
export interface DateRangeFilters { period?: number; date_from?: string; date_to?: string; all_time?: boolean }
function dashboardParams(filters: DateRangeFilters) {
  const params = new URLSearchParams()
  params.set('period', String(filters.period ?? 30))
  if (filters.date_from) params.set('date_from', filters.date_from)
  if (filters.date_to) params.set('date_to', filters.date_to)
  if (filters.all_time) params.set('all_time', 'true')
  return params
}

// --- Journal ---

export interface WorkReportOut {
  id: number
  employee_id: number
  employee_name: string
  report_type: 'daily' | 'monthly' | 'next_month_plan'
  period_date: string
  status: 'awaiting' | 'draft' | 'editing' | 'approved'
  started_at: string | null
  ended_at: string | null
  work_time?: {
    total_minutes: number
    remote_minutes: number
    in_person_minutes: number
    entries: { id: number; mode: 'remote' | 'in_person'; started_at: string; ended_at: string | null; minutes: number; open: boolean }[]
  }
  text: string | null
  latest_revision_status: 'draft' | 'superseded' | 'deleted' | 'approved' | null
  approved_revision_id: number | null
  created_at: string
  updated_at: string
  revisions?: { id: number; text: string; status: string; created_at: string; updated_at: string }[]
}
export function useWorkReport(reportId: number | null) {
  return useQuery<WorkReportOut & { revisions: NonNullable<WorkReportOut['revisions']> }>({
    queryKey: ['work-report', reportId],
    queryFn: () => api.get(`/work-reports/${reportId}`).then((r) => r.data),
    enabled: reportId !== null,
  })
}

export type PlanHorizon = 'long_term' | 'mid_term' | 'short_term'
export interface CompanyPlanItem {
  id: number; plan_month: string; title: string; content: string | null; horizon: PlanHorizon; position: number
  status: 'approved' | 'archived'; due_date: string | null; source_employee_id: number | null; source_employee_name: string | null; source_report_id: number | null; source_idea_ids: number[]
  approved_at: string; created_at: string; updated_at: string
}
export interface PlanSuggestion {
  id: number; employee_id: number; employee_name: string; period_date: string; text: string | null
  created_at: string; updated_at: string; company_plan_item_count: number
}
export function useCompanyPlan(month: string) {
  return useQuery<CompanyPlanItem[]>({ queryKey: ['company-plan', month], queryFn: () => api.get(`/company-plans?month=${month}`).then((r) => r.data) })
}
export function useCreateCompanyPlanItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { source_report_id?: number; title: string; content?: string; plan_month: string; horizon: PlanHorizon; due_date?: string | null }) => api.post('/company-plans/items', data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['company-plan'] }); qc.invalidateQueries({ queryKey: ['company-plan-suggestions'] }); toast.success(i18n.t('api.plan.addedToCompany')) },
  })
}

export interface PlanIdea { id: number; plan_month: string; title: string; content: string | null; suggested_due_date: string | null; status: 'pending' | 'approved' | 'rejected' | 'merged'; submitted_by_name: string | null; merged_into_plan_item_id: number | null; source_report_id: number | null; created_at: string; updated_at: string }
export function usePlanIdeas(month: string) { return useQuery<PlanIdea[]>({ queryKey: ['plan-ideas', month], queryFn: () => api.get('/company-plans/ideas', { params: { month } }).then((r) => r.data) }) }
export function useCreatePlanIdea() { const qc = useQueryClient(); return useMutation({ mutationFn: (data: { plan_month: string; title: string; content?: string; suggested_due_date?: string | null }) => api.post('/company-plans/ideas', data).then((r) => r.data), onSuccess: () => { qc.invalidateQueries({ queryKey: ['plan-ideas'] }); toast.success(i18n.t('api.idea.sent')) } }) }
export function useUpdatePlanIdea() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, ...data }: { id: number; title?: string; content?: string; suggested_due_date?: string | null; status?: string }) => api.patch(`/company-plans/ideas/${id}`, data).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['plan-ideas'] }) }) }
export function useDeletePlanIdea() { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.delete(`/company-plans/ideas/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['plan-ideas'] }) }) }
export function useMergePlanIdeas() { const qc = useQueryClient(); return useMutation({ mutationFn: (data: { idea_ids: number[]; plan_month: string; title: string; content?: string; horizon: PlanHorizon; due_date?: string | null }) => api.post('/company-plans/ideas/merge', data).then((r) => r.data), onSuccess: () => { qc.invalidateQueries({ queryKey: ['plan-ideas'] }); qc.invalidateQueries({ queryKey: ['company-plan'] }); toast.success(i18n.t('api.idea.merged')) } }) }
export function useUpdateCompanyPlanItem() { const qc = useQueryClient(); return useMutation({ mutationFn: ({ id, ...data }: { id: number; title?: string; content?: string; horizon?: PlanHorizon; due_date?: string | null }) => api.patch(`/company-plans/items/${id}`, data).then((r) => r.data), onSuccess: () => qc.invalidateQueries({ queryKey: ['company-plan'] }) }) }
export function useDeleteCompanyPlanItem() { const qc = useQueryClient(); return useMutation({ mutationFn: (id: number) => api.delete(`/company-plans/items/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['company-plan'] }) }) }
export function useReorderCompanyPlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { plan_month: string; columns: Record<PlanHorizon, number[]> }) => api.put('/company-plans/reorder', data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['company-plan'] }),
    onError: () => toast.error(i18n.t('api.plan.orderNotSaved')),
  })
}

// --- Manager Settings ---
export function useManagerSettings() {
  return useQuery({ queryKey: ['manager-settings'], queryFn: () => api.get('/manager-settings').then((r) => r.data) })
}
export interface ManagerRecipientOption {
  employee_id: number
  name: string
  telegram_id: string
  telegram_username: string | null
  job_title: string | null
  department: string | null
  role: string | null
}

/** Workers with a connected Telegram account, for the management recipient picker. */
export function useManagerRecipientOptions() {
  return useQuery<ManagerRecipientOption[]>({
    queryKey: ['manager-settings', 'recipient-options'],
    queryFn: () => api.get('/manager-settings/recipient-options').then((r) => r.data),
  })
}

export function useUpdateManagerSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: any) => api.put('/manager-settings', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['manager-settings'] }); toast.success(i18n.t('api.settings.saved')) },
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['onboarding'] }); toast.success(i18n.t('api.template.saved')) },
  })
}

// --- Company Knowledge ---
export interface KnowledgeEntry {
  id: number
  title: string
  category: string | null
  content: string
  attachment_filename: string | null
  attachment_content_type: string | null
  attachment_size: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface KnowledgeInput {
  title: string
  category?: string | null
  content: string
  is_active: boolean
}

export function useKnowledge() {
  return useQuery<KnowledgeEntry[]>({
    queryKey: ['knowledge'],
    queryFn: () => api.get('/knowledge').then((r) => r.data),
  })
}

export function useCreateKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: KnowledgeInput) => api.post('/knowledge', data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.knowledge.added'))
    },
    onError: () => toast.error(i18n.t('api.knowledge.addFailed')),
  })
}

export function useCreateKnowledgeWithAttachment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ data, file }: { data: KnowledgeInput; file: File }) => {
      const body = new FormData()
      body.append('title', data.title)
      body.append('category', data.category || '')
      body.append('content', data.content)
      body.append('is_active', String(data.is_active))
      body.append('file', file)
      return api.post('/knowledge/upload', body).then((r) => r.data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.knowledge.addedWithFile'))
    },
    onError: () => toast.error(i18n.t('api.attachFailed')),
  })
}

export function useUpdateKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: KnowledgeInput & { id: number }) =>
      api.put(`/knowledge/${id}`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.knowledge.saved'))
    },
    onError: () => toast.error(i18n.t('api.knowledge.saveFailed')),
  })
}

export function useDeleteKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/knowledge/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.knowledge.deleted'))
    },
    onError: () => toast.error(i18n.t('api.knowledge.deleteFailed')),
  })
}

export function useReplaceKnowledgeAttachment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => {
      const body = new FormData()
      body.append('file', file)
      return api.post(`/knowledge/${id}/attachment`, body).then((r) => r.data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.attached'))
    },
    onError: () => toast.error(i18n.t('api.attachFailed')),
  })
}

export function useDeleteKnowledgeAttachment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/knowledge/${id}/attachment`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      toast.success(i18n.t('api.attachment.deleted'))
    },
    onError: () => toast.error(i18n.t('api.attachment.deleteFailed')),
  })
}

// --- OYUNS developer learning ---
export type AssistantContextIntent = 'create_task_draft' | 'get_user_tasks' | 'search_company_knowledge'

export interface UnknownAssistantRequest {
  id: number
  text: string
  language: string
  channel: string
  terms: string[]
  reason: string
  occurrence_count: number
  status: 'pending' | 'reviewed' | 'dismissed'
  created_at: string
  last_seen_at: string
}

export interface AssistantContextExample {
  id: number
  phrase: string
  intent: AssistantContextIntent
  meaning: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AssistantContextInput {
  phrase: string
  intent: AssistantContextIntent
  meaning: string
  is_active: boolean
}

export function useUnknownAssistantRequests() {
  return useQuery<UnknownAssistantRequest[]>({
    queryKey: ['assistant-learning', 'unknown'],
    queryFn: () => api.get('/assistant-learning/unknown').then((r) => r.data),
  })
}

export function useAssistantContextExamples() {
  return useQuery<AssistantContextExample[]>({
    queryKey: ['assistant-learning', 'contexts'],
    queryFn: () => api.get('/assistant-learning/contexts').then((r) => r.data),
  })
}

export function useUpdateUnknownAssistantRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: UnknownAssistantRequest['status'] }) =>
      api.put(`/assistant-learning/unknown/${id}`, { status }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assistant-learning', 'unknown'] })
      toast.success(i18n.t('api.request.statusUpdated'))
    },
    onError: () => toast.error(i18n.t('api.request.statusFailed')),
  })
}

export function usePromoteUnknownAssistantRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: AssistantContextInput & { id: number }) =>
      api.post(`/assistant-learning/unknown/${id}/promote-context`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assistant-learning'] })
      toast.success(i18n.t('api.context.addedGlossary'))
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || i18n.t('api.context.addFailed')),
  })
}

export function useCreateAssistantContextExample() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AssistantContextInput) => api.post('/assistant-learning/contexts', data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assistant-learning', 'contexts'] })
      toast.success(i18n.t('api.context.added'))
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || i18n.t('api.context.addFailed')),
  })
}

export function useUpdateAssistantContextExample() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: AssistantContextInput & { id: number }) =>
      api.put(`/assistant-learning/contexts/${id}`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assistant-learning', 'contexts'] })
      toast.success(i18n.t('api.context.saved'))
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || i18n.t('api.context.saveFailed')),
  })
}

export function useDeleteAssistantContextExample() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/assistant-learning/contexts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assistant-learning', 'contexts'] })
      toast.success(i18n.t('api.context.deleted'))
    },
    onError: () => toast.error(i18n.t('api.context.deleteFailed')),
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
