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
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { labelOr } from '../utils/labelMap'
import {
  type TenantDnsRecord, type TenantDomain, tenancyErrorMessage, useAddTenantDomain, useRefreshTenantDomain,
  useRemoveTenantDomain, useTenantDomains,
} from '../api/tenancy'

const HOSTNAME = /^(?=.{4,253}$)(?:[a-z0-9\u0080-￿](?:[a-z0-9\u0080-￿-]{0,61}[a-z0-9\u0080-￿])?\.)+[a-z\u0080-￿][a-z0-9\u0080-￿-]{1,62}$/i

const DOMAIN_STATUS_VARIANT: Record<TenantDomain['status'], 'success' | 'warning' | 'error'> = { active: 'success', pending: 'warning', error: 'error' }

function cleanHostname(value: string) {
  return value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0].replace(/\.$/, '')
}

function copy(value: string) {
  void navigator.clipboard?.writeText(value).then(() => toast.success(i18n.t('st.dom.copied')))
}

interface RecordRow extends Record<string, unknown> { id: string; record: TenantDnsRecord }

function DnsRecords({ records }: { records: TenantDnsRecord[] }) {
  const { t } = useTranslation()
  const rows: RecordRow[] = records.map((record, index) => ({ id: `${record.purpose}-${index}`, record }))
  return <Table<RecordRow> data={rows} idKey="id" density="compact" columns={[
    { key: 'type', header: t('st.dom.col.type'), width: pixel(90), renderCell: ({ record }) => <Token size="sm" color={record.type === 'CNAME' ? 'blue' : 'gray'} label={record.type} /> },
    { key: 'name', header: t('st.dom.col.name'), width: proportional(2), renderCell: ({ record }) => <HStack gap={1} vAlign="center"><Code>{record.name}</Code><Button label={t('st.dom.copyName')} isIconOnly size="sm" variant="ghost" icon={<Copy size={13} />} onClick={() => copy(record.name)} /></HStack> },
    { key: 'value', header: t('st.dom.col.value'), width: proportional(3), renderCell: ({ record }) => <HStack gap={1} vAlign="center"><Code>{record.value}</Code><Button label={t('st.dom.copyValue')} isIconOnly size="sm" variant="ghost" icon={<Copy size={13} />} onClick={() => copy(record.value)} /></HStack> },
    { key: 'purpose', header: t('st.dom.col.purpose'), width: pixel(170), renderCell: ({ record }) => <Text type="supporting">{labelOr('st.dom.purpose', record.purpose)}</Text> },
  ]} />
}

function DomainCard({ domain }: { domain: TenantDomain }) {
  const { t } = useTranslation()
  const refresh = useRefreshTenantDomain()
  const remove = useRemoveTenantDomain()
  const statusKey = domain.status in DOMAIN_STATUS_VARIANT ? domain.status : 'pending'
  const status = { label: t(`st.dom.status.${statusKey}`), variant: DOMAIN_STATUS_VARIANT[statusKey] }
  const check = async () => {
    try {
      const result = await refresh.mutateAsync(domain.id)
      toast.success(result.status === 'active' ? t('st.dom.activated') : t('st.dom.checkedPending'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.dom.checkFailed')))
    }
  }
  const destroy = async () => {
    if (!window.confirm(t('st.dom.confirmRemove', { hostname: domain.hostname }))) return
    try {
      await remove.mutateAsync(domain.id)
      toast.success(t('st.dom.removed'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.dom.removeFailed')))
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
          {domain.provider === 'cloudflare' && <Button label={t('st.dom.verify')} size="sm" variant="secondary" icon={<RefreshCw size={14} />} clickAction={check} />}
          <Button label={t('st.dom.remove')} size="sm" variant="ghost" icon={<Trash2 size={14} />} clickAction={destroy} />
        </HStack>
      </HStack>
      {domain.last_error && <Banner status="error" collapsible={false} title={t('st.dom.cloudflareMessage')} description={domain.last_error} />}
      {domain.status !== 'active' && domain.dns_records.length > 0 && <VStack gap={2}>
        <Text type="supporting">{t('st.dom.dnsHint')}</Text>
        <DnsRecords records={domain.dns_records} />
      </VStack>}
    </VStack>
  </Card>
}

/** Settings → Байгууллага → Өөрийн домэйн: Cloudflare for SaaS custom hostnames. */
export function TenantDomainSettings() {
  const { t } = useTranslation()
  const domains = useTenantDomains()
  const add = useAddTenantDomain()
  const [hostname, setHostname] = useState('')

  if (domains.isLoading) return <Card padding={5}><Skeleton height={200} /></Card>
  if (domains.isError || !domains.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(domains.error, t('st.dom.loadFailed'))} />

  const data = domains.data
  const value = cleanHostname(hostname)
  const invalid = Boolean(value) && !HOSTNAME.test(value)
  const full = data.domains.length >= data.limit
  const submit = async () => {
    try {
      await add.mutateAsync(value)
      setHostname('')
      toast.success(t('st.dom.added'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.dom.addFailed')))
    }
  }

  return <VStack gap={4}>
    <Card padding={5}>
      <VStack gap={4}>
        <VStack gap={1}>
          <Heading level={3}>{t('st.dom.connectTitle')}</Heading>
          <Text type="supporting">{t('st.dom.intro')}</Text>
        </VStack>
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Text type="supporting">{t('st.dom.currentAddress')}</Text>
          <Link href={data.platform_url} isExternalLink target="_blank" rel="noreferrer">{data.platform_url.replace(/^https?:\/\//, '')}</Link>
        </HStack>
        {!data.available && <Banner status="info" collapsible={false} title={t('st.dom.unavailableTitle')}
          description={t('st.dom.unavailableDesc')} />}
        {data.available && data.cname_target && <Text type="supporting">{t('st.dom.cnameHint', { target: data.cname_target })}</Text>}
        <HStack gap={2} vAlign="end" wrap="wrap">
          <TextInput label={t('st.dom.domain')} value={hostname} onChange={setHostname} placeholder="erp.company.mn" width={320}
            onEnter={() => { if (value && !invalid && !full && data.available) void submit() }}
            isDisabled={!data.available || full} disabledMessage={full ? t('st.dom.limit', { limit: data.limit }) : t('st.dom.serviceOff')}
            status={invalid ? { type: 'error', message: t('st.dom.invalid') } : undefined} />
          <Button label={t('st.dom.add')} variant="primary" icon={<Plus size={15} />} clickAction={submit} isDisabled={!data.available || full || !value || invalid} />
        </HStack>
      </VStack>
    </Card>
    {data.domains.length === 0
      ? <Card padding={0}><EmptyState title={t('st.dom.emptyTitle')} description={t('st.dom.emptyDesc')} /></Card>
      : data.domains.map((domain) => <DomainCard key={domain.id} domain={domain} />)}
  </VStack>
}
