type Messages = Record<string, string>

/**
 * One domain's strings, with every language side by side.
 *
 * `mn` is the source of truth. `ru` and `en` must have exactly the same keys
 * (a missing or extra key is a compile error), so every string ships in all
 * three languages.
 */
export interface MessageSet<T extends Messages> {
  mn: T
  ru: { [K in keyof NoInfer<T>]: string }
  en: { [K in keyof NoInfer<T>]: string }
}

export function defineMessages<const T extends Messages>(set: MessageSet<T>): MessageSet<T> {
  return set
}
