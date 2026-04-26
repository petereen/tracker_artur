import { useState } from 'react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useQuestions, useCreateQuestion, useDeleteQuestion, useReorderQuestions } from '../api/hooks'

const TYPE_OPTIONS = [
  { value: 'integer', label: 'Число (целое)' },
  { value: 'decimal', label: 'Число (дробное)' },
  { value: 'boolean', label: 'Да / Нет' },
  { value: 'choice',  label: 'Выбор' },
  { value: 'text',    label: 'Текст' },
]
const typeColor: Record<string, any> = { integer: 'blue', decimal: 'blue', boolean: 'purple', choice: 'yellow', text: 'muted' }

export function QuestionsPage() {
  const { data: questions = [] } = useQuestions()
  const create = useCreateQuestion()
  const del = useDeleteQuestion()
  const reorder = useReorderQuestions()

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ text: '', answer_type: 'integer', is_required: true })

  const required = questions.filter((q: any) => q.is_required).length

  const move = (i: number, dir: -1 | 1) => {
    const arr = [...questions]
    const j = i + dir
    if (j < 0 || j >= arr.length) return
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    reorder.mutate(arr.map((q: any) => q.id))
  }

  const submit = async () => {
    await create.mutateAsync({ ...form, sort_order: questions.length })
    setShowModal(false)
    setForm({ text: '', answer_type: 'integer', is_required: true })
  }

  return (
    <div>
      <PageHeader title="Вопросы" sub="Базовый набор для вечернего чек-ина">
        <Btn variant="primary" onClick={() => setShowModal(true)}>+ Добавить вопрос</Btn>
      </PageHeader>

      {required >= 5 && (
        <div className="bg-yellow-dim border border-[#5a4010] rounded-xl px-4 py-3 mb-5 flex items-center gap-2.5">
          <span className="text-base">⚠️</span>
          <span className="text-[13px] text-yellow">Достигнут лимит в <b>5 обязательных вопросов</b>. При 6+ заполняемость падает ниже 50%.</span>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {questions.map((q: any, i: number) => (
          <Card key={q.id} className="!p-4">
            <div className="flex items-start gap-3.5">
              <div className="w-7 h-7 rounded-lg bg-surface3 flex items-center justify-center text-[13px] font-bold text-muted flex-shrink-0 mt-0.5">{i + 1}</div>
              <div className="flex-1">
                <div className="font-medium text-sm mb-2">{q.text}</div>
                <div className="flex gap-2">
                  <Badge color={typeColor[q.answer_type] || 'muted'}>
                    {TYPE_OPTIONS.find((t) => t.value === q.answer_type)?.label}
                  </Badge>
                  {q.is_required ? <Badge color="red">Обязательный</Badge> : <Badge color="muted">Необязательный</Badge>}
                </div>
              </div>
              <div className="flex gap-1.5 flex-shrink-0">
                {!q.is_required && <Btn variant="danger" onClick={() => del.mutate(q.id)}>Удалить</Btn>}
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
        <b>Продуктовый принцип:</b> максимум 5 обязательных вопросов. Кнопки предпочтительнее текстового ввода.
      </div>

      {showModal && (
        <Modal title="Новый вопрос" onClose={() => setShowModal(false)}>
          <div className="flex flex-col gap-3.5">
            <Input label="Текст вопроса" value={form.text} onChange={(v) => setForm((f) => ({ ...f, text: v }))} placeholder="Сколько звонков сделали?" fullWidth />
            <Select label="Тип ответа" value={form.answer_type} onChange={(v) => setForm((f) => ({ ...f, answer_type: v }))} options={TYPE_OPTIONS} fullWidth />
            <div className="flex items-center gap-3">
              <input type="checkbox" id="req" checked={form.is_required} onChange={(e) => setForm((f) => ({ ...f, is_required: e.target.checked }))} className="accent-accent" />
              <label htmlFor="req" className="text-[13px] text-muted cursor-pointer">Обязательный</label>
            </div>
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={() => setShowModal(false)}>Отмена</Btn>
              <Btn variant="primary" onClick={submit} disabled={!form.text || create.isPending}>Добавить</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
