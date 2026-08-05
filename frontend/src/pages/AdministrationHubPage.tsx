import { useState } from 'react'
import { BookOpen, Bot, CalendarClock, ClipboardList, Code2, KeyRound, Settings2, UserRoundCog, UserPlus, Users2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useCreateManagedAccount, useGoogleCalendarConnect, useManagedAccounts, useUpdateManagedAccount } from '../api/enterprise'

const ITEMS = [
  { to: '/legacy/employees', label: 'Ажилтнууд', text: 'Профайл, Telegram болон хандалт', icon: Users2 },
  { to: '/legacy/questions', label: 'Check-in асуулт', text: 'Өдрийн асуултын банк', icon: ClipboardList },
  { to: '/legacy/schedule', label: 'Хуваарь', text: 'Сануулга ба check-in цаг', icon: CalendarClock },
  { to: '/legacy/manager', label: 'Мэдэгдэл', text: 'Quiet hours, digest, escalation', icon: UserRoundCog },
  { to: '/legacy/knowledge', label: 'Компанийн мэдлэг', text: 'OYUNS-ийн баталгаатай эх сурвалж', icon: BookOpen },
  { to: '/legacy/onboarding', label: 'Онбординг', text: 'Шинэ ажилтны танилцуулга', icon: Bot },
  { to: '/legacy/developer', label: 'OYUNS сургалт', text: 'Тодорхойгүй хүсэлтийн review', icon: Code2 },
]

const ROLES = [
  ['member', 'Member'], ['manager', 'Supervisor'], ['team_lead', 'Team lead'],
  ['contractor', 'Contractor'], ['client_auditor', 'Client auditor'], ['admin', 'Admin'],
] as const

export function AdministrationHubPage() {
  const calendar = useGoogleCalendarConnect()
  const accounts = useManagedAccounts()
  const createAccount = useCreateManagedAccount()
  const updateAccount = useUpdateManagedAccount()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('member')
  const connectCalendar = async () => {
    const result = await calendar.mutateAsync()
    if (result.authorization_url) window.location.assign(result.authorization_url)
    else toast.error('Google OAuth тохиргоо дутуу байна')
  }
  const create = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      await createAccount.mutateAsync({ email: username, password, roles: [role], locale: 'mn' })
      setUsername(''); setPassword(''); toast.success('Хэрэглэгч үүслээ')
    } catch (error: any) { toast.error(error.response?.data?.detail || 'Хэрэглэгч үүссэнгүй') }
  }
  const changePassword = async (account: { id: number; email: string }) => {
    const next = window.prompt(`${account.email} шинэ нууц үг (10+ тэмдэгт):`)
    if (!next) return
    if (next.length < 10) { toast.error('Нууц үг 10+ тэмдэгт байх ёстой'); return }
    await updateAccount.mutateAsync({ id: account.id, password: next }); toast.success('Нууц үг шинэчлэгдлээ')
  }
  const toggleRole = async (account: { id: number; roles: string[] }, roleName: string) => {
    const roles = account.roles.includes(roleName) ? account.roles.filter((item) => item !== roleName) : [...account.roles, roleName]
    if (!roles.length) { toast.error('Хэрэглэгч дор хаяж нэг эрхтэй байна'); return }
    try { await updateAccount.mutateAsync({ id: account.id, roles }); toast.success('Хандалтын эрх шинэчлэгдлээ') }
    catch (error: any) { toast.error(error.response?.data?.detail || 'Эрх шинэчлэгдсэнгүй') }
  }
  return <div><div className="view-toolbar"><div><h2>Системийн тохиргоо</h2><p>erp.oyuns.mn-д username/password админ горим идэвхтэй. И-мэйл баталгаажуулалт шаарддаггүй.</p></div><Settings2 /></div><section className="account-admin panel"><div className="panel-heading"><div><span className="eyebrow">Access control</span><h2>Хэрэглэгчид ба эрхүүд</h2><p>Шинэ Telegram хэрэглэгч Member эрхээр орно. Admin эндээс эрхийг нь өөрчилнө.</p></div><Users2 /></div><form className="account-create-form" onSubmit={create}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={10} autoComplete="new-password" required /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value)}>{ROLES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="primary-action compact" disabled={createAccount.isPending}><UserPlus size={15} />Нэмэх</button></form><div className="account-list" aria-live="polite">{accounts.data?.map((account) => <article key={account.id}><div className="account-identity"><strong>{account.email}</strong><span>{account.status} · {account.employee_id ? `Employee #${account.employee_id}` : 'ажилтантай холбоогүй'}</span></div><fieldset className="role-editor"><legend>Access roles</legend>{ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleRole(account, value)} disabled={updateAccount.isPending} /><span>{label}</span></label>)}</fieldset><div><button className="icon-action" onClick={() => changePassword(account)} aria-label={`${account.email} password солих`}><KeyRound size={15} /></button><button className="secondary-action compact" onClick={() => updateAccount.mutate({ id: account.id, status: account.status === 'disabled' ? 'active' : 'disabled' })}>{account.status === 'disabled' ? 'Идэвхжүүлэх' : 'Идэвхгүй болгох'}</button></div></article>)}</div></section><section className="integration-grid"><article className="panel integration-panel"><CalendarClock /><div><strong>Google Calendar</strong><p>Өөрийн Google Calendar-тай даалгаврын хугацааг синк хийнэ.</p></div><button className="secondary-action" onClick={connectCalendar} disabled={calendar.isPending}>Холбох</button></article></section><div className="admin-hub">{ITEMS.map(({ to, label, text, icon: Icon }) => <Link to={to} key={to}><Icon /><div><strong>{label}</strong><span>{text}</span></div></Link>)}</div></div>
}
