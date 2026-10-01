import { useLayoutEffect, useRef, useState } from 'react'
import { Bold, Heading2, Italic, Link2, List, ListOrdered, Quote, type LucideIcon } from 'lucide-react'
import { Card } from '@astryxdesign/core/Card'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { Markdown } from '@astryxdesign/core/Markdown'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { VStack } from '@astryxdesign/core/VStack'
import { applyMarkdownFormat, type MarkdownFormat } from './markdownEditing'

const ACTIONS: Array<{ format: MarkdownFormat; label: string; icon: LucideIcon }> = [
  { format: 'bold', label: 'Тод', icon: Bold },
  { format: 'italic', label: 'Налуу', icon: Italic },
  { format: 'heading', label: 'Гарчиг', icon: Heading2 },
  { format: 'bullet', label: 'Жагсаалт', icon: List },
  { format: 'numbered', label: 'Дугаарласан жагсаалт', icon: ListOrdered },
  { format: 'quote', label: 'Ишлэл', icon: Quote },
  { format: 'link', label: 'Холбоос', icon: Link2 },
]

/** Basic text editor: a formatting toolbar over a Markdown text area, with a preview. */
export function MarkdownEditor({ label, value, onChange, maxLength, rows = 12 }: { label: string; value: string; onChange: (value: string) => void; maxLength?: number; rows?: number }) {
  const field = useRef<HTMLTextAreaElement>(null)
  const pendingSelection = useRef<[number, number] | null>(null)
  const [mode, setMode] = useState<'write' | 'preview'>('write')

  // Restore the selection once the formatted text has been rendered.
  useLayoutEffect(() => {
    const selection = pendingSelection.current
    if (!selection || !field.current) return
    pendingSelection.current = null
    field.current.focus()
    field.current.setSelectionRange(selection[0], selection[1])
  }, [value])

  const format = (kind: MarkdownFormat) => {
    const element = field.current
    const start = element?.selectionStart ?? value.length
    const end = element?.selectionEnd ?? value.length
    const edit = applyMarkdownFormat(value, start, end, kind)
    pendingSelection.current = [edit.selectionStart, edit.selectionEnd]
    onChange(edit.value)
  }

  return (
    <VStack gap={2}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <HStack gap={0.5} vAlign="center" wrap="wrap">
          {ACTIONS.map(({ format: kind, label: actionLabel, icon: ActionIcon }) => (
            <IconButton key={kind} label={actionLabel} tooltip={actionLabel} icon={<ActionIcon size={15} />} size="sm" variant="ghost" isDisabled={mode === 'preview'} onClick={() => format(kind)} />
          ))}
        </HStack>
        <SegmentedControl label="Засварлагчийн горим" size="sm" value={mode} onChange={(next) => setMode(next === 'preview' ? 'preview' : 'write')}>
          <SegmentedControlItem value="write" label="Бичих" />
          <SegmentedControlItem value="preview" label="Урьдчилан харах" />
        </SegmentedControl>
      </HStack>
      {mode === 'write'
        ? <TextArea ref={field} label={label} isLabelHidden value={value} onChange={onChange} rows={rows} maxLength={maxLength} width="100%" placeholder="Мэдээний агуулгаа энд бичнэ үү…" />
        : <Card padding={4}>
          {value.trim() ? <Markdown density="compact" headingLevelStart={3} contentWidth="100%">{value}</Markdown> : <Text type="supporting">Агуулга хоосон байна.</Text>}
        </Card>}
    </VStack>
  )
}
