import { KeychainAccess, SecureStorage } from '@aparajita/capacitor-secure-storage'
import { isNativePlatform } from './runtime'

const REFRESH_TOKEN_KEY = 'native_refresh_token'
const STORAGE_PREFIX = 'mn.oyuns.workspace.'
let configured: Promise<void> | null = null

async function configureStorage() {
  if (!isNativePlatform()) return
  if (!configured) {
    configured = Promise.all([
      SecureStorage.setKeyPrefix(STORAGE_PREFIX),
      SecureStorage.setSynchronize(false),
      SecureStorage.setDefaultKeychainAccess(KeychainAccess.afterFirstUnlockThisDeviceOnly),
    ]).then(() => undefined)
  }
  await configured
}

export async function readSecureValue(key: string) {
  if (!isNativePlatform()) return null
  await configureStorage()
  return SecureStorage.getItem(key)
}

export async function writeSecureValue(key: string, value: string) {
  if (!isNativePlatform()) return
  await configureStorage()
  await SecureStorage.setItem(key, value)
}

export async function removeSecureValue(key: string) {
  if (!isNativePlatform()) return
  await configureStorage()
  await SecureStorage.removeItem(key)
}

export const getNativeRefreshToken = () => readSecureValue(REFRESH_TOKEN_KEY)
export const setNativeRefreshToken = (token: string) => writeSecureValue(REFRESH_TOKEN_KEY, token)
export const clearNativeRefreshToken = () => removeSecureValue(REFRESH_TOKEN_KEY)
