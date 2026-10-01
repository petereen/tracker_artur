import i18n from '../i18n'
import { intlLocale } from '../utils/locale'
import { useTranslation } from 'react-i18next'
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
  { id: 'long_term', get label() { return i18n.t('plans.horizon.long') }, get hint() { return i18n.t('plans.horizon.longHint') }, color: 'orange' },
  { id: 'mid_term', get label() { return i18n.t('plans.horizon.mid') }, get hint() { return i18n.t('plans.horizon.midHint') }, color: 'blue' },
  { id: 'short_term', get label() { return i18n.t('plans.horizon.short') }, get hint() { return i18n.t('plans.horizon.shortHint') }, color: 'green' },
]
const HORIZON_OPTIONS = HORIZONS.map((horizon) => ({ value: horizon.id, label: horizon.label }))
const IDEA_STATUS: Record<PlanIdea['status'], { label: string; color: 'blue' | 'green' | 'purple' | 'gray' }> = {
  pending: { get label() { return i18n.t('plans.status.pending') }, color: 'blue' },
  approved: { get label() { return i18n.t('plans.status.approved') }, color: 'green' },
  merged: { get label() { return i18n.t('plans.status.merged') }, color: 'purple' },
  rejected: { get label() { return i18n.t('plans.status.rejected') }, color: 'gray' },
}

const currentMonth = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}` }
const monthDate = (value: string) => `${value}-01`
const shiftMonth = (value: string, delta: number) => {
  const [year, month] = value.split('-').map(Number)
  const next = new Date(year, month - 1 + delta, 1)
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}
const monthLabel = (value: string) => new Date(`${value}-01T12:00:00`).toLocaleDateString(intlLocale(), { year: 'numeric', month: 'long' })
const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(intlLocale(), { month: 'short', day: 'numeric' })

export function PlansPage() {
  const { t } = useTranslation()
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
        <Tab value="company" label={t('plans.tab.company')} icon={<Target size={15} />} endContent={companyPlan.data?.length ? <Badge label={companyPlan.data.length} /> : undefined} />
        <Tab value="ideas" label={t('plans.tab.ideas')} icon={<Lightbulb size={15} />} endContent={pending.length ? <Badge label={pending.length} /> : undefined} />
      </TabList>
      <HStack gap={3} vAlign="center" wrap="wrap">
        <HStack gap={1} vAlign="center">
          <IconButton label={t('plans.prevMonth')} tooltip={t('plans.prevMonth')} icon={<ChevronLeft size={16} />} variant="ghost" size="sm" onClick={() => setMonth(shiftMonth(month, -1))} />
          <Text weight="semibold" hasTabularNumbers>{monthLabel(month)}</Text>
          <IconButton label={t('plans.nextMonth')} tooltip={t('plans.nextMonth')} icon={<ChevronRight size={16} />} variant="ghost" size="sm" onClick={() => setMonth(shiftMonth(month, 1))} />
          {month !== currentMonth() && <Button label={t('plans.thisMonth')} variant="ghost" size="sm" onClick={() => setMonth(currentMonth())} />}
        </HStack>
        {tab === 'company' && canReview && <Button label={t('plans.addPlan')} variant="primary" icon={<Plus size={15} />} onClick={() => setEditingItem({ horizon: 'short_term' })} />}
        {tab === 'ideas' && <Button label={t('plans.sendIdea')} variant="primary" icon={<Plus size={15} />} onClick={() => setEditingIdea('new')} />}
      </HStack>
    </HStack>

    {tab === 'company' && (companyPlan.isLoading
      ? <Skeleton height={360} />
      : companyPlan.isError
        ? <Banner status="error" collapsible={false} title={t('plans.loadFailed')} />
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
                      {canReview && <IconButton label={t('plans.addToHorizon', { horizon: horizon.label })} tooltip={t('plans.add')} icon={<Plus size={15} />} variant="ghost" size="sm" onClick={() => setEditingItem({ horizon: horizon.id })} />}
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
                            {canReview && <MoreMenu label={t('plans.itemActions', { title: item.title })} size="sm" alignment="end" items={[
                              { label: t('plans.edit'), onClick: () => setEditingItem(item) },
                              { type: 'section', title: t('plans.move'), items: HORIZONS.filter((target) => target.id !== horizon.id).map((target) => ({ label: target.label, onClick: () => moveItem(item.id, target.id) })) },
                              { type: 'divider' },
                              { label: t('plans.archive'), variant: 'destructive', onClick: () => { if (window.confirm(t('plans.archiveConfirm', { title: item.title }))) deleteItem.mutate(item.id) } },
                            ]} />}
                          </HStack>
                          {item.content && <Text type="supporting" maxLines={4}>{item.content}</Text>}
                          <HStack gap={2} vAlign="center" wrap="wrap">
                            <Token size="sm" color={item.due_date ? 'default' : 'gray'} icon={<CalendarClock size={12} />} label={item.due_date ? dateLabel(item.due_date) : t('plans.noDeadline')} />
                            {item.source_idea_ids.length > 0 && <Token size="sm" color="purple" icon={<Lightbulb size={12} />} label={t('plans.ideaCount', { n: item.source_idea_ids.length })} />}
                            {item.source_employee_name && <Token size="sm" icon={<UserRound size={12} />} label={item.source_employee_name} />}
                          </HStack>
                        </VStack>
                      </Card>
                    </article>
                  ))}
                  {columns[horizon.id].length === 0 && <EmptyState isCompact title={t('plans.empty')} description={canReview ? t('plans.emptyHintManager') : t('plans.emptyHintViewer')} />}
                </VStack>
              </Card>
            </section>
          ))}
        </Grid>)}

    {tab === 'ideas' && (ideas.isLoading
      ? <Skeleton height={320} />
      : ideas.isError
        ? <Banner status="error" collapsible={false} title={t('plans.ideasLoadFailed')} />
        : <VStack gap={3}>
          <HStack gap={3} vAlign="center" hAlign="between" wrap="wrap">
            <SegmentedControl label={t('plans.ideaStatus')} value={ideaFilter} onChange={(value) => setIdeaFilter(value as IdeaFilter)}>
              <SegmentedControlItem value="pending" label={t('plans.filter.pending', { n: pending.length })} />
              <SegmentedControlItem value="all" label={t('plans.filter.all', { n: allIdeas.length })} />
            </SegmentedControl>
            {canReview && selected.length > 0 && <HStack gap={2} vAlign="center">
              <Text type="supporting">{t('plans.selectedCount', { n: selected.length })}</Text>
              <Button label={t('plans.cancel')} variant="ghost" size="sm" onClick={() => setSelected([])} />
              <Button label={selected.length > 1 ? t('plans.mergeApprove') : t('plans.approve')} variant="primary" size="sm" icon={<GitMerge size={14} />} onClick={() => setApproving(selected)} />
            </HStack>}
          </HStack>
          <Card padding={0}>
            {visibleIdeas.length === 0
              ? <EmptyState icon={<Lightbulb size={28} />} title={allIdeas.length ? t('plans.noPending') : t('plans.noIdeasMonth')} description={t('plans.noIdeasHint')}
                actions={<Button label={t('plans.sendIdea')} variant="secondary" icon={<Plus size={15} />} onClick={() => setEditingIdea('new')} />} />
              : visibleIdeas.map((idea, index) => {
                const reviewable = canReview && idea.status === 'pending'
                return <article key={idea.id} id={`plan-idea-${idea.id}`}>
                  {index > 0 && <Divider />}
                  <Card variant={linkedIdeaId === idea.id ? 'blue' : 'transparent'} padding={4}>
                    <HStack gap={3} vAlign="start">
                      {reviewable && <CheckboxInput label={t('plans.selectIdea', { title: idea.title })} isLabelHidden value={selected.includes(idea.id)} onChange={() => toggleIdea(idea.id)} />}
                      <VStack gap={1.5} width="100%">
                        <HStack gap={2} vAlign="center" wrap="wrap">
                          <Text weight="semibold" color={idea.status === 'rejected' ? 'secondary' : 'primary'}>{idea.title}</Text>
                          <Token size="sm" color={IDEA_STATUS[idea.status].color} label={IDEA_STATUS[idea.status].label} />
                        </HStack>
                        {idea.content && <Text type="supporting" as="p">{idea.content}</Text>}
                        <HStack gap={3} vAlign="center" wrap="wrap">
                          <HStack gap={1} vAlign="center"><UserRound size={13} aria-hidden /><Text type="supporting">{idea.submitted_by_name || t('plans.member')}</Text></HStack>
                          {idea.suggested_due_date && <HStack gap={1} vAlign="center"><CalendarClock size={13} aria-hidden /><Text type="supporting">{t('plans.until', { date: dateLabel(idea.suggested_due_date) })}</Text></HStack>}
                        </HStack>
                      </VStack>
                      {reviewable && <HStack gap={1} vAlign="center">
                        <Button label={t('plans.approve')} variant="secondary" size="sm" onClick={() => setApproving([idea.id])} />
                        <MoreMenu label={t('plans.itemActions', { title: idea.title })} size="sm" alignment="end" items={[
                          { label: t('plans.edit'), onClick: () => setEditingIdea(idea) },
                          { label: t('plans.reject'), variant: 'destructive', onClick: () => { if (window.confirm(t('plans.rejectConfirm', { title: idea.title }))) { deleteIdea.mutate(idea.id); setSelected((ids) => ids.filter((id) => id !== idea.id)) } } },
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
  const { t } = useTranslation()
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
    <DialogHeader title={existing ? t('plans.editPlanTitle') : t('plans.addPlan')} subtitle={t('plans.visibleToAll')} onOpenChange={close} />
    <DialogScrollBody label={t('plans.planForm')} actions={<>
      <Button label={t('plans.cancel')} variant="ghost" onClick={onClose} />
      <Button label={existing ? t('plans.save') : t('plans.add')} variant="primary" isDisabled={!title.trim()} clickAction={save} />
    </>}>
      <TextInput label={t('plans.titleField')} isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label={t('plans.description')} isOptional value={content} onChange={setContent} rows={5} placeholder={t('plans.contentPlaceholder')} width="100%" />
      <Grid columns={{ minWidth: 200 }} gap={3}>
        <Selector label={t('plans.horizon')} options={HORIZON_OPTIONS} value={horizon} onChange={(value) => setHorizon(value as PlanHorizon)} />
        <DateInput label={t('plans.dueDate')} isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
      </Grid>
    </DialogScrollBody>
  </Dialog>
}

/** Submit a new idea, or let a reviewer tidy a pending one before approving it. */
function IdeaDialog({ idea, month, onClose }: { idea: PlanIdea | null; month: string; onClose: () => void }) {
  const { t } = useTranslation()
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
    <DialogHeader title={idea ? t('plans.editIdeaTitle') : t('plans.sendIdea')} subtitle={t('plans.ideaSubtitle', { month: monthLabel(month.slice(0, 7)) })} onOpenChange={close} />
    <DialogScrollBody label={t('plans.ideaForm')} actions={<>
      <Button label={t('plans.cancel')} variant="ghost" onClick={onClose} />
      <Button label={idea ? t('plans.save') : t('plans.send')} variant="primary" isDisabled={!title.trim()} clickAction={save} />
    </>}>
      <TextInput label={t('plans.shortTitle')} isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label={t('plans.description')} isOptional value={content} onChange={setContent} rows={5} placeholder={t('plans.contentPlaceholder')} width="100%" />
      <DateInput label={t('plans.proposedDue')} isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
    </DialogScrollBody>
  </Dialog>
}

/** Turn one or several pending ideas into a single company plan item. */
function ApproveIdeasDialog({ ideas, month, onClose }: { ideas: PlanIdea[]; month: string; onClose: (done: boolean) => void }) {
  const { t } = useTranslation()
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
    <DialogHeader title={single ? t('plans.approveIdeaTitle') : t('plans.mergeTitle', { n: ideas.length })} subtitle={t('plans.approveHint')} onOpenChange={close} />
    <DialogScrollBody label={t('plans.approveForm')} actions={<>
      <Button label={t('plans.cancel')} variant="ghost" onClick={() => onClose(false)} />
      <Button label={t('plans.addToPlan')} variant="primary" isDisabled={!title.trim() || ideas.length === 0} clickAction={save} />
    </>}>
      {!single && <HStack gap={1.5} wrap="wrap">{ideas.map((idea) => <Token key={idea.id} size="sm" color="blue" label={idea.title} />)}</HStack>}
      <TextInput label={t('plans.planTitle')} isRequired value={title} onChange={setTitle} hasAutoFocus width="100%" />
      <TextArea label={t('plans.description')} isOptional value={content} onChange={setContent} rows={7} width="100%" />
      <Grid columns={{ minWidth: 200 }} gap={3}>
        <Selector label={t('plans.horizon')} options={HORIZON_OPTIONS} value={horizon} onChange={(value) => setHorizon(value as PlanHorizon)} />
        <DateInput label={t('plans.dueDate')} isOptional hasClear weekStartsOn="mon" value={(due || undefined) as ISODateString | undefined} onChange={(value) => setDue(value ?? '')} />
      </Grid>
    </DialogScrollBody>
  </Dialog>
}
