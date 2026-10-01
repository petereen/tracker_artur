import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarClock, ChevronLeft, ChevronRight, GitMerge, Lightbulb, Plus, Target, UserRound } from 'lucide-react'
import { Badge } from '@astryxdesign/core/Badge'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import type { ISODateString } from '@astryxdesign/core/Calendar'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { DateInput } from '@astryxdesign/core/DateInput'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Divider } from '@astryxdesign/core/Divider'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { MoreMenu } from '@astryxdesign/core/MoreMenu'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Tab, TabList } from '@astryxdesign/core/TabList'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type CompanyPlanItem, type PlanHorizon, type PlanIdea,
  useCompanyPlan, useCreateCompanyPlanItem, useCreatePlanIdea, useDeleteCompanyPlanItem, useDeletePlanIdea, useMergePlanIdeas,
  usePlanIdeas, useReorderCompanyPlan, useUpdateCompanyPlanItem, useUpdatePlanIdea,
} from '../api/hooks'
import { DialogScrollBody } from '../components/DialogScrollBody'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

type PlanTab = 'company' | 'ideas'
type IdeaFilter = 'pending' | 'all'

const HORIZONS: { id: PlanHorizon; label: string; hint: string; color: 'orange' | 'blue' | 'green' }[] = [
  { id: 'long_term', label: 'Урт хугацааны', hint: 'Стратегийн зорилт', color: 'orange' },
  { id: 'mid_term', label: 'Дунд хугацааны', hint: 'Улирлын зорилт', color: 'blue' },
  { id: 'short_term', label: 'Богино хугацааны', hint: 'Энэ сарын ажил', color: 'green' },
]
const HORIZON_OPTIONS = HORIZONS.map((horizon) => ({ value: horizon.id, label: horizon.label }))
const IDEA_STATUS: Record<PlanIdea['status'], { label: string; color: 'blue' | 'green' | 'purple' | 'gray' }> = {
  pending: { label: 'Хүлээгдэж буй', color: 'blue' },
  approved: { label: 'Баталсан', color: 'green' },
  merged: { label: 'Төлөвлөгөөнд орсон', color: 'purple' },
  rejected: { label: 'Татгалзсан', color: 'gray' },
}

const currentMonth = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}` }
const monthDate = (value: string) => `${value}-01`
const shiftMonth = (value: string, delta: number) => {
  const [year, month] = value.split('-').map(Number)
  const next = new Date(year, month - 1 + delta, 1)
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}
const monthLabel = (value: string) => new Date(`${value}-01T12:00:00`).toLocaleDateString('mn-MN', { year: 'numeric', month: 'long' })
const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString('mn-MN', { month: 'short', day: 'numeric' })

export function PlansPage() {
  // Deep links from shared chat cards: /plans?month=YYYY-MM&item=ID | &idea=ID
  const [searchParams] = useSearchParams()
  const linkedItemId = Number(searchParams.get('item')) || undefined
  const linkedIdeaId = Number(searchParams.get('idea')) || undefined
  const linkedMonth = /^\d{4}-\d{2}$/.test(searchParams.get('month') ?? '') ? searchParams.get('month')! : undefined
  const [tab, setTab] = useState<PlanTab>(linkedIdeaId && !linkedItemId ? 'ideas' : 'company')
  const [month, setMonth] = useState(() => linkedMonth ?? currentMonth())
  const [ideaFilter, setIdeaFilter] = useState<IdeaFilter>(linkedIdeaId ? 'all' : 'pending')
  const [selected, setSelected] = useState<number[]>([])
  const [approving, setApproving] = useState<number[] | null>(null)
  const [editingItem, setEditingItem] = useState<CompanyPlanItem | { horizon: PlanHorizon } | null>(null)
  const [editingIdea, setEditingIdea] = useState<PlanIdea | 'new' | null>(null)
  const [draggedId, setDraggedId] = useState<number | null>(null)
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canReview = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const ideas = usePlanIdeas(monthDate(month))
  const companyPlan = useCompanyPlan(monthDate(month))
  const reorder = useReorderCompanyPlan()
  const deleteIdea = useDeletePlanIdea()
  const deleteItem = useDeleteCompanyPlanItem()

  useEffect(() => {
    if (linkedItemId) setTab('company')
    else if (linkedIdeaId) { setTab('ideas'); setIdeaFilter('all') }
    if (linkedMonth) setMonth(linkedMonth)
  }, [linkedItemId, linkedIdeaId, linkedMonth])
  const linkedId = linkedItemId ? `plan-item-${linkedItemId}` : linkedIdeaId ? `plan-idea-${linkedIdeaId}` : undefined
  const linkedLoaded = Boolean(linkedItemId ? companyPlan.data : ideas.data)
  useEffect(() => {
    if (linkedId && linkedLoaded) document.getElementById(linkedId)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }, [linkedId, linkedLoaded, tab])
  useEffect(() => setSelected([]), [month])

  const columns = useMemo(() => HORIZONS.reduce((result, horizon) => ({
    ...result,
    [horizon.id]: (companyPlan.data || []).filter((item) => item.horizon === horizon.id).sort((a, b) => a.position - b.position),
  }), {} as Record<PlanHorizon, CompanyPlanItem[]>), [companyPlan.data])
  const allIdeas = ideas.data ?? []
  const pending = allIdeas.filter((idea) => idea.status === 'pending')
  const visibleIdeas = ideaFilter === 'pending' ? pending : allIdeas

  const moveItem = (itemId: number | null, target: PlanHorizon, targetIndex?: number) => {
    if (itemId === null || !companyPlan.data) return
    const all = HORIZONS.reduce((result, horizon) => ({ ...result, [horizon.id]: [...columns[horizon.id]] }), {} as Record<PlanHorizon, CompanyPlanItem[]>)
    let moved: CompanyPlanItem | undefined
    for (const horizon of HORIZONS) {
      const index = all[horizon.id].findIndex((item) => item.id === itemId)
      if (index >= 0) moved = all[horizon.id].splice(index, 1)[0]
    }
    if (!moved) return
    all[target].splice(targetIndex ?? all[target].length, 0, moved)
    reorder.mutate({
      plan_month: monthDate(month),
      columns: HORIZONS.reduce((result, horizon) => ({ ...result, [horizon.id]: all[horizon.id].map((item) => item.id) }), {} as Record<PlanHorizon, number[]>),
    })
    setDraggedId(null)
  }
  const toggleIdea = (id: number) => setSelected((ids) => ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id])

  return <VStack gap={4}>
    <HStack gap={3} vAlign="end" hAlign="between" wrap="wrap">
      <TabList value={tab} onChange={(value) => setTab(value as PlanTab)}>
        <Tab value="company" label="Компаний төлөвлөгөө" icon={<Target size={15} />} endContent={companyPlan.data?.length ? <Badge label={companyPlan.data.length} /> : undefined} />
        <Tab value="ideas" label="Ажилтнуудын санал" icon={<Lightbulb size={15} />} endContent={pending.length ? <Badge label={pending.length} /> : undefined} />
      </TabList>
      <HStack gap={3} vAlign="center" wrap="wrap">
        <HStack gap={1} vAlign="center">
          <IconButton label="Өмнөх сар" tooltip="Өмнөх сар" icon={<ChevronLeft size={16} />} variant="ghost" size="sm" onClick={() => setMonth(shiftMonth(month, -1))} />
          <Text weight="semibold" hasTabularNumbers>{monthLabel(month)}</Text>
          <IconButton label="Дараагийн сар" tooltip="Дараагийн сар" icon={<ChevronRight size={16} />} variant="ghost" size="sm" onClick={() => setMonth(shiftMonth(month, 1))} />
          {month !== currentMonth() && <Button label="Энэ сар" variant="ghost" size="sm" onClick={() => setMonth(currentMonth())} />}
        </HStack>
        {tab === 'company' && canReview && <Button label="Төлөвлөгөө нэмэх" variant="primary" icon={<Plus size={15} />} onClick={() => setEditingItem({ horizon: 'short_term' })} />}
        {tab === 'ideas' && <Button label="Санал илгээх" variant="primary" icon={<Plus size={15} />} onClick={() => setEditingIdea('new')} />}
      </HStack>
    </HStack>

    {tab === 'company' && (companyPlan.isLoading
      ? <Skeleton height={360} />
      : companyPlan.isError
        ? <Banner status="error" collapsible={false} title="Компаний төлөвлөгөөг ачаалж чадсангүй. Дахин оролдоно уу." />
        : <Grid columns={{ minWidth: 280, max: 3 }} gap={3} align="start">
          {HORIZONS.map((horizon) => (
            <section key={horizon.id} aria-label={horizon.label} onDragOver={(event) => event.preventDefault()} onDrop={() => moveItem(draggedId, horizon.id)}>
              <Card variant="muted" padding={3} minHeight={280}>
                <VStack gap={3}>
                  <HStack gap={2} vAlign="center" hAlign="between">
                    <VStack gap={0.5}>
                      <Token color={horizon.color} label={horizon.label} />
                      <Text type="supporting">{horizon.hint}</Text>
                    </VStack>
                    <HStack gap={1} vAlign="center">
                      <Badge label={columns[horizon.id].length} />
                      {canReview && <IconButton label={`${horizon.label} төлөвлөгөө нэмэх`} tooltip="Нэмэх" icon={<Plus size={15} />} variant="ghost" size="sm" onClick={() => setEditingItem({ horizon: horizon.id })} />}
                    </HStack>
                  </HStack>
                  {columns[horizon.id].map((item, index) => (
                    <article
                      key={item.id}
                      id={`plan-item-${item.id}`}
                      draggable={canReview}
                      onDragStart={() => setDraggedId(item.id)}
                      onDragEnd={() => setDraggedId(null)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => { event.stopPropagation(); moveItem(draggedId, horizon.id, index) }}
                    >
                      <Card padding={3} variant={linkedItemId === item.id ? 'blue' : 'default'} elevation={draggedId === item.id ? 'med' : 'none'}>
                        <VStack gap={2}>
                          <HStack gap={2} vAlign="start" hAlign="between">
                            <Text weight="semibold">{item.title}</Text>
                            {canReview && <MoreMenu label={`${item.title} үйлдэл`} size="sm" alignment="end" items={[
                              { label: 'Засах', onClick: () => setEditingItem(item) },
                              { type: 'section', title: 'Шилжүүлэх', items: HORIZONS.filter((target) => target.id !== horizon.id).map((target) => ({ label: target.label, onClick: () => moveItem(item.id, target.id) })) },
                              { type: 'divider' },
                              { label: 'Архивлах', variant: 'destructive', onClick: () => { if (window.confirm(`«${item.title}» төлөвлөгөөг архивлах уу?`)) deleteItem.mutate(item.id) } },
                            ]} />}
                          </HStack>
                          {item.content && <Text type="supporting" maxLines={4}>{item.content}</Text>}
                          <HStack gap={2} vAlign="center" wrap="wrap">
                            <Token size="sm" color={item.due_date ? 'default' : 'gray'} icon={<CalendarClock size={12} />} label={item.due_date ? dateLabel(item.due_date) : 'Хугацаагүй'} />
                            {item.source_idea_ids.length > 0 && <Token size="sm" color="purple" icon={<Lightbulb size={12} />} label={`${item.source_idea_ids.length} санал`} />}
                            {item.source_employee_name && <Token size="sm" icon={<UserRound size={12} />} label={item.source_employee_name} />}
                          </HStack>
                        </VStack>
                      </Card>
                    </article>
                  ))}
                  {columns[horizon.id].length === 0 && <EmptyState isCompact title="Төлөвлөгөө алга" description={canReview ? 'Шинээр нэмэх эсвэл ажилтнуудын саналаас батална уу.' : 'Энэ түвшинд батлагдсан төлөвлөгөө алга.'} />}
                </VStack>
              </Card>
            </section>
          ))}
        </Grid>)}

    {tab === 'ideas' && (ideas.isLoading
      ? <Skeleton height={320} />
      : ideas.isError
        ? <Banner status="error" collapsible={false} title="Саналуудыг ачаалж чадсангүй. Дахин оролдоно уу." />
        : <VStack gap={3}>
          <HStack gap={3} vAlign="center" hAlign="between" wrap="wrap">
            <SegmentedControl label="Саналын төлөв" value={ideaFilter} onChange={(value) => setIdeaFilter(value as IdeaFilter)}>
              <SegmentedControlItem value="pending" label={`Хүлээгдэж буй (${pending.length})`} />
              <SegmentedControlItem value="all" label={`Бүгд (${allIdeas.length})`} />
            </SegmentedControl>
            {canReview && selected.length > 0 && <HStack gap={2} vAlign="center">
              <Text type="supporting">{selected.length} санал сонгосон</Text>
              <Button label="Цуцлах" variant="ghost" size="sm" onClick={() => setSelected([])} />
              <Button label={selected.length > 1 ? 'Нэгтгэж батлах' : 'Батлах'} variant="primary" size="sm" icon={<GitMerge size={14} />} onClick={() => setApproving(selected)} />
            </HStack>}
          </HStack>
          <Card padding={0}>
            {visibleIdeas.length === 0
              ? <EmptyState icon={<Lightbulb size={28} />} title={allIdeas.length ? 'Хүлээгдэж буй санал алга' : 'Энэ сарын санал алга'} description="Ажилтнууд дараа сарын төлөвлөгөөнд оруулах саналаа эндээс илгээнэ."
                actions={<Button label="Санал илгээх" variant="secondary" icon={<Plus size={15} />} onClick={() => setEditingIdea('new')} />} />
              : visibleIdeas.map((idea, index) => {
                const reviewable = canReview && idea.status === 'pending'
                return <article key={idea.id} id={`plan-idea-${idea.id}`}>
                  {index > 0 && <Divider />}
                  <Card variant={linkedIdeaId === idea.id ? 'blue' : 'transparent'} padding={4}>
                    <HStack gap={3} vAlign="start">
                      {reviewable && <CheckboxInput label={`${idea.title} сонгох`} isLabelHidden value={selected.includes(idea.id)} onChange={() => toggleIdea(idea.id)} />}
                      <VStack gap={1.5} width="100%">
                        <HStack gap={2} vAlign="center" wrap="wrap">
                          <Text weight="semibold" color={idea.status === 'rejected' ? 'secondary' : 'primary'}>{idea.title}</Text>
                          <Token size="sm" color={IDEA_STATUS[idea.status].color} label={IDEA_STATUS[idea.status].label} />
                        </HStack>
                        {idea.content && <Text type="supporting" as="p">{idea.content}</Text>}
                        <HStack gap={3} vAlign="center" wrap="wrap">
                          <HStack gap={1} vAlign="center"><UserRound size={13} aria-hidden /><Text type="supporting">{idea.submitted_by_name || 'Гишүүн'}</Text></HStack>
                          {idea.suggested_due_date && <HStack gap={1} vAlign="center"><CalendarClock size={13} aria-hidden /><Text type="supporting">{dateLabel(idea.suggested_due_date)} хүртэл</Text></HStack>}
                        </HStack>
                      </VStack>
                      {reviewable && <HStack gap={1} vAlign="center">
                        <Button label="Батлах" variant="secondary" size="sm" onClick={() => setApproving([idea.id])} />
                        <MoreMenu label={`${idea.title} үйлдэл`} size="sm" alignment="end" items={[
                          { label: 'Засах', onClick: () => setEditingIdea(idea) },
                          { label: 'Татгалзах', variant: 'destructive', onClick: () => { if (window.confirm(`«${idea.title}» саналаас татгалзах уу?`)) { deleteIdea.mutate(idea.id); setSelected((ids) => ids.filter((id) => id !== idea.id)) } } },
                        ]} />
                      </HStack>}
                    </HStack>
                  </Card>
                </article>
              })}
          </Card>
        </VStack>)}

    {editingItem && <PlanItemDialog item={editingItem} month={monthDate(month)} onClose={() => setEditingItem(null)} />}
    {editingIdea && <IdeaDialog idea={editingIdea === 'new' ? null : editingIdea} month={monthDate(month)} onClose={() => setEditingIdea(null)} />}
    {approving && <ApproveIdeasDialog ideas={pending.filter((idea) => approving.includes(idea.id))} month={monthDate(month)}
      onClose={(done) => { setApproving(null); if (done) setSelected([]) }} />}
  </VStack>
}

/** Create or edit a company plan item (management only). */
function PlanItemDialog({ item, month, onClose }: { item: CompanyPlanItem | { horizon: PlanHorizon }; month: string; onClose: () => void }) {
  const existing = 'id' in item ? item : null
  const create = useCreateCompanyPlanItem()
  const update = useUpdateCompanyPlanItem()
  const [title, setTitle] = useState(existing?.title ?? '')
  const [content, setContent] = useState(existing?.content ?? '')
  const [horizon, setHorizon] = useState<PlanHorizon>(item.horizon)
  const [due, setDue] = useState(existing?.due_date ?? '')
  const close = (open: boolean) => { if (!open) onClose() }
  const save = async () => {
    const payload = { title: title.trim(), content, horizon, due_date: due || null }
    if (existing) await update.mutateAsync({ id: existing.id, ...payload })
    else await create.mutateAsync({ ...payload, plan_month: month })
    onClose()
  }
  return <Dialog isOpen onOpenChange={close} width={560} purpose="form" maxHeight="92dvh">
    <DialogHeader title={existing ? 'Төлөвлөгөө засах' : 'Төлөвлөгөө нэмэх'} subtitle="Компаний төлөвлөгөөг бүх ажилтан харна." onOpenChange={close} />
    <DialogScrollBody label="Төлөвлөгөөний маягт" actions={<>
      <Button label="Цуцлах" variant="ghost" onClick={onClose} />
      <Button label={existing ? 'Хадгалах' : 'Нэмэх'} variant="primary" isDisabled={!title.trim()} clickAction={save} />
    </>}>
      <TextInput label="Гарчиг" isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label="Тайлбар" isOptional value={content} onChange={setContent} rows={5} placeholder="Ямар үр дүнд, ямар арга замаар хүрэх вэ?" width="100%" />
      <Grid columns={{ minWidth: 200 }} gap={3}>
        <Selector label="Хугацааны түвшин" options={HORIZON_OPTIONS} value={horizon} onChange={(value) => setHorizon(value as PlanHorizon)} />
        <DateInput label="Дуусах хугацаа" isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
      </Grid>
    </DialogScrollBody>
  </Dialog>
}

/** Submit a new idea, or let a reviewer tidy a pending one before approving it. */
function IdeaDialog({ idea, month, onClose }: { idea: PlanIdea | null; month: string; onClose: () => void }) {
  const create = useCreatePlanIdea()
  const update = useUpdatePlanIdea()
  const [title, setTitle] = useState(idea?.title ?? '')
  const [content, setContent] = useState(idea?.content ?? '')
  const [due, setDue] = useState(idea?.suggested_due_date ?? '')
  const close = (open: boolean) => { if (!open) onClose() }
  const save = async () => {
    const payload = { title: title.trim(), content, suggested_due_date: due || null }
    if (idea) await update.mutateAsync({ id: idea.id, ...payload })
    else await create.mutateAsync({ ...payload, plan_month: month })
    onClose()
  }
  return <Dialog isOpen onOpenChange={close} width={520} purpose="form" maxHeight="92dvh">
    <DialogHeader title={idea ? 'Санал засах' : 'Санал илгээх'} subtitle={`${monthLabel(month.slice(0, 7))}-ын төлөвлөгөөнд оруулах санал. Удирдлага хянаад баталсны дараа компаний төлөвлөгөөнд орно.`} onOpenChange={close} />
    <DialogScrollBody label="Саналын маягт" actions={<>
      <Button label="Цуцлах" variant="ghost" onClick={onClose} />
      <Button label={idea ? 'Хадгалах' : 'Илгээх'} variant="primary" isDisabled={!title.trim()} clickAction={save} />
    </>}>
      <TextInput label="Товч гарчиг" isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label="Тайлбар" isOptional value={content} onChange={setContent} rows={5} placeholder="Ямар үр дүнд, ямар арга замаар хүрэх вэ?" width="100%" />
      <DateInput label="Санал болгох хугацаа" isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
    </DialogScrollBody>
  </Dialog>
}

/** Turn one or several pending ideas into a single company plan item. */
function ApproveIdeasDialog({ ideas, month, onClose }: { ideas: PlanIdea[]; month: string; onClose: (done: boolean) => void }) {
  const merge = useMergePlanIdeas()
  const single = ideas.length === 1 ? ideas[0] : null
  const [title, setTitle] = useState(single?.title ?? '')
  const [content, setContent] = useState(() => single ? single.content ?? '' : ideas.map((idea) => `${idea.title}\n${idea.content || ''}`.trim()).join('\n\n'))
  const [due, setDue] = useState(single?.suggested_due_date ?? '')
  const [horizon, setHorizon] = useState<PlanHorizon>('short_term')
  const close = (open: boolean) => { if (!open) onClose(false) }
  const save = async () => {
    await merge.mutateAsync({ idea_ids: ideas.map((idea) => idea.id), plan_month: month, title: title.trim(), content, horizon, due_date: due || null })
    onClose(true)
  }
  return <Dialog isOpen onOpenChange={close} width={600} purpose="form" maxHeight="92dvh">
    <DialogHeader title={single ? 'Саналыг батлах' : `${ideas.length} саналыг нэгтгэх`} subtitle="Батлагдсан санал компаний төлөвлөгөөний нэг мөр болно." onOpenChange={close} />
    <DialogScrollBody label="Батлах маягт" actions={<>
      <Button label="Цуцлах" variant="ghost" onClick={() => onClose(false)} />
      <Button label="Төлөвлөгөөнд оруулах" variant="primary" isDisabled={!title.trim() || ideas.length === 0} clickAction={save} />
    </>}>
      {!single && <HStack gap={1.5} wrap="wrap">{ideas.map((idea) => <Token key={idea.id} size="sm" color="blue" label={idea.title} />)}</HStack>}
      <TextInput label="Төлөвлөгөөний гарчиг" isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label="Тайлбар" isOptional value={content} onChange={setContent} rows={7} width="100%" />
      <Grid columns={{ minWidth: 200 }} gap={3}>
        <Selector label="Хугацааны түвшин" options={HORIZON_OPTIONS} value={horizon} onChange={(value) => setHorizon(value as PlanHorizon)} />
        <DateInput label="Дуусах хугацаа" isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
      </Grid>
    </DialogScrollBody>
  </Dialog>
}
