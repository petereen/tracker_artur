import toast from 'react-hot-toast'
import { Banner } from '@astryxdesign/core/Banner'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Switch } from '@astryxdesign/core/Switch'
import { VStack } from '@astryxdesign/core/VStack'
import { useUpdateWorktimeMethods, useWorktimeMethods, type WorktimeMethods } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

/** Admin on/off switches for QR and location based office check-in. */
export function WorktimeMethodsSettings() {
  const methods = useWorktimeMethods()
  const update = useUpdateWorktimeMethods()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  if (methods.isError) return <Banner status="error" title="Цаг бүртгэх аргын тохиргоог ачаалж чадсангүй" collapsible={false} />
  if (!methods.data) return <Skeleton height={96} />
  const { qr_enabled: qr, location_enabled: location } = methods.data
  const save = async (input: Partial<WorktimeMethods>) => {
    try { await update.mutateAsync(input); toast.success('Цаг бүртгэх арга шинэчлэгдлээ') } catch { toast.error('Тохиргоо хадгалагдсангүй') }
  }
  const disabledMessage = canEdit ? undefined : 'Зөвхөн админ өөрчилнө'
  return <VStack gap={3}>
    <Switch
      label="QR кодоор бүртгэх"
      description="Ажилтны «Ажлын цаг» хэсэгт QR scanner харагдаж, оффисын дэлгэцийн QR-аар цагаа эхлүүлж, дуусгана."
      value={qr}
      changeAction={(checked) => save({ qr_enabled: checked })}
      isDisabled={!canEdit}
      disabledMessage={disabledMessage}
    />
    <Switch
      label="Байршлаар бүртгэх"
      description="Оффисын периметр дотор байхдаа вэб, аппликейшн болон Telegram-аар байршлаа илгээж ажлаа эхлүүлнэ."
      value={location}
      changeAction={(checked) => save({ location_enabled: checked })}
      isDisabled={!canEdit}
      disabledMessage={disabledMessage}
    />
    {!qr && !location && <Banner status="warning" title="Баталгаажуулалтгүй бүртгэл" description="Хоёр арга хаалттай үед ажилтан «Ажил эхлүүлэх» товчоор байршил, QR шалгалтгүйгээр оффисын цагаа эхлүүлнэ." collapsible={false} />}
    {qr && !location && <Banner status="info" title="Зөвхөн QR" description="Оффисын цагийг зөвхөн QR уншуулж эхлүүлнэ. Байршлаар эхлүүлэх хүсэлтийг систем хүлээж авахгүй." collapsible={false} />}
  </VStack>
}
