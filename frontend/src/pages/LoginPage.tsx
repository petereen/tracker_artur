import { useState } from 'react'
import { ArrowRight, LockKeyhole, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { useEnterpriseLogin } from '../api/enterprise'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useEnterpriseLogin()

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
        <footer><a href="/privacy">Нууцлал</a><a href="/terms">Үйлчилгээний нөхцөл</a></footer>
      </section>
    </main>
  )
}
