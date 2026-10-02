// Олон нийтэд нээлттэй эрх зүйн хуудсууд. Нийтлэхийн өмнө хуульчаар хянуулна.
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

const CONTACT = 'info@oyuns.mn'
const DOMAIN = 'erp.oyuns.mn'

/** `**bold**`, `{domain}` and `{email}` markers in a translated sentence become inline elements. */
function rich(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*|\{domain\}|\{email\})/).map((part, index) => {
    if (part === '{domain}') return <b key={index}>{DOMAIN}</b>
    if (part === '{email}') return <a key={index} href={`mailto:${CONTACT}`}>{CONTACT}</a>
    if (part.startsWith('**')) return <b key={index}>{part.slice(2, -2)}</b>
    return part
  })
}

function LegalShell({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className="min-h-screen bg-gray-950 text-gray-200">
      <div className="max-w-2xl mx-auto px-5 py-8">
        <a href="/" className="text-sky-400 text-sm">{t('legal.back')}</a>
        <h1 className="text-2xl font-bold text-white mt-4 mb-1">{title}</h1>
        <div className="text-xs text-gray-500 mb-6">{t('legal.updatedLabel', { date: t('legal.updated') })}</div>
        <div className="space-y-4 text-[14px] leading-relaxed [&_h2]:text-white [&_h2]:font-semibold [&_h2]:mt-6 [&_h2]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1 [&_a]:text-sky-400">
          {children}
        </div>
        <div className="mt-10 flex gap-4 text-sm">
          <a href="/privacy" className="text-sky-400">{t('legal.nav.privacy')}</a>
          <a href="/terms" className="text-sky-400">{t('legal.nav.terms')}</a>
        </div>
      </div>
    </div>
  )
}

function Section({ heading, items, children }: { heading: string; items?: string[]; children?: string }) {
  const { t } = useTranslation()
  return <>
    <h2>{t(heading)}</h2>
    {children && <p>{rich(t(children))}</p>}
    {items && <ul>{items.map((key) => <li key={key}>{rich(t(key))}</li>)}</ul>}
  </>
}

export function PrivacyPage() {
  const { t } = useTranslation()
  return (
    <LegalShell title={t('legal.nav.privacy')}>
      <p>{rich(t('legal.privacy.intro', { operator: t('legal.operator') }))}</p>

      <Section heading="legal.privacy.h1" items={['legal.privacy.d1', 'legal.privacy.d2', 'legal.privacy.d3', 'legal.privacy.d4', 'legal.privacy.d5']} />
      <Section heading="legal.privacy.h2" items={['legal.privacy.p1', 'legal.privacy.p2', 'legal.privacy.p3', 'legal.privacy.p4']} />
      <Section heading="legal.privacy.h3" items={['legal.privacy.t1', 'legal.privacy.t2', 'legal.privacy.t3']} />
      <Section heading="legal.privacy.h4">legal.privacy.storage</Section>
      <Section heading="legal.privacy.h5">legal.privacy.retention</Section>
      <Section heading="legal.privacy.h6">legal.privacy.rights</Section>
      <Section heading="legal.privacy.h7">legal.privacy.contact</Section>
    </LegalShell>
  )
}

export function TermsPage() {
  const { t } = useTranslation()
  return (
    <LegalShell title={t('legal.nav.terms')}>
      <p>{rich(t('legal.terms.intro'))}</p>

      <Section heading="legal.terms.h1">legal.terms.purpose</Section>
      <Section heading="legal.terms.h2" items={['legal.terms.a1', 'legal.terms.a2', 'legal.terms.a3']} />
      <Section heading="legal.terms.h3" items={['legal.terms.u1', 'legal.terms.u2', 'legal.terms.u3']} />
      <Section heading="legal.terms.h4">legal.terms.ai</Section>
      <Section heading="legal.terms.h5">legal.terms.changes</Section>
      <Section heading="legal.terms.h6">legal.terms.contact</Section>
    </LegalShell>
  )
}
