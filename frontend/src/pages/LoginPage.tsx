import { useState } from 'react'
import { useAuthStore } from '../store/auth'
import { useLogin } from '../api/hooks'
import toast from 'react-hot-toast'

export function LoginPage() {
  const [email, setEmail] = useState('admin@company.ru')
  const [password, setPassword] = useState('')
  const setToken = useAuthStore((s) => s.setToken)
  const login = useLogin()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const data = await login.mutateAsync({ email, password })
      setToken(data.access_token)
    } catch {
      toast.error('Неверный email или пароль')
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="bg-surface border border-border rounded-2xl p-8 w-full max-w-sm">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-accent flex items-center justify-center text-xl font-bold text-white">T</div>
          <div>
            <div className="text-base font-semibold">Трекер активности</div>
            <div className="text-xs text-muted">Панель администратора</div>
          </div>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted font-medium">Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted font-medium">Пароль</label>
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors" />
          </div>
          <button type="submit" disabled={login.isPending}
            className="mt-2 bg-accent text-white border-none rounded-lg py-2 font-medium text-sm cursor-pointer hover:opacity-85 transition-opacity disabled:opacity-40">
            {login.isPending ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}
