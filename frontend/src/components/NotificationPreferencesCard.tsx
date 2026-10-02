import { Bell } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { Banner } from '@astryxdesign/core/Banner'
import { Card } from '@astryxdesign/core/Card'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { StackItem } from '@astryxdesign/core/Stack'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type PersonalNotificationCategory, usePersonalNotificationPreferences, useUpdatePersonalNotificationPreferences } from '../api/notificationSettings'
import { catalogText } from '../utils/labelMap'

function lockReason(category: PersonalNotificationCategory) {
  if (!category.available) return i18n.t('st.pref.lockedOrg')
  if (!category.editable) return i18n.t('st.pref.lockedAdmin')
  return null
}

/** Profile: where each kind of notification reaches me (platform bell, Telegram). */
export function NotificationPreferencesCard() {
  const { t } = useTranslation()
  const query = usePersonalNotificationPreferences()
  const update = useUpdatePersonalNotificationPreferences()
  const data = query.data
  const telegramReady = Boolean(data?.telegram_linked && data?.telegram_bot_connected)
  const change = (key: string, channel: 'web' | 'telegram', value: boolean) => update.mutate({ categories: { [key]: { [channel]: value } } })

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center"><Bell size={18} aria-hidden /><Heading level={3}>{t('st.notif.title')}</Heading></HStack>
      <Text type="supporting">{t('st.pref.intro')}</Text>
      {query.isLoading && <Text type="supporting">{t('st.common.loading')}</Text>}
      {query.isError && <Banner status="error" title={t('st.notif.loadFailed')} />}
      {data && !telegramReady && <Banner status="info" collapsible={false}
        title={t('st.pref.noTelegramTitle')}
        description={data.telegram_bot_connected ? t('st.pref.linkTelegram') : t('st.pref.noBot')} />}
      {data?.categories.map((category) => {
        const reason = lockReason(category)
        const locked = Boolean(reason)
        return <div key={category.key} role="group" aria-label={t('st.pref.groupAria', { label: catalogText(`cat.notif.${category.key}.label`, category.label) })}><HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <VStack gap={0.5}>
              <HStack gap={1.5} vAlign="center" wrap="wrap"><Text weight="medium">{catalogText(`cat.notif.${category.key}.label`, category.label)}</Text>{reason && <Token size="sm" color="gray" label={reason} />}</HStack>
              <Text type="supporting">{catalogText(`cat.notif.${category.key}.description`, category.description)}</Text>
            </VStack>
          </StackItem>
          <Switch label={t('st.notif.platform')} size="sm" value={category.web} isDisabled={locked || update.isPending} onChange={(value) => change(category.key, 'web', value)} />
          <Switch label={t('st.notif.telegram')} size="sm" value={category.telegram} isDisabled={locked || update.isPending || !telegramReady} onChange={(value) => change(category.key, 'telegram', value)} />
        </HStack></div>
      })}
    </VStack>
  </Card>
}
