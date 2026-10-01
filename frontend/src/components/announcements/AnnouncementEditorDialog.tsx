import { useState } from 'react'
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
        toast.error(announcementErrorText(error, `${file.name} зургийг байршуулж чадсангүй`))
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
      toast.success(status === 'published' ? (published ? 'Мэдээ шинэчлэгдлээ' : 'Мэдээ нийтлэгдлээ') : 'Ноорог хадгалагдлаа')
      onClose()
    } catch (error) {
      toast.error(announcementErrorText(error, 'Мэдээг хадгалж чадсангүй'))
    }
  }

  const close = (open: boolean) => { if (!open) onClose() }
  const blocked = !title || overLimit

  return (
    <Dialog isOpen onOpenChange={close} width={760} purpose="form" maxHeight="92dvh">
      <DialogHeader title={announcement ? 'Мэдээ засах' : 'Шинэ мэдээ'} subtitle="Нийтэлсэн мэдээ «Өнөөдөр» хуудасны «Мэдээ, мэдэгдэл» хэсэгт харагдана." onOpenChange={close} />
      <DialogScrollBody label="Мэдээний маягт" actions={<>
        <Button label="Цуцлах" variant="ghost" onClick={onClose} />
        <Button label={published ? 'Ноорог болгох' : 'Ноорог хадгалах'} variant="secondary" isDisabled={blocked} clickAction={() => submit('draft')} />
        <Button label={published ? 'Хадгалах' : 'Нийтлэх'} variant="primary" isDisabled={blocked} clickAction={() => submit('published')} />
      </>}>
        <TextInput label="Гарчиг" isRequired value={form.title} onChange={(value) => set('title', value.slice(0, ANNOUNCEMENT_LIMITS.title))} hasAutoFocus width="100%" />
        <HStack gap={3} vAlign="start" wrap="wrap">
          <TextInput label="Ангилал" isOptional value={form.category ?? ''} onChange={(value) => set('category', value.slice(0, ANNOUNCEMENT_LIMITS.category) || null)} placeholder="Жишээ: Хүний нөөц" width={260} />
          {canPin && <Switch label="Онцлох" description="Жагсаалтын эхэнд байрлана." value={form.is_pinned} onChange={(value) => set('is_pinned', value)} />}
        </HStack>
        <TextArea label="Товч агуулга" isOptional value={form.summary ?? ''} onChange={(value) => set('summary', value || null)} rows={2} maxLength={ANNOUNCEMENT_LIMITS.summary} width="100%" />

        <VStack gap={1}>
          <Text weight="semibold">Агуулга</Text>
          <MarkdownEditor label="Агуулга" value={form.body} onChange={(value) => set('body', value)} maxLength={ANNOUNCEMENT_LIMITS.body} />
        </VStack>

        <VStack gap={2}>
          <FileInput label="Нүүр зураг" isOptional description="PNG, JPEG эсвэл WebP, 8 MB хүртэл." value={null} onChange={() => undefined} changeAction={uploadCover}
            accept={ANNOUNCEMENT_IMAGE_TYPES} maxSize={ANNOUNCEMENT_LIMITS.imageBytes} placeholder={form.cover_url ? 'Зураг солих' : 'Зураг сонгох'} width="100%" />
          {form.cover_url && <HStack gap={2}><Thumbnail src={resolvePublicAssetUrl(form.cover_url) ?? undefined} label="Нүүр зураг" alt="Нүүр зураг" showRemoveOn="always" onRemove={() => set('cover_url', null)} /></HStack>}
        </VStack>

        <VStack gap={2}>
          <FileInput label="Нэмэлт зургууд" isOptional description={`Мэдээний доор цомог болж харагдана. ${form.image_urls.length}/${ANNOUNCEMENT_LIMITS.images}`} isMultiple value={[]} onChange={() => undefined} changeAction={uploadGallery}
            accept={ANNOUNCEMENT_IMAGE_TYPES} maxSize={ANNOUNCEMENT_LIMITS.imageBytes} placeholder="Зураг нэмэх" isDisabled={galleryFull} disabledMessage={`${ANNOUNCEMENT_LIMITS.images} хүртэл зураг хавсаргана`} width="100%" />
          {form.image_urls.length > 0 && <HStack gap={2} wrap="wrap">
            {form.image_urls.map((url, index) => (
              <Thumbnail key={url} src={resolvePublicAssetUrl(url) ?? undefined} label={`Зураг ${index + 1}`} alt={`Зураг ${index + 1}`} showRemoveOn="always"
                onRemove={() => set('image_urls', form.image_urls.filter((item) => item !== url))} />
            ))}
          </HStack>}
        </VStack>
      </DialogScrollBody>
    </Dialog>
  )
}
