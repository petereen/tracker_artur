import { useEffect, useRef, useState, type CSSProperties } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Link2, Paperclip, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type EditableBranding, tenancyErrorMessage, useTenantBrandingSettings, useUpdateTenantBranding } from '../api/tenancy'
import { useAuthStore, EMPTY_ROLES } from '../store/auth'
import { isHexColor, lighten, onColor } from '../theme/tenantBranding'

const EMPTY: EditableBranding = { display_name: null, logo_url: null, favicon_url: null, primary_color: null, secondary_color: null }

const LOGO_MAX_BYTES = 512 * 1024
const FAVICON_MAX_BYTES = 128 * 1024
const IMAGE_TYPES = 'image/png,image/jpeg,image/webp,image/gif,image/x-icon,image/vnd.microsoft.icon,.ico'
const DEFAULT_PRIMARY = '#2d62ec'
const DEFAULT_SECONDARY = '#00c885'

const isDataImage = (value: string | null) => Boolean(value?.startsWith('data:image/'))
const dataSizeKb = (value: string) => Math.max(1, Math.round(((value.length - value.indexOf(',') - 1) * 3) / 4 / 1024))

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function validUrl(value: string) {
  return !value || isDataImage(value) || (value.startsWith('/') && !value.startsWith('//')) || value.toLowerCase().startsWith('https://')
}

interface ImageFieldProps {
  label: string
  description: string
  value: string | null
  fallbackSrc: string
  maxBytes: number
  isDisabled: boolean
  error?: string
  onChange: (value: string | null) => void
}

/** Image setting with three controls: attach a file, enter a URL, delete (icon-only). */
function ImageField({ label, description, value, fallbackSrc, maxBytes, isDisabled, error, onChange }: ImageFieldProps) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [urlOpen, setUrlOpen] = useState(Boolean(value) && !isDataImage(value))
  const [fileError, setFileError] = useState<string>()

  const attach = async (file: File | undefined) => {
    if (!file) return
    if (!file.type.startsWith('image/') || file.type === 'image/svg+xml') return setFileError(t('st.brand.fileType'))
    if (file.size > maxBytes) return setFileError(t('st.brand.fileTooBig', { kb: Math.round(maxBytes / 1024) }))
    try {
      onChange(await readAsDataUrl(file))
      setFileError(undefined)
      setUrlOpen(false)
    } catch {
      setFileError(t('st.brand.fileReadFailed'))
    }
  }

  return <VStack gap={2}>
    <VStack gap={0}>
      <Text weight="semibold">{label}</Text>
      <Text type="supporting">{description}</Text>
    </VStack>
    <HStack gap={3} vAlign="center" wrap="wrap">
      <div style={{ width: 48, height: 48, borderRadius: 10, border: '1px solid var(--color-border)', background: 'var(--color-surface-2)', display: 'grid', placeItems: 'center', overflow: 'hidden', flex: 'none' }}>
        <img src={value || fallbackSrc} alt={label} style={{ maxWidth: '80%', maxHeight: '80%', objectFit: 'contain', opacity: value ? 1 : 0.45 }} />
      </div>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label={t('st.brand.attachFile')} variant="secondary" size="sm" icon={<Paperclip size={15} />} isDisabled={isDisabled} onClick={() => input.current?.click()} />
        <Button label={t('st.brand.useUrl')} variant={urlOpen ? 'primary' : 'secondary'} size="sm" icon={<Link2 size={15} />} isDisabled={isDisabled} onClick={() => setUrlOpen((open) => !open)} />
        <Button label={t('st.brand.remove')} tooltip={t('st.brand.remove')} variant="secondary" size="sm" icon={<Trash2 size={15} />} isIconOnly
          isDisabled={isDisabled || !value} onClick={() => { onChange(null); setUrlOpen(false); setFileError(undefined) }} />
        <input ref={input} type="file" accept={IMAGE_TYPES} hidden aria-label={t('st.brand.attachFile')}
          onChange={(event) => { void attach(event.target.files?.[0]); event.target.value = '' }} />
      </HStack>
      {isDataImage(value) && <Token size="sm" label={t('st.brand.attached', { kb: dataSizeKb(value as string) })} />}
    </HStack>
    {urlOpen && <TextInput label={t('st.brand.urlLabel')} isLabelHidden value={isDataImage(value) ? '' : value ?? ''} onChange={(next) => onChange(next.trim() ? next : null)}
      isDisabled={isDisabled} placeholder="https://…" status={error || fileError ? { type: 'error', message: (error || fileError) as string } : undefined} />}
    {!urlOpen && (error || fileError) && <span role="alert" style={{ color: 'var(--color-red-strong)', fontSize: 13 }}>{error || fileError}</span>}
  </VStack>
}

interface PreviewProps { name: string; logoLight: string; logoDark: string; favicon: string; primary: string; secondary: string }

/** Mock of the workspace in light and dark theme with the draft branding applied. */
function BrandPreview({ name, logoLight, logoDark, favicon, primary, secondary }: PreviewProps) {
  const { t } = useTranslation()
  const panes = [
    { key: 'light', label: t('st.brand.previewLight'), logo: logoLight, accent: primary, bg: '#f4f6fa', surface: '#ffffff', text: '#231f20', muted: '#667085', border: 'rgba(35,31,32,0.12)' },
    { key: 'dark', label: t('st.brand.previewDark'), logo: logoDark, accent: lighten(primary, 0.35), bg: '#0d1220', surface: '#161c2c', text: '#eef1f7', muted: '#98a2b3', border: 'rgba(255,255,255,0.14)' },
  ]
  return <Grid columns={{ minWidth: 260, max: 2 }} gap={3}>
    {panes.map((pane) => {
      const on = onColor(pane.accent)
      const frame: CSSProperties = { background: pane.bg, color: pane.text, border: `1px solid ${pane.border}`, borderRadius: 12, padding: 12, display: 'grid', gap: 10 }
      const box: CSSProperties = { background: pane.surface, border: `1px solid ${pane.border}`, borderRadius: 8 }
      return <div key={pane.key} style={frame} data-testid={`brand-preview-${pane.key}`}>
        <span style={{ fontSize: 11, fontWeight: 600, color: pane.muted, textTransform: 'uppercase', letterSpacing: 0.4 }}>{pane.label}</span>
        <div style={{ ...box, display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', fontSize: 11, color: pane.muted }}>
          <img src={favicon} alt="" width={14} height={14} style={{ objectFit: 'contain' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{`${name} · OYUNS ERP`}</span>
        </div>
        <div style={{ ...box, padding: 10, display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <img src={pane.logo} alt="" height={24} style={{ maxWidth: 80, objectFit: 'contain' }} />
            <strong style={{ fontSize: 13 }}>{name}</strong>
          </div>
          <div style={{ background: `color-mix(in srgb, ${pane.accent} 14%, ${pane.surface})`, color: pane.accent, borderRadius: 6, padding: '6px 8px', fontSize: 12, fontWeight: 600 }}>{t('st.brand.previewNav')}</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ background: pane.accent, color: on, borderRadius: 6, padding: '5px 10px', fontSize: 12, fontWeight: 600 }}>{t('st.brand.previewButton')}</span>
            <span style={{ background: secondary, color: onColor(secondary), borderRadius: 999, padding: '3px 9px', fontSize: 11, fontWeight: 600 }}>{t('st.brand.previewBadge')}</span>
            <span style={{ color: pane.accent, fontSize: 12, textDecoration: 'underline' }}>{t('st.brand.previewLink')}</span>
          </div>
        </div>
      </div>
    })}
  </Grid>
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
  const setImage = (key: 'logo_url' | 'favicon_url', value: string | null) => setDraft((current) => ({ ...current, [key]: value }))
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
        <TextInput label={t('st.brand.name')} value={draft.display_name ?? ''} onChange={(value) => set('display_name', value)} isDisabled={!canEdit} placeholder={preview.name}
          description={t('st.brand.nameUse')} />
        <ImageField label={t('st.brand.logoUrl')} description={t('st.brand.logoUse')} value={draft.logo_url} fallbackSrc={preview.logo_url} maxBytes={LOGO_MAX_BYTES}
          isDisabled={!canEdit} error={urlError(draft.logo_url)} onChange={(value) => setImage('logo_url', value)} />
        <ImageField label={t('st.brand.faviconUrl')} description={t('st.brand.faviconUse')} value={draft.favicon_url} fallbackSrc={preview.favicon_url} maxBytes={FAVICON_MAX_BYTES}
          isDisabled={!canEdit} error={urlError(draft.favicon_url)} onChange={(value) => setImage('favicon_url', value)} />
        <TextInput label={t('st.brand.primary')} value={draft.primary_color ?? ''} onChange={(value) => set('primary_color', value)} isDisabled={!canEdit}
          placeholder={DEFAULT_PRIMARY} description={t('st.brand.primaryUse')} width={260} status={status(colorError(draft.primary_color))} />
        <TextInput label={t('st.brand.secondary')} value={draft.secondary_color ?? ''} onChange={(value) => set('secondary_color', value)} isDisabled={!canEdit}
          placeholder={DEFAULT_SECONDARY} description={t('st.brand.secondaryUse')} width={260} status={status(colorError(draft.secondary_color))} />
      </FormLayout>
      <VStack gap={2}>
        <Text weight="semibold">{t('st.brand.previewTitle')}</Text>
        <BrandPreview name={draft.display_name || preview.name} logoLight={draft.logo_url || preview.logo_url} logoDark={draft.logo_url || preview.dark_logo_url}
          favicon={draft.favicon_url || preview.favicon_url} primary={isHexColor(draft.primary_color) ? draft.primary_color : preview.primary_color ?? DEFAULT_PRIMARY}
          secondary={isHexColor(draft.secondary_color) ? draft.secondary_color : preview.secondary_color ?? DEFAULT_SECONDARY} />
      </VStack>
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
