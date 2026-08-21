import { Component, type ErrorInfo, type ReactNode, useLayoutEffect } from 'react'
import type { PluginListenerHandle } from '@capacitor/core'
import { App } from '@capacitor/app'
import { CapacitorUpdater } from '@capgo/capacitor-updater'
import * as Sentry from '@sentry/react'
import { isNativePlatform } from './runtime'
import { checkSelfHostedUpdate } from './self-hosted-updater'

let listenersPromise: Promise<PluginListenerHandle[]> | null = null
let readinessPromise: Promise<unknown> | null = null
let lifecyclePromise: Promise<PluginListenerHandle> | null = null

function recordUpdaterEvent(eventName: string) {
  Sentry.addBreadcrumb({
    category: 'ota.lifecycle',
    message: eventName,
    level: eventName.toLowerCase().includes('failed') ? 'error' : 'info',
  })
}

function attachUpdaterListeners() {
  if (!listenersPromise) {
    listenersPromise = Promise.all([
      CapacitorUpdater.addListener('updateAvailable', () => recordUpdaterEvent('updateAvailable')),
      CapacitorUpdater.addListener('downloadComplete', () => recordUpdaterEvent('downloadComplete')),
      CapacitorUpdater.addListener('setNext', () => recordUpdaterEvent('setNext')),
      CapacitorUpdater.addListener('set', () => recordUpdaterEvent('set')),
      CapacitorUpdater.addListener('downloadFailed', () => recordUpdaterEvent('downloadFailed')),
      CapacitorUpdater.addListener('updateFailed', () => recordUpdaterEvent('updateFailed')),
      CapacitorUpdater.addListener('appReady', () => recordUpdaterEvent('appReady')),
    ])
  }
  return listenersPromise
}

function attachSelfHostedUpdaterLifecycle() {
  if (!lifecyclePromise) {
    lifecyclePromise = App.addListener('resume', () => {
      void checkSelfHostedUpdate()
    })
  }
  return lifecyclePromise
}

function NativeReadySignal({ children }: { children: ReactNode }) {
  useLayoutEffect(() => {
    if (!isNativePlatform()) return
    let timer: number | undefined
    let cancelled = false
    void attachUpdaterListeners().then(() => {
      if (!readinessPromise) readinessPromise = CapacitorUpdater.notifyAppReady()
      return readinessPromise
    }).then(() => {
      if (cancelled) return
      void checkSelfHostedUpdate()
      void attachSelfHostedUpdaterLifecycle()
      timer = window.setInterval(() => void checkSelfHostedUpdate(), 60 * 60 * 1000)
    }).catch((error) => Sentry.captureException(error))
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [])
  return children
}

class BootErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, { contexts: { react: { componentStack: info.componentStack } } })
  }

  render() {
    if (this.state.failed) {
      return <main className="native-boot-error" role="alert"><h1>Аппыг эхлүүлж чадсангүй</h1><p>Аппыг хаагаад дахин нээнэ үү.</p></main>
    }
    return this.props.children
  }
}

export function NativeBootBoundary({ children }: { children: ReactNode }) {
  if (!isNativePlatform()) return children
  return <BootErrorBoundary><NativeReadySignal>{children}</NativeReadySignal></BootErrorBoundary>
}
