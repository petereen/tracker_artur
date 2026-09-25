/**
 * Mongolian civil registration number (Регистрын дугаар): 2 Cyrillic letters
 * + 8 digits. Digits 1-6 are the birth date YYMMDD (month + 20 for births in
 * 2000 or later); the second-to-last digit is odd for men, even for women.
 * Mirrors backend/app/hr/identity.py.
 */
export interface DecodedRegistrationNumber { value: string; birthday: string; gender: 'male' | 'female' }

export function normalizeRegistrationNumber(raw: string): string {
  return raw.replace(/[\s-]/g, '').toUpperCase()
}

export function parseRegistrationNumber(raw: string, today = new Date()): DecodedRegistrationNumber | null {
  const value = normalizeRegistrationNumber(raw)
  const match = /^[А-ЯЁӨҮ]{2}(\d{2})(\d{2})(\d{2})(\d)\d$/.exec(value)
  if (!match) return null
  let year = Number(match[1])
  let month = Number(match[2])
  const day = Number(match[3])
  if (month > 20) { month -= 20; year += 2000 } else { year += 1900 }
  const date = new Date(Date.UTC(year, month - 1, day))
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day || date > today) return null
  const birthday = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  return { value, birthday, gender: Number(match[4]) % 2 ? 'male' : 'female' }
}
