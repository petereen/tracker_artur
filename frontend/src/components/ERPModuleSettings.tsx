import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { BookText, Calculator, Handshake, PiggyBank } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { type ERPModule, useERPMetadata, useUpdateERPModules } from '../api/enterprise'
import { RouterLink } from './budget/shared'

// Only modules with their own workspace are switchable; each one adds its own
// sidebar entry when enabled. There is no separate ERP hub page.
const MODULES: Array<{ key: ERPModule; icon: typeof Handshake; to: string }> = [
  { key: 'crm', icon: Handshake, to: '/erp/crm' },
  { key: 'budget', icon: PiggyBank, to: '/erp/budget' },
  { key: 'payroll', icon: Calculator, to: '/erp/payroll' },
]

export function ERPModuleSettings() {
  const { t } = useTranslation()
  const metadata = useERPMetadata()
  const update = useUpdateERPModules()

  if (metadata.isLoading) return <Card padding={5}><Skeleton height={180} /></Card>
  if (metadata.isError || !metadata.data) return <Banner status="error" title={t('st.mod.loadFailed')} collapsible={false} />

  const modules = metadata.data.modules
  const toggle = (key: ERPModule, enabled: boolean) => {
    const next = Object.fromEntries(MODULES.map((module) => [module.key, Boolean(modules[module.key])])) as Record<ERPModule, boolean>
    update.mutate({ ...next, [key]: enabled }, {
      onSuccess: () => toast.success(enabled ? t('st.mod.enabled') : t('st.mod.disabled')),
      onError: (error: any) => toast.error(error.response?.data?.detail?.code || error.response?.data?.detail || t('st.mod.saveFailed')),
    })
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={3}>{t('st.mod.title')}</Heading>
        <Text type="supporting">{t('st.mod.intro')}</Text>
      </VStack>
      <List hasDividers>
        {MODULES.map(({ key, icon: Icon, to }) => {
          const enabled = Boolean(modules[key])
          const label = t(`st.mod.${key}.label`)
          return <ListItem
            key={key}
            label={label}
            description={t(`st.mod.${key}.description`)}
            startContent={<Icon size={20} aria-hidden />}
            endContent={<HStack gap={3} vAlign="center">
              {enabled && <Button size="sm" variant="ghost" label={t('st.mod.open')} href={to} as={RouterLink} />}
              <Switch label={t('st.mod.enableFor', { label })} isLabelHidden value={enabled} onChange={(value) => toggle(key, value)} isDisabled={update.isPending} />
            </HStack>}
          />
        })}
        <ListItem
          label={t('st.mod.chart')}
          description={t('st.mod.chartDesc')}
          startContent={<BookText size={20} aria-hidden />}
          endContent={<HStack gap={3} vAlign="center">
            <Token size="sm" color="gray" label={t('st.mod.base')} />
            <Button size="sm" variant="ghost" label={t('st.mod.open')} href="/erp/accounts" as={RouterLink} />
          </HStack>}
        />
      </List>
      <Text type="supporting">{t('st.mod.offHint')}</Text>
    </VStack>
  </Card>
}
