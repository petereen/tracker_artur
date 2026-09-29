import { useState } from 'react'
import toast from 'react-hot-toast'
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

const scenarioOptions = (Object.keys(SCENARIO_LABELS) as BudgetScenario[]).map((value) => ({ value, label: SCENARIO_LABELS[value] }))

/** Хувилах — next year's budget or an optimistic / conservative variant of this one. */
export function CopyBudgetDialog({ budget, onClose, onCopied }: { budget: Budget; onClose: () => void; onCopied: (copy: BudgetDetail) => void }) {
  const [name, setName] = useState(`${budget.name} (хуулбар)`)
  const [scenario, setScenario] = useState<BudgetScenario>(budget.scenario === 'base' ? 'optimistic' : budget.scenario)
  const [shiftYears, setShiftYears] = useState(0)
  const [adjustPct, setAdjustPct] = useState(0)
  const copy = useCopyBudget()
  const save = async () => {
    try {
      const result = await copy.mutateAsync({ id: budget.id, name, scenario, shift_years: shiftYears, adjust_pct: String(adjustPct) })
      toast.success(`${result.number} хуулбар үүслээ`)
      onCopied(result)
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={500} purpose="form">
    <DialogHeader title="Төсөв хувилах" subtitle={`${budget.number} · ${budget.name}`} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label="Шинэ төсвийн нэр" value={name} onChange={setName} isRequired />
        <Selector label="Хувилбар" options={scenarioOptions} value={scenario} onChange={(value) => setScenario(value as BudgetScenario)} />
        <NumberInput label="Хугацааг шилжүүлэх (жил)" value={shiftYears} onChange={setShiftYears} min={-5} max={5} isIntegerOnly hasNumberSteppers description="1 бол ирэх оны төсөв болгон хуулна." />
        <NumberInput label="Дүнг өөрчлөх" value={adjustPct} onChange={setAdjustPct} min={-100} max={1000} units="%" description="Жишээ: өөдрөг хувилбарт +10, болгоомжит хувилбарт −10. Тэмдэг (орлого +, зардал −) хадгалагдана." />
      </FormLayout>
      <HStack gap={2} hAlign="end">
        <Button label="Болих" variant="ghost" onClick={onClose} />
        <Button label="Хувилах" variant="primary" clickAction={save} isDisabled={!name.trim()} />
      </HStack>
    </VStack>
  </Dialog>
}

/** Spread a total over the budget's periods (d161: 1.2 тэрбум → сар бүр). */
export function SplitDialog({ accountLabel, kind, periods, onClose, onApply }: {
  accountLabel: string; kind: BudgetKind; periods: number; onClose: () => void; onApply: (total: number) => void
}) {
  const [total, setTotal] = useState(0)
  const signed = applySign(kind, total)
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={440} purpose="form">
    <DialogHeader title="Нийт дүнг хуваах" subtitle={accountLabel} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <NumberInput label="Нийт дүн" value={total} onChange={setTotal} formatValue={formatAmount} hasAutoFocus
        description={`${KIND_LABELS[kind]} тул ${KIND_HINTS[kind]} утгаар хадгална. ${periods} хугацаанд тэнцүү хуваана.`} />
      <Text type="supporting">Нэг хугацаанд ≈ {formatAmount(periods ? signed / periods : 0)}. Улирлын шинжтэй бол хуваасны дараа сар бүрийг гараар тохируулна уу.</Text>
      <HStack gap={2} hAlign="end">
        <Button label="Болих" variant="ghost" onClick={onClose} />
        <Button label="Хуваах" variant="primary" onClick={() => onApply(signed)} isDisabled={!total} />
      </HStack>
    </VStack>
  </Dialog>
}

interface ImportProblem { row: number | null; message: string }

/** Excel-ээс импортлох — replaces the draft grid; nothing is saved if a row fails. */
export function ImportBudgetDialog({ budget, onClose, onDownload }: { budget: Budget; onClose: () => void; onDownload: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [problems, setProblems] = useState<ImportProblem[]>([])
  const importBudget = useImportBudget(budget.id)
  const run = async () => {
    if (!file) return
    setProblems([])
    try {
      const result = await importBudget.mutateAsync(file)
      toast.success(`${result.imported_rows} мөр импортлогдлоо`)
      onClose()
    } catch (error) {
      const detail = budgetErrorDetail<{ errors?: ImportProblem[] }>(error)
      setProblems(detail?.errors?.length ? detail.errors : [{ row: null, message: budgetErrorText(error) }])
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={560} purpose="form" maxHeight="90dvh">
    <DialogHeader title="Excel-ээс импортлох" subtitle={`${budget.number} · ${budget.name}`} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <Text type="supporting">Эхлээд “Excel татах”-аар загварыг аваад дүнгээ бөглөнө. Импорт хийхэд энэ төсвийн бүх мөр файлын агуулгаар солигдоно.</Text>
      <HStack><Button label="Загвар татах" size="sm" onClick={onDownload} /></HStack>
      <FileInput label="Excel файл" value={file} onChange={(value) => { setFile(Array.isArray(value) ? value[0] ?? null : value); setProblems([]) }} accept=".xlsx" maxSize={5 * 1024 * 1024} mode="dropzone" />
      {problems.length > 0 && <Banner status="error" title={`${problems.length} алдаа олдлоо — юу ч хадгалагдаагүй`} collapsible={false}>
        <List>{problems.slice(0, 30).map((problem, index) => <ListItem key={index} label={problem.message} description={problem.row ? `${problem.row}-р мөр` : undefined} />)}</List>
      </Banner>}
      <HStack gap={2} hAlign="end">
        <Button label="Болих" variant="ghost" onClick={onClose} />
        <Button label="Импортлох" variant="primary" clickAction={run} isDisabled={!file} />
      </HStack>
    </VStack>
  </Dialog>
}
