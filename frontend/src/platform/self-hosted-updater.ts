import { CapacitorUpdater } from '@capgo/capacitor-updater'
import { getApiBaseUrl, getNativeApiOrigin, isNativePlatform, nativePlatform } from './runtime'
import { addTelemetryBreadcrumb, captureTelemetryException } from './telemetry'

const APP_ID = 'mn.oyuns.workspace'
const UPDATE_CHANNEL = import.meta.env.VITE_OTA_CHANNEL === 'staging' ? 'staging' : 'production'
let checkPromise: Promise<void> | null = null

type UpdateDescriptor = {
  version: string
  url: string
  checksum: string
  size: number
  channel: string
}

type UpdateCheckResponse = { update: UpdateDescriptor | null }

function record(message: string, level: 'info' | 'warning' | 'error' = 'info') {
  addTelemetryBreadcrumb({ category: 'ota.self-hosted', message, level: level === 'warning' ? 'warning' : level })
}

function trustedBundleUrl(value: string) {
  const url = new URL(value)
  const sameApiHost = url.host === new URL(getNativeApiOrigin()).host
  if (url.protocol !== 'https:' || !sameApiHost || !url.pathname.startsWith('/api/v1/mobile-updates/bundles/') || url.pathname.includes('..')) {
    throw new Error('Self-hosted OTA returned an untrusted bundle URL')
  }
  return url.toString()
}

export async function checkSelfHostedUpdate(): Promise<void> {
  if (!isNativePlatform()) return
  if (checkPromise) return checkPromise

  checkPromise = (async () => {
    const platform = nativePlatform()
    if (!platform) return

    const current = await CapacitorUpdater.current()
    const currentVersion = current.bundle?.version || 'builtin'
    const response = await fetch(`${getApiBaseUrl()}/v1/mobile-updates/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_id: APP_ID,
        channel: UPDATE_CHANNEL,
        platform,
        current_version: currentVersion,
      }),
    })
    if (!response.ok) throw new Error(`Self-hosted OTA check failed (${response.status})`)

    const payload = (await response.json()) as UpdateCheckResponse
    if (!payload.update) return

    const update = payload.update
    record(`updateAvailable:${update.version}`)
    const bundle = await CapacitorUpdater.download({
      url: trustedBundleUrl(update.url),
      version: update.version,
      checksum: update.checksum,
    })
    await CapacitorUpdater.next({ id: bundle.id })
    record(`updateQueued:${update.version}`)
  })()
    .catch((error) => {
      record('updateCheckFailed', 'warning')
      captureTelemetryException(error)
    })
    .finally(() => {
      checkPromise = null
    })

  return checkPromise
}
