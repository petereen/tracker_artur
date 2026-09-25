import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'
import { requireWebCapability } from '../platform/runtime'

export type ReportType = 'daily' | 'monthly' | 'next_month_plan'
export type ReportGroupBy = 'worker' | 'department'
export type ReportScope = 'all' | 'employee' | 'department'

export interface ReportInsightScope {
  employees: Array<{ id: number; name: string; department_id: number | null; department: string | null; is_active: boolean }>
  departments: Array<{ id: number; name: string }>
}

export interface ReportExportParams {
  date_from: string
  date_to: string
  group_by: ReportGroupBy
  employee_ids: number[]
  department_ids: number[]
  report_types: ReportType[]
  approved_only: boolean
}

export interface ReportExportPreview {
  report_count: number
  format: 'zip' | 'md' | null
  groups: Array<{ name: string; count: number }>
}

export interface ReportSummaryInput {
  date_from: string
  date_to: string
  scope: ReportScope
  employee_id?: number
  department_id?: number
  report_types: ReportType[]
  prompt?: string
  history?: Array<{ role: 'user' | 'assistant'; content: string }>
}

export interface ReportSummaryResult {
  answer: string
  degraded: boolean
  scope_label: string
  date_from: string
  date_to: string
  report_count: number
  reports_in_context: number
  kpis: Partial<Record<'employees' | 'tasks_due' | 'tasks_completed' | 'tasks_overdue_open' | 'worked_minutes' | 'reports' | 'reports_submitted' | 'task_completion_rate' | 'report_submission_rate', number>>
}

// FastAPI reads repeated keys (?employee_ids=1&employee_ids=2), not axios' default brackets.
const repeatKeys = { indexes: null } as const

export function useReportInsightScope(enabled = true) {
  return useQuery<ReportInsightScope>({ queryKey: ['v1', 'report-insights', 'scope'], queryFn: () => api.get('/v1/report-insights/scope').then((response) => response.data), enabled, staleTime: 60_000 })
}

export function useReportExportPreview(params: ReportExportParams, enabled = true) {
  return useQuery<ReportExportPreview>({
    queryKey: ['v1', 'report-insights', 'preview', params],
    queryFn: ({ signal }) => api.get('/v1/report-insights/export/preview', { params, paramsSerializer: repeatKeys, signal }).then((response) => response.data),
    enabled,
    placeholderData: keepPreviousData,
  })
}

function filenameFrom(disposition: string | undefined, fallback: string) {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) { try { return decodeURIComponent(encoded) } catch { /* fall through */ } }
  return disposition?.match(/filename="?([^";]+)"?/i)?.[1] || fallback
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadReportExport(params: ReportExportParams) {
  requireWebCapability('File downloads')
  const response = await api.get('/v1/report-insights/export', { params, paramsSerializer: repeatKeys, responseType: 'blob' })
  const filename = filenameFrom(response.headers['content-disposition'], `reports_${params.date_from}_${params.date_to}.zip`)
  saveBlob(response.data, filename)
  return { filename, count: Number(response.headers['x-report-count'] || 0) }
}

export function useReportSummary() {
  return useMutation<ReportSummaryResult, any, ReportSummaryInput>({
    mutationFn: (input) => api.post('/v1/report-insights/summary', input).then((response) => response.data),
  })
}
