import { App } from '@capacitor/app'
import { Capacitor, type PluginListenerHandle } from '@capacitor/core'
import { api, acceptSession } from '../api/client'
import i18n from '../i18n'

const CALLBACK_HOST = 'erp.oyuns.mn'
const CALLBACK_PATH = '/mobile-auth/telegram/callback'

export type NativeTelegramAuthState =
  | { status: 'idle' }
  | { status: 'opening' }
  | { status: 'waiting' }
  | { status: 'success' }
  | { status: 'cancelled' }
  | { status: 'error'; message: string }

type AuthSubscriber = (state: NativeTelegramAuthState) => void

let listener: PluginListenerHandle | null = null
let stateListener: PluginListenerHandle | null = null
let launchChecked = false
let exchangeInFlight = false
let currentState: NativeTelegramAuthState = { status: 'idle' }
const subscribers = new Set<AuthSubscriber>()

function emit(state: NativeTelegramAuthState) {
  currentState = state
  subscribers.forEach((subscriber) => subscriber(state))
}

function callbackParams(url: string) {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  if (parsed.protocol !== 'https:' || parsed.hostname !== CALLBACK_HOST || parsed.pathname !== CALLBACK_PATH) return null
  return parsed.searchParams
}

export function isNativeTelegramCallbackUrl(url: string) {
  return callbackParams(url) !== null
}

async function consumeCallback(url: string) {
  const params = callbackParams(url)
  if (!params) return false
  const providerError = params.get('error')
  if (providerError) {
    emit({ status: providerError === 'access_denied' ? 'cancelled' : 'error', message: i18n.t(providerError === 'access_denied' ? 'auth.telegram.cancelledNative' : 'auth.telegram.provider_error') })
    return true
  }
  const code = params.get('code')
  const state = params.get('state')
  if (!code || !state) {
    emit({ status: 'error', message: i18n.t('auth.telegram.badCallback') })
    return true
  }
  if (exchangeInFlight) return true
  exchangeInFlight = true
  emit({ status: 'waiting' })
  try {
    const { data } = await api.post('/v1/auth/telegram-native/exchange', { code, state })
    await acceptSession(data)
    emit({ status: 'success' })
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    emit({ status: 'error', message: typeof detail === 'string' ? detail : i18n.t('auth.telegram.provider_error') })
  } finally {
    exchangeInFlight = false
  }
  return true
}

export function subscribeToNativeTelegramAuth(subscriber: AuthSubscriber) {
  subscribers.add(subscriber)
  subscriber(currentState)
  return () => { subscribers.delete(subscriber) }
}

export async function startNativeTelegramLogin() {
  if (!Capacitor.isNativePlatform()) {
    emit({ status: 'error', message: i18n.t('auth.telegram.nativeOnly') })
    return
  }
  emit({ status: 'opening' })
  try {
    const platform = Capacitor.getPlatform()
    if (platform !== 'ios' && platform !== 'android') throw new Error('Unsupported native platform')
    const { data } = await api.post('/v1/auth/telegram-native/start', { platform })
    emit({ status: 'waiting' })
    // Hand the URL to the system, not to an in-app browser: an in-app browser keeps the
    // callback redirect to itself and signs in the web app there instead of returning to
    // this one. Capacitor opens a top-level navigation to another host with the OS
    // (iOS UIApplication.open / Android ACTION_VIEW), so Telegram's app link opens the
    // Telegram app when it is installed and the callback App Link brings the user back here.
    window.location.assign(data.authorization_url)
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    emit({ status: 'error', message: typeof detail === 'string' ? detail : i18n.t('auth.telegram.startFailed') })
  }
}

export async function installNativeTelegramAuth() {
  if (!Capacitor.isNativePlatform() || listener) return () => undefined
  listener = await App.addListener('appUrlOpen', ({ url }) => { void consumeCallback(url) })
  // Coming back without a callback (the person backed out of Telegram) must not leave the button stuck on "waiting".
  stateListener = await App.addListener('appStateChange', ({ isActive }) => {
    if (!isActive) return
    window.setTimeout(() => { if (currentState.status === 'waiting' && !exchangeInFlight) emit({ status: 'idle' }) }, 1500)
  })
  if (!launchChecked) {
    launchChecked = true
    const launch = await App.getLaunchUrl()
    if (launch?.url) await consumeCallback(launch.url)
  }
  return () => {
    listener?.remove()
    listener = null
    stateListener?.remove()
    stateListener = null
  }
}
