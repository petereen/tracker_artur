import { useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select, Toggle } from '../components/ui'
import {
  AssistantContextExample,
  AssistantContextInput,
  AssistantContextIntent,
  UnknownAssistantRequest,
  useAssistantContextExamples,
  useCreateAssistantContextExample,
  useDeleteAssistantContextExample,
  usePromoteUnknownAssistantRequest,
  useUnknownAssistantRequests,
  useUpdateAssistantContextExample,
  useUpdateUnknownAssistantRequest,
} from '../api/hooks'

const INTENT_OPTIONS = [
  { value: 'create_task_draft', label: 'Даалгаврын ноорог' },
  { value: 'get_user_tasks', label: 'Миний даалгавар' },
  { value: 'search_company_knowledge', label: 'Компанийн мэдлэг хайх' },
]

const EMPTY_CONTEXT: AssistantContextInput = {
  phrase: '',
  intent: 'create_task_draft',
  meaning: '',
  is_active: true,
}

function intentLabel(intent: AssistantContextIntent) {
  return INTENT_OPTIONS.find((item) => item.value === intent)?.label || intent
}

function dateTime(value: string) {
  return new Date(value).toLocaleString('mn-MN')
}

export function DeveloperPage() {
  const { data: unknownRequests = [], isLoading: unknownLoading } = useUnknownAssistantRequests()
  const { data: contexts = [], isLoading: contextsLoading } = useAssistantContextExamples()
  const createContext = useCreateAssistantContextExample()
  const updateContext = useUpdateAssistantContextExample()
  const removeContext = useDeleteAssistantContextExample()
  const updateUnknown = useUpdateUnknownAssistantRequest()
  const promoteUnknown = usePromoteUnknownAssistantRequest()
  const [editing, setEditing] = useState<AssistantContextExample | null>(null)
  const [promoting, setPromoting] = useState<UnknownAssistantRequest | null>(null)
  const [form, setForm] = useState<AssistantContextInput>(EMPTY_CONTEXT)
  const [editorOpen, setEditorOpen] = useState(false)

  const openCreate = () => {
    setEditing(null)
    setPromoting(null)
    setForm(EMPTY_CONTEXT)
    setEditorOpen(true)
  }

  const openEdit = (context: AssistantContextExample) => {
    setPromoting(null)
    setEditing(context)
    setForm({ phrase: context.phrase, intent: context.intent, meaning: context.meaning, is_active: context.is_active })
    setEditorOpen(true)
  }

  const openPromote = (request: UnknownAssistantRequest) => {
    setEditing(null)
    setPromoting(request)
    setForm({
      phrase: request.text,
      intent: 'create_task_draft',
      meaning: '',
      is_active: true,
    })
    setEditorOpen(true)
  }

  const closeModal = () => {
    setEditing(null)
    setPromoting(null)
    setForm(EMPTY_CONTEXT)
    setEditorOpen(false)
  }

  const saveContext = async () => {
    const payload = { ...form, phrase: form.phrase.trim(), meaning: form.meaning.trim() }
    if (promoting) {
      await promoteUnknown.mutateAsync({ id: promoting.id, ...payload })
    } else if (editing) {
      await updateContext.mutateAsync({ id: editing.id, ...payload })
    } else {
      await createContext.mutateAsync(payload)
    }
    closeModal()
  }

  const toggleContext = (context: AssistantContextExample, is_active: boolean) => {
    updateContext.mutate({
      id: context.id,
      phrase: context.phrase,
      intent: context.intent,
      meaning: context.meaning,
      is_active,
    })
  }

  const deleteContext = (context: AssistantContextExample) => {
    if (window.confirm(`“${context.phrase}” контекстийг устгах уу?`)) removeContext.mutate(context.id)
  }

  const busy = createContext.isPending || updateContext.isPending || promoteUnknown.isPending

  return (
    <div>
      <PageHeader
        title="OYUNS хөгжүүлэлт"
        sub="Танигдаагүй хэллэгийг хянаж, баталгаатай контекстийн толь бичигт нэмнэ үү."
      >
        <Btn variant="primary" onClick={openCreate}>+ Контекст нэмэх</Btn>
      </PageHeader>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <section>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-base font-semibold">Танигдаагүй хүсэлтүүд</h2>
              <p className="text-xs text-muted mt-0.5">Давтагдсан хэллэгүүд автоматаар нэгтгэгдэнэ.</p>
            </div>
            <Badge color="yellow">{unknownRequests.filter((item) => item.status === 'pending').length} хүлээгдэж байна</Badge>
          </div>
          {unknownLoading && <div className="text-sm text-muted">Ачаалж байна...</div>}
          {!unknownLoading && unknownRequests.length === 0 && (
            <Card className="text-center text-sm text-muted">Одоогоор хянах танигдаагүй хүсэлт алга.</Card>
          )}
          <div className="flex flex-col gap-3">
            {unknownRequests.map((request) => (
              <Card key={request.id} className="!p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{request.text}</p>
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      <Badge color={request.status === 'pending' ? 'yellow' : request.status === 'reviewed' ? 'green' : 'muted'}>
                        {request.status === 'pending' ? 'Хянах' : request.status === 'reviewed' ? 'Хянасан' : 'Хэрэгсэхгүй'}
                      </Badge>
                      <Badge color="muted">{request.language.toUpperCase()} · {request.channel}</Badge>
                      <Badge color="purple">{request.occurrence_count} удаа</Badge>
                      <Badge color="red">{request.reason}</Badge>
                    </div>
                    {request.terms.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {request.terms.map((term) => <Badge key={term} color="blue">{term}</Badge>)}
                      </div>
                    )}
                    <div className="text-[11px] text-muted mt-3">Сүүлд: {dateTime(request.last_seen_at)}</div>
                  </div>
                  <div className="flex flex-col gap-2 flex-shrink-0">
                    <Btn variant="primary" onClick={() => openPromote(request)}>Тольд нэмэх</Btn>
                    {request.status !== 'dismissed' && (
                      <Btn onClick={() => updateUnknown.mutate({ id: request.id, status: 'dismissed' })} disabled={updateUnknown.isPending}>Хэрэгсэхгүй</Btn>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </section>

        <section>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-base font-semibold">Контекстийн толь бичиг</h2>
              <p className="text-xs text-muted mt-0.5">Зөвхөн идэвхтэй, админаар баталгаажсан жишээ router-д орно.</p>
            </div>
            <Badge color="green">{contexts.filter((item) => item.is_active).length} идэвхтэй</Badge>
          </div>
          {contextsLoading && <div className="text-sm text-muted">Ачаалж байна...</div>}
          {!contextsLoading && contexts.length === 0 && (
            <Card className="text-center text-sm text-muted">Контекстийн толь бичиг хоосон байна.</Card>
          )}
          <div className="flex flex-col gap-3">
            {contexts.map((context) => (
              <Card key={context.id} className="!p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm">{context.phrase}</div>
                    <div className="mt-2"><Badge color="blue">{intentLabel(context.intent)}</Badge></div>
                    <p className="text-[13px] text-muted leading-relaxed mt-2 whitespace-pre-wrap">{context.meaning}</p>
                    <div className="text-[11px] text-muted mt-3">Шинэчилсэн: {dateTime(context.updated_at)}</div>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <Toggle checked={context.is_active} onChange={(value) => toggleContext(context, value)} />
                    <Btn onClick={() => openEdit(context)}>Засах</Btn>
                    <Btn variant="danger" onClick={() => deleteContext(context)} disabled={removeContext.isPending}>Устгах</Btn>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </section>
      </div>

      {editorOpen && (
        <Modal title={promoting ? 'Танигдаагүй хүсэлтийг тольд нэмэх' : editing ? 'Контекст засах' : 'Шинэ контекст'} onClose={closeModal}>
          <div className="flex flex-col gap-3.5">
            {promoting && <p className="text-xs text-muted">Хүсэлтийг “Хянасан” төлөвт оруулж, доорх жишээг router-д ашиглана.</p>}
            <Input label="Хэллэг / жишээ" value={form.phrase} onChange={(phrase) => setForm((current) => ({ ...current, phrase }))} fullWidth />
            <Select
              label="Зорилтот үйлдэл"
              value={form.intent}
              onChange={(intent) => setForm((current) => ({ ...current, intent: intent as AssistantContextIntent }))}
              options={INTENT_OPTIONS}
              fullWidth
            />
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted font-medium">Энэ хэллэгийн утга</label>
              <textarea
                value={form.meaning}
                onChange={(event) => setForm((current) => ({ ...current, meaning: event.target.value }))}
                rows={4}
                maxLength={1000}
                placeholder="Жишээ: Бүх ажилтанд уулзалтын даалгаврын ноорог бэлтгэ."
                className="w-full bg-surface2 border border-border rounded-lg p-3 text-text text-sm leading-relaxed resize-y outline-none focus:border-accent"
              />
            </div>
            <div className="flex items-center justify-between rounded-lg bg-surface2 px-3 py-2">
              <div>
                <div className="text-[13px] font-medium">Router-д ашиглуулах</div>
                <div className="text-[11px] text-muted">Идэвхгүй бичлэг OYUNS-ийн контекстэд орохгүй.</div>
              </div>
              <Toggle checked={form.is_active} onChange={(is_active) => setForm((current) => ({ ...current, is_active }))} />
            </div>
            <div className="flex justify-end gap-2.5">
              <Btn onClick={closeModal}>Цуцлах</Btn>
              <Btn variant="primary" onClick={saveContext} disabled={!form.phrase.trim() || !form.meaning.trim() || busy}>Хадгалах</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
