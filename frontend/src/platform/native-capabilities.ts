import { registerPlugin } from '@capacitor/core'
import { isNativePlatform } from './runtime'

/**
 * What the installed binary can do. The web layer ships over the air and may
 * run on an older binary, so a feature that needs native code asks here first
 * and hides itself instead of calling a plugin that is not there.
 */
export type NativeCapabilities = {
  /** Build number of the native layer; binaries without the plugin are build 1. */
  nativeVersion: number
  geofence: number
  biometric: number
}

interface NativeCapabilitiesPlugin {
  getNativeCapabilities(): Promise<Partial<NativeCapabilities>>
}

const WEB: NativeCapabilities = { nativeVersion: 0, geofence: 0, biometric: 0 }
const FIRST_BINARY: NativeCapabilities = { nativeVersion: 1, geofence: 0, biometric: 0 }
let cached: Promise<NativeCapabilities> | null = null

async function read(): Promise<NativeCapabilities> {
  try {
    const value = await registerPlugin<NativeCapabilitiesPlugin>('NativeCapabilities').getNativeCapabilities()
    return {
      nativeVersion: Number(value.nativeVersion) || 1,
      geofence: Number(value.geofence) || 0,
      biometric: Number(value.biometric) || 0,
    }
  } catch {
    // The first store binary has no capability plugin at all.
    return FIRST_BINARY
  }
}

export function getNativeCapabilities(): Promise<NativeCapabilities> {
  if (!isNativePlatform()) return Promise.resolve(WEB)
  if (!cached) cached = read()
  return cached
}
