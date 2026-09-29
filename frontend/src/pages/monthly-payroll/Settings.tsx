import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Plus, Trash2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import type { ISODateString } from '@astryxdesign/core/Calendar'
import { Collapsible } from '@astryxdesign/core/Collapsible'
import { DateInput } from '@astryxdesign/core/DateInput'
import { Divider } from '@astryxdesign/core/Divider'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { Link } from '@astryxdesign/core/Link'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  useCreateMonthlyPayrollRuleDraft, useERPAccountOptions, useMonthlyPayrollCalendar, useMonthlyPayrollMonths, useMonthlyPayrollRuleSets,
  useMonthlyPayrollRuleTemplate, useMonthlyPayrollSettings, usePayrollCapabilities, usePublishMonthlyPayrollRuleDraft,
  useSaveMonthlyPayrollSettings, useSetMonthlyPayrollCalendarDay, useUpdateMonthlyPayrollRuleDraft, useValidateMonthlyPayrollRuleDraft,
} from '../../api/enterprise'
import type { ERPAccountClassification, ERPAccountOption, MonthlyPayrollCompanySettings, MonthlyPayrollRuleSet } from '../../api/enterprise'
import { CHART_OF_ACCOUNTS_PATH, CLASSIFICATION_LABELS, accountSelectorOptions } from '../../components/accounts/accountShared'
import { MonthStepper, MonthlyShell, monthKey, parseMonthKey, requestError } from './shared'
import { plainNumber } from '../../utils/numbers'

export function MonthlyPayrollSettingsPage() {
  const caps = usePayrollCapabilities()
  const now = new Date()
  const [calendarMonth, setCalendarMonth] = useState(monthKey(now.getFullYear(), now.getMonth() + 1))
  const { year, month } = parseMonthKey(calendarMonth)
  if (caps.data && !caps.data.capabilities.administer) return <MonthlyShell><p className="mp-empty">Цалингийн тохиргоог зөвхөн админ өөрчилнө.</p></MonthlyShell>
  return <MonthlyShell canAdminister>
    <VStack gap={5}>
      <VStack gap={0.5}>
        <Heading level={2}>Цалингийн тохиргоо</Heading>
        <Text type="supporting">Байгууллагын тохиргоо, хуулийн дүрмийн хувилбар, ажлын календарь. Нээсэн сарууд өөрийн хуулбарыг хадгална.</Text>
      </VStack>
      <MonthlySettingsPanel />
      <MonthlyRuleSetEditor />
      <Card padding={5}>
        <VStack gap={4}>
          <HStack gap={3} hAlign="between" vAlign="center" wrap="wrap">
            <SectionTitle title="Ажлын календарь" description="Ажлын, амралтын болон нийтийн амралтын өдрүүд. Илүү цагийн бодолт үүнийг ашиглана." />
            <MonthStepper value={calendarMonth} onChange={setCalendarMonth} />
          </HStack>
          <MonthlyCalendarEditor year={year} monthNumber={month} />
        </VStack>
      </Card>
    </VStack>
  </MonthlyShell>
}

function SectionTitle({ title, description }: { title: string; description?: string }) {
  return <VStack gap={0.5}>
    <Heading level={3}>{title}</Heading>
    {description && <Text type="supporting">{description}</Text>}
  </VStack>
}

function GroupTitle({ title, description }: { title: string; description?: string }) {
  return <VStack gap={0.5}>
    <Heading level={5}>{title}</Heading>
    {description && <Text type="supporting">{description}</Text>}
  </VStack>
}

const settingsFrom = (data: MonthlyPayrollCompanySettings): MonthlyPayrollCompanySettings => ({
  ...data,
  daily_norm_hours: plainNumber(data.daily_norm_hours),
  weekday_overtime_multiplier: plainNumber(data.weekday_overtime_multiplier),
  rest_day_overtime_multiplier: plainNumber(data.rest_day_overtime_multiplier),
  public_holiday_overtime_multiplier: plainNumber(data.public_holiday_overtime_multiplier),
  default_advance_percent: plainNumber(data.default_advance_percent),
})

const ADVANCE_BASES = [
  { value: 'FIXED', label: 'Тогтмол дүн' },
  { value: 'PERCENT', label: 'Үндсэн цалингийн хувь' },
  { value: 'WORKED-TO-DATE', label: 'Ажилласан цагаар' },
]

function MonthlySettingsPanel() {
  const settings = useMonthlyPayrollSettings()
  const save = useSaveMonthlyPayrollSettings()
  const accounts = useERPAccountOptions()
  const saved = useMemo(() => (settings.data ? settingsFrom(settings.data) : null), [settings.data])
  const [draft, setDraft] = useState<MonthlyPayrollCompanySettings | null>(null)
  useEffect(() => { if (saved) setDraft(saved) }, [saved])
  if (!draft || !saved) return null
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const update = (key: keyof MonthlyPayrollCompanySettings, value: unknown) => setDraft((current) => (current ? { ...current, [key]: value } : current))
  const numeric = (key: keyof MonthlyPayrollCompanySettings) => (value: number | null) => update(key, String(value ?? 0))
  const injuryPercent = Math.round(Number(draft.employer_injury_rate || 0) * 1000) / 10
  const submit = () => save.mutate(draft, { onSuccess: () => toast.success('Тохиргоо хадгалагдлаа'), onError: (error) => toast.error(requestError(error)) })
  return <Card padding={5}>
    <VStack gap={5}>
      <SectionTitle title="Байгууллагын цалингийн тохиргоо" description="Эдгээр тохиргоо дараа нээх саруудад үйлчилнэ. Нээсэн сарын дүрэм, хуанли өөрчлөгдөхгүй." />

      <VStack gap={3}>
        <GroupTitle title="Ерөнхий" />
        <Grid columns={{ minWidth: 240 }} gap={3}>
          <TextInput label="Компанийн нэр" value={draft.legal_company_name || ''} onChange={(value) => update('legal_company_name', value || null)} />
          <NumberInput label="Өдрийн норм цаг" value={Number(draft.daily_norm_hours)} onChange={numeric('daily_norm_hours')} min={1} max={24} step={0.25} units="цаг" />
        </Grid>
      </VStack>
      <Divider />

      <VStack gap={3}>
        <GroupTitle title="Илүү цаг ба нийгмийн даатгал" description="Илүү цагийн үржүүлэгч нь Хөдөлмөрийн тухай хуулийн доод хэмжээнээс багагүй байна." />
        <Grid columns={{ minWidth: 240 }} gap={3}>
          <NumberInput label="Ажлын өдрийн илүү цаг" value={Number(draft.weekday_overtime_multiplier)} onChange={numeric('weekday_overtime_multiplier')} min={1.5} max={10} step={0.1} units="дахин" />
          <NumberInput label="Амралтын өдрийн нэмэгдэл" value={Number(draft.rest_day_overtime_multiplier)} onChange={numeric('rest_day_overtime_multiplier')} min={1.5} max={10} step={0.1} units="дахин" />
          <NumberInput label="Баярын өдрийн нэмэгдэл" value={Number(draft.public_holiday_overtime_multiplier)} onChange={numeric('public_holiday_overtime_multiplier')} min={2} max={10} step={0.1} units="дахин" />
        </Grid>
        <Grid columns={{ minWidth: 240 }} gap={3}>
          <NumberInput label="ҮОМШӨ хувь" description={`Ажил олгогчийн БНДШ нийт ${(12 + injuryPercent).toFixed(1)}%`} value={injuryPercent} onChange={(value) => update('employer_injury_rate', String(Number(((value ?? 0) / 100).toFixed(6))))} min={0.5} max={2.5} step={0.1} units="%" />
        </Grid>
      </VStack>
      <Divider />

      <VStack gap={3}>
        <GroupTitle title="Цалингийн урьдчилгаа" />
        <Grid columns={{ minWidth: 240 }} gap={3}>
          <Selector label="Урьдчилгааны үндсэн арга" value={draft.default_advance_basis} onChange={(value) => update('default_advance_basis', value ?? 'FIXED')} options={ADVANCE_BASES} />
          <NumberInput label="Урьдчилгааны үндсэн хувь" value={Number(draft.default_advance_percent)} onChange={numeric('default_advance_percent')} min={1} max={100} step={1} units="%" />
        </Grid>
      </VStack>
      <Divider />

      <VStack gap={3}>
        <GroupTitle title="Суутгал" />
        <TextArea label="Бусад суутгалын төрлүүд" description="Мөр тус бүрд нэг төрөл бичнэ." rows={4}
          value={draft.deduction_types.join('\n')} onChange={(value) => update('deduction_types', value.split('\n').map((line) => line.trim()).filter(Boolean))} />
      </VStack>
      <Divider />

      <VStack gap={3}>
        <GroupTitle title="Дансны холболт" description="Цалингийн бичилт аль дансанд орохыг тодорхойлно." />
        <FormLayout>
          <PayrollAccountSelect label="Цалингийн зардлын данс" hint="Зардал ангиллын данс (жишээ: 5100 Цалингийн зардал)" accounts={accounts.data} value={draft.salary_expense_account_id} classifications={['expense']} purposes={['salary_expense']} onChange={(value) => update('salary_expense_account_id', value)} />
          <PayrollAccountSelect label="Ажил олгогчийн НДШ-ийн зардлын данс" hint="Зардал ангиллын данс (жишээ: 5110)" accounts={accounts.data} value={draft.employer_shi_account_id} classifications={['expense']} purposes={['employer_shi_expense']} onChange={(value) => update('employer_shi_account_id', value)} />
          <PayrollAccountSelect label="Урьдчилгааны данс" hint="Хөрөнгө (жишээ: 2350 Цалингийн урьдчилгааны тооцоо) эсвэл Зардал (жишээ: 5100 Цалингийн зардал) ангиллын данс" accounts={accounts.data} value={draft.advance_clearing_account_id} classifications={['asset', 'expense']} purposes={['advance_clearing', 'salary_expense']} onChange={(value) => update('advance_clearing_account_id', value)} />
        </FormLayout>
        <Text type="supporting">Дансыг <Link as={RouterLink} href={CHART_OF_ACCOUNTS_PATH}>Дансны төлөвлөгөө</Link> хэсэгт нээж, нэрлэж, зориулалтыг нь тохируулна.</Text>
      </VStack>
      <Divider />

      <HStack gap={3} hAlign="end" vAlign="center" wrap="wrap">
        {dirty && <Token size="sm" color="orange" label="Хадгалаагүй өөрчлөлт байна" />}
        <Button label="Болих" variant="ghost" isDisabled={!dirty || save.isPending} onClick={() => setDraft(saved)} />
        <Button label="Тохиргоо хадгалах" variant="primary" isDisabled={!dirty} isLoading={save.isPending} onClick={submit} />
      </HStack>
    </VStack>
  </Card>
}

/** Only accounts of the right classification, grouped as in the chart of accounts; the matching-purpose account is suggested first. */
function PayrollAccountSelect({ label, hint, accounts, value, classifications, purposes, onChange }: {
  label: string; hint: string; accounts: ERPAccountOption[] | undefined; value: number | null | undefined
  classifications: ERPAccountClassification[]; purposes: string[]; onChange: (value: number | null) => void
}) {
  const sections = accountSelectorOptions(accounts, { classifications, preferredPurposes: purposes, keepId: value })
  const current = accounts?.find((account) => account.id === value)
  const mismatch = Boolean(current && current.classification && !classifications.includes(current.classification))
  const allowed = classifications.map((item) => CLASSIFICATION_LABELS[item]).join(' эсвэл ')
  return <Selector label={label} description={hint} value={value ? String(value) : null} onChange={(next) => onChange(next ? Number(next) : null)}
    options={sections} hasSearch hasClear placeholder="Данс сонгох" emptyText="Тохирох данс алга"
    status={mismatch ? { type: 'warning', message: `Сонгосон данс тохирохгүй ангилалтай — ${allowed} ангиллын данс сонгоно уу.` } : undefined} />
}

const DAY_TYPES = [
  { value: 'working', label: 'Ажлын өдөр' },
  { value: 'weekly_rest', label: 'Амралтын өдөр' },
  { value: 'public_holiday', label: 'Нийтийн амралт' },
]
const DAY_COLORS = { working: 'green', weekly_rest: 'gray', public_holiday: 'red' } as const

function MonthlyCalendarEditor({ year, monthNumber }: { year: number; monthNumber: number }) {
  const days = useMonthlyPayrollCalendar(year, monthNumber)
  const update = useSetMonthlyPayrollCalendarDay(year, monthNumber)
  const months = useMonthlyPayrollMonths()
  const locked = Boolean(months.data?.some((item) => item.year === year && item.month === monthNumber))
  const [names, setNames] = useState<Record<string, string>>({})
  const change = (date: string, day_type: 'working' | 'weekly_rest' | 'public_holiday', holiday_name: string | null) => update.mutate({ date, day_type, holiday_name }, { onError: (error) => toast.error(requestError(error)) })
  const working = days.data?.filter((day) => day.day_type === 'working').length || 0
  return <VStack gap={3}>
    {locked
      ? <Banner status="info" collapsible={false} title="Энэ сарын календарь түгжигдсэн" description="Цалингийн бодолт нээгдсэн тул календарь хадгалагдсан хуулбараар түгжигдсэн." />
      : <Text type="supporting">Ажлын {working} өдөр. Шилжүүлсэн бямба гарагийг «Ажлын өдөр», баярыг «Нийтийн амралт» болгоно.</Text>}
    <Grid columns={{ minWidth: 168 }} gap={2}>
      {days.data?.map((day) => <Card key={day.date} padding={2} variant={day.day_type === 'working' ? 'default' : 'muted'}>
        <VStack gap={1.5}>
          <HStack gap={1} hAlign="between" vAlign="center">
            <Text weight="bold">{new Date(`${day.date}T12:00:00`).toLocaleDateString('mn-MN', { weekday: 'short', day: 'numeric' })}</Text>
            <Token size="sm" color={DAY_COLORS[day.day_type]} label={DAY_TYPES.find((item) => item.value === day.day_type)?.label ?? day.day_type} />
          </HStack>
          <Selector label={`${day.date} өдрийн төрөл`} isLabelHidden size="sm" value={day.day_type} isDisabled={locked || update.isPending} options={DAY_TYPES}
            onChange={(value) => change(day.date, (value ?? 'working') as typeof day.day_type, value === 'public_holiday' ? (names[day.date] ?? day.holiday_name ?? null) : null)} />
          {day.day_type === 'public_holiday' && <TextInput label={`${day.date} баярын нэр`} isLabelHidden size="sm" placeholder="Баярын нэр" isDisabled={locked}
            value={names[day.date] ?? day.holiday_name ?? ''} onChange={(value) => setNames((current) => ({ ...current, [day.date]: value }))}
            onBlur={() => names[day.date] !== undefined && names[day.date] !== (day.holiday_name || '') && change(day.date, 'public_holiday', names[day.date] || null)} />}
        </VStack>
      </Card>)}
    </Grid>
  </VStack>
}

// Rates are stored as fractions; round away float noise (0.085 × 100 = 8.500000000000002).
const asPercent = (rate: string) => String(Number((Number(rate || 0) * 100).toFixed(6)))
type RuleRateRow = { code: string; rate: string }
type RulePitRow = { lower: string; upper: string; rate: string; base_tax: string }
type RuleReliefRow = { lower: string; upper: string; amount: string }
type RuleEditorDraft = { id?: number; version?: number; status?: MonthlyPayrollRuleSet['status']; valid_from: string; valid_to: string; minimum_wage: string; shi_cap_multiplier: string; employee_rates: RuleRateRow[]; employer_rates: RuleRateRow[]; pit_brackets: RulePitRow[]; relief_tiers: RuleReliefRow[]; overtime_multipliers: RuleRateRow[]; source_references: string }
function ruleDraft(rule: Partial<MonthlyPayrollRuleSet>): RuleEditorDraft { return { id: rule.id, version: rule.version, status: rule.status, valid_from: rule.valid_from || '', valid_to: rule.valid_to || '', minimum_wage: plainNumber(rule.minimum_wage), shi_cap_multiplier: plainNumber(rule.shi_cap_multiplier || '10'), employee_rates: Object.entries(rule.employee_rates || {}).map(([code, rate]) => ({ code, rate: plainNumber(rate) })), employer_rates: Object.entries(rule.employer_rates || {}).map(([code, rate]) => ({ code, rate: plainNumber(rate) })), pit_brackets: (rule.pit_brackets || []).map((tier) => ({ lower: plainNumber(tier.lower), upper: plainNumber(tier.upper), rate: plainNumber(tier.rate), base_tax: plainNumber(tier.base_tax || '0') })), relief_tiers: (rule.relief_tiers || []).map((tier) => ({ lower: plainNumber(tier.lower), upper: plainNumber(tier.upper), amount: plainNumber(tier.amount) })), overtime_multipliers: Object.entries(rule.overtime_multipliers || {}).map(([code, rate]) => ({ code, rate: plainNumber(rate) })), source_references: (rule.source_references || []).join('\n') } }
function MonthlyRuleSetEditor() {
  const rules = useMonthlyPayrollRuleSets()
  const template = useMonthlyPayrollRuleTemplate()
  const create = useCreateMonthlyPayrollRuleDraft()
  const update = useUpdateMonthlyPayrollRuleDraft()
  const validate = useValidateMonthlyPayrollRuleDraft()
  const publish = usePublishMonthlyPayrollRuleDraft()
  const [draft, setDraft] = useState<RuleEditorDraft | null>(null)
  const set = (key: 'valid_from' | 'valid_to' | 'minimum_wage' | 'shi_cap_multiplier' | 'source_references', value: string) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, [key]: value, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setRates = (key: 'employee_rates' | 'employer_rates' | 'overtime_multipliers', rows: RuleRateRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, [key]: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setPIT = (rows: RulePitRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, pit_brackets: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const setRelief = (rows: RuleReliefRow[]) => setDraft((currentDraft) => currentDraft && currentDraft.status !== 'published' ? { ...currentDraft, relief_tiers: rows, status: currentDraft.id ? 'draft' : undefined } : currentDraft)
  const startDraft = (rule?: MonthlyPayrollRuleSet) => {
    const source = rule || rules.data?.find((item) => item.status === 'published')
    if (source) setDraft({ ...ruleDraft(source), id: undefined, version: undefined, status: undefined })
    else if (template.data) setDraft(ruleDraft(template.data))
    else toast.error('Дүрмийн загвар ачаалж байна.')
  }
  const payload = () => ({ valid_from: draft!.valid_from, valid_to: draft!.valid_to || null, minimum_wage: draft!.minimum_wage, shi_cap_multiplier: draft!.shi_cap_multiplier, employee_rates: Object.fromEntries(draft!.employee_rates.map(({ code, rate }) => [code.trim(), rate])), employer_rates: Object.fromEntries(draft!.employer_rates.map(({ code, rate }) => [code.trim(), rate])), pit_brackets: draft!.pit_brackets.map((tier) => ({ lower: tier.lower, upper: tier.upper || null, rate: tier.rate, base_tax: tier.base_tax || '0' })), relief_tiers: draft!.relief_tiers.map((tier) => ({ lower: tier.lower, upper: tier.upper || null, amount: tier.amount })), overtime_multipliers: Object.fromEntries(draft!.overtime_multipliers.map(({ code, rate }) => [code.trim(), rate])), source_references: draft!.source_references.split('\n').map((line) => line.trim()).filter(Boolean) })
  const saveDraft = async () => {
    if (!draft) return
    try {
      const saved = draft.id ? await update.mutateAsync({ id: draft.id, ...payload() }) : await create.mutateAsync(payload())
      setDraft(ruleDraft(saved))
      toast.success(`Ноорог хувилбар ${saved.version} хадгалагдлаа`)
      return saved
    } catch (error) { toast.error(requestError(error)); return undefined }
  }
  const checkDraft = async () => { const saved = await saveDraft(); if (!saved) return; validate.mutate(saved.id, { onSuccess: (result) => { setDraft(ruleDraft(result)); toast.success(result.status === 'validated' ? 'Дүрэм шалгалтад тэнцлээ' : `Шалгах алдаа: ${(result.validation_issues || []).join(', ')}`) }, onError: (error) => toast.error(requestError(error)) }) }
  const publishDraft = () => { if (!draft?.id || draft.status !== 'validated') { toast.error('Нооргийг хадгалж шалгасны дараа нийтэлнэ үү.'); return }; publish.mutate(draft.id, { onSuccess: (result) => { setDraft(ruleDraft(result)); toast.success(`Хувилбар ${result.version} нийтлэгдлээ`) }, onError: (error) => toast.error(requestError(error)) }) }
  const busy = create.isPending || update.isPending || validate.isPending || publish.isPending
  const locked = draft?.status === 'published'
  const statusToken = draft?.status === 'published' ? { color: 'green', label: 'Нийтэлсэн' } : draft?.status === 'validated' ? { color: 'blue', label: 'Шалгалт тэнцсэн' } : { color: 'gray', label: 'Ноорог' }
  return <Card padding={5}>
    <Collapsible defaultIsOpen={false} trigger={<SectionTitle title="Хууль, татварын хүчинтэй дүрмийн хувилбар" description="Шинэ дүрэм ноороглож, эх сурвалж тэмдэглэн шалгасны дараа нийтэлнэ. Нээсэн сарууд өөрийн дүрмийн хуулбарыг хадгална." />}>
      <VStack gap={4} paddingBlockStart={4}>
        <HStack gap={2} vAlign="end" wrap="wrap">
          <Selector label="Хувилбар" width={320} value={draft?.id ? String(draft.id) : undefined} placeholder="Ноорог сонгох"
            onChange={(value) => { const selected = rules.data?.find((item) => item.id === Number(value)); setDraft(selected ? ruleDraft(selected) : null) }}
            options={(rules.data ?? []).map((item) => ({ value: String(item.id), label: `v${item.version} · ${item.status === 'published' ? 'Нийтэлсэн' : item.status === 'validated' ? 'Шалгасан' : 'Ноорог'} · ${item.valid_from}` }))} />
          <Button label="Одоогийн дүрмээс шинэ хувилбар" variant="secondary" isDisabled={busy} onClick={() => startDraft()} />
        </HStack>
        {draft && <>
          <Divider />
          <Grid columns={{ minWidth: 240 }} gap={3}>
            <DateInput label="Хүчинтэй эхлэх өдөр" value={(draft.valid_from || undefined) as ISODateString | undefined} format="system_date" onChange={(value) => set('valid_from', value ?? '')} isDisabled={locked} />
            <DateInput label="Хүчинтэй дуусах өдөр" value={(draft.valid_to || undefined) as ISODateString | undefined} format="system_date" onChange={(value) => set('valid_to', value ?? '')} isDisabled={locked} isOptional />
          </Grid>
          <Grid columns={{ minWidth: 240 }} gap={3}>
            <NumberInput label="Хөдөлмөрийн хөлсний доод хэмжээ" value={Number(draft.minimum_wage)} onChange={(value) => set('minimum_wage', String(value ?? 0))} min={1} isDisabled={locked} units="₮" />
            <NumberInput label="НДШ дээд хязгаарын үржүүлэгч" value={Number(draft.shi_cap_multiplier)} onChange={(value) => set('shi_cap_multiplier', String(value ?? 0))} min={1} step={0.1} isDisabled={locked} units="дахин" />
          </Grid>
          <Divider />
          <RateRowsEditor title="Ажилтны НДШ хувь" percent rows={draft.employee_rates} disabled={locked} onChange={(rows) => setRates('employee_rates', rows)} />
          <RateRowsEditor title="Ажил олгогчийн НДШ хувь" percent rows={draft.employer_rates} disabled={locked} onChange={(rows) => setRates('employer_rates', rows)} />
          <TierRowsEditor title="ХХОАТ шатлал" rows={draft.pit_brackets} disabled={locked} onChange={setPIT} />
          <ReliefRowsEditor rows={draft.relief_tiers} disabled={locked} onChange={setRelief} />
          <RateRowsEditor title="Илүү цагийн үржүүлэгч" rows={draft.overtime_multipliers} disabled={locked} onChange={(rows) => setRates('overtime_multipliers', rows)} />
          <TextArea label="Хуулийн заалт, албан эх сурвалжийн холбоос" description="Мөр тус бүрд нэг эх сурвалж бичнэ." rows={5} isDisabled={locked}
            value={draft.source_references} onChange={(value) => set('source_references', value)} placeholder="Хуулийн нэр, зүйл заалт, legalinfo.mn холбоос" />
          <Divider />
          <HStack gap={3} hAlign="between" vAlign="center" wrap="wrap">
            <HStack gap={2} vAlign="center">
              {draft.status && <Token size="sm" color={statusToken.color as 'green' | 'blue' | 'gray'} label={`${statusToken.label} · v${draft.version}`} />}
              {draft.status === 'draft' && <Text type="supporting">Эх сурвалж болон шатлалын утгыг шалгаж байж нийтлэх боломж нээгдэнэ.</Text>}
            </HStack>
            <HStack gap={2}>
              <Button label="Ноорог хадгалах" variant="secondary" isDisabled={busy || locked} onClick={saveDraft} />
              <Button label="Шалгах" variant="secondary" isDisabled={busy || locked} onClick={checkDraft} />
              <Button label="Нийтлэх" variant="primary" isDisabled={busy || draft.status !== 'validated'} onClick={publishDraft} />
            </HStack>
          </HStack>
        </>}
        {!draft && rules.isLoading && <Text type="supporting">Хувилбар ачаалж байна…</Text>}
        {!draft && rules.error && <Banner status="error" collapsible={false} title={requestError(rules.error)} />}
      </VStack>
    </Collapsible>
  </Card>
}

function RowsSection({ title, children, onAdd, addLabel, disabled }: { title: string; children: React.ReactNode; onAdd: () => void; addLabel: string; disabled: boolean }) {
  return <VStack gap={2}>
    <Heading level={5}>{title}</Heading>
    {children}
    <HStack><Button label={addLabel} variant="ghost" size="sm" icon={<Plus size={14} />} isDisabled={disabled} onClick={onAdd} /></HStack>
  </VStack>
}

const RemoveButton = ({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) => <IconButton label={label} icon={<Trash2 size={14} />} size="sm" variant="ghost" isDisabled={disabled} onClick={onClick} />
const cell = (value: number | null | undefined) => (value == null ? '' : String(value))

function RateRowsEditor({ title, rows, disabled, percent = false, onChange }: { title: string; rows: RuleRateRow[]; disabled: boolean; percent?: boolean; onChange: (rows: RuleRateRow[]) => void }) {
  const edit = (index: number, patch: Partial<RuleRateRow>) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  return <RowsSection title={title} disabled={disabled} addLabel="Мөр нэмэх" onAdd={() => onChange([...rows, { code: '', rate: '0' }])}>
    {rows.map((row, index) => <HStack key={`${title}-${index}`} gap={2} vAlign="end" wrap="wrap">
      <TextInput label="Код" width={200} value={row.code} isDisabled={disabled} onChange={(value) => edit(index, { code: value })} />
      <NumberInput label={percent ? 'Хувь' : 'Үржүүлэгч'} width={160} value={Number(percent ? asPercent(row.rate) : row.rate)} min={0} max={percent ? 100 : undefined} step={percent ? 0.01 : 0.0001} units={percent ? '%' : 'дахин'} isDisabled={disabled}
        onChange={(value) => edit(index, { rate: percent ? String(Number(((value ?? 0) / 100).toFixed(6))) : String(value ?? 0) })} />
      <RemoveButton label={`${title} мөр хасах`} disabled={disabled} onClick={() => onChange(rows.filter((_, i) => i !== index))} />
    </HStack>)}
  </RowsSection>
}

function TierRowsEditor({ title, rows, disabled, onChange }: { title: string; rows: RulePitRow[]; disabled: boolean; onChange: (rows: RulePitRow[]) => void }) {
  const edit = (index: number, key: keyof RulePitRow, value: string) => onChange(rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)))
  const add = () => { const previous = rows[rows.length - 1]; onChange([...rows, { lower: previous?.upper || previous?.lower || '0', upper: '', rate: '0', base_tax: '0' }]) }
  return <RowsSection title={title} disabled={disabled} addLabel="Шатлал нэмэх" onAdd={add}>
    {rows.map((row, index) => <HStack key={`pit-${index}`} gap={2} vAlign="end" wrap="wrap">
      <NumberInput label="Эхлэх орлого" width={150} value={Number(row.lower)} min={0} isDisabled={disabled} onChange={(value) => edit(index, 'lower', String(value ?? 0))} />
      <NumberInput label="Дуусах орлого" width={150} value={row.upper === '' ? null : Number(row.upper)} min={0} hasClear placeholder="Дээд хязгааргүй" isDisabled={disabled} onChange={(value) => edit(index, 'upper', cell(value as number | null))} />
      <NumberInput label="Хувь" width={120} value={Number(asPercent(row.rate))} min={0} max={100} step={0.1} units="%" isDisabled={disabled} onChange={(value) => edit(index, 'rate', String(Number(((value ?? 0) / 100).toFixed(6))))} />
      <NumberInput label="Суурь татвар" width={150} value={Number(row.base_tax)} min={0} isDisabled={disabled} onChange={(value) => edit(index, 'base_tax', String(value ?? 0))} />
      <RemoveButton label={`${title} мөр хасах`} disabled={disabled} onClick={() => onChange(rows.filter((_, i) => i !== index))} />
    </HStack>)}
  </RowsSection>
}

function ReliefRowsEditor({ rows, disabled, onChange }: { rows: RuleReliefRow[]; disabled: boolean; onChange: (rows: RuleReliefRow[]) => void }) {
  const edit = (index: number, key: keyof RuleReliefRow, value: string) => onChange(rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)))
  const add = () => { const previous = rows[rows.length - 1]; onChange([...rows, { lower: previous?.upper || previous?.lower || '0', upper: '', amount: '0' }]) }
  return <RowsSection title="Татварын хөнгөлөлтийн шатлал" disabled={disabled} addLabel="Шатлал нэмэх" onAdd={add}>
    {rows.map((row, index) => <HStack key={`relief-${index}`} gap={2} vAlign="end" wrap="wrap">
      <NumberInput label="Эхлэх орлого" width={150} value={Number(row.lower)} min={0} isDisabled={disabled} onChange={(value) => edit(index, 'lower', String(value ?? 0))} />
      <NumberInput label="Дуусах орлого" width={150} value={row.upper === '' ? null : Number(row.upper)} min={0} hasClear placeholder="Дээд хязгааргүй" isDisabled={disabled} onChange={(value) => edit(index, 'upper', cell(value as number | null))} />
      <NumberInput label="Хөнгөлөлтийн дүн" width={170} value={Number(row.amount)} min={0} isDisabled={disabled} onChange={(value) => edit(index, 'amount', String(value ?? 0))} />
      <RemoveButton label="Хөнгөлөлтийн мөр хасах" disabled={disabled} onClick={() => onChange(rows.filter((_, i) => i !== index))} />
    </HStack>)}
  </RowsSection>
}
