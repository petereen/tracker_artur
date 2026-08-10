import { useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useQuestions, useCreateQuestion, useDeleteQuestion, useEmployees, useReorderQuestions, useUpdateQuestion } from '../api/hooks'

const TYPE_OPTIONS = [
  { value: 'integer', label: 'Бүхэл тоо' },
  { value: 'decimal', label: 'Бутархай тоо' },
  { value: 'boolean', label: 'Тийм / Үгүй' },
  { value: 'choice',  label: 'Сонголт' },
  { value: 'text',    label: 'Текст' },
]
const typeColor: Record<string, any> = { integer: 'blue', decimal: 'blue', boolean: 'purple', choice: 'yellow', text: 'muted' }

export function QuestionsPage() {
  const { data: questions = [] } = useQuestions()
  const { data: employees = [] } = useEmployees()
  const create = useCreateQuestion()
  const update = useUpdateQuestion()
  const del = useDeleteQuestion()
  const reorder = useReorderQuestions()

  const [showModal, setShowModal] = useState(false)
  const [editingQuestion, setEditingQuestion] = useState<any | null>(null)
  const [form, setForm] = useState({ text: '', answer_type: 'integer', is_required: true, employee_ids: [] as number[] })

  const required = questions.filter((q: any) => q.is_required).length

  const move = (i: number, dir: -1 | 1) => {
    const arr = [...questions]
    const j = i + dir
    if (j < 0 || j >= arr.length) return
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    reorder.mutate(arr.map((q: any) => q.id))
  }

  const submit = async () => {
    if (editingQuestion) {
      await update.mutateAsync({ id: editingQuestion.id, ...form })
    } else {
      await create.mutateAsync({ ...form, sort_order: questions.length })
    }
    setShowModal(false)
    setEditingQuestion(null)
    setForm({ text: '', answer_type: 'integer', is_required: true, employee_ids: [] })
  }

  const openCreate = () => {
    setEditingQuestion(null)
    setForm({ text: '', answer_type: 'integer', is_required: true, employee_ids: [] })
    setShowModal(true)
  }

  const openEdit = (question: any) => {
    setEditingQuestion(question)
    setForm({
      text: question.text,
      answer_type: question.answer_type,
      is_required: question.is_required,
      employee_ids: question.employee_ids || [],
    })
    setShowModal(true)
  }

  return (
    <div>
      <PageHeader title="Асуултууд" sub="Оройн чек-иний үндсэн асуултууд">
        <Btn variant="primary" onClick={openCreate}>+ Асуулт нэмэх</Btn>
      </PageHeader>

      {required >= 5 && (
        <div className="bg-yellow-dim border border-[#5a4010] rounded-xl px-4 py-3 mb-5 flex items-center gap-2.5">
          <span className="text-base">⚠️</span>
          <span className="text-[13px] text-yellow"><b>Заавал хариулах 5 асуулт</b> гэсэн дээд хязгаарт хүрлээ. 6-аас дээш бол бөглөлт 50%-иас доошилдог.</span>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {questions.map((q: any, i: number) => (
          <Card key={q.id} className="!p-4">
            <div className="flex items-start gap-3.5">
              <div className="w-7 h-7 rounded-lg bg-surface3 flex items-center justify-center text-[13px] font-bold text-muted flex-shrink-0 mt-0.5">{i + 1}</div>
              <div className="flex-1">
                <div className="font-medium text-sm mb-2">{q.text}</div>
                <div className="flex gap-2 flex-wrap">
                  <Badge color={typeColor[q.answer_type] || 'muted'}>
                    {TYPE_OPTIONS.find((t) => t.value === q.answer_type)?.label}
                  </Badge>
                  {q.is_required ? <Badge color="red">Заавал</Badge> : <Badge color="muted">Заавал биш</Badge>}
                  <Badge color="muted">
                    {q.employee_ids?.length
                      ? `Зөвхөн: ${q.employee_ids.map((id: number) => employees.find((e: any) => e.id === id)?.name || id).join(', ')}`
                      : 'Бүх ажилтан'}
                  </Badge>
                </div>
              </div>
              <div className="flex gap-1.5 flex-shrink-0">
                <Btn onClick={() => openEdit(q)}>Засах</Btn>
                <Btn variant="danger" onClick={() => {
                  if (window.confirm('Энэ check-in асуултыг устгах уу?')) del.mutate(q.id)
                }}>Устгах</Btn>
                <div className="flex flex-col gap-0.5">
                  <button disabled={i === 0} onClick={() => move(i, -1)}
                    className="bg-surface3 border-none rounded text-muted text-[10px] px-1.5 py-0.5 cursor-pointer disabled:opacity-30">▲</button>
                  <button disabled={i === questions.length - 1} onClick={() => move(i, 1)}
                    className="bg-surface3 border-none rounded text-muted text-[10px] px-1.5 py-0.5 cursor-pointer disabled:opacity-30">▼</button>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-5 px-4 py-3.5 bg-accent-dim border border-[#1c3a6b] rounded-xl text-[13px] text-accent">
        <b>Үндсэн зарчим:</b> заавал хариулах асуулт 5 хүртэл байна. Текстэн хариултаас сонголтын товч илүү тохиромжтой.
      </div>

      {showModal && (
        <Modal title={editingQuestion ? 'Асуулт засах' : 'Шинэ асуулт'} onClose={() => { setShowModal(false); setEditingQuestion(null) }}>
          <div className="flex flex-col gap-3.5">
            <Input label="Асуултын текст" value={form.text} onChange={(v) => setForm((f) => ({ ...f, text: v }))} placeholder="Хэдэн дуудлага хийсэн бэ?" fullWidth />
            <Select label="Хариултын төрөл" value={form.answer_type} onChange={(v) => setForm((f) => ({ ...f, answer_type: v }))} options={TYPE_OPTIONS} fullWidth />
            <div className="flex items-center gap-3">
              <input type="checkbox" id="req" checked={form.is_required} onChange={(e) => setForm((f) => ({ ...f, is_required: e.target.checked }))} className="accent-accent" />
              <label htmlFor="req" className="text-[13px] text-muted cursor-pointer">Заавал хариулах</label>
            </div>
            <div className="flex flex-col gap-2">
              <div className="text-xs text-muted font-medium">Хэн хариулах вэ?</div>
              <div className="text-[12px] text-muted">Ажилтан сонгохгүй бол бүх ажилтанд асууна.</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-40 overflow-y-auto">
                {employees.filter((employee: any) => employee.is_active).map((employee: any) => (
                  <label key={employee.id} className="flex items-center gap-2 text-[13px] text-text cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.employee_ids.includes(employee.id)}
                      onChange={(event) => setForm((current) => ({
                        ...current,
                        employee_ids: event.target.checked
                          ? [...current.employee_ids, employee.id]
                          : current.employee_ids.filter((id) => id !== employee.id),
                      }))}
                      className="accent-accent"
                    />
                    {employee.name}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={() => { setShowModal(false); setEditingQuestion(null) }}>Цуцлах</Btn>
              <Btn variant="primary" onClick={submit} disabled={!form.text || create.isPending || update.isPending}>{editingQuestion ? 'Хадгалах' : 'Нэмэх'}</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
