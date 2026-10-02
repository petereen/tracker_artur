import { registerPlugin } from '@capacitor/core'
import { getNativeCapabilities } from './native-capabilities'
import { getApiBaseUrl, isNativePlatform, nativePlatform } from './runtime'
import { addTelemetryBreadcrumb } from './telemetry'

/**
 * Office geofences on the phone. The native layer only registers the areas
 * and reports transitions with its own device credential; whether the clock
 * starts or stops is decided by the server.
 */
export type GeofencePermission = 'always' | 'when_in_use' | 'denied' | 'prompt'

export type GeofenceStatus = {
  enrolled: boolean
  permission: GeofencePermission
  accuracy: 'precise' | 'approximate'
  monitoring: boolean
  regions: number
  pendingEvents: number
  batteryUnrestricted: boolean
  mode: 'off' | 'shadow' | 'on'
  lastUploadAt: string | null
  lastError: string | null
}

interface GeofencePlugin {
  getStatus(): Promise<GeofenceStatus>
  requestPermissions(options: { background: boolean }): Promise<GeofenceStatus>
  configure(options: { apiBaseUrl: string; credential: string }): Promise<GeofenceStatus>
  refresh(): Promise<GeofenceStatus>
  disable(): Promise<GeofenceStatus>
  requestBatteryExemption(): Promise<Partial<GeofenceStatus>>
  openBackgroundSettings(): Promise<{ opened: boolean; vendor?: string | null }>
  openSettings(): Promise<{ opened: boolean }>
}

let registered: GeofencePlugin | null = null
const native = () => (registered ??= registerPlugin<GeofencePlugin>('Geofence'))

/** The binary has the geofence plugin (an older binary running a newer bundle does not). */
export async function geofenceSupported() {
  return isNativePlatform() && (await getNativeCapabilities()).geofence >= 1
}

export async function getGeofenceStatus(): Promise<GeofenceStatus | null> {
  if (!(await geofenceSupported())) return null
  return native().getStatus()
}

export const requestGeofencePermissions = () => native().requestPermissions({ background: true })
export const requestBatteryExemption = () => native().requestBatteryExemption().then(() => native().getStatus())
export const openBackgroundSettings = () => native().openBackgroundSettings()
export const openLocationSettings = () => native().openSettings()

/** Hand the one-time device credential to the native layer and start monitoring. */
export async function enrollGeofence(credential: string) {
  const status = await native().configure({ apiBaseUrl: getApiBaseUrl(), credential })
  addTelemetryBreadcrumb({ category: 'native.geofence', message: 'Geofence monitoring configured', level: 'info' })
  return status
}

/** App opened or resumed: re-read the sites and report whether the phone is inside. */
export async function refreshGeofence() {
  if (!(await geofenceSupported())) return null
  const status = await native().getStatus()
  return status.enrolled ? native().refresh() : status
}

/** Consent withdrawn, automatic mode left, or signed out: forget everything on the phone. */
export async function disableGeofence() {
  if (!(await geofenceSupported())) return null
  return native().disable()
}

/** What the device reports to the server about itself. */
export function deviceState(status: GeofenceStatus) {
  return {
    location_permission: status.permission === 'prompt' ? 'denied' as const : status.permission,
    location_accuracy: status.accuracy,
    battery_unrestricted: status.batteryUnrestricted,
  }
}

export const geofencePlatform = nativePlatform
