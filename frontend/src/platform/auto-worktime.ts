import { fetchAutoWorktimeStatus, revokeOwnDevice, updateDeviceState } from '../api/worktimeAuto'
import { deviceState, disableGeofence, geofenceSupported, getGeofenceStatus, refreshGeofence } from './geofence'
import { captureTelemetryException } from './telemetry'

/**
 * App opened or resumed: the native layer re-reads the office sites, reports
 * whether the phone is inside one (this repairs a missed transition), and the
 * server learns the current permission and battery state.
 */
export async function syncAutoWorktime() {
  try {
    if (!(await geofenceSupported())) return
    const native = await getGeofenceStatus()
    if (!native?.enrolled) return
    const refreshed = (await refreshGeofence()) ?? native
    const server = await fetchAutoWorktimeStatus()
    if (server.device) await updateDeviceState(server.device.id, deviceState(refreshed))
    // No device on the server (consent withdrawn elsewhere, phone replaced):
    // the native layer notices on its own request and switches itself off.
  } catch (error) {
    captureTelemetryException(error)
  }
}

/** Signing out stops automatic tracking on this phone. */
export async function stopAutoWorktimeOnSignOut() {
  try {
    if (!(await geofenceSupported())) return
    const native = await getGeofenceStatus()
    if (!native?.enrolled) return
    const server = await fetchAutoWorktimeStatus().catch(() => null)
    if (server?.device) await revokeOwnDevice(server.device.id).catch(() => undefined)
    await disableGeofence()
  } catch (error) {
    captureTelemetryException(error)
  }
}
