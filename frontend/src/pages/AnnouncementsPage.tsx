import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Archive, Pencil, Pin, Plus, Send, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  ANNOUNCEMENT_EDITOR_ROLES, type AnnouncementStatus, type ManagedAnnouncement, announcementErrorText,
  useDeleteAnnouncement, useManagedAnnouncements, useSaveAnnouncement,
} from '../api/announcements'
import { useActor } from '../api/enterprise'
import { AnnouncementEditorDialog } from '../components/announcements/AnnouncementEditorDialog'

type StatusFilter = AnnouncementStatus | 'all'
interface Row extends Record<string, unknown> { id: number; announcement: ManagedAnnouncement }

const STATUS: Record<AnnouncementStatus, { label: string; color: 'green' | 'gray' | 'orange' }> = {
  published: { label: 'Нийтэлсэн', color: 'green' },
  draft: { label: 'Ноорог', color: 'orange' },
  archived: { label: 'Архивласан', color: 'gray' },
}

const formatDate = (value: string | null) => (value ? new Date(value).toLocaleString('mn-MN', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

/** Authoring workspace for news & announcements (admins, managers, team leads). */
export function AnnouncementsPage() {
  const actor = useActor()
  const announcements = useManagedAnnouncements()
  const save = useSaveAnnouncement()
  const remove = useDeleteAnnouncement()
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<ManagedAnnouncement | 'new' | null>(null)

  const canPin = Boolean(actor.data?.roles.some((role) => ANNOUNCEMENT_EDITOR_ROLES.includes(role)))
  const all = announcements.data ?? []
  const counts = useMemo(() => {
    const result: Record<AnnouncementStatus, number> = { published: 0, draft: 0, archived: 0 }
    for (const item of all) result[item.status] += 1
    return result
  }, [all])
  const rows: Row[] = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return all
      .filter((item) => filter === 'all' || item.status === filter)
      .filter((item) => !needle || [item.title, item.category, item.author_name].some((value) => value?.toLowerCase().includes(needle)))
      .map((announcement) => ({ id: announcement.id, announcement }))
  }, [all, filter, search])

  if (announcements.isLoading) return <Skeleton height={320} />
  if (announcements.isError) return <Banner status="error" collapsible={false} title={announcementErrorText(announcements.error, 'Мэдээг ачаалж чадсангүй')} />

  const setStatus = async (announcement: ManagedAnnouncement, status: AnnouncementStatus, done: string) => {
    try {
      await save.mutateAsync({ id: announcement.id, input: { status } })
      toast.success(done)
    } catch (error) {
      toast.error(announcementErrorText(error, 'Төлөвийг өөрчилж чадсангүй'))
    }
  }

  const destroy = async (announcement: ManagedAnnouncement) => {
    if (!window.confirm(`«${announcement.title}» мэдээг бүр мөсөн устгах уу?`)) return
    try {
      await remove.mutateAsync(announcement.id)
      toast.success('Мэдээ устгагдлаа')
    } catch (error) {
      toast.error(announcementErrorText(error, 'Мэдээг устгаж чадсангүй'))
    }
  }

  return <VStack gap={4}>
    <VStack gap={1}>
      <Heading level={1}>Мэдээ, мэдэгдэл</Heading>
      <Text type="supporting">Байгууллагын мэдээ, зарлалыг бичиж нийтэлнэ. Нийтэлсэн мэдээг бүх ажилтан «Өнөөдөр» хуудаснаас уншина.</Text>
    </VStack>

    <HStack gap={3} vAlign="center" hAlign="between" wrap="wrap">
      <HStack gap={3} vAlign="center" wrap="wrap">
        <SegmentedControl label="Төлөв" value={filter} onChange={(value) => setFilter(value as StatusFilter)}>
          <SegmentedControlItem value="all" label={`Бүгд (${all.length})`} />
          {(Object.keys(STATUS) as AnnouncementStatus[]).map((key) => <SegmentedControlItem key={key} value={key} label={`${STATUS[key].label} (${counts[key]})`} />)}
        </SegmentedControl>
        <TextInput label="Хайх" isLabelHidden value={search} onChange={setSearch} placeholder="Гарчиг, ангилал, зохиогч…" hasClear width={260} />
      </HStack>
      <Button label="Мэдээ нэмэх" variant="primary" icon={<Plus size={15} />} onClick={() => setEditing('new')} />
    </HStack>

    <Card padding={0}>
      {rows.length === 0
        ? <EmptyState title={all.length ? 'Мэдээ олдсонгүй' : 'Мэдээ алга'} description={all.length ? 'Шүүлтүүрээ өөрчилнө үү.' : '“Мэдээ нэмэх”-ээр анхны мэдээгээ бичнэ үү.'} />
        : <Table<Row>
          data={rows} idKey="id" density="compact" hasHover
          columns={[
            { key: 'title', header: 'Гарчиг', width: proportional(4), renderCell: ({ announcement }) => <VStack gap={0}>
              <HStack gap={1} vAlign="center">
                {announcement.is_pinned && <Pin size={12} aria-label="Онцолсон" />}
                <Text weight="medium" maxLines={1}>{announcement.title}</Text>
              </HStack>
              {announcement.summary && <Text type="supporting" maxLines={1}>{announcement.summary}</Text>}
            </VStack> },
            { key: 'status', header: 'Төлөв', width: pixel(130), renderCell: ({ announcement }) => <Token size="sm" color={STATUS[announcement.status].color} label={STATUS[announcement.status].label} /> },
            { key: 'category', header: 'Ангилал', width: proportional(1.5), renderCell: ({ announcement }) => <Text type="supporting" maxLines={1}>{announcement.category ?? '—'}</Text> },
            { key: 'author', header: 'Зохиогч', width: proportional(1.5), renderCell: ({ announcement }) => <Text type="supporting" maxLines={1}>{announcement.author_name ?? '—'}</Text> },
            { key: 'date', header: 'Нийтэлсэн', width: pixel(170), renderCell: ({ announcement }) => <Text type="supporting">{formatDate(announcement.published_at)}</Text> },
            { key: 'actions', header: '', width: pixel(120), renderCell: ({ announcement }) => announcement.can_edit ? <HStack gap={0.5} hAlign="end">
              <IconButton label="Засах" tooltip="Засах" icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditing(announcement)} />
              {announcement.status === 'published'
                ? <IconButton label="Архивлах" tooltip="Архивлах — мэдээний жагсаалтаас нуух" icon={<Archive size={14} />} size="sm" variant="ghost" clickAction={() => setStatus(announcement, 'archived', 'Мэдээ архивлагдлаа')} />
                : <IconButton label="Нийтлэх" tooltip="Нийтлэх" icon={<Send size={14} />} size="sm" variant="ghost" clickAction={() => setStatus(announcement, 'published', 'Мэдээ нийтлэгдлээ')} />}
              <IconButton label="Устгах" tooltip="Устгах" icon={<Trash2 size={14} />} size="sm" variant="ghost" clickAction={() => destroy(announcement)} />
            </HStack> : null },
          ]}
        />}
    </Card>

    {editing && <AnnouncementEditorDialog announcement={editing === 'new' ? null : editing} canPin={canPin} onClose={() => setEditing(null)} />}
  </VStack>
}
