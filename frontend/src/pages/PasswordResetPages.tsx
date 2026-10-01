import { useState } from 'react'
import { KeyRound, Mail } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { usePasswordResetConfirm, usePasswordResetRequest } from '../api/enterprise'
import { LanguageSwitcher } from '../components/LanguageSwitcher'

function AuthCard({ children, title, description }: { children?: React.ReactNode; title: string; description: string }) {
  const { t } = useTranslation()
  return <main className="login-stage"><section className="login-card" aria-labelledby="auth-title">
    <img src="/oyuns-aio-logo.png" alt="OYUNS All-in-One" className="login-logo" />
    <h1 id="auth-title">{title}</h1><p>{description}</p>{children}
    <a className="auth-help-link" href="/">{t('auth.reset.backToLogin')}</a>
    <LanguageSwitcher />
  </section></main>
}

export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const request = usePasswordResetRequest()
  if (request.isSuccess) return <AuthCard title={t('auth.reset.checkEmailTitle')} description={t('auth.reset.checkEmailText')} />
  return <AuthCard title={t('auth.reset.requestTitle')} description={t('auth.reset.requestText')}>
    <form className="login-form" onSubmit={(event) => { event.preventDefault(); request.mutate(email) }}>
      <label><span>{t('auth.reset.email')}</span><div className="field-with-icon"><Mail size={16} aria-hidden /><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></div></label>
      <button className="primary-action" disabled={request.isPending}>{request.isPending ? t('auth.reset.sending') : t('auth.reset.send')}</button>
    </form>
  </AuthCard>
}

export function ResetPasswordPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const reset = usePasswordResetConfirm()
  if (!token) return <AuthCard title={t('auth.reset.badLinkTitle')} description={t('auth.reset.badLinkText')} />
  if (reset.isSuccess) return <AuthCard title={t('auth.reset.doneTitle')} description={t('auth.reset.doneText')} />
  return <AuthCard title={t('auth.reset.newTitle')} description={t('auth.reset.newText')}>
    <form className="login-form" onSubmit={(event) => { event.preventDefault(); if (password === confirmation) reset.mutate({ token, new_password: password }) }}>
      <label><span>{t('auth.reset.newPassword')}</span><div className="field-with-icon"><KeyRound size={16} aria-hidden /><input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(event) => setPassword(event.target.value)} required /></div></label>
      <label><span>{t('auth.reset.repeat')}</span><div className="field-with-icon"><KeyRound size={16} aria-hidden /><input type="password" autoComplete="new-password" minLength={10} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></div></label>
      {confirmation && password !== confirmation && <p role="alert" className="auth-error">{t('auth.reset.mismatch')}</p>}
      {reset.isError && <p role="alert" className="auth-error">{t('auth.reset.invalidLink')}</p>}
      <button className="primary-action" disabled={reset.isPending || password !== confirmation}>{reset.isPending ? t('auth.reset.saving') : t('auth.reset.submit')}</button>
    </form>
  </AuthCard>
}
