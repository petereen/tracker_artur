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
      toast.error('И-мэйл эсвэл нууц үг буруу байна')
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="bg-surface border border-border rounded-2xl p-8 w-full max-w-sm">
        <div className="mb-8">
          <img
            src="/oyuns-aio-logo.png"
            alt="OYUNS All-in-One"
            className="w-full max-w-[280px] h-auto max-h-14 object-contain object-left"
          />
          <div className="mt-3 text-xs text-muted">Админ самбар</div>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted font-medium">Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted font-medium">Нууц үг</label>
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required
              className="bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors" />
          </div>
          <button type="submit" disabled={login.isPending}
            className="mt-2 bg-accent text-white border-none rounded-lg py-2 font-medium text-sm cursor-pointer hover:opacity-85 transition-opacity disabled:opacity-40">
            {login.isPending ? 'Нэвтэрч байна...' : 'Нэвтрэх'}
          </button>
        </form>
        <div className="mt-6 pt-4 border-t border-border flex justify-center gap-4 text-[11px] text-muted">
          <a href="/privacy" className="hover:text-text">Нууцлал</a>
          <a href="/terms" className="hover:text-text">Үйлчилгээний нөхцөл</a>
        </div>
      </div>
    </div>
  )
}
