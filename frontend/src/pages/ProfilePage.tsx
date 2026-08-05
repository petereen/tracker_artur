import { useEffect, useState } from 'react'
import { KeyRound, Save, UserRound } from 'lucide-react'
import { useProfile, useUpdateProfile } from '../api/enterprise'

export function ProfilePage() {
  const profile = useProfile()
  const update = useUpdateProfile()
  const [form, setForm] = useState({ username: '', avatar_url: '', locale: 'mn', current_password: '', new_password: '' })
  useEffect(() => {
    if (profile.data) setForm((current) => ({ ...current, username: profile.data.username, avatar_url: profile.data.avatar_url ?? '', locale: profile.data.locale }))
  }, [profile.data])
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    await update.mutateAsync({ username: form.username, avatar_url: form.avatar_url || null, locale: form.locale, current_password: form.current_password || undefined, new_password: form.new_password || undefined })
    setForm((current) => ({ ...current, current_password: '', new_password: '' }))
  }
  return <div className="profile-page"><div className="view-toolbar"><div><h2>Миний профайл</h2><p>Нэвтрэх нэр, зураг, хэл болон нууц үгээ удирдана.</p></div></div><form className="profile-grid" onSubmit={submit}><section className="panel profile-card"><div className="profile-avatar">{form.avatar_url ? <img src={form.avatar_url} alt="Профайл зураг" /> : <UserRound />}</div><div><span className="eyebrow">Админаас оноосон нэр</span><h2>{profile.data?.name ?? '…'}</h2><p>{profile.data?.telegram_username ? `Telegram: @${profile.data.telegram_username}` : 'Telegram нэр холбогдоогүй'}</p><small>Ажилтны үндсэн нэрийг зөвхөн админ өөрчилнө. Telegram-ээр нэвтрэхэд энэ нэр автоматаар харагдана.</small></div></section><section className="panel profile-form"><label>Профайл зургийн HTTPS холбоос<input type="url" value={form.avatar_url} onChange={(event) => setForm({ ...form, avatar_url: event.target.value })} placeholder="https://…" /></label><label>Нэвтрэх нэр<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></label><label>Хэл<select value={form.locale} onChange={(event) => setForm({ ...form, locale: event.target.value })}><option value="mn">Монгол</option><option value="en">English</option><option value="ru">Русский</option></select></label></section><section className="panel password-form"><div><KeyRound /><h3>Нууц үг</h3><p>Нэвтрэх нэр эсвэл нууц үг солиход одоогийн нууц үгээ оруулна.</p></div><label>Одоогийн нууц үг<input type="password" autoComplete="current-password" value={form.current_password} onChange={(event) => setForm({ ...form, current_password: event.target.value })} /></label><label>Шинэ нууц үг<input type="password" minLength={10} autoComplete="new-password" value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} /></label></section><button className="primary-action profile-save" disabled={update.isPending}><Save size={16} />Хадгалах</button></form></div>
}
