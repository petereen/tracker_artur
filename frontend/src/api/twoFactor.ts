import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { acceptSession, api, refreshAccessToken } from './client'

export interface TwoFactorEnrolment {
  secret: string
  otpauth_uri: string
  issuer: string
  account: string
}

interface VerifiedSession {
  access_token: string
  expires_in: number
  recovery_codes?: string[]
  recovery_codes_left?: number
}

export interface TwoFactorSettings {
  required: boolean
  accounts: number
  enrolled: number
}

export function twoFactorErrorCode(error: unknown): string | undefined {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return detail && typeof detail === 'object' ? (detail as { code?: string }).code : undefined
}

export function useTwoFactorEnrolment() {
  return useQuery<TwoFactorEnrolment>({
    queryKey: ['v1', 'two-factor', 'setup'],
    queryFn: () => api.post('/v1/auth/2fa/setup').then((response) => response.data),
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  })
}

async function submitCode(step: 'enable' | 'verify', code: string): Promise<VerifiedSession> {
  const send = () => api.post(`/v1/auth/2fa/${step}`, { code }).then((response) => response.data as VerifiedSession)
  let data: VerifiedSession
  try {
    data = await send()
  } catch (error) {
    // The access token outlived its (rotated) session: take a fresh one and retry once.
    if (twoFactorErrorCode(error) !== 'session_refresh_required') throw error
    await refreshAccessToken()
    data = await send()
  }
  // The new access token says the session passed the second factor.
  await acceptSession(data, { preserveIdentity: true })
  return data
}

export function useTwoFactorCode(step: 'enable' | 'verify') {
  return useMutation({ mutationFn: (code: string) => submitCode(step, code) })
}

const settingsKey = ['v1', 'settings', 'two-factor']

export function useTwoFactorSettings(enabled = true) {
  return useQuery<TwoFactorSettings>({ queryKey: settingsKey, queryFn: () => api.get('/v1/settings/two-factor').then((response) => response.data), enabled })
}

export function useUpdateTwoFactorSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (required: boolean) => api.put('/v1/settings/two-factor', { required }).then((response) => response.data as TwoFactorSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKey, data)
      // Switching it on gates this very session: re-read what it now owes.
      void queryClient.invalidateQueries({ queryKey: ['v1', 'actor'] })
    },
  })
}

export function useResetAccountTwoFactor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (accountId: number) => api.post(`/v1/auth/accounts/${accountId}/two-factor/reset`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['v1', 'accounts'] })
      void queryClient.invalidateQueries({ queryKey: settingsKey })
      void queryClient.invalidateQueries({ queryKey: ['v1', 'actor'] })
    },
  })
}
