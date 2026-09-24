/**
 * A decimal string as a form value without Numeric column padding:
 * "4000000.0000" -> "4000000", "8.50" -> "8.5". Non-numeric values pass through,
 * so the user's own dot input still defines any decimals they want.
 */
export function plainNumber(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = String(value).trim()
  if (!/^-?\d+\.\d+$/.test(text)) return text
  return text.replace(/0+$/, '').replace(/\.$/, '')
}
