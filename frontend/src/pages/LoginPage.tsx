import { useEffect, useState } from 'react'
import { ArrowRight, LockKeyhole, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { useEnterpriseLogin, useTelegramWidgetLogin } from '../api/enterprise'

declare global {
  interface Window { onTelegramAuth?: (user: Record<string, string | number>) => void }
}

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useEnterpriseLogin()
  const { mutate: loginWithTelegram } = useTelegramWidgetLogin()

  useEffect(() => {
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
        <div className="eyebrow">Enterprise workspace</div>
        <h1 id="login-title">Ажлаа нэг хэмнэлд оруул.</h1>
        <p>Төсөл, даалгавар, цаг, тайлан болон багийн ачааллаа нэг орчноос удирдана.</p>
        <form onSubmit={submit} className="login-form">
          <label>
            <span>Username</span>
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
        {import.meta.env.VITE_TELEGRAM_BOT_USERNAME && <div className="telegram-login"><span>эсвэл Telegram-аар</span><div id="telegram-login-widget" /></div>}
        <footer><a href="/privacy">Нууцлал</a><a href="/terms">Үйлчилгээний нөхцөл</a></footer>
      </section>
    </main>
  )
}
