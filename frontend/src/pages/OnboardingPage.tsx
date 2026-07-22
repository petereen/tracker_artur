import { useState, useEffect } from 'react'
import { Btn, Card, PageHeader } from '../components/ui'
import { useOnboardingTemplate, useUpdateOnboardingTemplate } from '../api/hooks'

const DEFAULT = `Сайн байна уу, {нэр}! 👋

Би компанийн «Даалгавар хянагч» бот байна.

Өдөр бүр {цаг}-т танд 5 асуулттай богино асуулга илгээнэ. Бөглөхөд ердөө 2–3 минут зарцуулна.

Танд боломжтой зүйлс:
📊 Өөрийн статистикаа харах — /my_stats
🔥 Бөглөлтийн цувралаа хянах
🏆 Багийн чансааг харах — /leaderboard

/start командыг дарж эхлээрэй!`

export function OnboardingPage() {
  const { data } = useOnboardingTemplate()
  const save = useUpdateOnboardingTemplate()

  const [msg, setMsg] = useState(DEFAULT)
  const [softWeeks, setSoftWeeks] = useState(1)

  useEffect(() => { if (data?.message) setMsg(data.message) }, [data])

  const preview = msg.replace('{нэр}', 'Бат').replace('{цаг}', '17:30')

  return (
    <div>
      <PageHeader title="Танилцуулга" sub="Мэндчилгээний загвар ба зөөлөн эхлэл" />
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-4">
          <Card>
            <div className="font-semibold text-[15px] mb-1">Мэндчилгээний мессеж</div>
            <div className="text-xs text-muted mb-3.5">Эхний /start дээр илгээнэ. Хувьсагч: {'{нэр}'}, {'{цаг}'}</div>
            <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={14}
              className="w-full bg-surface2 border border-border rounded-lg p-3 text-text font-mono text-xs leading-relaxed resize-y outline-none focus:border-accent" />
            <div className="flex gap-2 mt-3">
              <Btn onClick={() => setMsg(DEFAULT)}>Сэргээх</Btn>
              <Btn variant="primary" onClick={() => save.mutate({ message: msg })} disabled={save.isPending}>Загвар хадгалах</Btn>
            </div>
          </Card>

          <Card>
            <div className="font-semibold text-[15px] mb-1">Зөөлөн горим</div>
            <div className="text-xs text-muted mb-3.5">Эхний N долоо хоногт сануулгыг зөвхөн ажилтанд илгээнэ</div>
            <div className="flex items-center gap-3">
              <input type="range" min={0} max={4} value={softWeeks} onChange={(e) => setSoftWeeks(+e.target.value)} className="flex-1 accent-accent" />
              <span className="font-mono font-semibold text-accent min-w-[60px]">{softWeeks === 0 ? 'Унтраалттай' : `${softWeeks} долоо хоног`}</span>
            </div>
          </Card>
        </div>

        <Card>
          <div className="font-semibold text-[15px] mb-4">Telegram урьдчилан харах</div>
          <div className="rounded-xl p-5" style={{ background: '#17212B', fontFamily: 'system-ui' }}>
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-9 h-9 rounded-full bg-accent flex items-center justify-center text-lg">🤖</div>
              <div>
                <div className="font-semibold text-white text-[13px]">Даалгавар хянагч</div>
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
