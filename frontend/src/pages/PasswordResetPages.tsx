import { useState } from 'react'
import { KeyRound, Mail } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { usePasswordResetConfirm, usePasswordResetRequest } from '../api/enterprise'

function AuthCard({ children, title, description }: { children?: React.ReactNode; title: string; description: string }) {
  return <main className="login-stage"><section className="login-card" aria-labelledby="auth-title">
    <img src="/oyuns-aio-logo.png" alt="OYUNS All-in-One" className="login-logo" />
    <h1 id="auth-title">{title}</h1><p>{description}</p>{children}
    <a className="auth-help-link" href="/">Нэвтрэх хэсэг рүү буцах</a>
  </section></main>
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const request = usePasswordResetRequest()
  if (request.isSuccess) return <AuthCard title="И-мэйлээ шалгана уу" description="Бүртгэл байгаа бол нэг удаагийн хамгаалалттай холбоос илгээлээ." />
  return <AuthCard title="Нууц үг сэргээх" description="Бүртгэлтэй и-мэйл хаягаа оруулна уу.">
    <form className="login-form" onSubmit={(event) => { event.preventDefault(); request.mutate(email) }}>
      <label><span>И-мэйл</span><div className="field-with-icon"><Mail size={16} aria-hidden /><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></div></label>
      <button className="primary-action" disabled={request.isPending}>{request.isPending ? 'Илгээж байна…' : 'Сэргээх холбоос илгээх'}</button>
    </form>
  </AuthCard>
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const reset = usePasswordResetConfirm()
  if (!token) return <AuthCard title="Холбоос буруу байна" description="Шинэ сэргээх холбоос хүснэ үү." />
  if (reset.isSuccess) return <AuthCard title="Нууц үг шинэчлэгдлээ" description="Одоо шинэ нууц үгээрээ нэвтэрч болно." />
  return <AuthCard title="Шинэ нууц үг" description="Доод тал нь 10 тэмдэгттэй нууц үг сонгоно уу.">
    <form className="login-form" onSubmit={(event) => { event.preventDefault(); if (password === confirmation) reset.mutate({ token, new_password: password }) }}>
      <label><span>Шинэ нууц үг</span><div className="field-with-icon"><KeyRound size={16} aria-hidden /><input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(event) => setPassword(event.target.value)} required /></div></label>
      <label><span>Нууц үг давтах</span><div className="field-with-icon"><KeyRound size={16} aria-hidden /><input type="password" autoComplete="new-password" minLength={10} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></div></label>
      {confirmation && password !== confirmation && <p role="alert" className="auth-error">Нууц үг таарахгүй байна.</p>}
      {reset.isError && <p role="alert" className="auth-error">Холбоос хүчингүй эсвэл хугацаа дууссан байна.</p>}
      <button className="primary-action" disabled={reset.isPending || password !== confirmation}>{reset.isPending ? 'Хадгалж байна…' : 'Нууц үг шинэчлэх'}</button>
    </form>
  </AuthCard>
}
