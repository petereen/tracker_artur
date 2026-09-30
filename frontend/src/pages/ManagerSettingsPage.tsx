import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card as AstryxCard } from '@astryxdesign/core/Card'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { Selector } from '@astryxdesign/core/Selector'
import { Slider } from '@astryxdesign/core/Slider'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { TimeInput, type ISOTimeString } from '@astryxdesign/core/TimeInput'
import { VStack } from '@astryxdesign/core/VStack'
import { Btn, Card as LegacyCard, Input } from '../components/ui'
import { type ManagerRecipientOption, useAdminUsers, useChangeOwnPassword, useCreateAdminUser, useDeleteAdminUser, useManagerRecipientOptions, useManagerSettings, useUpdateManagerSettings } from '../api/hooks'
import { useTenantContext } from '../api/tenancy'

const DAY_OPTIONS = [
  { value: '1', label: 'Даваа' }, { value: '2', label: 'Мягмар' },
  { value: '3', label: 'Лхагва' }, { value: '4', label: 'Пүрэв' },
  { value: '5', label: 'Баасан' }, { value: '6', label: 'Бямба' },
  { value: '0', label: 'Ням' },
]

export function AdminAccessPanel() {
  const { data: adminUsers = [] } = useAdminUsers()
  const createAdmin = useCreateAdminUser()
  const deleteAdmin = useDeleteAdminUser()
  const changePassword = useChangeOwnPassword()
  const [newAdmin, setNewAdmin] = useState({ email: '', password: '' })
  const [passwordForm, setPasswordForm] = useState({ current_password: '', new_password: '', confirm_password: '' })

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

  return <>
    <LegacyCard>
      <div className="font-semibold text-[15px] mb-1">Админ хандалт</div>
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
    </LegacyCard>

    <LegacyCard>
      <div className="font-semibold text-[15px] mb-1">Миний нууц үг</div>
      <div className="grid grid-cols-3 gap-3 items-end">
        <Input label="Одоогийн нууц үг" value={passwordForm.current_password} onChange={(v) => setPasswordForm((p) => ({ ...p, current_password: v }))} type="password" fullWidth />
        <Input label="Шинэ нууц үг" value={passwordForm.new_password} onChange={(v) => setPasswordForm((p) => ({ ...p, new_password: v }))} type="password" fullWidth />
        <div className="flex gap-2 items-end">
          <Input label="Давтах" value={passwordForm.confirm_password} onChange={(v) => setPasswordForm((p) => ({ ...p, confirm_password: v }))} type="password" fullWidth />
          <Btn variant="primary" size="lg" onClick={updatePassword} disabled={changePassword.isPending}>Солих</Btn>
        </div>
      </div>
    </LegacyCard>
  </>
}

type ManagerForm = {
  telegram_admin_ids: string[]
  summary_time: string
  weekly_summary_time: string
  weekly_summary_day: string
  alerts_enabled: boolean
  gamification_enabled: boolean
  soft_mode_weeks: number
  tts_answers_enabled: boolean
  daily_report_reminders_enabled: boolean
}

const MANAGER_OPTIONS: { key: keyof ManagerForm; label: string; desc: string }[] = [
  { key: 'alerts_enabled', label: 'Алгасалтын анхааруулга', desc: 'Ажилтан хугацаа дууссаны дараа бөглөөгүй бол удирдлагад мэдэгдэх' },
  { key: 'gamification_enabled', label: 'Урамшууллын систем', desc: 'Ажилтнуудад чансаа болон бөглөлтийн цувралыг харуулах' },
  { key: 'tts_answers_enabled', label: 'Агентын дуу хоолойгоор хариулах горим', desc: 'Асуултад хариулахдаа текстийн хамт Chimege-ээр үүсгэсэн аудио илгээх' },
  { key: 'daily_report_reminders_enabled', label: 'Өдрийн ажлын тайлангийн сануулга', desc: 'Ажилтнуудад Telegram болон notification bar-аар өдрийн тайлангийн сануулга илгээх' },
]

function toForm(data: any): ManagerForm {
  return {
    telegram_admin_ids: (data?.telegram_admin_ids as string[] | undefined)?.filter(Boolean) ?? [],
    summary_time: data?.summary_time?.slice(0, 5) || '09:00',
    weekly_summary_time: data?.weekly_summary_time?.slice(0, 5) || '17:00',
    weekly_summary_day: String(data?.weekly_summary_day ?? 5),
    alerts_enabled: data?.alerts_enabled ?? true,
    gamification_enabled: data?.gamification_enabled ?? true,
    soft_mode_weeks: data?.soft_mode_weeks ?? 1,
    tts_answers_enabled: data?.tts_answers_enabled ?? true,
    daily_report_reminders_enabled: data?.daily_report_reminders_enabled ?? true,
  }
}

/** "Захирал · Удирдлага" — position first, then the system role, then the department. */
export function recipientSubtitle(option: ManagerRecipientOption) {
  return [option.job_title || option.role, option.department].filter(Boolean).join(' · ')
}

function RecipientPicker({ selected, options, onChange, botConnected }: {
  selected: string[]
  options: ManagerRecipientOption[]
  onChange: (ids: string[]) => void
  botConnected: boolean
}) {
  const [manualId, setManualId] = useState('')
  const byId = new Map(options.map((option) => [option.telegram_id, option]))
  const available = options.filter((option) => !selected.includes(option.telegram_id))
  const manual = manualId.trim()
  const manualInvalid = Boolean(manual) && !/^\d{5,16}$/.test(manual)
  const add = (id: string) => { if (id && !selected.includes(id)) onChange([...selected, id]) }

  return <VStack gap={3}>
    {!botConnected && <Banner status="warning" collapsible={false} title="Telegram бот холбогдоогүй"
      description="Мэдэгдэл илгээхийн тулд эхлээд дээрх «Telegram бот» хэсэгт байгууллагынхаа ботыг холбоно уу." />}
    {selected.length === 0
      ? <Text type="supporting">Хүлээн авагч сонгоогүй байна.</Text>
      : <List hasDividers density="compact">
        {selected.map((id) => {
          const option = byId.get(id)
          return <ListItem key={id}
            label={option ? option.name : `Telegram ID ${id}`}
            description={option ? `${recipientSubtitle(option) || 'Ажилтан'} · ID ${id}` : 'Ажилтны бүртгэлтэй холбогдоогүй ID'}
            endContent={<Button label="Хасах" size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={() => onChange(selected.filter((item) => item !== id))} />} />
        })}
      </List>}
    <HStack gap={2} vAlign="end" wrap="wrap">
      <Selector label="Ажилтнаас сонгох" value={undefined} onChange={(value) => add(value)} hasSearch searchPlaceholder="Нэр, албан тушаал…"
        placeholder={available.length ? 'Telegram холбосон ажилтан' : 'Сонгох ажилтан алга'} isDisabled={available.length === 0}
        emptyText="Telegram холбосон ажилтан алга"
        options={available.map((option) => ({ value: option.telegram_id, label: option.name, description: [recipientSubtitle(option), `ID ${option.telegram_id}`].filter(Boolean).join(' · ') }))} />
      <TextInput label="Эсвэл Telegram ID" value={manualId} onChange={setManualId} placeholder="100012345" width={200}
        status={manualInvalid ? { type: 'error', message: 'Зөвхөн тоо' } : undefined}
        onEnter={() => { if (manual && !manualInvalid) { add(manual); setManualId('') } }} />
      <Button label="Нэмэх" variant="secondary" icon={<Plus size={15} />} isDisabled={!manual || manualInvalid}
        onClick={() => { add(manual); setManualId('') }} />
    </HStack>
  </VStack>
}

export function ManagerSettingsPage() {
  const { data } = useManagerSettings()
  const save = useUpdateManagerSettings()
  const recipients = useManagerRecipientOptions()
  const tenant = useTenantContext()
  const baseline = useMemo(() => toForm(data), [data])
  const [draft, setDraft] = useState<ManagerForm | null>(null)
  const form = draft ?? baseline
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline)
  const f = <K extends keyof ManagerForm>(key: K, value: ManagerForm[K]) => setDraft({ ...form, [key]: value })
  const submit = async () => {
    try {
      await save.mutateAsync(form)
      setDraft(null)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      toast.error(typeof detail === 'object' ? detail?.message || 'Тохиргоо хадгалагдсангүй' : detail || 'Тохиргоо хадгалагдсангүй')
    }
  }

  return <VStack gap={4}>
    <AstryxCard padding={5}>
      <VStack gap={4}>
        <VStack gap={1}>
          <Heading level={3}>Удирдлагын телеграм мэдэгдлийн тохиргоо</Heading>
          <Text type="supporting">Сарын AI хураангуй, алгасалтын анхааруулга болон удирдлагын мэдэгдлийг сонгосон хүмүүсийн Telegram руу илгээнэ.</Text>
        </VStack>
        <RecipientPicker selected={form.telegram_admin_ids} options={recipients.data ?? []} onChange={(ids) => f('telegram_admin_ids', ids)}
          botConnected={tenant.data?.telegram_bot_connected ?? true} />
      </VStack>
    </AstryxCard>

    <AstryxCard padding={5}>
      <VStack gap={4}>
        <Heading level={3}>Хураангуй</Heading>
        <HStack gap={3} wrap="wrap" vAlign="end">
          <TimeInput label="Өглөөний хураангуйн цаг" value={form.summary_time as ISOTimeString} onChange={(value) => value && f('summary_time', value)} hourFormat="24h" width={200} />
          <Selector label="7 хоногийн хураангуйн өдөр" value={form.weekly_summary_day} onChange={(value) => f('weekly_summary_day', value)} options={DAY_OPTIONS} />
          <TimeInput label="Цаг" value={form.weekly_summary_time as ISOTimeString} onChange={(value) => value && f('weekly_summary_time', value)} hourFormat="24h" width={160} />
        </HStack>
      </VStack>
    </AstryxCard>

    <AstryxCard padding={5}>
      <VStack gap={4}>
        <Heading level={3}>Сонголтууд</Heading>
        {MANAGER_OPTIONS.map((option) => <Switch key={option.key} label={option.label} description={option.desc}
          value={Boolean(form[option.key])} onChange={(value) => f(option.key, value as never)} labelPosition="start" labelSpacing="spread" width="100%" />)}
        <Slider label="Танилцуулгын зөөлөн горим" description={`Эхний ${form.soft_mode_weeks} долоо хоногт сануулгыг зөвхөн ажилтанд илгээнэ`}
          value={form.soft_mode_weeks} min={0} max={4} valueDisplay="text" formatValue={(value) => `${value} долоо хоног`}
          onChange={(value: number) => f('soft_mode_weeks', value)} width={320} />
      </VStack>
    </AstryxCard>

    <HStack gap={2} hAlign="end" vAlign="center">
      {dirty && <StatusDot variant="warning" label="Хадгалаагүй өөрчлөлт" />}
      <Button label="Буцаах" variant="ghost" onClick={() => setDraft(null)} isDisabled={!dirty} />
      <Button label="Тохиргоо хадгалах" variant="primary" clickAction={submit} isDisabled={!dirty} />
    </HStack>
  </VStack>
}
