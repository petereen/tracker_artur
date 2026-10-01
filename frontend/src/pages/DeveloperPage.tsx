import i18n from '../i18n'
import { intlLocale } from '../utils/locale'
import { useTranslation } from 'react-i18next'
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
  { value: 'create_task_draft', get label() { return i18n.t('dev.intent.createTaskDraft') } },
  { value: 'get_user_tasks', get label() { return i18n.t('dev.intent.getUserTasks') } },
  { value: 'search_company_knowledge', get label() { return i18n.t('dev.intent.searchKnowledge') } },
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
  return new Date(value).toLocaleString(intlLocale())
}

export function DeveloperPage() {
  const { t } = useTranslation()
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
    if (window.confirm(t('dev.deleteConfirm', { phrase: context.phrase }))) removeContext.mutate(context.id)
  }

  const busy = createContext.isPending || updateContext.isPending || promoteUnknown.isPending

  return (
    <div>
      <PageHeader
        title={t('dev.title')}
      >
        <Btn variant="primary" onClick={openCreate}>{t('dev.addContext')}</Btn>
      </PageHeader>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <section>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-base font-semibold">{t('dev.unknownTitle')}</h2>
              <p className="text-xs text-muted mt-0.5">{t('dev.unknownHint')}</p>
            </div>
            <Badge color="yellow">{t('dev.pendingCount', { n: unknownRequests.filter((item) => item.status === 'pending').length })}</Badge>
          </div>
          {unknownLoading && <div className="text-sm text-muted">{t('dev.loading')}</div>}
          {!unknownLoading && unknownRequests.length === 0 && (
            <Card className="text-center text-sm text-muted">{t('dev.noUnknown')}</Card>
          )}
          <div className="flex flex-col gap-3">
            {unknownRequests.map((request) => (
              <Card key={request.id} className="!p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{request.text}</p>
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      <Badge color={request.status === 'pending' ? 'yellow' : request.status === 'reviewed' ? 'green' : 'muted'}>
                        {request.status === 'pending' ? t('dev.status.pending') : request.status === 'reviewed' ? t('dev.status.reviewed') : t('dev.dismiss')}
                      </Badge>
                      <Badge color="muted">{request.language.toUpperCase()} · {request.channel}</Badge>
                      <Badge color="purple">{t('dev.occurrences', { n: request.occurrence_count })}</Badge>
                      <Badge color="red">{request.reason}</Badge>
                    </div>
                    {request.terms.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {request.terms.map((term) => <Badge key={term} color="blue">{term}</Badge>)}
                      </div>
                    )}
                    <div className="text-[11px] text-muted mt-3">{t('dev.lastSeen', { date: dateTime(request.last_seen_at) })}</div>
                  </div>
                  <div className="flex flex-col gap-2 flex-shrink-0">
                    <Btn variant="primary" onClick={() => openPromote(request)}>{t('dev.promote')}</Btn>
                    {request.status !== 'dismissed' && (
                      <Btn onClick={() => updateUnknown.mutate({ id: request.id, status: 'dismissed' })} disabled={updateUnknown.isPending}>{t('dev.dismiss')}</Btn>
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
              <h2 className="text-base font-semibold">{t('dev.dictTitle')}</h2>
              <p className="text-xs text-muted mt-0.5">{t('dev.dictHint')}</p>
            </div>
            <Badge color="green">{t('dev.activeCount', { n: contexts.filter((item) => item.is_active).length })}</Badge>
          </div>
          {contextsLoading && <div className="text-sm text-muted">{t('dev.loading')}</div>}
          {!contextsLoading && contexts.length === 0 && (
            <Card className="text-center text-sm text-muted">{t('dev.dictEmpty')}</Card>
          )}
          <div className="flex flex-col gap-3">
            {contexts.map((context) => (
              <Card key={context.id} className="!p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm">{context.phrase}</div>
                    <div className="mt-2"><Badge color="blue">{intentLabel(context.intent)}</Badge></div>
                    <p className="text-[13px] text-muted leading-relaxed mt-2 whitespace-pre-wrap">{context.meaning}</p>
                    <div className="text-[11px] text-muted mt-3">{t('dev.updated', { date: dateTime(context.updated_at) })}</div>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <Toggle checked={context.is_active} onChange={(value) => toggleContext(context, value)} />
                    <Btn onClick={() => openEdit(context)}>{t('dev.edit')}</Btn>
                    <Btn variant="danger" onClick={() => deleteContext(context)} disabled={removeContext.isPending}>{t('dev.delete')}</Btn>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </section>
      </div>

      {editorOpen && (
        <Modal title={promoting ? t('dev.promoteTitle') : editing ? t('dev.editTitle') : t('dev.newTitle')} onClose={closeModal}>
          <div className="flex flex-col gap-3.5">
            {promoting && <p className="text-xs text-muted">{t('dev.promoteHint')}</p>}
            <Input label={t('dev.phrase')} value={form.phrase} onChange={(phrase) => setForm((current) => ({ ...current, phrase }))} fullWidth />
            <Select
              label={t('dev.intent')}
              value={form.intent}
              onChange={(intent) => setForm((current) => ({ ...current, intent: intent as AssistantContextIntent }))}
              options={INTENT_OPTIONS}
              fullWidth
            />
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted font-medium">{t('dev.meaning')}</label>
              <textarea
                value={form.meaning}
                onChange={(event) => setForm((current) => ({ ...current, meaning: event.target.value }))}
                rows={4}
                maxLength={1000}
                placeholder={t('dev.meaningPlaceholder')}
                className="w-full bg-surface2 border border-border rounded-lg p-3 text-text text-sm leading-relaxed resize-y outline-none focus:border-accent"
              />
            </div>
            <div className="flex items-center justify-between rounded-lg bg-surface2 px-3 py-2">
              <div>
                <div className="text-[13px] font-medium">{t('dev.useInRouter')}</div>
                <div className="text-[11px] text-muted">{t('dev.inactiveHint')}</div>
              </div>
              <Toggle checked={form.is_active} onChange={(is_active) => setForm((current) => ({ ...current, is_active }))} />
            </div>
            <div className="flex justify-end gap-2.5">
              <Btn onClick={closeModal}>{t('dev.cancel')}</Btn>
              <Btn variant="primary" onClick={saveContext} disabled={!form.phrase.trim() || !form.meaning.trim() || busy}>{t('dev.save')}</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
