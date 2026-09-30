import { useState } from 'react'
import toast from 'react-hot-toast'
import { Copy, Globe, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Code } from '@astryxdesign/core/Code'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Icon } from '@astryxdesign/core/Icon'
import { Link } from '@astryxdesign/core/Link'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type TenantDnsRecord, type TenantDomain, tenancyErrorMessage, useAddTenantDomain, useRefreshTenantDomain,
  useRemoveTenantDomain, useTenantDomains,
} from '../api/tenancy'

const HOSTNAME = /^(?=.{4,253}$)(?:[a-z0-9\u0080-￿](?:[a-z0-9\u0080-￿-]{0,61}[a-z0-9\u0080-￿])?\.)+[a-z\u0080-￿][a-z0-9\u0080-￿-]{1,62}$/i

const DOMAIN_STATUS: Record<TenantDomain['status'], { label: string; variant: 'success' | 'warning' | 'error' }> = {
  active: { label: 'Идэвхтэй', variant: 'success' },
  pending: { label: 'DNS / SSL хүлээж байна', variant: 'warning' },
  error: { label: 'Алдаа', variant: 'error' },
}

const PURPOSE: Record<TenantDnsRecord['purpose'], string> = {
  routing: 'Чиглүүлэлт',
  ownership: 'Эзэмшил баталгаажуулах',
  certificate: 'SSL сертификат',
}

function cleanHostname(value: string) {
  return value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0].replace(/\.$/, '')
}

function copy(value: string) {
  void navigator.clipboard?.writeText(value).then(() => toast.success('Хуулагдлаа'))
}

interface RecordRow extends Record<string, unknown> { id: string; record: TenantDnsRecord }

function DnsRecords({ records }: { records: TenantDnsRecord[] }) {
  const rows: RecordRow[] = records.map((record, index) => ({ id: `${record.purpose}-${index}`, record }))
  return <Table<RecordRow> data={rows} idKey="id" density="compact" columns={[
    { key: 'type', header: 'Төрөл', width: pixel(90), renderCell: ({ record }) => <Token size="sm" color={record.type === 'CNAME' ? 'blue' : 'gray'} label={record.type} /> },
    { key: 'name', header: 'Нэр (Host)', width: proportional(2), renderCell: ({ record }) => <HStack gap={1} vAlign="center"><Code>{record.name}</Code><Button label="Нэр хуулах" isIconOnly size="sm" variant="ghost" icon={<Copy size={13} />} onClick={() => copy(record.name)} /></HStack> },
    { key: 'value', header: 'Утга (Target)', width: proportional(3), renderCell: ({ record }) => <HStack gap={1} vAlign="center"><Code>{record.value}</Code><Button label="Утга хуулах" isIconOnly size="sm" variant="ghost" icon={<Copy size={13} />} onClick={() => copy(record.value)} /></HStack> },
    { key: 'purpose', header: 'Зориулалт', width: pixel(170), renderCell: ({ record }) => <Text type="supporting">{PURPOSE[record.purpose] ?? record.purpose}</Text> },
  ]} />
}

function DomainCard({ domain }: { domain: TenantDomain }) {
  const refresh = useRefreshTenantDomain()
  const remove = useRemoveTenantDomain()
  const status = DOMAIN_STATUS[domain.status] ?? DOMAIN_STATUS.pending
  const check = async () => {
    try {
      const result = await refresh.mutateAsync(domain.id)
      toast.success(result.status === 'active' ? 'Домэйн идэвхжлээ' : 'Шалгалаа — DNS эсвэл SSL хүлээгдэж байна')
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Шалгаж чадсангүй'))
    }
  }
  const destroy = async () => {
    if (!window.confirm(`${domain.hostname} домэйнийг салгах уу? Энэ хаягаар нэвтрэх боломжгүй болно.`)) return
    try {
      await remove.mutateAsync(domain.id)
      toast.success('Домэйн салгагдлаа')
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Домэйн салгаж чадсангүй'))
    }
  }
  return <Card padding={4}>
    <VStack gap={3}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Icon icon={Globe} color="secondary" />
          {domain.status === 'active' ? <Link href={domain.url} isExternalLink target="_blank" rel="noreferrer">{domain.hostname}</Link> : <Text weight="semibold">{domain.hostname}</Text>}
          <StatusDot variant={status.variant} label={status.label} />
          <Text type="supporting">{status.label}{domain.ssl_status && domain.status !== 'active' ? ` · SSL: ${domain.ssl_status}` : ''}</Text>
        </HStack>
        <HStack gap={2}>
          {domain.provider === 'cloudflare' && <Button label="Шалгах" size="sm" variant="secondary" icon={<RefreshCw size={14} />} clickAction={check} />}
          <Button label="Салгах" size="sm" variant="ghost" icon={<Trash2 size={14} />} clickAction={destroy} />
        </HStack>
      </HStack>
      {domain.last_error && <Banner status="error" collapsible={false} title="Cloudflare-ийн мэдэгдэл" description={domain.last_error} />}
      {domain.status !== 'active' && domain.dns_records.length > 0 && <VStack gap={2}>
        <Text type="supporting">Домэйнээ удирддаг DNS үйлчилгээнд (Cloudflare, GoDaddy, Datacom г.м.) доорх бичлэгүүдийг нэмнэ үү. Шалгалт 5 минут тутамд автоматаар явагдана.</Text>
        <DnsRecords records={domain.dns_records} />
      </VStack>}
    </VStack>
  </Card>
}

/** Settings → Байгууллага → Өөрийн домэйн: Cloudflare for SaaS custom hostnames. */
export function TenantDomainSettings() {
  const domains = useTenantDomains()
  const add = useAddTenantDomain()
  const [hostname, setHostname] = useState('')

  if (domains.isLoading) return <Card padding={5}><Skeleton height={200} /></Card>
  if (domains.isError || !domains.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(domains.error, 'Домэйны мэдээллийг ачаалж чадсангүй')} />

  const data = domains.data
  const value = cleanHostname(hostname)
  const invalid = Boolean(value) && !HOSTNAME.test(value)
  const full = data.domains.length >= data.limit
  const submit = async () => {
    try {
      await add.mutateAsync(value)
      setHostname('')
      toast.success('Домэйн нэмэгдлээ. DNS бичлэгүүдээ тохируулна уу.')
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Домэйн нэмж чадсангүй'))
    }
  }

  return <VStack gap={4}>
    <Card padding={5}>
      <VStack gap={4}>
        <VStack gap={1}>
          <Heading level={3}>Өөрийн домэйн холбох</Heading>
          <Text type="supporting">Ажилтнууд танай домэйн (жишээ нь erp.company.mn) хаягаар нэвтэрнэ. Cloudflare автоматаар SSL сертификат олгож, хүсэлтийг OYUNS ERP рүү дамжуулна.</Text>
        </VStack>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Text type="supporting">Одоогийн хаяг:</Text>
          <Link href={data.platform_url} isExternalLink target="_blank" rel="noreferrer">{data.platform_url.replace(/^https?:\/\//, '')}</Link>
        </HStack>
        {!data.available && <Banner status="info" collapsible={false} title="Өөрийн домэйн холбох үйлчилгээ идэвхгүй"
          description="Платформын Cloudflare тохиргоо хийгдээгүй байна. OYUNS ERP үйлчилгээ үзүүлэгчтэй холбогдоно уу." />}
        {data.available && data.cname_target && <Text type="supporting">{`Домэйнээ CNAME бичлэгээр ${data.cname_target} руу заана. Үндсэн домэйн (company.mn) бол DNS үйлчилгээ тань CNAME flattening / ALIAS дэмжих шаардлагатай тул дэд домэйн (erp.company.mn) ашиглахыг зөвлөж байна.`}</Text>}
        <HStack gap={2} vAlign="end" wrap="wrap">
          <TextInput label="Домэйн" value={hostname} onChange={setHostname} placeholder="erp.company.mn" width={320}
            onEnter={() => { if (value && !invalid && !full && data.available) void submit() }}
            isDisabled={!data.available || full} disabledMessage={full ? `${data.limit} хүртэл домэйн холбоно` : 'Үйлчилгээ идэвхгүй'}
            status={invalid ? { type: 'error', message: 'Домэйн нэр буруу' } : undefined} />
          <Button label="Нэмэх" variant="primary" icon={<Plus size={15} />} clickAction={submit} isDisabled={!data.available || full || !value || invalid} />
        </HStack>
      </VStack>
    </Card>
    {data.domains.length === 0
      ? <Card padding={0}><EmptyState title="Холбосон домэйн алга" description="Нэмсэн домэйн, түүний DNS бичлэг, SSL төлөв энд харагдана." /></Card>
      : data.domains.map((domain) => <DomainCard key={domain.id} domain={domain} />)}
  </VStack>
}
