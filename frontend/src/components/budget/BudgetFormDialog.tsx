import { useState } from 'react'
import toast from 'react-hot-toast'
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
const scenarioOptions = (Object.keys(SCENARIO_LABELS) as BudgetScenario[]).map((value) => ({ value, label: SCENARIO_LABELS[value] }))
const periodOptions = (Object.keys(PERIOD_LABELS) as BudgetPeriodType[]).map((value) => ({ value, label: PERIOD_LABELS[value] }))

/** Create a budget, or edit the header of a draft (the period stays fixed once amounts exist). */
export function BudgetFormDialog({ budget, lookups, hasAmounts, onClose, onSaved }: {
  budget?: Budget
  lookups: BudgetLookups
  hasAmounts?: boolean
  onClose: () => void
  onSaved: (budget: Budget) => void
}) {
  const [draft, setDraft] = useState<BudgetInput>(() => budget
    ? { name: budget.name, purpose: budget.purpose, scenario: budget.scenario, period_type: budget.period_type, start_date: budget.start_date, end_date: budget.end_date, project_id: budget.project_id }
    : { name: `${year} оны төсөв`, purpose: '', scenario: 'base', period_type: 'month', start_date: `${year}-01-01`, end_date: `${year}-12-31`, project_id: null })
  const create = useCreateBudget()
  const update = useUpdateBudget(budget?.id ?? 0)
  const set = (patch: Partial<BudgetInput>) => setDraft((current) => ({ ...current, ...patch }))
  const invalidPeriod = draft.start_date > draft.end_date
  const save = async () => {
    try {
      const saved = budget ? await update.mutateAsync({ ...draft, version: budget.version }) : await create.mutateAsync(draft)
      toast.success(budget ? 'Төсөв шинэчлэгдлээ' : `${saved.number} төсөв үүслээ`)
      onSaved(saved)
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  const projectOptions = lookups.projects.map((project) => ({ value: String(project.id), label: `${project.code} · ${project.name}` }))

  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={560} purpose="form" maxHeight="90dvh">
    <DialogHeader title={budget ? 'Төсвийн мэдээлэл' : 'Шинэ төсөв'} subtitle="Нэр, зориулалт, хугацааг тодорхой бичвэл аль төсөв хүчин төгөлдөр болохыг андуурахгүй." onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label="Нэр" value={draft.name} onChange={(value) => set({ name: value })} isRequired placeholder="2026 оны үндсэн төсөв" />
        <TextArea label="Зориулалт" value={draft.purpose ?? ''} onChange={(value) => set({ purpose: value })} rows={2} isOptional placeholder="Жишээ: ТУЗ-д батлуулах жилийн орлого, зардлын төлөвлөгөө" />
        <Selector label="Хувилбар" options={scenarioOptions} value={draft.scenario} onChange={(value) => set({ scenario: value as BudgetScenario })} description="Base, Optimistic, Conservative хувилбаруудыг зэрэгцүүлэн харьцуулж болно." />
        <Selector label="Задаргаа" options={periodOptions} value={draft.period_type} onChange={(value) => set({ period_type: value as BudgetPeriodType })}
          isDisabled={hasAmounts} disabledMessage="Дүн оруулсан төсвийн задаргааг өөрчлөхгүй. Хувилж шинээр үүсгэнэ үү." />
        <HStack gap={3} wrap="wrap">
          <DateInput label="Эхлэх огноо" value={draft.start_date as ISODateString} onChange={(value) => value && set({ start_date: value })} format="system_date" isDisabled={hasAmounts} />
          <DateInput label="Дуусах огноо" value={draft.end_date as ISODateString} onChange={(value) => value && set({ end_date: value })} format="system_date" isDisabled={hasAmounts}
            status={invalidPeriod ? { type: 'error', message: 'Эхлэх огнооноос хойш байх ёстой' } : undefined} />
        </HStack>
        <Selector label="Төсөл" options={projectOptions} value={draft.project_id ? String(draft.project_id) : null} onChange={(value) => set({ project_id: value ? Number(value) : null })}
          hasClear hasSearch isOptional placeholder="Байгууллагын нийт төсөв" description="Төсөл сонговол бодит гүйцэтгэлийг зөвхөн тухайн төслийн гүйлгээнээс тооцно." />
      </FormLayout>
      {draft.project_id && <Banner status="info" title="Төслийн төсөв" description="Журнал бичилт, баримтад тухайн төслийг зөв сонгож хадгалсан байх шаардлагатай — эс бөгөөс бодит гүйцэтгэлд тусахгүй." collapsible={false} />}
      <HStack gap={2} hAlign="end">
        <Button label="Болих" variant="ghost" onClick={onClose} />
        <Button label={budget ? 'Хадгалах' : 'Үүсгэх'} variant="primary" clickAction={save} isDisabled={!draft.name.trim() || invalidPeriod} />
      </HStack>
    </VStack>
  </Dialog>
}
