import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@astryxdesign/core/Button'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { FileInput } from '@astryxdesign/core/FileInput'
import { HStack } from '@astryxdesign/core/HStack'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Thumbnail } from '@astryxdesign/core/Thumbnail'
import { VStack } from '@astryxdesign/core/VStack'
import {
  ANNOUNCEMENT_IMAGE_TYPES, ANNOUNCEMENT_LIMITS, type AnnouncementInput, type AnnouncementStatus, type ManagedAnnouncement,
  announcementErrorText, uploadAnnouncementImage, useSaveAnnouncement,
} from '../../api/announcements'
import { resolvePublicAssetUrl } from '../../platform/runtime'
import { DialogScrollBody } from '../DialogScrollBody'
import { MarkdownEditor } from './MarkdownEditor'

function initialForm(announcement: ManagedAnnouncement | null): AnnouncementInput {
  return {
    title: announcement?.title ?? '',
    summary: announcement?.summary ?? null,
    body: announcement?.body ?? '',
    cover_url: announcement?.cover_url ?? null,
    image_urls: announcement?.image_urls ?? [],
    category: announcement?.category ?? null,
    is_pinned: announcement?.is_pinned ?? false,
    status: announcement?.status ?? 'draft',
  }
}

const asFiles = (value: File | File[] | null) => (Array.isArray(value) ? value : value ? [value] : [])

/** Create / edit a news post: text, Markdown body, cover picture and gallery. */
export function AnnouncementEditorDialog({ announcement, canPin, onClose }: { announcement: ManagedAnnouncement | null; canPin: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveAnnouncement()
  const [form, setForm] = useState(() => initialForm(announcement))
  const set = <K extends keyof AnnouncementInput>(key: K, value: AnnouncementInput[K]) => setForm((current) => ({ ...current, [key]: value }))

  const title = form.title.trim()
  const overLimit = form.body.length > ANNOUNCEMENT_LIMITS.body || (form.summary?.length ?? 0) > ANNOUNCEMENT_LIMITS.summary
  const galleryFull = form.image_urls.length >= ANNOUNCEMENT_LIMITS.images
  const published = announcement?.status === 'published'

  const upload = async (files: File[]) => {
    const uploaded: string[] = []
    for (const file of files) {
      try {
        uploaded.push(await uploadAnnouncementImage(file))
      } catch (error) {
        toast.error(announcementErrorText(error, t('announcements.editor.imageUploadFailed', { name: file.name })))
      }
    }
    return uploaded
  }

  const uploadCover = async (value: File | File[] | null) => {
    const [url] = await upload(asFiles(value).slice(0, 1))
    if (url) set('cover_url', url)
  }

  const uploadGallery = async (value: File | File[] | null) => {
    const room = ANNOUNCEMENT_LIMITS.images - form.image_urls.length
    const urls = await upload(asFiles(value).slice(0, room))
    if (urls.length) setForm((current) => ({ ...current, image_urls: [...current.image_urls, ...urls].slice(0, ANNOUNCEMENT_LIMITS.images) }))
  }

  const submit = async (status: AnnouncementStatus) => {
    try {
      await save.mutateAsync({ id: announcement?.id, input: { ...form, title, status } })
      toast.success(status === 'published' ? (published ? t('announcements.editor.updated') : t('announcements.publishedToast')) : t('announcements.editor.draftSaved'))
      onClose()
    } catch (error) {
      toast.error(announcementErrorText(error, t('announcements.editor.saveFailed')))
    }
  }

  const close = (open: boolean) => { if (!open) onClose() }
  const blocked = !title || overLimit

  return (
    <Dialog isOpen onOpenChange={close} width={760} purpose="form" maxHeight="92dvh">
      <DialogHeader title={announcement ? t('announcements.editor.editTitle') : t('announcements.editor.newTitle')} subtitle={t('announcements.editor.subtitle')} onOpenChange={close} />
      <DialogScrollBody label={t('announcements.editor.formLabel')} actions={<>
        <Button label={t('announcements.editor.cancel')} variant="ghost" onClick={onClose} />
        <Button label={published ? t('announcements.editor.makeDraft') : t('announcements.editor.saveDraft')} variant="secondary" isDisabled={blocked} clickAction={() => submit('draft')} />
        <Button label={published ? t('announcements.editor.save') : t('announcements.editor.publish')} variant="primary" isDisabled={blocked} clickAction={() => submit('published')} />
      </>}>
        <TextInput label={t('announcements.editor.fieldTitle')} isRequired value={form.title} onChange={(value) => set('title', value.slice(0, ANNOUNCEMENT_LIMITS.title))} hasAutoFocus width="100%" />
        <HStack gap={3} vAlign="start" wrap="wrap">
          <TextInput label={t('announcements.editor.fieldCategory')} isOptional value={form.category ?? ''} onChange={(value) => set('category', value.slice(0, ANNOUNCEMENT_LIMITS.category) || null)} placeholder={t('announcements.editor.categoryPlaceholder')} width={260} />
          {canPin && <Switch label={t('announcements.editor.pin')} description={t('announcements.editor.pinHint')} value={form.is_pinned} onChange={(value) => set('is_pinned', value)} />}
        </HStack>
        <TextArea label={t('announcements.editor.summary')} isOptional value={form.summary ?? ''} onChange={(value) => set('summary', value || null)} rows={2} maxLength={ANNOUNCEMENT_LIMITS.summary} width="100%" />

        <VStack gap={1}>
          <Text weight="semibold">{t('announcements.editor.content')}</Text>
          <MarkdownEditor label={t('announcements.editor.content')} value={form.body} onChange={(value) => set('body', value)} maxLength={ANNOUNCEMENT_LIMITS.body} />
        </VStack>

        <VStack gap={2}>
          <FileInput label={t('announcements.editor.cover')} isOptional description={t('announcements.editor.coverHint')} value={null} onChange={() => undefined} changeAction={uploadCover}
            accept={ANNOUNCEMENT_IMAGE_TYPES} maxSize={ANNOUNCEMENT_LIMITS.imageBytes} placeholder={form.cover_url ? t('announcements.editor.replaceImage') : t('announcements.editor.pickImage')} width="100%" />
          {form.cover_url && <HStack gap={2}><Thumbnail src={resolvePublicAssetUrl(form.cover_url) ?? undefined} label={t('announcements.editor.cover')} alt={t('announcements.editor.cover')} showRemoveOn="always" onRemove={() => set('cover_url', null)} /></HStack>}
        </VStack>

        <VStack gap={2}>
          <FileInput label={t('announcements.editor.gallery')} isOptional description={t('announcements.editor.galleryHint', { n: form.image_urls.length, max: ANNOUNCEMENT_LIMITS.images })} isMultiple value={[]} onChange={() => undefined} changeAction={uploadGallery}
            accept={ANNOUNCEMENT_IMAGE_TYPES} maxSize={ANNOUNCEMENT_LIMITS.imageBytes} placeholder={t('announcements.editor.addImage')} isDisabled={galleryFull} disabledMessage={t('announcements.editor.galleryFull', { max: ANNOUNCEMENT_LIMITS.images })} width="100%" />
          {form.image_urls.length > 0 && <HStack gap={2} wrap="wrap">
            {form.image_urls.map((url, index) => (
              <Thumbnail key={url} src={resolvePublicAssetUrl(url) ?? undefined} label={t('announcements.editor.imageN', { n: index + 1 })} alt={t('announcements.editor.imageN', { n: index + 1 })} showRemoveOn="always"
                onRemove={() => set('image_urls', form.image_urls.filter((item) => item !== url))} />
            ))}
          </HStack>}
        </VStack>
      </DialogScrollBody>
    </Dialog>
  )
}
