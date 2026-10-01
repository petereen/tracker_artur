import { describe, expect, it } from 'vitest'
import { messageSets, resources } from './index'

const placeholders = (value: string) => [...value.matchAll(/{{\s*(\w+)\s*}}/g)].map((match) => match[1]).sort()
const entries = Object.entries(messageSets)

describe('locale catalogue', () => {
  it('declares every key in exactly one domain', () => {
    const owner = new Map<string, string>()
    const clashes: string[] = []
    for (const [domain, set] of entries) {
      for (const key of Object.keys(set.mn)) {
        if (owner.has(key)) clashes.push(`${key} (${owner.get(key)} and ${domain})`)
        owner.set(key, domain)
      }
    }
    expect(clashes).toEqual([])
  })

  it('has a Russian string for every Mongolian one, and no stray keys', () => {
    for (const [domain, set] of entries) {
      expect(Object.keys(set.ru).sort(), domain).toEqual(Object.keys(set.mn).sort())
    }
  })

  it('only overrides keys that exist in Mongolian for English', () => {
    for (const [domain, set] of entries) {
      const extra = Object.keys(set.en ?? {}).filter((key) => !(key in set.mn))
      expect(extra, domain).toEqual([])
    }
  })

  it('keeps interpolation placeholders identical across languages', () => {
    const problems: string[] = []
    for (const set of Object.values(messageSets)) {
      for (const [key, mn] of Object.entries(set.mn)) {
        for (const language of ['ru', 'en'] as const) {
          const translated = (set[language] as Record<string, string> | undefined)?.[key]
          if (translated !== undefined && placeholders(translated).join() !== placeholders(mn).join()) problems.push(`${language}:${key}`)
        }
      }
    }
    expect(problems).toEqual([])
  })

  it('has no empty strings', () => {
    const empty = (['mn', 'ru', 'en'] as const).flatMap((language) => Object.entries(resources[language].translation).filter(([, value]) => !value.trim()).map(([key]) => `${language}:${key}`))
    expect(empty).toEqual([])
  })

  it('does not leave Mongolian text in the Russian catalogue', () => {
    // Ө/Ү (and ө/ү) exist in Mongolian Cyrillic but not in Russian.
    const leaked = Object.entries(resources.ru.translation).filter(([, value]) => /[ӨҮөү]/.test(value)).map(([key]) => key)
    expect(leaked).toEqual([])
  })
})
