import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Switch } from '@astryxdesign/core/Switch'
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type TenantNotificationCategory, useTenantNotificationSettings, useUpdateTenantNotificationSettings } from '../api/notificationSettings'
import { catalogText } from '../utils/labelMap'

type Rule = Pick<TenantNotificationCategory, 'enabled' | 'web' | 'telegram' | 'user_editable'>
type Draft = Record<string, Rule>

function toDraft(categories: TenantNotificationCategory[]): Draft {
  return Object.fromEntries(categories.map(({ key, enabled, web, telegram, user_editable }) => [key, { enabled, web, telegram, user_editable }]))
}

/**
 * Company-wide notification rules: which categories exist, their web and
 * Telegram defaults, and whether workers may change them in their profile.
 * Telegram messages follow exactly these rules.
 */
export function NotificationSettings() {
  const { t } = useTranslation()
  const query = useTenantNotificationSettings()
  const update = useUpdateTenantNotificationSettings()
  const [draft, setDraft] = useState<Draft | null>(null)

  useEffect(() => { if (query.data) setDraft(toDraft(query.data.categories)) }, [query.data])

  if (query.isLoading || !draft) return <Text type="supporting">{t('st.common.loading')}</Text>
  if (query.isError || !query.data) return <Banner status="error" title={t('st.notif.loadFailed')} />

  const saved = toDraft(query.data.categories)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const set = (key: string, patch: Partial<Rule>) => setDraft({ ...draft, [key]: { ...draft[key], ...patch } })
  const enabledCount = query.data.categories.filter((category) => draft[category.key]?.enabled).length

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Heading level={3}>{t('st.notif.title')}</Heading>
        <Token size="sm" label={t('st.notif.activeCount', { n: enabledCount, total: query.data.categories.length })} color="blue" />
      </HStack>
      <Text type="supporting">{t('st.notif.intro')}</Text>
      <Table density="compact">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{t('st.notif.category')}</TableHeaderCell>
            <TableHeaderCell>{t('st.notif.active')}</TableHeaderCell>
            <TableHeaderCell>{t('st.notif.platform')}</TableHeaderCell>
            <TableHeaderCell>{t('st.notif.telegram')}</TableHeaderCell>
            <TableHeaderCell>{t('st.notif.userEditable')}</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data.categories.map((category) => {
            const rule = draft[category.key]
            const off = !rule.enabled
            return <TableRow key={category.key}>
              <TableCell>
                <VStack gap={0.5}>
                  <HStack gap={1.5} vAlign="center" wrap="wrap"><Text weight="medium">{catalogText(`cat.notif.${category.key}.label`, category.label)}</Text>{category.legacy && <Token size="sm" color="gray" label={t('st.notif.legacy')} />}</HStack>
                  <Text type="supporting">{catalogText(`cat.notif.${category.key}.description`, category.description)}</Text>
                </VStack>
              </TableCell>
              <TableCell><Switch label={t('st.notif.activeFor', { label: catalogText(`cat.notif.${category.key}.label`, category.label) })} isLabelHidden value={rule.enabled} onChange={(value) => set(category.key, { enabled: value })} /></TableCell>
              <TableCell><Switch label={t('st.notif.platformFor', { label: catalogText(`cat.notif.${category.key}.label`, category.label) })} isLabelHidden value={rule.web} isDisabled={off} onChange={(value) => set(category.key, { web: value })} /></TableCell>
              <TableCell><Switch label={t('st.notif.telegramFor', { label: catalogText(`cat.notif.${category.key}.label`, category.label) })} isLabelHidden value={rule.telegram} isDisabled={off} onChange={(value) => set(category.key, { telegram: value })} /></TableCell>
              <TableCell><Switch label={t('st.notif.userEditableFor', { label: catalogText(`cat.notif.${category.key}.label`, category.label) })} isLabelHidden value={rule.user_editable} isDisabled={off} onChange={(value) => set(category.key, { user_editable: value })} /></TableCell>
            </TableRow>
          })}
        </TableBody>
      </Table>
      <Text type="supporting">{t('st.notif.quietHint')}</Text>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label={t('st.common.save')} variant="primary" isDisabled={!dirty} isLoading={update.isPending} onClick={() => update.mutate({ categories: draft })} />
        {dirty && <Button label={t('st.common.revert')} onClick={() => setDraft(saved)} />}
      </HStack>
    </VStack>
  </Card>
}
