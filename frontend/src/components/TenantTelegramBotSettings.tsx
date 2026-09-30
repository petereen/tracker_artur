import { useState } from 'react'
import toast from 'react-hot-toast'
import { Bot, ExternalLink, Link2, RefreshCw, Unplug } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Code } from '@astryxdesign/core/Code'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Link } from '@astryxdesign/core/Link'
import { MetadataList, MetadataListItem } from '@astryxdesign/core/MetadataList'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Step, Stepper } from '@astryxdesign/core/Stepper'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type TenantTelegramBot, tenancyErrorMessage, useConnectTelegramBot, useDisconnectTelegramBot,
  useRenewTelegramHandshake, useTenantTelegramBot,
} from '../api/tenancy'
import { formatDate } from './TenantLicenseSettings'

const TOKEN_PATTERN = /^\d{5,16}:[A-Za-z0-9_-]{30,64}$/

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('mn-MN', { dateStyle: 'short', timeStyle: 'short' })
}

function statusOf(bot: TenantTelegramBot): { label: string; variant: 'success' | 'warning' | 'error' | 'neutral' } {
  if (bot.status === 'active') return bot.source === 'platform' ? { label: 'Платформын ботоор холбогдсон', variant: 'success' } : { label: 'Холбогдсон', variant: 'success' }
  if (bot.status === 'pending') return { label: 'Баталгаажуулалт хүлээж байна', variant: 'warning' }
  if (bot.status === 'error') return { label: 'Алдаа', variant: 'error' }
  return { label: 'Холбогдоогүй', variant: 'neutral' }
}

function activeStep(bot: TenantTelegramBot) {
  if (bot.status === 'active') return 3
  if (bot.status === 'pending') return 1
  return 0
}

/** Token form: step 1 of the handshake (also used to replace a bot). */
function TokenForm({ onDone, submitLabel }: { onDone?: () => void; submitLabel: string }) {
  const connect = useConnectTelegramBot()
  const [token, setToken] = useState('')
  const trimmed = token.trim()
  const invalid = Boolean(trimmed) && !TOKEN_PATTERN.test(trimmed)
  const submit = async () => {
    try {
      await connect.mutateAsync(trimmed)
      setToken('')
      toast.success('Токен баталгаажлаа. Одоо ботоо Telegram-аас баталгаажуулна уу.')
      onDone?.()
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Бот холбож чадсангүй'))
    }
  }
  return <VStack gap={3}>
    <TextInput label="BotFather токен" value={token} onChange={setToken} type="password" placeholder="123456789:AAH…"
      description="Telegram дээр @BotFather → /newbot командаар бот үүсгээд өгсөн токеныг буулгана. Токен шифрлэгдэж хадгалагдана."
      status={invalid ? { type: 'error', message: 'Токены хэлбэр буруу байна' } : undefined} autoComplete="off" />
    <HStack gap={2} hAlign="end">
      <Button label={submitLabel} variant="primary" icon={<Link2 size={15} />} clickAction={submit} isDisabled={!trimmed || invalid} />
    </HStack>
  </VStack>
}

/**
 * Settings → Интеграци → Telegram бот. Each tenant connects its own BotFather
 * bot; the handshake finishes when the admin opens the one-time /start link
 * and the bot runner receives it through that bot.
 */
export function TenantTelegramBotSettings() {
  const bot = useTenantTelegramBot()
  const renew = useRenewTelegramHandshake()
  const disconnect = useDisconnectTelegramBot()
  const [replacing, setReplacing] = useState(false)

  if (bot.isLoading) return <Card padding={5}><Skeleton height={180} /></Card>
  if (bot.isError || !bot.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(bot.error, 'Telegram ботын мэдээллийг ачаалж чадсангүй')} />

  const data = bot.data
  const status = statusOf(data)
  const connected = data.status !== 'not_connected'

  const renewLink = async () => {
    try {
      await renew.mutateAsync()
      toast.success('Шинэ холбоос үүслээ')
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Холбоос үүсгэж чадсангүй'))
    }
  }
  const remove = async () => {
    if (!window.confirm('Telegram ботыг салгах уу? Ажилтнууд ботоор мэдэгдэл авахаа болино.')) return
    try {
      await disconnect.mutateAsync()
      setReplacing(false)
      toast.success('Бот салгагдлаа')
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Бот салгаж чадсангүй'))
    }
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <VStack gap={1}>
          <Heading level={3}>Байгууллагын Telegram бот</Heading>
          <Text type="supporting">Даалгавар, сануулга, тайлан, цагийн бүртгэлийг танай байгууллагын өөрийн ботоор илгээнэ. Бусад байгууллагын өгөгдөлтэй холилдохгүй.</Text>
        </VStack>
        <HStack gap={2} vAlign="center"><StatusDot variant={status.variant} label={status.label} /><Text weight="semibold">{status.label}</Text></HStack>
      </HStack>

      {data.source !== 'platform' && <Stepper activeStep={activeStep(data)} label="Бот холбох алхам" density="compact" horizontalOptions={{ minimumStepWidth: 112, collapsedVariant: 'withLabel' }}>
        <Step step={0} label="Токен оруулах" description="@BotFather-ийн токен" />
        <Step step={1} label="Баталгаажуулах" description="Telegram-аас /start" status={data.status === 'error' ? 'error' : undefined} />
        <Step step={2} label="Ажиллаж байна" description="Мэдэгдэл илгээнэ" />
      </Stepper>}

      {data.status === 'error' && <Banner status="error" collapsible={false} title="Бот ажиллахгүй байна"
        description={data.last_error || 'Telegram токеныг хүлээн авсангүй. BotFather-аас шинэ токен авч дахин холбоно уу.'} />}

      {data.status === 'pending' && <Banner status="warning" collapsible={false} title="Сүүлийн алхам: ботоо баталгаажуулна уу"
        description={`Доорх холбоосыг админы Telegram-аас нээж «Start» дарна уу. Бот хариу өгмөгц энэ хуудас автоматаар шинэчлэгдэнэ.${data.handshake_expires_at ? ` Холбоос ${formatDateTime(data.handshake_expires_at)} хүртэл хүчинтэй.` : ''}`}
        endContent={data.handshake_url
          ? <Link href={data.handshake_url} isExternalLink target="_blank" rel="noreferrer">Telegram-аар нээх</Link>
          : undefined} />}

      {connected && <MetadataList columns={2}>
        <MetadataListItem label="Бот">{data.bot_username ? <Link href={`https://t.me/${data.bot_username}`} isExternalLink target="_blank" rel="noreferrer">{`@${data.bot_username}`}</Link> : (data.bot_name || '—')}</MetadataListItem>
        <MetadataListItem label="Нэр">{data.bot_name || '—'}</MetadataListItem>
        {data.source === 'tenant' && <MetadataListItem label="Сүүлд идэвхтэй">{data.online ? 'Одоо ажиллаж байна' : formatDateTime(data.last_seen_at)}</MetadataListItem>}
        {data.source === 'tenant' && <MetadataListItem label="Баталгаажсан">{data.handshake_completed_at ? formatDate(data.handshake_completed_at) : '—'}</MetadataListItem>}
        {data.bot_id ? <MetadataListItem label="Bot ID"><Code>{String(data.bot_id)}</Code></MetadataListItem> : null}
      </MetadataList>}

      {data.source === 'platform' && <Text type="supporting">Үндсэн байгууллага платформын ботыг ашиглаж байна. Өөрийн бот холбовол түүгээр солигдоно.</Text>}

      {(!connected || replacing || data.status === 'error') && <TokenForm submitLabel={connected ? 'Шинэ токеноор солих' : 'Холбох'} onDone={() => setReplacing(false)} />}

      {connected && <HStack gap={2} hAlign="end" wrap="wrap">
        {data.status === 'pending' && <Button label="Шинэ холбоос" variant="secondary" icon={<RefreshCw size={15} />} clickAction={renewLink} />}
        {data.bot_username && data.status === 'active' && <Button label="Ботыг нээх" variant="ghost" icon={<ExternalLink size={15} />} onClick={() => window.open(`https://t.me/${data.bot_username}`, '_blank', 'noopener')} />}
        {!replacing && data.status !== 'error' && <Button label={data.source === 'platform' ? 'Өөрийн бот холбох' : 'Бот солих'} variant="secondary" icon={<Bot size={15} />} onClick={() => setReplacing(true)} />}
        {data.source === 'tenant' && <Button label="Салгах" variant="destructive" icon={<Unplug size={15} />} clickAction={remove} />}
      </HStack>}
    </VStack>
  </Card>
}
