import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { Btn, Card, Input, PageHeader, Select, Toggle } from '../components/ui'
import { useAdminUsers, useChangeOwnPassword, useCreateAdminUser, useDeleteAdminUser, useManagerSettings, useUpdateManagerSettings } from '../api/hooks'

const DAY_OPTIONS = [
  { value: '1', label: 'Даваа' }, { value: '2', label: 'Мягмар' },
  { value: '3', label: 'Лхагва' }, { value: '4', label: 'Пүрэв' },
  { value: '5', label: 'Баасан' }, { value: '6', label: 'Бямба' },
  { value: '0', label: 'Ням' },
]

export function ManagerSettingsPage() {
  const { data } = useManagerSettings()
  const { data: adminUsers = [] } = useAdminUsers()
  const save = useUpdateManagerSettings()
  const createAdmin = useCreateAdminUser()
  const deleteAdmin = useDeleteAdminUser()
  const changePassword = useChangeOwnPassword()

  const [newAdmin, setNewAdmin] = useState({ email: '', password: '' })
  const [passwordForm, setPasswordForm] = useState({ current_password: '', new_password: '', confirm_password: '' })

  const [form, setForm] = useState({
    telegram_id: '', telegram_username: '',
    summary_time: '09:00', weekly_summary_time: '17:00', weekly_summary_day: '5',
    alerts_enabled: true, gamification_enabled: true, soft_mode_weeks: 1,
  })

  useEffect(() => {
    if (data) setForm({
      telegram_id: data.telegram_id || '',
      telegram_username: data.telegram_username || '',
      summary_time: data.summary_time?.slice(0, 5) || '09:00',
      weekly_summary_time: data.weekly_summary_time?.slice(0, 5) || '17:00',
      weekly_summary_day: String(data.weekly_summary_day ?? 5),
      alerts_enabled: data.alerts_enabled,
      gamification_enabled: data.gamification_enabled,
      soft_mode_weeks: data.soft_mode_weeks,
    })
  }, [data])

  const f = (k: string, v: any) => setForm((prev) => ({ ...prev, [k]: v }))

  const addAdmin = async () => {
    if (!newAdmin.email || newAdmin.password.length < 8) {
      toast.error('И-мэйл болон хамгийн багадаа 8 тэмдэгттэй нууц үг оруулна уу')
      return
    }
    try {
      await createAdmin.mutateAsync(newAdmin)
      setNewAdmin({ email: '', password: '' })
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Админ нэмэхэд алдаа гарлаа')
    }
  }

  const updatePassword = async () => {
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      toast.error('Шинэ нууц үг таарахгүй байна')
      return
    }
    try {
      await changePassword.mutateAsync(passwordForm)
      setPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Нууц үг солиход алдаа гарлаа')
    }
  }

  const OPTIONS = [
    { key: 'alerts_enabled',        label: 'Алгасалтын анхааруулга', desc: 'Ажилтан хугацаа дууссаны дараа бөглөөгүй бол удирдлагад мэдэгдэх' },
    { key: 'gamification_enabled',  label: 'Урамшууллын систем', desc: 'Ажилтнуудад чансаа болон бөглөлтийн цувралыг харуулах' },
  ]

  return (
    <div>
      <PageHeader title="Удирдлагын тохиргоо" sub="Telegram холболт ба мэдэгдлийн тохиргоо" />
      <div className="flex flex-col gap-4 max-w-[700px]">
        <Card>
          <div className="font-semibold text-[15px] mb-4">Telegram</div>
          <div className="grid grid-cols-2 gap-3.5">
            <Input label="Удирдлагын Telegram ID" value={form.telegram_id} onChange={(v) => f('telegram_id', v)} placeholder="100012345" />
            <Input label="Username" value={form.telegram_username} onChange={(v) => f('telegram_username', v)} placeholder="@username" />
          </div>
        </Card>

        <Card>
          <div className="font-semibold text-[15px] mb-1">Админ хандалт</div>
          <div className="text-xs text-muted mb-4">Энд нэмсэн и-мэйл болон нууц үгээр админ самбарт нэвтэрнэ.</div>
          <div className="flex flex-col gap-3">
            {adminUsers.map((user) => (
              <div key={user.id} className="flex items-center justify-between gap-3 rounded-lg bg-surface2 px-3 py-2">
                <div className="text-sm truncate">{user.email}</div>
                <Btn variant="danger" onClick={() => deleteAdmin.mutate(user.id)} disabled={deleteAdmin.isPending || adminUsers.length === 1}>Эрх цуцлах</Btn>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-[1fr_1fr_auto] gap-3 mt-4 items-end">
            <Input label="Шинэ админы и-мэйл" value={newAdmin.email} onChange={(v) => setNewAdmin((p) => ({ ...p, email: v }))} type="email" fullWidth />
            <Input label="Түр нууц үг" value={newAdmin.password} onChange={(v) => setNewAdmin((p) => ({ ...p, password: v }))} type="password" fullWidth />
            <Btn variant="primary" size="lg" onClick={addAdmin} disabled={createAdmin.isPending}>Админ нэмэх</Btn>
          </div>
        </Card>

        <Card>
          <div className="font-semibold text-[15px] mb-1">Миний нууц үг</div>
          <div className="text-xs text-muted mb-4">Шинэ нууц үг хамгийн багадаа 8 тэмдэгт байна.</div>
          <div className="grid grid-cols-3 gap-3 items-end">
            <Input label="Одоогийн нууц үг" value={passwordForm.current_password} onChange={(v) => setPasswordForm((p) => ({ ...p, current_password: v }))} type="password" fullWidth />
            <Input label="Шинэ нууц үг" value={passwordForm.new_password} onChange={(v) => setPasswordForm((p) => ({ ...p, new_password: v }))} type="password" fullWidth />
            <div className="flex gap-2 items-end">
              <Input label="Давтах" value={passwordForm.confirm_password} onChange={(v) => setPasswordForm((p) => ({ ...p, confirm_password: v }))} type="password" fullWidth />
              <Btn variant="primary" size="lg" onClick={updatePassword} disabled={changePassword.isPending}>Солих</Btn>
            </div>
          </div>
        </Card>

        <Card>
          <div className="font-semibold text-[15px] mb-4">Хураангуй</div>
          <div className="grid grid-cols-2 gap-3.5">
            <Input label="Өглөөний хураангуйн цаг" value={form.summary_time} onChange={(v) => f('summary_time', v)} type="time" />
            <div className="grid grid-cols-2 gap-2">
              <Select label="7 хоногийн хураангуйн өдөр" value={form.weekly_summary_day} onChange={(v) => f('weekly_summary_day', v)} options={DAY_OPTIONS} />
              <Input label="Цаг" value={form.weekly_summary_time} onChange={(v) => f('weekly_summary_time', v)} type="time" />
            </div>
          </div>
        </Card>

        <Card>
          <div className="font-semibold text-[15px] mb-4">Сонголтууд</div>
          <div className="flex flex-col gap-3.5">
            {OPTIONS.map((opt) => (
              <div key={opt.key} className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-medium text-[13px]">{opt.label}</div>
                  <div className="text-xs text-muted mt-0.5 max-w-[480px]">{opt.desc}</div>
                </div>
                <Toggle checked={(form as any)[opt.key]} onChange={(v) => f(opt.key, v)} />
              </div>
            ))}
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-medium text-[13px]">Танилцуулгын зөөлөн горим</div>
                <div className="text-xs text-muted mt-0.5">Эхний {form.soft_mode_weeks} долоо хоногт сануулгыг зөвхөн ажилтанд илгээнэ</div>
              </div>
              <input type="range" min={0} max={4} value={form.soft_mode_weeks}
                onChange={(e) => f('soft_mode_weeks', +e.target.value)}
                className="w-24 accent-accent mt-1" />
            </div>
          </div>
        </Card>

        <div className="flex justify-end gap-2.5">
          <Btn>Сэргээх</Btn>
          <Btn variant="primary" size="lg" onClick={() => save.mutate(form)} disabled={save.isPending}>Тохиргоо хадгалах</Btn>
        </div>
      </div>
    </div>
  )
}
