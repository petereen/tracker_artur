import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'
import i18n from '../i18n'

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
  /** Chimege Mongolian STT/TTS: tokens are write-only, like the OpenAI key. */
  chimege?: ChimegeSettings
  /** Voice call engine: `auto` = Chimege for Mongolian, OpenAI Realtime otherwise. */
  voice_call_provider?: VoiceCallProvider
  voice_call_providers?: VoiceCallProvider[]
  /** ElevenLabs streaming TTS + Scribe STT; the key is write-only. */
  elevenlabs?: ElevenLabsSettings
  defaults: { primary_model: string; fallback_model: string | null; reasoning_effort: ReasoningEffort; max_output_tokens: number; realtime_model?: string; realtime_voice?: string }
  limits: { min_output_tokens: number; max_output_tokens: number }
  updated_at: string | null
}

export type VoiceCallProvider = 'auto' | 'openai' | 'chimege' | 'elevenlabs'

export interface ElevenLabsSettings {
  has_key: boolean
  key_last4: string | null
  source: AiKeySource
  enabled: boolean
  ready: boolean
  voice_id: string
  model: string
  models: string[]
  default_voice_id: string
}

export interface ElevenLabsVoice { voice_id: string; name: string; category?: string | null; description?: string | null }

export interface ElevenLabsTestResult { ok: boolean; error: string | null; latency_ms: number | null; voices: number }

export interface ChimegeTokenState {
  has_token: boolean
  token_last4: string | null
  source: AiKeySource
  enabled: boolean
}

export interface ChimegeSettings {
  stt: ChimegeTokenState
  tts: ChimegeTokenState
  voice_call_enabled: boolean
  voice_call_ready: boolean
}

export interface ChimegeTestResult {
  tts: { ok: boolean | null; error: string | null; latency_ms?: number }
  stt: { ok: boolean | null; error: string | null; transcript?: string | null; latency_ms?: number }
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
  chimege_stt_token?: string | null
  chimege_tts_token?: string | null
  clear_chimege_stt_token?: boolean
  clear_chimege_tts_token?: boolean
  chimege_stt_enabled?: boolean
  chimege_tts_enabled?: boolean
  chimege_voice_call_enabled?: boolean
  voice_call_provider?: VoiceCallProvider
  elevenlabs_api_key?: string | null
  clear_elevenlabs_api_key?: boolean
  elevenlabs_enabled?: boolean
  elevenlabs_voice_id?: string
  elevenlabs_model?: string
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
      queryClient.invalidateQueries({ queryKey: [...SETTINGS_KEY, 'elevenlabs-voices'] })
      toast.success(i18n.t('st.api.aiSaved'))
    },
    onError: (error: any) => toast.error(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : i18n.t('st.api.aiNotSaved')),
  })
}

export function useTestAiConnection() {
  return useMutation({
    mutationFn: (input: { api_key?: string | null; model?: string | null }) => api.post('/v1/settings/ai-agent/test', input).then((response) => response.data as AiConnectionTest),
  })
}

export function useTestChimege() {
  return useMutation({
    mutationFn: (input: { stt_token?: string | null; tts_token?: string | null }) => api.post('/v1/settings/ai-agent/chimege/test', input, { timeout: 90_000 }).then((response) => response.data as ChimegeTestResult),
  })
}

export function useElevenLabsVoices(enabled = true) {
  return useQuery<{ voices: ElevenLabsVoice[]; error: string | null }>({
    queryKey: [...SETTINGS_KEY, 'elevenlabs-voices'],
    queryFn: () => api.get('/v1/settings/ai-agent/elevenlabs/voices').then((response) => response.data),
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useTestElevenLabs() {
  return useMutation({
    mutationFn: (input: { api_key?: string | null }) => api.post('/v1/settings/ai-agent/elevenlabs/test', input, { timeout: 60_000 }).then((response) => response.data as ElevenLabsTestResult),
  })
}

export interface AiAccessEntry { read: boolean; write: boolean }
export interface AiAccessSection { key: string; label: string; description: string; has_write: boolean }
export interface AiAccessGroup { key: string; label: string; sections: AiAccessSection[] }
export interface AiAccessSettings {
  groups: AiAccessGroup[]
  sections: Record<string, AiAccessEntry>
  configured: boolean
  updated_at: string | null
}

const ACCESS_KEY = [...SETTINGS_KEY, 'access']

export function useAiAccessSettings(enabled = true) {
  return useQuery<AiAccessSettings>({ queryKey: ACCESS_KEY, queryFn: () => api.get('/v1/settings/ai-agent/access').then((response) => response.data), enabled })
}

export function useUpdateAiAccessSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sections: Record<string, AiAccessEntry>) => api.put('/v1/settings/ai-agent/access', { sections }).then((response) => response.data as AiAccessSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(ACCESS_KEY, data)
      toast.success(i18n.t('st.api.aiAccessSaved'))
    },
    onError: (error: any) => toast.error(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : i18n.t('st.api.aiAccessNotSaved')),
  })
}
