import { useState, useEffect } from 'react'
import { Btn, Card, PageHeader } from '../components/ui'
import { useOnboardingTemplate, useUpdateOnboardingTemplate } from '../api/hooks'

const DEFAULT = `Привет, {имя}! 👋

Я — бот трекера активности отдела продаж.

Каждый день в {время} я буду присылать тебе короткий опрос из 5 вопросов — он займёт буквально 2–3 минуты.

Что ты получаешь:
📊 Видишь свою динамику — /my_stats
🔥 Следишь за серией заполнений
🏆 Смотришь на рейтинг отдела — /leaderboard

Нажми /start, чтобы начать!`

export function OnboardingPage() {
  const { data } = useOnboardingTemplate()
  const save = useUpdateOnboardingTemplate()

  const [msg, setMsg] = useState(DEFAULT)
  const [softWeeks, setSoftWeeks] = useState(1)

  useEffect(() => { if (data?.message) setMsg(data.message) }, [data])

  const preview = msg.replace('{имя}', 'Иван').replace('{время}', '17:30')

  return (
    <div>
      <PageHeader title="Онбординг" sub="Шаблон приветствия и мягкий старт" />
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-4">
          <Card>
            <div className="font-semibold text-[15px] mb-1">Приветственное сообщение</div>
            <div className="text-xs text-muted mb-3.5">Отправляется при первом /start. Переменные: {'{имя}'}, {'{время}'}</div>
            <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={14}
              className="w-full bg-surface2 border border-border rounded-lg p-3 text-text font-mono text-xs leading-relaxed resize-y outline-none focus:border-accent" />
            <div className="flex gap-2 mt-3">
              <Btn onClick={() => setMsg(DEFAULT)}>Сбросить</Btn>
              <Btn variant="primary" onClick={() => save.mutate({ message: msg })} disabled={save.isPending}>Сохранить шаблон</Btn>
            </div>
          </Card>

          <Card>
            <div className="font-semibold text-[15px] mb-1">Мягкий режим</div>
            <div className="text-xs text-muted mb-3.5">Первые N недель — напоминания только сотруднику, без алертов руководителю</div>
            <div className="flex items-center gap-3">
              <input type="range" min={0} max={4} value={softWeeks} onChange={(e) => setSoftWeeks(+e.target.value)} className="flex-1 accent-accent" />
              <span className="font-mono font-semibold text-accent min-w-[60px]">{softWeeks === 0 ? 'Выкл.' : `${softWeeks} нед.`}</span>
            </div>
          </Card>
        </div>

        <Card>
          <div className="font-semibold text-[15px] mb-4">Предпросмотр в Telegram</div>
          <div className="rounded-xl p-5" style={{ background: '#17212B', fontFamily: 'system-ui' }}>
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-9 h-9 rounded-full bg-accent flex items-center justify-center text-lg">🤖</div>
              <div>
                <div className="font-semibold text-white text-[13px]">Трекер Активности</div>
                <div className="text-[11px]" style={{ color: '#8899A6' }}>бот</div>
              </div>
            </div>
            <div className="rounded-[0_12px_12px_12px] px-3.5 py-2.5 text-white text-[13px] leading-relaxed whitespace-pre-wrap" style={{ background: '#2B5278' }}>
              {preview}
            </div>
            <div className="text-right text-[11px] mt-1.5" style={{ color: '#8899A6' }}>17:30 ✓✓</div>
          </div>
        </Card>
      </div>
    </div>
  )
}
