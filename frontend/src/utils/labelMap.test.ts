import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { CLASSIFICATION_LABELS } from '../components/accounts/accountShared'
import { KIND_LABELS, formatMoney } from '../components/budget/shared'
import { labelMap, labelOr } from './labelMap'

afterEach(async () => { await i18n.changeLanguage('mn') })

describe('labelMap', () => {
  it('resolves labels in the current UI language on every read', async () => {
    const labels = labelMap('contracts.type', ['contract', 'agreement'])
    expect(labels.contract).toBe('Гэрээ')
    await i18n.changeLanguage('ru')
    expect(labels.contract).toBe('Договор')
    expect(Object.keys(labels)).toEqual(['contract', 'agreement'])
  })

  it('falls back to the raw value for codes without a label', () => {
    expect(labelOr('contracts.status', 'DRAFT')).toBe('Ноорог')
    expect(labelOr('contracts.status', 'SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })

  it('keeps the shared module-level label tables language-aware', async () => {
    expect(KIND_LABELS.cogs).toBe('ББӨ')
    expect(CLASSIFICATION_LABELS.asset).toBe('Хөрөнгө')
    await i18n.changeLanguage('ru')
    expect(KIND_LABELS.cogs).toBe('Себестоимость проданных товаров')
    expect(CLASSIFICATION_LABELS.asset).toBe('Активы')
    expect(formatMoney(1234567)).toBe(`${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(1234567)}₮`)
  })
})
