import i18n from '../i18n'

/** Label table whose values follow the UI language: each read resolves `${prefix}.${key}` at call time, not at import. */
export function labelMap<K extends string>(prefix: string, keys: readonly K[]): Record<K, string> {
  const map = {} as Record<K, string>
  for (const key of keys) Object.defineProperty(map, key, { enumerable: true, get: () => i18n.t(`${prefix}.${key}`) })
  return map
}

/** `${prefix}.${key}` translated, or `key` itself when the backend sends a value we have no label for. */
export function labelOr(prefix: string, key: string): string {
  const full = `${prefix}.${key}`
  return i18n.exists(full) ? i18n.t(full) : key
}

/**
 * Catalog text the backend serves in Mongolian (notification categories, AI access sections, role catalog, license
 * features). Other languages overlay a translation keyed by the item's code; unknown codes keep the server text.
 */
export function catalogText(key: string, fallback: string): string {
  return i18n.language !== 'mn' && i18n.exists(key) ? i18n.t(key) : fallback
}
