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
import { intlLocale } from '../utils/locale'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { formatDate } from './TenantLicenseSettings'

const TOKEN_PATTERN = /^\d{5,16}:[A-Za-z0-9_-]{30,64}$/

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(intlLocale(), { dateStyle: 'short', timeStyle: 'short' })
}

function statusOf(bot: TenantTelegramBot): { label: string; variant: 'success' | 'warning' | 'error' | 'neutral' } {
  if (bot.status === 'active') return { label: i18n.t(bot.source === 'platform' ? 'st.tg.status.platform' : 'st.tg.status.connected'), variant: 'success' }
  if (bot.status === 'pending') return { label: i18n.t('st.tg.status.pending'), variant: 'warning' }
  if (bot.status === 'error') return { label: i18n.t('st.tg.status.error'), variant: 'error' }
  return { label: i18n.t('st.tg.status.none'), variant: 'neutral' }
}

function activeStep(bot: TenantTelegramBot) {
  if (bot.status === 'active') return 3
  if (bot.status === 'pending') return 1
  return 0
}

/** Token form: step 1 of the handshake (also used to replace a bot). */
function TokenForm({ onDone, submitLabel }: { onDone?: () => void; submitLabel: string }) {
  const { t } = useTranslation()
  const connect = useConnectTelegramBot()
  const [token, setToken] = useState('')
  const trimmed = token.trim()
  const invalid = Boolean(trimmed) && !TOKEN_PATTERN.test(trimmed)
  const submit = async () => {
    try {
      await connect.mutateAsync(trimmed)
      setToken('')
      toast.success(t('st.tg.tokenOk'))
      onDone?.()
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.tg.connectFailed')))
    }
  }
  return <VStack gap={3}>
    <TextInput label={t('st.tg.tokenLabel')} value={token} onChange={setToken} type="password" placeholder="123456789:AAH…"
      description={t('st.tg.tokenHint')}
      status={invalid ? { type: 'error', message: t('st.tg.tokenInvalid') } : undefined} autoComplete="off" />
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
  const { t } = useTranslation()
  const bot = useTenantTelegramBot()
  const renew = useRenewTelegramHandshake()
  const disconnect = useDisconnectTelegramBot()
  const [replacing, setReplacing] = useState(false)

  if (bot.isLoading) return <Card padding={5}><Skeleton height={180} /></Card>
  if (bot.isError || !bot.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(bot.error, t('st.tg.loadFailed'))} />

  const data = bot.data
  const status = statusOf(data)
  const connected = data.status !== 'not_connected'

  const renewLink = async () => {
    try {
      await renew.mutateAsync()
      toast.success(t('st.tg.linkCreated'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.tg.linkFailed')))
    }
  }
  const remove = async () => {
    if (!window.confirm(t('st.tg.disconnectConfirm'))) return
    try {
      await disconnect.mutateAsync()
      setReplacing(false)
      toast.success(t('st.tg.disconnected'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.tg.disconnectFailed')))
    }
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <VStack gap={1}>
          <Heading level={3}>{t('st.tg.title')}</Heading>
          <Text type="supporting">{t('st.tg.intro')}</Text>
        </VStack>
        <HStack gap={2} vAlign="center"><StatusDot variant={status.variant} label={status.label} /><Text weight="semibold">{status.label}</Text></HStack>
      </HStack>

      {data.source !== 'platform' && <Stepper activeStep={activeStep(data)} label={t('st.tg.stepsLabel')} density="compact" horizontalOptions={{ minimumStepWidth: 112, collapsedVariant: 'withLabel' }}>
        <Step step={0} label={t('st.tg.step1')} description={t('st.tg.step1Desc')} />
        <Step step={1} label={t('st.tg.step2')} description={t('st.tg.step2Desc')} status={data.status === 'error' ? 'error' : undefined} />
        <Step step={2} label={t('st.tg.step3')} description={t('st.tg.step3Desc')} />
      </Stepper>}

      {data.status === 'error' && <Banner status="error" collapsible={false} title={t('st.tg.errorTitle')}
        description={data.last_error || t('st.tg.errorDesc')} />}

      {data.status === 'pending' && <Banner status="warning" collapsible={false} title={t('st.tg.pendingTitle')}
        description={`${t('st.tg.pendingDesc')}${data.handshake_expires_at ? ` ${t('st.tg.linkValidUntil', { date: formatDateTime(data.handshake_expires_at) })}` : ''}`}
        endContent={data.handshake_url
          ? <Link href={data.handshake_url} isExternalLink target="_blank" rel="noreferrer">{t('st.tg.openInTelegram')}</Link>
          : undefined} />}

      {connected && <MetadataList columns={2}>
        <MetadataListItem label={t('st.tg.bot')}>{data.bot_username ? <Link href={`https://t.me/${data.bot_username}`} isExternalLink target="_blank" rel="noreferrer">{`@${data.bot_username}`}</Link> : (data.bot_name || '—')}</MetadataListItem>
        <MetadataListItem label={t('st.tg.name')}>{data.bot_name || '—'}</MetadataListItem>
        {data.source === 'tenant' && <MetadataListItem label={t('st.tg.lastSeen')}>{data.online ? t('st.tg.onlineNow') : formatDateTime(data.last_seen_at)}</MetadataListItem>}
        {data.source === 'tenant' && <MetadataListItem label={t('st.tg.confirmed')}>{data.handshake_completed_at ? formatDate(data.handshake_completed_at) : '—'}</MetadataListItem>}
        {data.bot_id ? <MetadataListItem label="Bot ID"><Code>{String(data.bot_id)}</Code></MetadataListItem> : null}
      </MetadataList>}

      {data.source === 'platform' && <Text type="supporting">{t('st.tg.platformNote')}</Text>}

      {(!connected || replacing || data.status === 'error') && <TokenForm submitLabel={connected ? t('st.tg.replaceWithToken') : t('st.tg.connect')} onDone={() => setReplacing(false)} />}

      {connected && <HStack gap={2} hAlign="end" wrap="wrap">
        {data.status === 'pending' && <Button label={t('st.tg.newLink')} variant="secondary" icon={<RefreshCw size={15} />} clickAction={renewLink} />}
        {data.bot_username && data.status === 'active' && <Button label={t('st.tg.openBot')} variant="ghost" icon={<ExternalLink size={15} />} onClick={() => window.open(`https://t.me/${data.bot_username}`, '_blank', 'noopener')} />}
        {!replacing && data.status !== 'error' && <Button label={data.source === 'platform' ? t('st.tg.connectOwn') : t('st.tg.replaceBot')} variant="secondary" icon={<Bot size={15} />} onClick={() => setReplacing(true)} />}
        {data.source === 'tenant' && <Button label={t('st.tg.disconnect')} variant="destructive" icon={<Unplug size={15} />} clickAction={remove} />}
      </HStack>}
    </VStack>
  </Card>
}
