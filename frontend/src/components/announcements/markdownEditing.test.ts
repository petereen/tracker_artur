import { describe, expect, it } from 'vitest'
import { applyMarkdownFormat } from './markdownEditing'

describe('applyMarkdownFormat', () => {
  it('wraps the selection and toggles it off again', () => {
    const bold = applyMarkdownFormat('сайн байна уу', 5, 10, 'bold')
    expect(bold.value).toBe('сайн **байна** уу')
    expect(bold.value.slice(bold.selectionStart, bold.selectionEnd)).toBe('байна')
    expect(applyMarkdownFormat(bold.value, bold.selectionStart, bold.selectionEnd, 'bold').value).toBe('сайн байна уу')
  })

  it('inserts a selected placeholder when nothing is selected', () => {
    const italic = applyMarkdownFormat('', 0, 0, 'italic')
    expect(italic.value).toBe('_налуу текст_')
    expect(italic.value.slice(italic.selectionStart, italic.selectionEnd)).toBe('налуу текст')
  })

  it('prefixes every selected line and numbers ordered lists', () => {
    const text = 'нэг\nхоёр\nгурав'
    expect(applyMarkdownFormat(text, 1, 7, 'bullet').value).toBe('- нэг\n- хоёр\nгурав')
    expect(applyMarkdownFormat(text, 0, text.length, 'numbered').value).toBe('1. нэг\n2. хоёр\n3. гурав')
  })

  it('switches between line formats and removes a format applied twice', () => {
    expect(applyMarkdownFormat('- нэг', 2, 2, 'quote').value).toBe('> нэг')
    expect(applyMarkdownFormat('## Гарчиг', 4, 4, 'heading').value).toBe('Гарчиг')
  })

  it('builds a link and selects the address', () => {
    const link = applyMarkdownFormat('журам үзэх', 0, 5, 'link')
    expect(link.value).toBe('[журам](https://) үзэх')
    expect(link.value.slice(link.selectionStart, link.selectionEnd)).toBe('https://')
  })
})
