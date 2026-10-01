import { useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { DateInput } from '@astryxdesign/core/DateInput'
import type { ISODateString } from '@astryxdesign/core/Calendar'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { HStack } from '@astryxdesign/core/HStack'
import { Selector } from '@astryxdesign/core/Selector'
import { TextArea } from '@astryxdesign/core/TextArea'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import { type Budget, type BudgetInput, type BudgetLookups, type BudgetPeriodType, type BudgetScenario, useCreateBudget, useUpdateBudget } from '../../api/budget'
import { PERIOD_LABELS, SCENARIO_LABELS, budgetErrorText } from './shared'

const year = new Date().getFullYear()

/** Create a budget, or edit the header of a draft (the period stays fixed once amounts exist). */
export function BudgetFormDialog({ budget, lookups, hasAmounts, onClose, onSaved }: {
  budget?: Budget
  lookups: BudgetLookups
  hasAmounts?: boolean
  onClose: () => void
  onSaved: (budget: Budget) => void
}) {
  const { t } = useTranslation()
  const scenarioOptions = (Object.keys(SCENARIO_LABELS) as BudgetScenario[]).map((value) => ({ value, label: SCENARIO_LABELS[value] }))
  const periodOptions = (Object.keys(PERIOD_LABELS) as BudgetPeriodType[]).map((value) => ({ value, label: PERIOD_LABELS[value] }))
  const [draft, setDraft] = useState<BudgetInput>(() => budget
    ? { name: budget.name, purpose: budget.purpose, scenario: budget.scenario, period_type: budget.period_type, start_date: budget.start_date, end_date: budget.end_date, project_id: budget.project_id }
    : { name: t('budget.form.defaultName', { year }), purpose: '', scenario: 'base', period_type: 'month', start_date: `${year}-01-01`, end_date: `${year}-12-31`, project_id: null })
  const create = useCreateBudget()
  const update = useUpdateBudget(budget?.id ?? 0)
  const set = (patch: Partial<BudgetInput>) => setDraft((current) => ({ ...current, ...patch }))
  const invalidPeriod = draft.start_date > draft.end_date
  const save = async () => {
    try {
      const saved = budget ? await update.mutateAsync({ ...draft, version: budget.version }) : await create.mutateAsync(draft)
      toast.success(budget ? t('budget.form.updated') : t('budget.form.created', { number: saved.number }))
      onSaved(saved)
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  const projectOptions = lookups.projects.map((project) => ({ value: String(project.id), label: `${project.code} · ${project.name}` }))

  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={560} purpose="form" maxHeight="90dvh">
    <DialogHeader title={budget ? t('budget.form.titleEdit') : t('budget.form.titleNew')} subtitle={t('budget.form.subtitle')} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label={t('budget.form.name')} value={draft.name} onChange={(value) => set({ name: value })} isRequired placeholder={t('budget.form.namePlaceholder')} />
        <TextArea label={t('budget.form.purpose')} value={draft.purpose ?? ''} onChange={(value) => set({ purpose: value })} rows={2} isOptional placeholder={t('budget.form.purposePlaceholder')} />
        <Selector label={t('budget.form.scenario')} options={scenarioOptions} value={draft.scenario} onChange={(value) => set({ scenario: value as BudgetScenario })} description={t('budget.form.scenarioHint')} />
        <Selector label={t('budget.form.granularity')} options={periodOptions} value={draft.period_type} onChange={(value) => set({ period_type: value as BudgetPeriodType })}
          isDisabled={hasAmounts} disabledMessage={t('budget.form.granularityLocked')} />
        <HStack gap={3} wrap="wrap">
          <DateInput label={t('budget.form.startDate')} value={draft.start_date as ISODateString} onChange={(value) => value && set({ start_date: value })} format="system_date" isDisabled={hasAmounts} />
          <DateInput label={t('budget.form.endDate')} value={draft.end_date as ISODateString} onChange={(value) => value && set({ end_date: value })} format="system_date" isDisabled={hasAmounts}
            status={invalidPeriod ? { type: 'error', message: t('budget.form.endBeforeStart') } : undefined} />
        </HStack>
        <Selector label={t('budget.form.project')} options={projectOptions} value={draft.project_id ? String(draft.project_id) : null} onChange={(value) => set({ project_id: value ? Number(value) : null })}
          hasClear hasSearch isOptional placeholder={t('budget.form.projectPlaceholder')} description={t('budget.form.projectHint')} />
      </FormLayout>
      {draft.project_id && <Banner status="info" title={t('budget.form.projectBannerTitle')} description={t('budget.form.projectBannerHint')} collapsible={false} />}
      <HStack gap={2} hAlign="end">
        <Button label={t('budget.form.cancel')} variant="ghost" onClick={onClose} />
        <Button label={budget ? t('budget.form.save') : t('budget.form.create')} variant="primary" clickAction={save} isDisabled={!draft.name.trim() || invalidPeriod} />
      </HStack>
    </VStack>
  </Dialog>
}
