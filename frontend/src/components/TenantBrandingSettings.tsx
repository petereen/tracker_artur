import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type EditableBranding, tenancyErrorMessage, useTenantBrandingSettings, useUpdateTenantBranding } from '../api/tenancy'
import { useAuthStore, EMPTY_ROLES } from '../store/auth'
import { isHexColor } from '../theme/tenantBranding'

const EMPTY: EditableBranding = { display_name: null, logo_url: null, favicon_url: null, primary_color: null, secondary_color: null }

function validUrl(value: string) {
  return !value || (value.startsWith('/') && !value.startsWith('//')) || value.toLowerCase().startsWith('https://')
}

/** Company name, logo/favicon URLs and brand colours applied to the whole workspace. */
export function TenantBrandingSettings() {
  const { t } = useTranslation()
  const settings = useTenantBrandingSettings()
  const update = useUpdateTenantBranding()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const [draft, setDraft] = useState<EditableBranding>(EMPTY)

  useEffect(() => { if (settings.data) setDraft(settings.data.branding) }, [settings.data])

  if (settings.isLoading) return <Card padding={5}><Skeleton height={200} /></Card>
  if (settings.isError || !settings.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(settings.error, t('st.brand.loadFailed'))} />

  const set = (key: keyof EditableBranding, value: string) => setDraft((current) => ({ ...current, [key]: value.trim() ? value : null }))
  const colorError = (value: string | null) => (value && !isHexColor(value) ? t('st.brand.hexError') : undefined)
  const urlError = (value: string | null) => (value && !validUrl(value) ? t('st.brand.urlError') : undefined)
  const invalid = Boolean(colorError(draft.primary_color) || colorError(draft.secondary_color) || urlError(draft.logo_url) || urlError(draft.favicon_url))
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.data.branding)

  const save = async () => {
    try {
      await update.mutateAsync(draft)
      toast.success(t('st.brand.saved'))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.brand.saveFailed')))
    }
  }

  const status = (message?: string) => (message ? { type: 'error' as const, message } : undefined)
  const preview = settings.data.preview
  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={3}>{t('st.adm.orgBranding')}</Heading>
        <Text type="supporting">{t('st.brand.intro')}</Text>
      </VStack>
      <FormLayout>
        <TextInput label={t('st.brand.name')} value={draft.display_name ?? ''} onChange={(value) => set('display_name', value)} isOptional isDisabled={!canEdit} placeholder={preview.name} />
        <TextInput label={t('st.brand.logoUrl')} value={draft.logo_url ?? ''} onChange={(value) => set('logo_url', value)} isOptional isDisabled={!canEdit}
          placeholder="https://…/logo.png" description={t('st.brand.logoHint')} status={status(urlError(draft.logo_url))} />
        <TextInput label={t('st.brand.faviconUrl')} value={draft.favicon_url ?? ''} onChange={(value) => set('favicon_url', value)} isOptional isDisabled={!canEdit}
          placeholder="https://…/favicon.png" status={status(urlError(draft.favicon_url))} />
        <TextInput label={t('st.brand.primary')} value={draft.primary_color ?? ''} onChange={(value) => set('primary_color', value)} isOptional isDisabled={!canEdit}
          placeholder="#2d62ec" width={160} status={status(colorError(draft.primary_color))} />
        <TextInput label={t('st.brand.secondary')} value={draft.secondary_color ?? ''} onChange={(value) => set('secondary_color', value)} isOptional isDisabled={!canEdit}
          placeholder="#00c885" width={160} status={status(colorError(draft.secondary_color))} />
      </FormLayout>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <HStack gap={2} vAlign="center" wrap="wrap">
          <Text type="supporting">{t('st.brand.current')}</Text>
          <Token size="sm" label={preview.name} />
          {preview.primary_color && <Token size="sm" color="blue" label={t('st.brand.primaryToken', { color: preview.primary_color })} />}
          {preview.secondary_color && <Token size="sm" color="green" label={t('st.brand.secondaryToken', { color: preview.secondary_color })} />}
        </HStack>
        {canEdit && <Button label={t('st.common.save')} variant="primary" clickAction={save} isDisabled={!dirty || invalid} />}
      </HStack>
    </VStack>
  </Card>
}
