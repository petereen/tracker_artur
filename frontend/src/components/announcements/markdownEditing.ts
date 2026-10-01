import i18n from '../../i18n'

/** Pure Markdown edits for the announcement editor's toolbar. */

export type MarkdownFormat = 'bold' | 'italic' | 'heading' | 'bullet' | 'numbered' | 'quote' | 'link'

export interface MarkdownEdit {
  value: string
  selectionStart: number
  selectionEnd: number
}

/** The placeholder is text inserted into the post, so it is resolved when the button is pressed. */
const WRAPPERS: Partial<Record<MarkdownFormat, { mark: string; placeholderKey: string }>> = {
  bold: { mark: '**', placeholderKey: 'announcements.md.boldPlaceholder' },
  italic: { mark: '_', placeholderKey: 'announcements.md.italicPlaceholder' },
}

const LINE_PREFIX = /^(#{1,6} |[-*] |\d+\. |> )/

function prefixFor(format: MarkdownFormat, index: number) {
  if (format === 'heading') return '## '
  if (format === 'bullet') return '- '
  if (format === 'numbered') return `${index + 1}. `
  return '> '
}

function matchesFormat(line: string, format: MarkdownFormat) {
  if (format === 'heading') return /^#{1,6} /.test(line)
  if (format === 'bullet') return /^[-*] /.test(line)
  if (format === 'numbered') return /^\d+\. /.test(line)
  return /^> /.test(line)
}

/** Applies a toolbar action to `value` and returns the text with the selection to restore. */
export function applyMarkdownFormat(value: string, start: number, end: number, format: MarkdownFormat): MarkdownEdit {
  const selected = value.slice(start, end)

  const wrapper = WRAPPERS[format]
  if (wrapper) {
    const { mark, placeholderKey } = wrapper
    // Pressing the button again on wrapped text removes the marks.
    if (value.slice(start - mark.length, start) === mark && value.slice(end, end + mark.length) === mark) {
      return { value: value.slice(0, start - mark.length) + selected + value.slice(end + mark.length), selectionStart: start - mark.length, selectionEnd: end - mark.length }
    }
    const inner = selected || i18n.t(placeholderKey)
    return { value: value.slice(0, start) + mark + inner + mark + value.slice(end), selectionStart: start + mark.length, selectionEnd: start + mark.length + inner.length }
  }

  if (format === 'link') {
    const text = selected || i18n.t('announcements.md.linkPlaceholder')
    const url = 'https://'
    const inserted = `[${text}](${url})`
    const urlStart = start + text.length + 3
    return { value: value.slice(0, start) + inserted + value.slice(end), selectionStart: urlStart, selectionEnd: urlStart + url.length }
  }

  // Line formats cover every line the selection touches.
  const blockStart = value.lastIndexOf('\n', start - 1) + 1
  const nextBreak = value.indexOf('\n', end)
  const blockEnd = nextBreak === -1 ? value.length : nextBreak
  const lines = value.slice(blockStart, blockEnd).split('\n')
  const remove = lines.every((line) => matchesFormat(line, format))
  const block = lines.map((line, index) => {
    const bare = line.replace(LINE_PREFIX, '')
    return remove ? bare : prefixFor(format, index) + bare
  }).join('\n')
  return { value: value.slice(0, blockStart) + block + value.slice(blockEnd), selectionStart: blockStart, selectionEnd: blockStart + block.length }
}
