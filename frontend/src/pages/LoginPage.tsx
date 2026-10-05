import { useEffect, useRef, useState } from 'react'
import { ArrowRight, LockKeyhole, Mail, Send } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { useAuthCapabilities, useEnterpriseLogin } from '../api/enterprise'
import { tenancyErrorMessage, useTenantBranding } from '../api/tenancy'
import { isNativePlatform, safeLocalStorage } from '../platform/runtime'
import { startNativeTelegramLogin, subscribeToNativeTelegramAuth, type NativeTelegramAuthState } from '../platform/telegram-auth'
import Grainient from '../components/Grainient'
import { LanguageSwitcher } from '../components/LanguageSwitcher'

/** Mixes two rgb() strings; null when either can't be read (jsdom, unresolved variables). */
function mixColors(a: string, b: string, weightA: number) {
  const parse = (value: string) => value.match(/\d+(\.\d+)?/g)?.slice(0, 3).map(Number)
  const first = parse(a)
  const second = parse(b)
  if (!first || !second || first.length < 3 || second.length < 3) return null
  const channel = (index: number) => Math.round(first[index] * weightA + second[index] * (1 - weightA)).toString(16).padStart(2, '0')
  return `#${channel(0)}${channel(1)}${channel(2)}`
}

const REMEMBER_KEY = 'oyuns.remember-me'
const TELEGRAM_ERROR_CODES = ['cancelled', 'invalid_state', 'invalid_callback', 'token_exchange_failed', 'invalid_id_token', 'not_configured', 'provider_unavailable', 'provider_error', 'account_unavailable', 'login_failed']

export function LoginPage() {
  const { t } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  // Kept signed in by default; the last choice on this device is remembered.
  const [remember, setRemember] = useState(() => safeLocalStorage().get(REMEMBER_KEY) !== '0')
  const login = useEnterpriseLogin()
  const native = isNativePlatform()
  const capabilities = useAuthCapabilities()
  const branding = useTenantBranding()
  // Tenant workspaces (other than OYUNS itself) show their own name.
  const workspaceName = branding.data?.name && !/^oyuns( erp)?$/i.test(branding.data.name.trim()) ? branding.data.name : null
  const [telegramState, setTelegramState] = useState<NativeTelegramAuthState>({ status: 'idle' })
  // Kept as a code, not text, so the message follows a language switch.
  const [webTelegramError, setWebTelegramError] = useState<string | null>(null)
  const stageRef = useRef<HTMLElement>(null)

  // On phones the top of the screen is the brand header, so the status bar / browser chrome takes its colour
  // instead of the app's light surface. Restored on unmount.
  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]')
    const stage = stageRef.current
    // Desktop has no status bar; only the stacked phone layout (see index.css) has a brand header at the top.
    if (!meta || !stage || !window.matchMedia('(max-width: 720px)').matches) return
    const previous = meta.getAttribute('content')
    const probe = document.createElement('i')
    stage.appendChild(probe)
    probe.style.color = 'var(--color-accent)'
    const accent = getComputedStyle(probe).color
    probe.style.color = 'var(--color-stage)'
    const base = getComputedStyle(probe).color
    probe.remove()
    const dark = document.documentElement.dataset.theme === 'dark'
    const color = mixColors(accent, base, dark ? 0.38 : 0.78)
    if (color) meta.setAttribute('content', color)
    return () => { if (previous) meta.setAttribute('content', previous) }
  }, [])

  useEffect(() => {
    if (!native) return
    return subscribeToNativeTelegramAuth(setTelegramState)
  }, [native])

  useEffect(() => {
    if (native) return
    const code = new URLSearchParams(window.location.search).get('telegram_auth_error')
    if (!code) return
    setWebTelegramError(TELEGRAM_ERROR_CODES.includes(code) ? code : 'login_failed')
    window.history.replaceState({}, document.title, `${window.location.pathname}${window.location.hash}`)
  }, [native])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      safeLocalStorage().set(REMEMBER_KEY, remember ? '1' : '0')
      await login.mutateAsync({ email: username, password, remember_me: remember })
    } catch (error: any) {
      toast.error(tenancyErrorMessage(error, t('auth.login.badCredentials')))
    }
  }

  return (
    <main className="login-stage auth-layout" ref={stageRef}>
      <section className="auth-form-side" aria-labelledby="login-title">
        <div className="auth-lang"><LanguageSwitcher /></div>
        <div className="auth-form-wrap">
          <header className="auth-form-head">
            {capabilities.isPending ? <div className="login-logo" aria-hidden /> : <img src={capabilities.data?.light_logo || '/oyuns-aio-logo.png'} alt="OYUNS All-in-One" className={capabilities.data?.light_logo ? 'login-logo' : 'login-logo is-default'} />}
            <div className="auth-form-heading">
              <h1 id="login-title">{t('auth.login.welcome')}</h1>
              <p>{workspaceName ?? t('auth.login.subtitle')}</p>
            </div>
          </header>
          <div className="auth-form-card">
            {!native && <div className="telegram-login telegram-login-primary">
              <button className="primary-action native-telegram-action telegram-brand-button" type="button" onClick={() => { window.location.assign('/api/v1/auth/telegram') }}>
                <Send size={17} aria-hidden /> {t('auth.login.telegram')}
              </button>
              {webTelegramError && <p className="login-inline-error" role="alert">{t(`auth.telegram.${webTelegramError}`)}</p>}
              <div className="login-divider"><span>{t('auth.login.orEmail')}</span></div>
            </div>}
            {native && capabilities.data?.telegram_native && <>
              <button className="primary-action native-telegram-action telegram-brand-button" type="button" onClick={() => void startNativeTelegramLogin()} disabled={telegramState.status === 'opening' || telegramState.status === 'waiting'}>
                {telegramState.status === 'opening' || telegramState.status === 'waiting' ? t('auth.login.telegramWaiting') : <><Send size={17} aria-hidden /> {t('auth.login.telegram')}</>}
              </button>
              {telegramState.status === 'error' && <p className="login-inline-error" role="alert">{telegramState.message}</p>}
              {telegramState.status === 'cancelled' && <p className="login-inline-hint">{t('auth.telegram.cancelled')}</p>}
              <div className="login-divider"><span>{t('auth.login.orPassword')}</span></div>
            </>}
            <form onSubmit={submit} className="login-form">
              <label>
                <span>{t('auth.login.username')}</span>
                <div className="field-with-icon"><Mail size={16} aria-hidden /><input value={username} onChange={(event) => setUsername(event.target.value)} type="text" autoComplete="username" required /></div>
              </label>
              <label>
                <span>{t('auth.login.password')}</span>
                <div className="field-with-icon"><LockKeyhole size={16} aria-hidden /><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></div>
              </label>
              <div className="auth-form-options">
                <label className="auth-remember"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /><span>{t('auth.login.remember')}</span></label>
                <a href="/forgot-password">{t('auth.login.forgot')}</a>
              </div>
              <button className="primary-action" type="submit" disabled={login.isPending}>
                {login.isPending ? t('auth.login.submitting') : t('auth.login.submit')} <ArrowRight size={16} aria-hidden />
              </button>
            </form>
            <footer><a href="/privacy">{t('auth.login.privacy')}</a><a href="/terms">{t('auth.login.terms')}</a></footer>
          </div>
        </div>
      </section>
      <aside className="auth-brand-side" aria-label={t('auth.login.brandAria')}>
        <Grainient className="auth-grainient" />
        <div className="auth-brand-content">
          <div className="auth-brand-copy">
            <span className="auth-brand-label">{t('auth.login.brandLabel')}</span>
            <h2>{t('auth.login.headline1')}<br />{t('auth.login.headline2')}</h2>
            <p>{t('auth.login.brandText')}</p>
          </div>
          <div className="auth-workspace-preview" aria-hidden="true">
            <div className="auth-preview-top"><span className="auth-preview-dot" /><span>{t('auth.login.previewTitle')}</span><span className="auth-preview-menu">•••</span></div>
            <div className="auth-preview-body">
              <div className="auth-preview-sidebar"><i /><i /><i /><i /></div>
              <div className="auth-preview-main">
                <div className="auth-preview-title"><i /><b /><b /></div>
                <div className="auth-preview-grid"><i /><i /><i /></div>
                <div className="auth-preview-list"><i /><i /><i /></div>
              </div>
            </div>
            <div className="auth-preview-caption"><span className="auth-preview-check">✓</span><span><b>{t('auth.login.previewCaptionTitle')}</b><small>{t('auth.login.previewCaptionText')}</small></span><span className="auth-preview-arrow">↗</span></div>
          </div>
          <div className="auth-brand-footer"><span>{t('auth.login.tagline')}</span><span>OYUNS ALL-IN-ONE © 2026</span></div>
        </div>
      </aside>
    </main>
  )
}
