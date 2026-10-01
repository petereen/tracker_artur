import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Underline from '@tiptap/extension-underline'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'

export interface RichContractEditorProps {
  value: Record<string, unknown>
  editable: boolean
  onChange?: (value: Record<string, unknown>) => void
  onSelection?: (anchor: { from: number; to: number; quote: string } | null) => void
}

export function RichContractEditor({ value, editable, onChange, onSelection }: RichContractEditorProps) {
  const { t } = useTranslation()
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3, 4] }, link: false, underline: false }),
      Link.configure({ openOnClick: false }),
      Underline,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: value,
    editable,
    onUpdate: ({ editor: instance }) => onChange?.(instance.getJSON() as Record<string, unknown>),
    onSelectionUpdate: ({ editor: instance }) => {
      const { from, to } = instance.state.selection
      onSelection?.(from === to ? null : { from, to, quote: instance.state.doc.textBetween(from, to, ' ') })
    },
  })

  useEffect(() => { if (editor) editor.setEditable(editable) }, [editable, editor])
  useEffect(() => {
    if (!editor) return
    if (JSON.stringify(editor.getJSON()) !== JSON.stringify(value)) editor.commands.setContent(value)
  }, [editor, value])

  if (!editor) return <div className="contract-editor-loading">{t('contracts.editorLoading')}</div>
  return (
    <div className={`contract-editor ${editable ? '' : 'is-locked'}`}>
      {editable && <div className="contract-editor-toolbar" role="toolbar" aria-label={t('contracts.editor.toolbar')}>
        <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} className={editor.isActive('bold') ? 'is-active' : ''}>B</button>
        <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} className={editor.isActive('italic') ? 'is-active' : ''}><em>I</em></button>
        <button type="button" onClick={() => editor.chain().focus().toggleUnderline().run()} className={editor.isActive('underline') ? 'is-active' : ''}><u>U</u></button>
        <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()}>{t('contracts.editor.bullets')}</button>
        <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()}>{t('contracts.editor.numbered')}</button>
        <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>{t('contracts.editor.heading')}</button>
        <button type="button" onClick={() => editor.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run()}>{t('contracts.editor.table')}</button>
      </div>}
      <EditorContent editor={editor} />
    </div>
  )
}
