import { useEffect, useState } from 'react'
import { ArrowRight, LockKeyhole, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthCapabilities, useEnterpriseLogin, useTelegramWidgetLogin } from '../api/enterprise'
import { isNativePlatform } from '../platform/runtime'
import { startNativeTelegramLogin, subscribeToNativeTelegramAuth, type NativeTelegramAuthState } from '../platform/telegram-auth'

declare global {
  interface Window { onTelegramAuth?: (user: Record<string, string | number>) => void }
}

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useEnterpriseLogin()
  const { mutate: loginWithTelegram } = useTelegramWidgetLogin()
  const native = isNativePlatform()
  const capabilities = useAuthCapabilities(native)
  const [telegramState, setTelegramState] = useState<NativeTelegramAuthState>({ status: 'idle' })

  useEffect(() => {
    if (!native) return
    return subscribeToNativeTelegramAuth(setTelegramState)
  }, [native])

  useEffect(() => {
    if (isNativePlatform()) return
    const username = import.meta.env.VITE_TELEGRAM_BOT_USERNAME
    if (!username) return
    window.onTelegramAuth = (user) => {
      loginWithTelegram(user)
    }
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.setAttribute('data-telegram-login', username)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-userpic', 'false')
    script.setAttribute('data-request-access', 'write')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    document.getElementById('telegram-login-widget')?.appendChild(script)
    return () => {
      delete window.onTelegramAuth
      script.remove()
    }
  }, [loginWithTelegram])

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
        {!native && import.meta.env.VITE_TELEGRAM_BOT_USERNAME && <div className="telegram-login"><span>эсвэл Telegram-аар</span><div id="telegram-login-widget" /></div>}
        <footer><a href="/privacy">Нууцлал</a><a href="/terms">Үйлчилгээний нөхцөл</a></footer>
      </section>
    </main>
  )
}
