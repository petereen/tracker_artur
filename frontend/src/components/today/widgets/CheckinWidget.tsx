import { useEffect, useState } from 'react'
import { ClipboardCheck } from 'lucide-react'
import { useStartCheckin, useSubmitCheckin, useTodayCheckin } from '../../../api/enterprise'
import { WidgetHeader } from './shared'

const DRAFT_KEY = 'oyuns-checkin-draft'

/** Daily check-in: the first questions as a focus prompt, the full form inline. */
export function CheckinWidget() {
  const todayCheckin = useTodayCheckin()
  const startCheckin = useStartCheckin()
  const submitCheckin = useSubmitCheckin()
  const [open, setOpen] = useState(false)
  const [answers, setAnswers] = useState<Record<number, string>>(() => {
    try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') } catch { return {} }
  })
  useEffect(() => {
    if (Object.keys(answers).length) localStorage.setItem(DRAFT_KEY, JSON.stringify(answers))
  }, [answers])

  const template = todayCheckin.data?.template
  const submitted = todayCheckin.data?.checkin?.status === 'submitted'
  const openCheckin = async () => {
    if (submitted) return
    if (!todayCheckin.data?.checkin && template?.id) await startCheckin.mutateAsync(template.id)
    setOpen(true)
  }
  const saveCheckin = async (event: React.FormEvent) => {
    event.preventDefault()
    const current = todayCheckin.data?.checkin || (await startCheckin.mutateAsync(template.id))
    const questions = template?.questions ?? []
    await submitCheckin.mutateAsync({
      id: current.id,
      answers: questions.map((question: any) =>
        question.answer_type === 'integer' || question.answer_type === 'decimal'
          ? { question_id: question.id, value_numeric: Number(answers[question.id]) }
          : { question_id: question.id, value_text: answers[question.id] },
      ),
    })
    localStorage.removeItem(DRAFT_KEY)
    setAnswers({})
    setOpen(false)
  }
  const setAnswer = (id: number, value: string) => setAnswers({ ...answers, [id]: value })

  return (
    <section className="today-widget daily-focus" aria-label="Өдрийн check-in">
      <WidgetHeader icon={ClipboardCheck} title="Өнөөдрийн төлөвлөгөө" />
      <h2>Хамгийн чухал ажлаа тодорхой болго</h2>
      {template?.questions?.slice(0, 2).map((question: any, index: number) => (
        <div className="focus-question" key={question.id}>
          <span>{index + 1}</span>
          <div>
            <strong>{question.prompt?.mn || question.prompt?.en}</strong>
            <p>{question.is_required ? 'Заавал хариулна' : 'Сонголттой'}</p>
          </div>
        </div>
      ))}
      {!template && <p>Check-in асуулт тохируулаагүй байна.</p>}
      <button className="secondary-action" onClick={openCheckin} disabled={!template || submitted}>
        {submitted ? 'Өнөөдрийн check-in бөглөгдсөн' : 'Өдрийн check-in бөглөх'}
      </button>
      {open && template && (
        <form className="checkin-form" onSubmit={saveCheckin}>
          {template.questions.map((question: any) => (
            <label key={question.id}>
              <strong>{question.prompt?.mn || question.prompt?.en}</strong>
              {question.choices?.length ? (
                <select required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)}>
                  <option value="">Сонгох</option>
                  {question.choices.map((choice: any) => <option key={String(choice)}>{String(choice)}</option>)}
                </select>
              ) : ['integer', 'decimal', 'number'].includes(question.answer_type) ? (
                <input type="number" step={question.answer_type === 'integer' ? '1' : 'any'} required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)} />
              ) : question.answer_type === 'boolean' ? (
                <select required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)}>
                  <option value="">Сонгох</option><option value="true">Тийм</option><option value="false">Үгүй</option>
                </select>
              ) : (
                <textarea required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)} />
              )}
            </label>
          ))}
          <div>
            <button type="button" className="secondary-action compact" onClick={() => setOpen(false)}>Цуцлах</button>
            <button className="primary-action compact" disabled={submitCheckin.isPending}>Хадгалах</button>
          </div>
        </form>
      )}
    </section>
  )
}
