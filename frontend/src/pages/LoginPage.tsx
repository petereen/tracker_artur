import { useEffect, useState } from 'react'
import { ArrowRight, LockKeyhole, Mail, Send } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthCapabilities, useEnterpriseLogin } from '../api/enterprise'
import { isNativePlatform } from '../platform/runtime'
import { startNativeTelegramLogin, subscribeToNativeTelegramAuth, type NativeTelegramAuthState } from '../platform/telegram-auth'
import Grainient from '../components/Grainient'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useEnterpriseLogin()
  const native = isNativePlatform()
  const capabilities = useAuthCapabilities()
  const [telegramState, setTelegramState] = useState<NativeTelegramAuthState>({ status: 'idle' })
  const [webTelegramError, setWebTelegramError] = useState<string | null>(null)

  useEffect(() => {
    if (!native) return
    return subscribeToNativeTelegramAuth(setTelegramState)
  }, [native])

  useEffect(() => {
    if (native) return
    const code = new URLSearchParams(window.location.search).get('telegram_auth_error')
    if (!code) return
    const messages: Record<string, string> = {
      cancelled: 'Telegram нэвтрэлтийг цуцалсан. Дахин оролдоно уу.',
      invalid_state: 'Telegram нэвтрэлтийн төлөв хүчингүй байна. Дахин оролдоно уу.',
      invalid_callback: 'Telegram-ээс буцсан холбоос хүчингүй байна.',
      token_exchange_failed: 'Telegram нэвтрэлтийг баталгаажуулж чадсангүй.',
      invalid_id_token: 'Telegram баталгаажуулалтын токен хүчингүй байна.',
      not_configured: 'Telegram нэвтрэлт одоогоор тохируулагдаагүй байна.',
      provider_unavailable: 'Telegram нэвтрэлт түр боломжгүй байна.',
      provider_error: 'Telegram нэвтрэлт амжилтгүй боллоо.',
      account_unavailable: 'Таны Telegram бүртгэл идэвхтэй ажилтантай холбогдоогүй байна.',
      login_failed: 'Telegram-аар нэвтрэх үед алдаа гарлаа.',
    }
    setWebTelegramError(messages[code] || messages.login_failed)
    window.history.replaceState({}, document.title, `${window.location.pathname}${window.location.hash}`)
  }, [native])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      await login.mutateAsync({ email: username, password })
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'И-мэйл эсвэл нууц үг буруу байна')
    }
  }

  return (
    <main className="login-stage auth-layout">
      <section className="auth-form-side" aria-labelledby="login-title">
        <div className="auth-form-wrap">
          <img src={capabilities.data?.light_logo || '/oyuns-aio-logo.png'} alt="OYUNS All-in-One" className="login-logo" />
          <div className="auth-form-heading">
            <h1 id="login-title">Тавтай морил</h1>
          </div>
          {!native && <div className="telegram-login telegram-login-primary">
            <button className="primary-action native-telegram-action telegram-brand-button" type="button" onClick={() => { window.location.assign('/api/v1/auth/telegram') }}>
              <Send size={17} aria-hidden /> Telegram-аар нэвтрэх
            </button>
            {webTelegramError && <p className="login-inline-error" role="alert">{webTelegramError}</p>}
            <div className="login-divider"><span>эсвэл и-мэйлээр</span></div>
          </div>}
          {native && capabilities.data?.telegram_native && <>
            <button className="primary-action native-telegram-action telegram-brand-button" type="button" onClick={() => void startNativeTelegramLogin()} disabled={telegramState.status === 'opening' || telegramState.status === 'waiting'}>
              {telegramState.status === 'opening' || telegramState.status === 'waiting' ? 'Telegram нэвтрэлтийг хүлээж байна…' : <><Send size={17} aria-hidden /> Telegram-аар нэвтрэх</>}
            </button>
            {telegramState.status === 'error' && <p className="login-inline-error" role="alert">{telegramState.message}</p>}
            {telegramState.status === 'cancelled' && <p className="login-inline-hint">Telegram нэвтрэлтийг цуцалсан. Дахин оролдоно уу.</p>}
            <div className="login-divider"><span>эсвэл нууц үгээр</span></div>
          </>}
          <form onSubmit={submit} className="login-form">
            <label>
              <span>Нэвтрэх нэр</span>
              <div className="field-with-icon"><Mail size={16} aria-hidden /><input value={username} onChange={(event) => setUsername(event.target.value)} type="text" autoComplete="username" required /></div>
            </label>
            <label>
              <span>Нууц үг</span>
              <div className="field-with-icon"><LockKeyhole size={16} aria-hidden /><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></div>
            </label>
            <div className="auth-form-options"><a href="/forgot-password">Нууц үгээ мартсан уу?</a></div>
            <button className="secondary-action" type="submit" disabled={login.isPending}>
              {login.isPending ? 'Нэвтэрч байна…' : 'Нэвтрэх'} <ArrowRight size={16} aria-hidden />
            </button>
          </form>
          <footer><a href="/privacy">Нууцлал</a><a href="/terms">Үйлчилгээний нөхцөл</a></footer>
        </div>
      </section>
      <aside className="auth-brand-side" aria-label="OYUNS ажлын талбар">
        <Grainient className="auth-grainient" />
        <div className="auth-brand-content">
          <div className="auth-brand-copy">
            <span className="auth-brand-label">ТАНЫ АЖЛЫН ОРОН ЗАЙ</span>
            <h2>Таны ажил<br />нэг дор, цэгцтэй, хялбар.</h2>
            <p>Төсөл, даалгавар, цагийн бүртгэл, тайлан, чөлөөний хүсэлт...</p>
          </div>
          <div className="auth-workspace-preview" aria-hidden="true">
            <div className="auth-preview-top"><span className="auth-preview-dot" /><span>Ажлын талбар</span><span className="auth-preview-menu">•••</span></div>
            <div className="auth-preview-body">
              <div className="auth-preview-sidebar"><i /><i /><i /><i /></div>
              <div className="auth-preview-main">
                <div className="auth-preview-title"><i /><b /><b /></div>
                <div className="auth-preview-grid"><i /><i /><i /></div>
                <div className="auth-preview-list"><i /><i /><i /></div>
              </div>
            </div>
            <div className="auth-preview-caption"><span className="auth-preview-check">✓</span><span><b>Бүгдийг нэг дороос</b><small>Төсөл, даалгавар, цагийн бүртгэл, тайлан, чөлөөний хүсэлт</small></span><span className="auth-preview-arrow">↗</span></div>
          </div>
          <div className="auth-brand-footer"><span>ХУРДАН · ХЯЛБАР · ЦЭГЦТЭЙ</span><span>OYUNS ALL-IN-ONE © 2026</span></div>
        </div>
      </aside>
    </main>
  )
}
