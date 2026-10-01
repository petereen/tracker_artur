import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ClipboardCheck } from 'lucide-react'
import { useStartCheckin, useSubmitCheckin, useTodayCheckin } from '../../../api/enterprise'
import { WidgetHeader } from './shared'

const DRAFT_KEY = 'oyuns-checkin-draft'

/** Daily check-in: the first questions as a focus prompt, the full form inline. */
export function CheckinWidget() {
  const { t } = useTranslation()
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
    <section className="today-widget daily-focus" aria-label={t('today.widget.checkin.title')}>
      <WidgetHeader icon={ClipboardCheck} title={t('today.checkin.heading')} />
      <h2>{t('today.checkin.focus')}</h2>
      {template?.questions?.slice(0, 2).map((question: any, index: number) => (
        <div className="focus-question" key={question.id}>
          <span>{index + 1}</span>
          <div>
            <strong>{question.prompt?.mn || question.prompt?.en}</strong>
            <p>{question.is_required ? t('today.checkin.required') : t('today.checkin.optional')}</p>
          </div>
        </div>
      ))}
      {!template && <p>{t('today.checkin.noTemplate')}</p>}
      <button className="secondary-action" onClick={openCheckin} disabled={!template || submitted}>
        {submitted ? t('today.checkin.submitted') : t('today.checkin.fill')}
      </button>
      {open && template && (
        <form className="checkin-form" onSubmit={saveCheckin}>
          {template.questions.map((question: any) => (
            <label key={question.id}>
              <strong>{question.prompt?.mn || question.prompt?.en}</strong>
              {question.choices?.length ? (
                <select required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)}>
                  <option value="">{t('today.checkin.select')}</option>
                  {question.choices.map((choice: any) => <option key={String(choice)}>{String(choice)}</option>)}
                </select>
              ) : ['integer', 'decimal', 'number'].includes(question.answer_type) ? (
                <input type="number" step={question.answer_type === 'integer' ? '1' : 'any'} required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)} />
              ) : question.answer_type === 'boolean' ? (
                <select required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)}>
                  <option value="">{t('today.checkin.select')}</option><option value="true">{t('today.checkin.yes')}</option><option value="false">{t('today.checkin.no')}</option>
                </select>
              ) : (
                <textarea required={question.is_required} value={answers[question.id] || ''} onChange={(event) => setAnswer(question.id, event.target.value)} />
              )}
            </label>
          ))}
          <div>
            <button type="button" className="secondary-action compact" onClick={() => setOpen(false)}>{t('today.checkin.cancel')}</button>
            <button className="primary-action compact" disabled={submitCheckin.isPending}>{t('today.checkin.save')}</button>
          </div>
        </form>
      )}
    </section>
  )
}
