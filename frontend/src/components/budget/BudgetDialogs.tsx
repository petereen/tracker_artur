import { useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { FileInput } from '@astryxdesign/core/FileInput'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import { type Budget, type BudgetDetail, type BudgetKind, type BudgetScenario, useCopyBudget, useImportBudget } from '../../api/budget'
import { KIND_HINTS, KIND_LABELS, SCENARIO_LABELS, applySign, budgetErrorDetail, budgetErrorText, formatAmount } from './shared'

/** Хувилах — next year's budget or an optimistic / conservative variant of this one. */
export function CopyBudgetDialog({ budget, onClose, onCopied }: { budget: Budget; onClose: () => void; onCopied: (copy: BudgetDetail) => void }) {
  const { t } = useTranslation()
  const scenarioOptions = (Object.keys(SCENARIO_LABELS) as BudgetScenario[]).map((value) => ({ value, label: SCENARIO_LABELS[value] }))
  const [name, setName] = useState(t('budget.copy.name', { name: budget.name }))
  const [scenario, setScenario] = useState<BudgetScenario>(budget.scenario === 'base' ? 'optimistic' : budget.scenario)
  const [shiftYears, setShiftYears] = useState(0)
  const [adjustPct, setAdjustPct] = useState(0)
  const copy = useCopyBudget()
  const save = async () => {
    try {
      const result = await copy.mutateAsync({ id: budget.id, name, scenario, shift_years: shiftYears, adjust_pct: String(adjustPct) })
      toast.success(t('budget.copy.created', { number: result.number }))
      onCopied(result)
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={500} purpose="form">
    <DialogHeader title={t('budget.copy.title')} subtitle={`${budget.number} · ${budget.name}`} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label={t('budget.copy.newName')} value={name} onChange={setName} isRequired />
        <Selector label={t('budget.copy.scenario')} options={scenarioOptions} value={scenario} onChange={(value) => setScenario(value as BudgetScenario)} />
        <NumberInput label={t('budget.copy.shift')} value={shiftYears} onChange={setShiftYears} min={-5} max={5} isIntegerOnly hasNumberSteppers description={t('budget.copy.shiftHint')} />
        <NumberInput label={t('budget.copy.adjust')} value={adjustPct} onChange={setAdjustPct} min={-100} max={1000} units="%" description={t('budget.copy.adjustHint')} />
      </FormLayout>
      <HStack gap={2} hAlign="end">
        <Button label={t('budget.copy.cancel')} variant="ghost" onClick={onClose} />
        <Button label={t('budget.copy.submit')} variant="primary" clickAction={save} isDisabled={!name.trim()} />
      </HStack>
    </VStack>
  </Dialog>
}

/** Spread a total over the budget's periods (d161: 1.2 тэрбум → сар бүр). */
export function SplitDialog({ accountLabel, kind, periods, onClose, onApply }: {
  accountLabel: string; kind: BudgetKind; periods: number; onClose: () => void; onApply: (total: number) => void
}) {
  const { t } = useTranslation()
  const [total, setTotal] = useState(0)
  const signed = applySign(kind, total)
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={440} purpose="form">
    <DialogHeader title={t('budget.split.title')} subtitle={accountLabel} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <NumberInput label={t('budget.split.total')} value={total} onChange={setTotal} formatValue={formatAmount} hasAutoFocus
        description={t('budget.split.hint', { kind: KIND_LABELS[kind], sign: KIND_HINTS[kind], periods })} />
      <Text type="supporting">{t('budget.split.perPeriod', { amount: formatAmount(periods ? signed / periods : 0) })}</Text>
      <HStack gap={2} hAlign="end">
        <Button label={t('budget.split.cancel')} variant="ghost" onClick={onClose} />
        <Button label={t('budget.split.apply')} variant="primary" onClick={() => onApply(signed)} isDisabled={!total} />
      </HStack>
    </VStack>
  </Dialog>
}

interface ImportProblem { row: number | null; message: string }

/** Excel-ээс импортлох — replaces the draft grid; nothing is saved if a row fails. */
export function ImportBudgetDialog({ budget, onClose, onDownload }: { budget: Budget; onClose: () => void; onDownload: () => void }) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [problems, setProblems] = useState<ImportProblem[]>([])
  const importBudget = useImportBudget(budget.id)
  const run = async () => {
    if (!file) return
    setProblems([])
    try {
      const result = await importBudget.mutateAsync(file)
      toast.success(t('budget.import.imported', { n: result.imported_rows }))
      onClose()
    } catch (error) {
      const detail = budgetErrorDetail<{ errors?: ImportProblem[] }>(error)
      setProblems(detail?.errors?.length ? detail.errors : [{ row: null, message: budgetErrorText(error) }])
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={560} purpose="form" maxHeight="90dvh">
    <DialogHeader title={t('budget.import.title')} subtitle={`${budget.number} · ${budget.name}`} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <Text type="supporting">{t('budget.import.hint')}</Text>
      <HStack><Button label={t('budget.import.template')} size="sm" onClick={onDownload} /></HStack>
      <FileInput label={t('budget.import.file')} value={file} onChange={(value) => { setFile(Array.isArray(value) ? value[0] ?? null : value); setProblems([]) }} accept=".xlsx" maxSize={5 * 1024 * 1024} mode="dropzone" />
      {problems.length > 0 && <Banner status="error" title={t('budget.import.errors', { n: problems.length })} collapsible={false}>
        <List>{problems.slice(0, 30).map((problem, index) => <ListItem key={index} label={problem.message} description={problem.row ? t('budget.import.rowN', { n: problem.row }) : undefined} />)}</List>
      </Banner>}
      <HStack gap={2} hAlign="end">
        <Button label={t('budget.import.cancel')} variant="ghost" onClick={onClose} />
        <Button label={t('budget.import.submit')} variant="primary" clickAction={run} isDisabled={!file} />
      </HStack>
    </VStack>
  </Dialog>
}
