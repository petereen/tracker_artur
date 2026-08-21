import { App } from '@capacitor/app'
import { Browser } from '@capacitor/browser'
import { Capacitor, type PluginListenerHandle } from '@capacitor/core'
import { api, acceptSession } from '../api/client'

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
    await Browser.close().catch(() => undefined)
    emit({ status: providerError === 'access_denied' ? 'cancelled' : 'error', message: providerError === 'access_denied' ? 'Telegram нэвтрэлтийг цуцаллаа.' : 'Telegram нэвтрэлт амжилтгүй боллоо.' })
    return true
  }
  const code = params.get('code')
  const state = params.get('state')
  if (!code || !state) {
    emit({ status: 'error', message: 'Telegram нэвтрэлтийн буцаах холбоос буруу байна.' })
    return true
  }
  if (exchangeInFlight) return true
  exchangeInFlight = true
  emit({ status: 'waiting' })
  try {
    const { data } = await api.post('/v1/auth/telegram-native/exchange', { code, state })
    await acceptSession(data)
    await Browser.close().catch(() => undefined)
    emit({ status: 'success' })
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    emit({ status: 'error', message: typeof detail === 'string' ? detail : 'Telegram нэвтрэлт амжилтгүй боллоо.' })
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
    emit({ status: 'error', message: 'Telegram нэвтрэлт зөвхөн native апп-д боломжтой.' })
    return
  }
  emit({ status: 'opening' })
  try {
    const platform = Capacitor.getPlatform()
    if (platform !== 'ios' && platform !== 'android') throw new Error('Unsupported native platform')
    const { data } = await api.post('/v1/auth/telegram-native/start', { platform })
    emit({ status: 'waiting' })
    await Browser.open({ url: data.authorization_url })
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    emit({ status: 'error', message: typeof detail === 'string' ? detail : 'Telegram нэвтрэлт эхлүүлж чадсангүй.' })
  }
}

export async function installNativeTelegramAuth() {
  if (!Capacitor.isNativePlatform() || listener) return () => undefined
  listener = await App.addListener('appUrlOpen', ({ url }) => { void consumeCallback(url) })
  if (!launchChecked) {
    launchChecked = true
    const launch = await App.getLaunchUrl()
    if (launch?.url) await consumeCallback(launch.url)
  }
  return () => {
    listener?.remove()
    listener = null
  }
}
