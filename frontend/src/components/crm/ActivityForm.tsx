import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { CheckCircle2, ClipboardCheck, Copy, ListTodo, Paperclip, RotateCcw, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  downloadCRMFile, useCreateCRMActivityTask, useCRMActivityAction, useCRMFiles, useCRMParty, useDeleteCRMActivity, useDeleteCRMFile,
  useSaveCRMActivity, useUploadCRMFile, type CRMActivity, type CRMActivityInput, type CRMCapabilities, type CRMLookups,
} from '../../api/crm'
import { Btn, Modal } from '../ui'
import { CheckField, Field, NativeSelect, PartyPicker, Section, StatusChip, TextArea, TextInput, crmErrorText, formatDateTime, fromLocalInput, toLocalInput } from './shared'

const NEW_TYPE = '__new__'

type FormState = {
  party_id: number | null; party_label: string | null; contact_id: string; contact_name: string; contact_phone: string; contact_email: string
  activity_at: string; subject: string; body: string; type_id: string; type_name: string; is_important: boolean
  due_at: string; duration_minutes: string; responsible_employee_id: string; status_id: string; completed_at: string; completion_note: string
  reference: string; contract_id: string; project_id: string; is_closed: boolean; expected_revenue: string; currency: string; is_active: boolean
}

function initialState(activity: CRMActivity | null, defaults: { employeeId: number | null; partyId?: number | null; partyLabel?: string | null }): FormState {
  const now = new Date().toISOString()
  return {
    party_id: activity?.party_id ?? defaults.partyId ?? null, party_label: activity ? (activity.party_name ? `${activity.party_name} (${activity.party_code})` : null) : defaults.partyLabel ?? null,
    contact_id: activity?.contact_id ? String(activity.contact_id) : '', contact_name: activity?.contact_name ?? '', contact_phone: activity?.contact_phone ?? '', contact_email: activity?.contact_email ?? '',
    activity_at: toLocalInput(activity?.activity_at ?? now), subject: activity?.subject ?? '', body: activity?.body ?? '',
    type_id: activity?.type_id ? String(activity.type_id) : '', type_name: '', is_important: activity?.is_important ?? false,
    due_at: toLocalInput(activity?.due_at), duration_minutes: activity?.duration_minutes != null ? String(activity.duration_minutes) : '',
    responsible_employee_id: String(activity?.responsible_employee_id ?? defaults.employeeId ?? ''), status_id: activity?.status_id ? String(activity.status_id) : '',
    completed_at: toLocalInput(activity?.completed_at), completion_note: activity?.completion_note ?? '',
    reference: activity?.reference ?? '', contract_id: activity?.contract_id ? String(activity.contract_id) : '', project_id: activity?.project_id ? String(activity.project_id) : '',
    is_closed: activity?.is_closed ?? false, expected_revenue: activity?.expected_revenue ?? '', currency: activity?.currency ?? 'MNT', is_active: activity?.is_active ?? true,
  }
}

const idOrNull = (value: string) => (value ? Number(value) : null)

export function ActivityForm({ activity, lookups, capabilities, defaultParty, onClose, onSaved }: {
  activity: CRMActivity | null
  lookups: CRMLookups
  capabilities: CRMCapabilities
  defaultParty?: { id: number; label: string } | null
  onClose: () => void
  onSaved?: (activity: CRMActivity) => void
}) {
  const [form, setForm] = useState<FormState>(() => initialState(activity, { employeeId: capabilities.employee_id, partyId: defaultParty?.id, partyLabel: defaultParty?.label }))
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((current) => ({ ...current, [key]: value }))
  const party = useCRMParty(form.party_id ?? undefined)
  const save = useSaveCRMActivity()
  const canEdit = activity ? capabilities.activities.edit : capabilities.activities.create
  const contacts = party.data?.contacts.filter((contact) => contact.is_active || String(contact.id) === form.contact_id) ?? []

  const chooseContact = (value: string) => {
    const contact = contacts.find((row) => String(row.id) === value)
    setForm((current) => ({ ...current, contact_id: value, contact_name: contact?.name ?? current.contact_name, contact_phone: contact?.phone ?? '', contact_email: contact?.email ?? '' }))
  }

  const submit = async () => {
    if (!form.subject.trim()) { toast.error('Утга оруулна уу'); return }
    const payload: CRMActivityInput = {
      party_id: form.party_id, contact_id: idOrNull(form.contact_id), contact_name: form.contact_name || null, contact_phone: form.contact_phone || null, contact_email: form.contact_email || null,
      activity_at: fromLocalInput(form.activity_at) ?? undefined, subject: form.subject, body: form.body || null,
      type_id: form.type_id && form.type_id !== NEW_TYPE ? Number(form.type_id) : null, type_name: form.type_id === NEW_TYPE ? form.type_name || null : null,
      is_important: form.is_important, due_at: fromLocalInput(form.due_at), duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null,
      responsible_employee_id: idOrNull(form.responsible_employee_id), status_id: idOrNull(form.status_id) ?? undefined,
      completed_at: fromLocalInput(form.completed_at), completion_note: form.completion_note || null, reference: form.reference || null,
      contract_id: idOrNull(form.contract_id), project_id: idOrNull(form.project_id), is_closed: form.is_closed,
      expected_revenue: form.expected_revenue || null, currency: form.currency || 'MNT', is_active: form.is_active,
    }
    if (form.type_id === NEW_TYPE && !form.type_name.trim()) { toast.error('Шинэ төрлийн нэрийг оруулна уу'); return }
    try {
      const saved = await save.mutateAsync(activity ? { id: activity.id, ...payload, version: activity.version } : payload)
      toast.success(activity ? 'Хадгаллаа' : `${saved.number} бүртгэгдлээ`)
      onSaved?.(saved)
      onClose()
    } catch (error) {
      toast.error(crmErrorText(error))
    }
  }

  const statusOptions = lookups.statuses.filter((row) => row.is_active || String(row.id) === form.status_id).map((row) => ({ value: String(row.id), label: row.name }))
  const typeOptions = [...lookups.activity_types.filter((row) => row.is_active || String(row.id) === form.type_id).map((row) => ({ value: String(row.id), label: row.name })), ...(capabilities.activities.create ? [{ value: NEW_TYPE, label: '+ Шинэ төрөл бичих…' }] : [])]
  const employeeOptions = lookups.employees.map((row) => ({ value: String(row.id), label: row.name }))

  return <Modal title={activity ? `${activity.number} — Харилцаа холбоо` : 'Шинэ харилцаа холбоо'} onClose={onClose} className="crm-modal">
    <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
      <fieldset disabled={!canEdit} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
        <Section title="1. Харилцагчийн мэдээлэл">
          <Field label="Харилцагч" hint={form.party_id ? <Link to={`/erp/crm/customers/${form.party_id}`} onClick={onClose}>Харилцагч харах</Link> : 'Дотоод ажил бол хоосон үлдээнэ'}>
            <PartyPicker value={form.party_id} label={form.party_label} onChange={(picked) => setForm((current) => ({ ...current, party_id: picked?.id ?? null, party_label: picked ? `${picked.name} (${picked.code})` : null, contact_id: '', contact_name: '', contact_phone: '', contact_email: '' }))} />
          </Field>
          <Field label="Хэн (холбогдох хүн)">
            {contacts.length
              ? <NativeSelect value={form.contact_id} onChange={chooseContact} options={contacts.map((row) => ({ value: String(row.id), label: row.position ? `${row.name} — ${row.position}` : row.name }))} placeholder="Сонгох эсвэл доор бичих" />
              : <TextInput value={form.contact_name} onChange={(value) => set('contact_name', value)} placeholder="Холбогдсон хүний нэр" />}
          </Field>
          <Field label="Утас"><TextInput value={form.contact_phone} onChange={(value) => set('contact_phone', value)} /></Field>
          <Field label="Mail"><TextInput value={form.contact_email} onChange={(value) => set('contact_email', value)} type="email" /></Field>
        </Section>

        <Section title="2. Үндсэн мэдээлэл">
          <Field label="Огноо"><TextInput type="datetime-local" value={form.activity_at} onChange={(value) => set('activity_at', value)} /></Field>
          <Field label="Төрөл">
            <NativeSelect value={form.type_id} onChange={(value) => set('type_id', value)} options={typeOptions} />
          </Field>
          {form.type_id === NEW_TYPE && <Field label="Шинэ төрлийн нэр" wide><TextInput value={form.type_name} onChange={(value) => set('type_name', value)} placeholder="Жишээ: Үзэсгэлэн" /></Field>}
          <Field label="Утга (товч)" wide><TextInput value={form.subject} onChange={(value) => set('subject', value)} required placeholder="Жишээ: 100 ширхэг бараа авах хүсэлт" /></Field>
          <Field label="Дэлгэрэнгүй" wide><TextArea value={form.body} onChange={(value) => set('body', value)} rows={4} placeholder="Юу ярилцсан, тохиролцсон, шийдвэрлэх асуудал…" /></Field>
          <div className="crm-checks hr-form-wide"><CheckField label="Чухал" checked={form.is_important} onChange={(value) => set('is_important', value)} /></div>
        </Section>

        <Section title="3. Ажлын хугацаа, хариуцагч">
          <Field label="Биелэх хугацаа"><TextInput type="datetime-local" value={form.due_at} onChange={(value) => set('due_at', value)} /></Field>
          <Field label="Хугацаа (минут)" hint="Зарцуулсан хугацаа"><TextInput type="number" min="0" value={form.duration_minutes} onChange={(value) => set('duration_minutes', value)} /></Field>
          <Field label="Хариуцагч"><NativeSelect value={form.responsible_employee_id} onChange={(value) => set('responsible_employee_id', value)} options={employeeOptions} /></Field>
          <Field label="Төлөв"><NativeSelect value={form.status_id} onChange={(value) => set('status_id', value)} options={statusOptions} placeholder="Анхны төлөв" /></Field>
          <Field label="Биелүүлсэн"><TextInput type="datetime-local" value={form.completed_at} onChange={(value) => set('completed_at', value)} /></Field>
          <Field label="Тайлбар (биелэлт)"><TextInput value={form.completion_note} onChange={(value) => set('completion_note', value)} /></Field>
        </Section>

        <Section title="4. Холбогдох бүртгэл">
          <Field label="Reference"><TextInput value={form.reference} onChange={(value) => set('reference', value)} placeholder="Бүртгэлийн дугаар" /></Field>
          <Field label="Гэрээ"><NativeSelect value={form.contract_id} onChange={(value) => set('contract_id', value)} options={lookups.contracts.map((row) => ({ value: String(row.id), label: row.title }))} /></Field>
          <Field label="Ажил / төсөл"><NativeSelect value={form.project_id} onChange={(value) => set('project_id', value)} options={lookups.projects.map((row) => ({ value: String(row.id), label: `${row.code} ${row.name}` }))} /></Field>
          {activity?.task_id && <Field label="Холбоотой даалгавар"><Link to={`/tasks?task=${activity.task_id}`} onClick={onClose}>#{activity.task_id} {activity.task_title}</Link></Field>}
        </Section>

        <Section title="5. Хаалт болон хяналт">
          <Field label="Expected revenue"><TextInput type="number" min="0" step="0.01" value={form.expected_revenue} onChange={(value) => set('expected_revenue', value)} /></Field>
          <Field label="Валют"><TextInput value={form.currency} onChange={(value) => set('currency', value.toUpperCase().slice(0, 3))} /></Field>
          {activity && <>
            <Field label="Хэтэрсэн хоног"><div className={activity.overdue_days ? 'crm-overdue' : ''}>{activity.overdue_days}</div></Field>
            <Field label="Хянасан">{activity.reviewed_by_name ? `${activity.reviewed_by_name} · ${formatDateTime(activity.reviewed_at)}` : '—'}</Field>
          </>}
          <div className="crm-checks hr-form-wide">
            <CheckField label="Хаагдсан" checked={form.is_closed} onChange={(value) => set('is_closed', value)} />
            <CheckField label="Идэвхтэй" checked={form.is_active} onChange={(value) => set('is_active', value)} />
            {activity?.status && <StatusChip name={activity.status.name} color={activity.status.color} />}
          </div>
        </Section>
      </fieldset>

      {activity && <ActivityFiles activity={activity} canEdit={capabilities.activities.edit} />}

      <div className="crm-actions">
        <div>{activity && <ActivityLifecycle activity={activity} capabilities={capabilities} onDone={onClose} />}</div>
        <div>
          <Btn onClick={onClose}>Болих</Btn>
          {canEdit && <Btn variant="primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Хадгалж байна…' : 'Хадгалах'}</Btn>}
        </div>
      </div>
    </form>
  </Modal>
}

function ActivityLifecycle({ activity, capabilities, onDone }: { activity: CRMActivity; capabilities: CRMCapabilities; onDone: () => void }) {
  const clone = useCRMActivityAction('clone')
  const close = useCRMActivityAction('close')
  const reopen = useCRMActivityAction('reopen')
  const review = useCRMActivityAction('review')
  const task = useCreateCRMActivityTask()
  const remove = useDeleteCRMActivity()
  const run = async (promise: Promise<unknown>, message: string, finish = false) => {
    try { await promise; toast.success(message); if (finish) onDone() } catch (error) { toast.error(crmErrorText(error)) }
  }
  const finished = activity.is_closed || !activity.is_open
  return <>
    {capabilities.activities.create && <Btn onClick={() => void run(clone.mutateAsync({ id: activity.id }), 'Хувилж шинэ бүртгэл үүсгэлээ', true)}><Copy size={14} />Хувилах</Btn>}
    {capabilities.activities.edit && (finished
      ? <Btn onClick={() => void run(reopen.mutateAsync({ id: activity.id }), 'Дахин нээлээ', true)}><RotateCcw size={14} />Дахин нээх</Btn>
      : <Btn onClick={() => { const note = window.prompt('Биелэлтийн тайлбар (заавал биш)') ?? undefined; void run(close.mutateAsync({ id: activity.id, completion_note: note || undefined }), 'Хаалаа', true) }}><CheckCircle2 size={14} />Хаах</Btn>)}
    {capabilities.activities.edit && capabilities.employee_id && <Btn onClick={() => void run(review.mutateAsync({ id: activity.id }), 'Хянасан гэж тэмдэглэлээ', true)}><ClipboardCheck size={14} />Хянасан</Btn>}
    {capabilities.activities.edit && !activity.task_id && <Btn onClick={() => void run(task.mutateAsync({ id: activity.id }), 'Даалгавар үүсгэлээ', true)}><ListTodo size={14} />Даалгавар үүсгэх</Btn>}
    {capabilities.activities.archive && <Btn variant="danger" onClick={() => { if (window.confirm(`${activity.number}-ийг устгах уу?`)) void run(remove.mutateAsync(activity.id), 'Устгалаа', true) }}><Trash2 size={14} />Устгах</Btn>}
  </>
}

function ActivityFiles({ activity, canEdit }: { activity: CRMActivity; canEdit: boolean }) {
  const files = useCRMFiles('activities', activity.id)
  const upload = useUploadCRMFile('activities', activity.id)
  const remove = useDeleteCRMFile()
  const items = useMemo(() => files.data ?? [], [files.data])
  return <>
    <h3 className="hr-form-section">Файл</h3>
    <div className="crm-list" style={{ marginTop: 10 }}>
      {items.map((file) => <article key={file.id}>
        <div><strong>{file.filename}</strong><small>{Math.ceil(file.size / 1024)} KB · {formatDateTime(file.created_at)}</small></div>
        <div className="crm-row-actions">
          <button type="button" onClick={() => void downloadCRMFile(file).catch((error) => toast.error(crmErrorText(error)))}>Татах</button>
          {canEdit && <button type="button" aria-label="Устгах" onClick={() => void remove.mutateAsync(file.id).catch((error) => toast.error(crmErrorText(error)))}><Trash2 size={13} /></button>}
        </div>
      </article>)}
      {!items.length && <div className="crm-muted">Файл хавсаргаагүй</div>}
      {canEdit && <label className="secondary-action" style={{ cursor: 'pointer', width: 'fit-content' }}><Paperclip size={14} />Файл нэмэх
        <input type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload.mutateAsync(file).then(() => toast.success('Файл нэмлээ')).catch((error) => toast.error(crmErrorText(error))) }} />
      </label>}
    </div>
  </>
}
