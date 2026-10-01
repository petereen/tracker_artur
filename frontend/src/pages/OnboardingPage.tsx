import i18n from '../i18n'
import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { Btn, Card, PageHeader } from '../components/ui'
import { useOnboardingTemplate, useUpdateOnboardingTemplate } from '../api/hooks'

const defaultMessage = () => i18n.t('profile.onboarding.default')
// The bot substitutes these tokens server-side, so they stay the same in every UI language.
const NAME_TOKEN = i18n.t('profile.onboarding.tokenName')
const TIME_TOKEN = i18n.t('profile.onboarding.tokenTime')

export function OnboardingPage() {
  const { t } = useTranslation()
  const { data } = useOnboardingTemplate()
  const save = useUpdateOnboardingTemplate()

  const [msg, setMsg] = useState(defaultMessage)
  const [softWeeks, setSoftWeeks] = useState(1)

  useEffect(() => { if (data?.message) setMsg(data.message) }, [data])

  const preview = msg.replace(NAME_TOKEN, t('profile.onboarding.sampleName')).replace(TIME_TOKEN, '17:30')

  return (
    <div>
      <PageHeader title={t('profile.onboarding.title')} />
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-4">
          <Card>
            <div className="font-semibold text-[15px] mb-1">{t('profile.onboarding.greetingTitle')}</div>
            <div className="text-xs text-muted mb-3.5">{t('profile.onboarding.greetingHint')} {NAME_TOKEN}, {TIME_TOKEN}</div>
            <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={14}
              className="w-full bg-surface2 border border-border rounded-lg p-3 text-text font-mono text-xs leading-relaxed resize-y outline-none focus:border-accent" />
            <div className="flex gap-2 mt-3">
              <Btn onClick={() => setMsg(defaultMessage())}>{t('profile.onboarding.reset')}</Btn>
              <Btn variant="primary" onClick={() => save.mutate({ message: msg })} disabled={save.isPending}>{t('profile.onboarding.saveTemplate')}</Btn>
            </div>
          </Card>

          <Card>
            <div className="font-semibold text-[15px] mb-1">{t('profile.onboarding.softMode')}</div>
            <div className="text-xs text-muted mb-3.5">{t('profile.onboarding.softModeHint')}</div>
            <div className="flex items-center gap-3">
              <input type="range" min={0} max={4} value={softWeeks} onChange={(e) => setSoftWeeks(+e.target.value)} className="flex-1 accent-accent" />
              <span className="font-mono font-semibold text-accent min-w-[60px]">{softWeeks === 0 ? t('profile.onboarding.off') : t('profile.onboarding.weeks', { n: softWeeks })}</span>
            </div>
          </Card>
        </div>

        <Card>
          <div className="font-semibold text-[15px] mb-4">{t('profile.onboarding.preview')}</div>
          <div className="rounded-xl p-5" style={{ background: '#17212B', fontFamily: 'system-ui' }}>
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-9 h-9 rounded-full bg-accent flex items-center justify-center text-lg">🤖</div>
              <div>
                <div className="font-semibold text-white text-[13px]">OYUNS All-In-One</div>
                <div className="text-[11px]" style={{ color: '#8899A6' }}>{t('profile.onboarding.bot')}</div>
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
