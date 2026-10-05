/** Kept apart from `index.ts` so UI code can import the list without pulling in every catalogue. */
export const LANGUAGES = ['mn', 'ru', 'en'] as const
export type Language = (typeof LANGUAGES)[number]
