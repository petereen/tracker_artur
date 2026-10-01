import { Bell } from 'lucide-react'
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

function lockReason(category: PersonalNotificationCategory) {
  if (!category.available) return 'Байгууллагын хэмжээнд унтраасан'
  if (!category.editable) return 'Админ тогтоосон'
  return null
}

/** Profile: where each kind of notification reaches me (platform bell, Telegram). */
export function NotificationPreferencesCard() {
  const query = usePersonalNotificationPreferences()
  const update = useUpdatePersonalNotificationPreferences()
  const data = query.data
  const telegramReady = Boolean(data?.telegram_linked && data?.telegram_bot_connected)
  const change = (key: string, channel: 'web' | 'telegram', value: boolean) => update.mutate({ categories: { [key]: { [channel]: value } } })

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center"><Bell size={18} aria-hidden /><Heading level={3}>Мэдэгдлийн тохиргоо</Heading></HStack>
      <Text type="supporting">Ямар мэдэгдэл платформ (хонх) болон Telegram-аар ирэхийг сонгоно. Админ тогтоосон ангиллыг өөрчлөх боломжгүй.</Text>
      {query.isLoading && <Text type="supporting">Ачаалж байна…</Text>}
      {query.isError && <Banner status="error" title="Мэдэгдлийн тохиргоог ачаалж чадсангүй" />}
      {data && !telegramReady && <Banner status="info" collapsible={false}
        title="Telegram мэдэгдэл ирэхгүй"
        description={data.telegram_bot_connected ? 'Telegram хаягаа профайлаасаа холбосны дараа Telegram мэдэгдэл ирнэ.' : 'Байгууллагын Telegram бот холбогдоогүй байна.'} />}
      {data?.categories.map((category) => {
        const reason = lockReason(category)
        const locked = Boolean(reason)
        return <div key={category.key} role="group" aria-label={`${category.label} мэдэгдэл`}><HStack gap={3} vAlign="center" wrap="wrap">
          <StackItem size="fill">
            <VStack gap={0.5}>
              <HStack gap={1.5} vAlign="center" wrap="wrap"><Text weight="medium">{category.label}</Text>{reason && <Token size="sm" color="gray" label={reason} />}</HStack>
              <Text type="supporting">{category.description}</Text>
            </VStack>
          </StackItem>
          <Switch label="Платформ" size="sm" value={category.web} isDisabled={locked || update.isPending} onChange={(value) => change(category.key, 'web', value)} />
          <Switch label="Telegram" size="sm" value={category.telegram} isDisabled={locked || update.isPending || !telegramReady} onChange={(value) => change(category.key, 'telegram', value)} />
        </HStack></div>
      })}
    </VStack>
  </Card>
}
