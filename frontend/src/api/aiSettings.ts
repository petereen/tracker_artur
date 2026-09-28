import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'

export type ReasoningEffort = 'none' | 'low' | 'medium' | 'high'
export type AiKeySource = 'organization' | 'environment' | 'none'

export interface AiAgentSettings {
  has_key: boolean
  key_last4: string | null
  key_source: AiKeySource
  env_key_available: boolean
  primary_model: string
  fallback_model: string | null
  reasoning_effort: ReasoningEffort
  max_output_tokens: number
  web_search_enabled: boolean
  /** Realtime model and voice for live voice calls with OYUNS. */
  realtime_model?: string
  realtime_voice?: string
  realtime_enabled?: boolean
  realtime_voices?: string[]
  defaults: { primary_model: string; fallback_model: string | null; reasoning_effort: ReasoningEffort; max_output_tokens: number; realtime_model?: string; realtime_voice?: string }
  limits: { min_output_tokens: number; max_output_tokens: number }
  updated_at: string | null
}

export interface AiAgentSettingsInput {
  api_key?: string | null
  clear_api_key?: boolean
  primary_model?: string
  fallback_model?: string
  reasoning_effort?: ReasoningEffort
  max_output_tokens?: number
  web_search_enabled?: boolean
  realtime_model?: string
  realtime_voice?: string
  realtime_enabled?: boolean
}

export interface AiConnectionTest {
  ok: boolean
  error: string | null
  latency_ms: number | null
  model: string | null
  model_listed?: boolean
  detail?: string
}

const SETTINGS_KEY = ['v1', 'settings', 'ai-agent']

export function useAiAgentSettings(enabled = true) {
  return useQuery<AiAgentSettings>({ queryKey: SETTINGS_KEY, queryFn: () => api.get('/v1/settings/ai-agent').then((response) => response.data), enabled })
}

export function useAiModels(enabled = true) {
  return useQuery<{ models: string[]; realtime_models?: string[]; error: string | null }>({
    queryKey: [...SETTINGS_KEY, 'models'],
    queryFn: () => api.get('/v1/settings/ai-agent/models').then((response) => response.data),
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useUpdateAiAgentSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: AiAgentSettingsInput) => api.put('/v1/settings/ai-agent', input).then((response) => response.data as AiAgentSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(SETTINGS_KEY, data)
      queryClient.invalidateQueries({ queryKey: [...SETTINGS_KEY, 'models'] })
      toast.success('AI тохиргоо хадгалагдлаа')
    },
    onError: (error: any) => toast.error(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'AI тохиргоо хадгалагдсангүй'),
  })
}

export function useTestAiConnection() {
  return useMutation({
    mutationFn: (input: { api_key?: string | null; model?: string | null }) => api.post('/v1/settings/ai-agent/test', input).then((response) => response.data as AiConnectionTest),
  })
}
