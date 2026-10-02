import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { api } from './client'
import i18n from '../i18n'

/** Tenant-wide rule for one notification category (admin settings). */
export interface TenantNotificationCategory {
  key: string
  label: string
  description: string
  legacy: boolean
  enabled: boolean
  web: boolean
  telegram: boolean
  user_editable: boolean
}

export interface TenantNotificationSettings { categories: TenantNotificationCategory[] }
export type TenantNotificationInput = { categories: Record<string, Partial<Pick<TenantNotificationCategory, 'enabled' | 'web' | 'telegram' | 'user_editable'>>> }

/** A category as the signed-in user sees it (profile). */
export interface PersonalNotificationCategory {
  key: string
  label: string
  description: string
  available: boolean
  editable: boolean
  web: boolean
  telegram: boolean
  default_web: boolean
  default_telegram: boolean
}

export interface PersonalNotificationPreferences {
  categories: PersonalNotificationCategory[]
  telegram_linked: boolean
  telegram_bot_connected: boolean
}
export type PersonalNotificationInput = { categories: Record<string, { web?: boolean; telegram?: boolean }> }

const tenantKey = ['v1', 'settings', 'notifications'] as const
const personalKey = ['v1', 'auth', 'preferences', 'notifications'] as const

export function useTenantNotificationSettings(enabled = true) {
  return useQuery<TenantNotificationSettings>({ queryKey: tenantKey, queryFn: () => api.get('/v1/settings/notifications').then((response) => response.data), enabled })
}

export function useUpdateTenantNotificationSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: TenantNotificationInput) => api.put('/v1/settings/notifications', input).then((response) => response.data as TenantNotificationSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(tenantKey, data)
      queryClient.invalidateQueries({ queryKey: personalKey })
      toast.success(i18n.t('st.api.notifSaved'))
    },
    onError: () => toast.error(i18n.t('st.api.notifNotSaved')),
  })
}

export function usePersonalNotificationPreferences(enabled = true) {
  return useQuery<PersonalNotificationPreferences>({ queryKey: personalKey, queryFn: () => api.get('/v1/auth/preferences/notifications').then((response) => response.data), enabled })
}

export function useUpdatePersonalNotificationPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: PersonalNotificationInput) => api.put('/v1/auth/preferences/notifications', input).then((response) => response.data as PersonalNotificationPreferences),
    onSuccess: (data) => queryClient.setQueryData(personalKey, data),
    onError: () => toast.error(i18n.t('st.api.notifNotSaved')),
  })
}
