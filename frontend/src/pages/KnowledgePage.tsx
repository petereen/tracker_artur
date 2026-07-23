import { useMemo, useRef, useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Toggle } from '../components/ui'
import {
  KnowledgeEntry,
  KnowledgeInput,
  useCreateKnowledge,
  useCreateKnowledgeWithAttachment,
  useDeleteKnowledge,
  useDeleteKnowledgeAttachment,
  useKnowledge,
  useReplaceKnowledgeAttachment,
  useUpdateKnowledge,
} from '../api/hooks'
import { api } from '../api/client'

const EMPTY_FORM: KnowledgeInput = {
  title: '',
  category: '',
  content: '',
  is_active: true,
}

export function KnowledgePage() {
  const { data: entries = [], isLoading } = useKnowledge()
  const create = useCreateKnowledge()
  const createWithAttachment = useCreateKnowledgeWithAttachment()
  const update = useUpdateKnowledge()
  const remove = useDeleteKnowledge()
  const replaceAttachment = useReplaceKnowledgeAttachment()
  const removeAttachment = useDeleteKnowledgeAttachment()
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<KnowledgeInput>(EMPTY_FORM)
  const [showModal, setShowModal] = useState(false)
  const [attachment, setAttachment] = useState<File | null>(null)
  const [removeExistingAttachment, setRemoveExistingAttachment] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const filtered = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    if (!term) return entries
    return entries.filter((entry) =>
      [entry.title, entry.category || '', entry.content]
        .some((value) => value.toLocaleLowerCase().includes(term)),
    )
  }, [entries, query])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setAttachment(null)
    setRemoveExistingAttachment(false)
    setShowModal(true)
  }

  const openEdit = (entry: KnowledgeEntry) => {
    setEditingId(entry.id)
    setForm({
      title: entry.title,
      category: entry.category || '',
      content: entry.content,
      is_active: entry.is_active,
    })
    setAttachment(null)
    setRemoveExistingAttachment(false)
    setShowModal(true)
  }

  const save = async () => {
    const payload = {
      ...form,
      title: form.title.trim(),
      category: form.category?.trim() || null,
      content: form.content.trim() || (attachment ? `Хавсаргасан файл: ${attachment.name}` : ''),
    }
    if (editingId) {
      await update.mutateAsync({ id: editingId, ...payload })
      if (attachment) await replaceAttachment.mutateAsync({ id: editingId, file: attachment })
      if (removeExistingAttachment && !attachment) await removeAttachment.mutateAsync(editingId)
    } else if (attachment) {
      await createWithAttachment.mutateAsync({ data: payload, file: attachment })
    } else {
      await create.mutateAsync(payload)
    }
    setShowModal(false)
  }

  const selectAttachment = (file: File | null) => {
    setAttachment(file)
    if (file && !form.title.trim()) {
      setForm((current) => ({ ...current, title: file.name.replace(/\.[^.]+$/, '') }))
    }
  }

  const downloadAttachment = async (entry: KnowledgeEntry) => {
    const response = await api.get(`/knowledge/${entry.id}/attachment`, { responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = entry.attachment_filename || 'attachment'
    link.click()
    URL.revokeObjectURL(url)
  }

  const selectedEntry = editingId ? entries.find((entry) => entry.id === editingId) : undefined

  const toggleActive = (entry: KnowledgeEntry, is_active: boolean) => {
    update.mutate({
      id: entry.id,
      title: entry.title,
      category: entry.category,
      content: entry.content,
      is_active,
    })
  }

  const confirmDelete = (entry: KnowledgeEntry) => {
    if (window.confirm(`“${entry.title}” мэдээллийг бүрмөсөн устгах уу?`)) {
      remove.mutate(entry.id)
    }
  }

  return (
    <div>
      <PageHeader
        title="Компанийн мэдлэг"
        sub="OYUNS туслахын хариултад ашиглах бодлого, журам, FAQ болон заавар"
      >
        <Btn variant="primary" onClick={openCreate}>+ Мэдээлэл нэмэх</Btn>
      </PageHeader>

      <div className="max-w-[760px] mb-5">
        <Input
          value={query}
          onChange={setQuery}
          placeholder="Гарчиг, ангилал эсвэл агуулгаар хайх"
          fullWidth
        />
      </div>

      {isLoading && <div className="text-sm text-muted">Ачаалж байна...</div>}
      {!isLoading && filtered.length === 0 && (
        <Card className="text-center text-sm text-muted">
          {entries.length ? 'Хайлтад тохирох мэдээлэл алга.' : 'Компанийн мэдлэгийн мэдээлэл хараахан нэмээгүй байна.'}
        </Card>
      )}

      <div className="flex flex-col gap-3 max-w-[900px]">
        {filtered.map((entry) => (
          <Card key={entry.id} className="!p-4">
            <div className="flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <div className="font-semibold text-sm">{entry.title}</div>
                  {entry.category && <Badge color="blue">{entry.category}</Badge>}
                  <Badge color={entry.is_active ? 'green' : 'muted'}>
                    {entry.is_active ? 'Идэвхтэй' : 'Идэвхгүй'}
                  </Badge>
                </div>
                <p className="text-[13px] text-muted leading-relaxed whitespace-pre-wrap line-clamp-4">
                  {entry.content}
                </p>
                {entry.attachment_filename && (
                  <button
                    onClick={() => downloadAttachment(entry)}
                    className="mt-3 text-xs text-accent hover:underline"
                  >
                    📎 {entry.attachment_filename}
                    {entry.attachment_size ? ` · ${(entry.attachment_size / 1024 / 1024).toFixed(1)} MB` : ''}
                    {' · Татах'}
                  </button>
                )}
                <div className="text-[11px] text-muted mt-3">
                  Шинэчилсэн: {new Date(entry.updated_at).toLocaleString()}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Toggle checked={entry.is_active} onChange={(value) => toggleActive(entry, value)} />
                <Btn onClick={() => openEdit(entry)}>Засах</Btn>
                <Btn variant="danger" onClick={() => confirmDelete(entry)}>Устгах</Btn>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {showModal && (
        <Modal
          title={editingId ? 'Мэдээлэл засах' : 'Шинэ мэдээлэл'}
          onClose={() => setShowModal(false)}
        >
          <div className="flex flex-col gap-3.5">
            <Input
              label="Гарчиг"
              value={form.title}
              onChange={(title) => setForm((current) => ({ ...current, title }))}
              placeholder="Жишээ: Чөлөө авах журам"
              fullWidth
            />
            <Input
              label="Ангилал"
              value={form.category || ''}
              onChange={(category) => setForm((current) => ({ ...current, category }))}
              placeholder="Жишээ: Хүний нөөц"
              fullWidth
            />
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted font-medium">Агуулга</label>
              <textarea
                value={form.content}
                onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
                rows={12}
                maxLength={20000}
                placeholder="Баталгаатай мэдээлэл, журам эсвэл зааврыг энд оруулна уу."
                className="w-full bg-surface2 border border-border rounded-lg p-3 text-text text-sm leading-relaxed resize-y outline-none focus:border-accent"
              />
              <div className="text-[11px] text-muted text-right">{form.content.length}/20000</div>
            </div>
            <div className="flex flex-col gap-2">
              <label className="text-xs text-muted font-medium">Файл хавсаргах</label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.doc,.docx,.rtf,.odt,.xls,.xlsx,.ods,.ppt,.pptx,.odp,.txt,.md,.csv,.png,.jpg,.jpeg,.webp,.svg"
                onChange={(event) => selectAttachment(event.target.files?.[0] || null)}
                className="block w-full text-xs text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-surface3 file:px-3 file:py-2 file:text-xs file:font-medium file:text-text hover:file:bg-border"
              />
              <div className="text-[11px] text-muted">PDF, Office баримт, TXT/CSV, зураг болон SVG · 20 MB хүртэл</div>
              {attachment && <div className="text-xs text-accent">Шинэ хавсралт: {attachment.name}</div>}
              {selectedEntry?.attachment_filename && !attachment && (
                <div className="flex items-center gap-2 text-xs text-muted">
                  Одоогийн хавсралт: {selectedEntry.attachment_filename}
                  <button
                    onClick={() => setRemoveExistingAttachment((value) => !value)}
                    className="text-red hover:underline"
                  >
                    {removeExistingAttachment ? 'Устгахыг буцаах' : 'Устгах'}
                  </button>
                </div>
              )}
            </div>
            <div className="flex items-center justify-between rounded-lg bg-surface2 px-3 py-2">
              <div>
                <div className="text-[13px] font-medium">Туслахад ашиглуулах</div>
                <div className="text-[11px] text-muted">Идэвхгүй мэдээлэл ботын хариултад орохгүй.</div>
              </div>
              <Toggle
                checked={form.is_active}
                onChange={(is_active) => setForm((current) => ({ ...current, is_active }))}
              />
            </div>
            <div className="flex gap-2.5 justify-end">
              <Btn onClick={() => setShowModal(false)}>Цуцлах</Btn>
              <Btn
                variant="primary"
                onClick={save}
                disabled={
                  !form.title.trim()
                  || (!form.content.trim() && !attachment)
                  || create.isPending
                  || createWithAttachment.isPending
                  || update.isPending
                  || replaceAttachment.isPending
                  || removeAttachment.isPending
                }
              >
                Хадгалах
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
