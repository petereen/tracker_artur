import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'

// Separate axios instance for Telegram Mini App — sends X-Telegram-Init-Data, NOT Bearer
export const miniApi = axios.create({ baseURL: '/api' })

function getInitData(): string {
  try {
    return (window as any).Telegram?.WebApp?.initData ?? ''
  } catch {
    return ''
  }
}

miniApi.interceptors.request.use((config) => {
  const initData = getInitData()
  if (initData) config.headers['X-Telegram-Init-Data'] = initData
  return config
})

export interface MiniAppMe {
  employee_id: number | null
  name: string
  is_manager: boolean
}

export type TaskScope = 'mine' | 'assigned' | 'created' | 'all'

export interface MiniTaskOut {
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

export function useMiniMe() {
  return useQuery<MiniAppMe>({
    queryKey: ['miniapp', 'me'],
    queryFn: () => miniApi.get('/miniapp/me').then((r) => r.data),
    retry: 1,
  })
}

export function useMiniTasks(scope: TaskScope = 'mine', includeDone = true) {
  return useQuery<MiniTaskOut[]>({
    queryKey: ['miniapp', 'tasks', scope, includeDone],
    queryFn: () =>
      miniApi.get(`/miniapp/tasks?scope=${scope}&include_done=${includeDone}`).then((r) => r.data),
    retry: 1,
  })
}

export function useMiniCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (d: { title: string; description?: string; assignee_id?: number; deadline_at?: string; priority: number }) =>
      miniApi.post('/miniapp/tasks', d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['miniapp', 'tasks'] }); toast.success('Задача создана') },
    onError: () => toast.error('Ошибка при создании'),
  })
}

export function useMiniUpdateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...d }: { id: number; status?: string; deadline_at?: string }) =>
      miniApi.patch(`/miniapp/tasks/${id}`, d).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['miniapp', 'tasks'] }),
    onError: () => toast.error('Ошибка при обновлении'),
  })
}
