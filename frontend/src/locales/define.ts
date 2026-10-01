type Messages = Record<string, string>

/**
 * One domain's strings, with every language side by side.
 *
 * `mn` is the source of truth. `ru` must have exactly the same keys (a missing
 * or extra key is a compile error), so a new string cannot ship untranslated.
 * `en` is optional and falls back to `mn` for keys it does not cover.
 */
export interface MessageSet<T extends Messages> {
  mn: T
  ru: { [K in keyof NoInfer<T>]: string }
  en?: { [K in keyof NoInfer<T>]?: string }
}

export function defineMessages<const T extends Messages>(set: MessageSet<T>): MessageSet<T> {
  return set
}
