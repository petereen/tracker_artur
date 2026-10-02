import { registerPlugin } from '@capacitor/core'
import { getNativeCapabilities } from './native-capabilities'
import { isNativePlatform, safeLocalStorage } from './runtime'

/** Face ID / fingerprint prompt, used for the app lock and to confirm consent. */
export type BiometricAvailability = {
  available: boolean
  /** The phone has a screen lock (PIN, pattern, passcode) to fall back to. */
  deviceSecure: boolean
  biometryType: 'face' | 'fingerprint' | 'biometric' | 'none'
}

interface BiometricAuthPlugin {
  isAvailable(): Promise<BiometricAvailability>
  authenticate(options: { reason: string; title?: string; cancelLabel?: string; allowDeviceCredential?: boolean }): Promise<{ success: boolean }>
}

let registered: BiometricAuthPlugin | null = null
const native = () => (registered ??= registerPlugin<BiometricAuthPlugin>('BiometricAuth'))
const UNAVAILABLE: BiometricAvailability = { available: false, deviceSecure: false, biometryType: 'none' }
const LOCK_KEY = 'oyuns.biometric-lock'

export async function biometricAvailability(): Promise<BiometricAvailability> {
  if (!isNativePlatform() || (await getNativeCapabilities()).biometric < 1) return UNAVAILABLE
  try {
    return await native().isAvailable()
  } catch {
    return UNAVAILABLE
  }
}

/** Resolves true when the person proved it is them; false when they cancelled or failed. */
export async function authenticateBiometric(reason: string, title?: string): Promise<boolean> {
  try {
    return (await native().authenticate({ reason, title, allowDeviceCredential: true })).success === true
  } catch {
    return false
  }
}

/** The lock is a per-device choice, so it lives on the device. */
export const isBiometricLockEnabled = () => safeLocalStorage().get(LOCK_KEY) === '1'

export function setBiometricLockEnabled(enabled: boolean) {
  if (enabled) safeLocalStorage().set(LOCK_KEY, '1')
  else safeLocalStorage().remove(LOCK_KEY)
}
