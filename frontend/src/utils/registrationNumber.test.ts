import { describe, expect, it } from 'vitest'
import { parseRegistrationNumber } from './registrationNumber'

describe('parseRegistrationNumber', () => {
  it('decodes 20th-century births and gender from the second-to-last digit', () => {
    expect(parseRegistrationNumber('уб 99011512')).toEqual({ value: 'УБ99011512', birthday: '1999-01-15', gender: 'male' })
  })

  it('treats month + 20 as a birth in the 2000s', () => {
    expect(parseRegistrationNumber('ТА01231524')).toEqual({ value: 'ТА01231524', birthday: '2001-03-15', gender: 'female' })
  })

  it.each(['UB99011512', 'УБ9901151', 'УБ99131512', 'УБ99023012'])('rejects %s', (value) => {
    expect(parseRegistrationNumber(value)).toBeNull()
  })
})
