import { Capacitor, type PluginListenerHandle } from '@capacitor/core'
import { PushNotifications, type PermissionStatus } from '@capacitor/push-notifications'
import * as Sentry from '@sentry/react'
import { api } from '../api/client'
import { readSecureValue, removeSecureValue, writeSecureValue } from './secure-session'
import { isNativePlatform, nativePlatform } from './runtime'

export type NotificationPermissionState = 'prompt' | 'granted' | 'denied' | 'unsupported'
export type NativePushRegistration = {
  platform: 'ios' | 'android'
  provider: 'apns' | 'fcm'
  token: string
}
export type NativeNotificationEvent =
  | { type: 'permission'; state: NotificationPermissionState }
  | { type: 'received' }
  | { type: 'action'; targetUrl?: string }
  | { type: 'registration-error' }

export interface NotificationService {
  initialize(): Promise<void>
  getPermissionState(): Promise<NotificationPermissionState>
  requestPermissionAndRegister(): Promise<NotificationPermissionState>
  syncExistingRegistration(): Promise<void>
  unregister(): Promise<void>
  subscribeToEvents(listener: (event: NativeNotificationEvent) => void): () => void
}

const REGISTRATION_KEY = 'native_push_registration'
const PENDING_REVOCATION_KEY = 'native_push_pending_revocation'

function mapPermission(status: PermissionStatus): NotificationPermissionState {
  if (status.receive === 'granted') return 'granted'
  if (status.receive === 'denied') return 'denied'
  return 'prompt'
}

function isSafeInternalTarget(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
}

class CapacitorNotificationService implements NotificationService {
  private initialization: Promise<void> | null = null
  private listeners: PluginListenerHandle[] = []
  private subscribers = new Set<(event: NativeNotificationEvent) => void>()

  private emit(event: NativeNotificationEvent) {
    this.subscribers.forEach((listener) => listener(event))
  }

  private async registrationFor(token: string): Promise<NativePushRegistration | null> {
    const platform = nativePlatform()
    if (!platform) return null
    return { platform, provider: platform === 'ios' ? 'apns' : 'fcm', token }
  }

  private async revoke(registration: NativePushRegistration) {
    await api.delete('/v1/mobile/push-registration', { data: registration })
  }

  private async retryPendingRevocation() {
    const pending = await readSecureValue(PENDING_REVOCATION_KEY)
    if (!pending) return
    try {
      await this.revoke(JSON.parse(pending) as NativePushRegistration)
      await removeSecureValue(PENDING_REVOCATION_KEY)
    } catch {
      // Retry on the next authenticated registration when connectivity returns.
    }
  }

  private async enroll(token: string) {
    const registration = await this.registrationFor(token)
    if (!registration) return
    await this.retryPendingRevocation()
    await api.put('/v1/mobile/push-registration', registration)
    await writeSecureValue(REGISTRATION_KEY, JSON.stringify(registration))
    Sentry.addBreadcrumb({ category: 'native.push', message: 'Push registration synchronized', level: 'info' })
  }

  async initialize() {
    if (!isNativePlatform()) return
    if (!this.initialization) {
      this.initialization = (async () => {
        this.listeners = await Promise.all([
          PushNotifications.addListener('registration', ({ value }) => {
            void this.enroll(value).catch(() => this.emit({ type: 'registration-error' }))
          }),
          PushNotifications.addListener('registrationError', () => {
            Sentry.addBreadcrumb({ category: 'native.push', message: 'Native push registration failed', level: 'error' })
            this.emit({ type: 'registration-error' })
          }),
          PushNotifications.addListener('pushNotificationReceived', () => this.emit({ type: 'received' })),
          PushNotifications.addListener('pushNotificationActionPerformed', ({ notification }) => {
            const targetUrl = notification.data?.target_url
            this.emit({ type: 'action', ...(isSafeInternalTarget(targetUrl) ? { targetUrl } : {}) })
          }),
        ])
        if (Capacitor.getPlatform() === 'android') {
          await PushNotifications.createChannel({
            id: 'oyuns-default',
            name: 'OYUNS Workspace',
            description: 'Workspace notifications',
            importance: 4,
            visibility: 1,
          })
        }
      })()
    }
    await this.initialization
  }

  async getPermissionState() {
    if (!isNativePlatform()) return 'unsupported'
    await this.initialize()
    const state = mapPermission(await PushNotifications.checkPermissions())
    this.emit({ type: 'permission', state })
    return state
  }

  async requestPermissionAndRegister() {
    if (!isNativePlatform()) return 'unsupported'
    await this.initialize()
    const current = mapPermission(await PushNotifications.checkPermissions())
    const state = current === 'prompt' ? mapPermission(await PushNotifications.requestPermissions()) : current
    this.emit({ type: 'permission', state })
    if (state === 'granted') await PushNotifications.register()
    return state
  }

  async syncExistingRegistration() {
    if (!isNativePlatform()) return
    await this.initialize()
    if (await this.getPermissionState() === 'granted') await PushNotifications.register()
  }

  async unregister() {
    if (!isNativePlatform()) return
    const encoded = await readSecureValue(REGISTRATION_KEY)
    if (encoded) {
      const registration = JSON.parse(encoded) as NativePushRegistration
      try {
        await this.revoke(registration)
        await removeSecureValue(PENDING_REVOCATION_KEY)
      } catch {
        await writeSecureValue(PENDING_REVOCATION_KEY, encoded)
      }
    }
    await PushNotifications.unregister()
    await removeSecureValue(REGISTRATION_KEY)
  }

  subscribeToEvents(listener: (event: NativeNotificationEvent) => void) {
    this.subscribers.add(listener)
    return () => this.subscribers.delete(listener)
  }
}

export const notificationService: NotificationService = new CapacitorNotificationService()
