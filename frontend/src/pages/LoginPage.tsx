import { useEffect, useState } from 'react'
import { ArrowRight, LockKeyhole, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthCapabilities, useEnterpriseLogin } from '../api/enterprise'
import { isNativePlatform } from '../platform/runtime'
import { startNativeTelegramLogin, subscribeToNativeTelegramAuth, type NativeTelegramAuthState } from '../platform/telegram-auth'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useEnterpriseLogin()
  const native = isNativePlatform()
  const capabilities = useAuthCapabilities(native)
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
    <main className="login-stage">
      <section className="login-card" aria-labelledby="login-title">
        <img src="/oyuns-aio-logo.png" alt="OYUNS All-in-One" className="login-logo" />
        <div className="eyebrow">OYUNS WORKSPACE</div>
        <h1 id="login-title">Илүү хурдан. Илүү хялбар.</h1>
        <p>Төсөл, даалгавар, цагийн бүртгэл, тайлан болон багийн ачааллаа нэг платформоос удирдана.</p>
        {native && capabilities.data?.telegram_native && <>
          <button className="primary-action native-telegram-action" type="button" onClick={() => void startNativeTelegramLogin()} disabled={telegramState.status === 'opening' || telegramState.status === 'waiting'}>
            {telegramState.status === 'opening' || telegramState.status === 'waiting' ? 'Telegram нэвтрэлтийг хүлээж байна…' : 'Telegram-аар нэвтрэх'} <ArrowRight size={16} aria-hidden />
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
          <button className="primary-action" type="submit" disabled={login.isPending}>
            {login.isPending ? 'Нэвтэрч байна…' : 'Нэвтрэх'} <ArrowRight size={16} aria-hidden />
          </button>
        </form>
        {!native && <div className="telegram-login">
          <span>эсвэл Telegram-аар</span>
          <button className="primary-action native-telegram-action" type="button" onClick={() => { window.location.assign('/api/v1/auth/telegram') }}>
            Telegram-аар нэвтрэх <ArrowRight size={16} aria-hidden />
          </button>
          {webTelegramError && <p className="login-inline-error" role="alert">{webTelegramError}</p>}
        </div>}
        <footer><a href="/privacy">Нууцлал</a><a href="/terms">Үйлчилгээний нөхцөл</a></footer>
      </section>
    </main>
  )
}
