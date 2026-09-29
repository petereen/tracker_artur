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
import { type ERPModule, useERPMetadata, useUpdateERPModules } from '../api/enterprise'
import { RouterLink } from './budget/shared'

// Only modules with their own workspace are switchable; each one adds its own
// sidebar entry when enabled. There is no separate ERP hub page.
const MODULES: Array<{ key: ERPModule; label: string; description: string; icon: typeof Handshake; to: string }> = [
  { key: 'crm', label: 'CRM · Харилцагч', description: 'Харилцагчийн бүртгэл, уулзалт, дуудлага, сануулга.', icon: Handshake, to: '/erp/crm' },
  { key: 'budget', label: 'Төсөв, гүйцэтгэл', description: 'Орлого, зардлын төсөв ба бодит гүйцэтгэлийн харьцуулалт.', icon: PiggyBank, to: '/erp/budget' },
  { key: 'payroll', label: 'Цалин', description: 'Сарын цалин бодолт, НДШ, ХХОАТ, банкны шилжүүлэг.', icon: Calculator, to: '/erp/payroll' },
]

export function ERPModuleSettings() {
  const metadata = useERPMetadata()
  const update = useUpdateERPModules()

  if (metadata.isLoading) return <Card padding={5}><Skeleton height={180} /></Card>
  if (metadata.isError || !metadata.data) return <Banner status="error" title="Модулийн тохиргоог ачаалж чадсангүй" collapsible={false} />

  const modules = metadata.data.modules
  const toggle = (key: ERPModule, enabled: boolean) => {
    const next = Object.fromEntries(MODULES.map((module) => [module.key, Boolean(modules[module.key])])) as Record<ERPModule, boolean>
    update.mutate({ ...next, [key]: enabled }, {
      onSuccess: () => toast.success(enabled ? 'Модулийг идэвхжүүллээ' : 'Модулийг унтраалаа'),
      onError: (error: any) => toast.error(error.response?.data?.detail?.code || error.response?.data?.detail || 'Модулийн тохиргоог хадгалж чадсангүй'),
    })
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={3}>Бизнесийн модулиуд</Heading>
        <Text type="supporting">Байгууллагадаа ашиглах модулийг асаана уу. Асаасан модуль хажуугийн цэсэнд гарч ирнэ. Хэн юу харахыг «Үүрэг ба эрх» хэсгийн ERP эрх тодорхойлно.</Text>
      </VStack>
      <List hasDividers>
        {MODULES.map(({ key, label, description, icon: Icon, to }) => {
          const enabled = Boolean(modules[key])
          return <ListItem
            key={key}
            label={label}
            description={description}
            startContent={<Icon size={20} aria-hidden />}
            endContent={<HStack gap={3} vAlign="center">
              {enabled && <Button size="sm" variant="ghost" label="Нээх" href={to} as={RouterLink} />}
              <Switch label={`${label} идэвхжүүлэх`} isLabelHidden value={enabled} onChange={(value) => toggle(key, value)} isDisabled={update.isPending} />
            </HStack>}
          />
        })}
        <ListItem
          label="Дансны төлөвлөгөө"
          description="Цалин, төсөв ашигладаг суурь данс. Үргэлж идэвхтэй."
          startContent={<BookText size={20} aria-hidden />}
          endContent={<HStack gap={3} vAlign="center">
            <Token size="sm" color="gray" label="Суурь" />
            <Button size="sm" variant="ghost" label="Нээх" href="/erp/accounts" as={RouterLink} />
          </HStack>}
        />
      </List>
      <Text type="supporting">Модулийг унтраахад зөвхөн цэснээс нуугдана. Өгөгдөл, эрх, аудит хэвээр хадгалагдана.</Text>
    </VStack>
  </Card>
}
