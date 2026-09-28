import { useEffect, useMemo, useState } from 'react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { type AiAccessEntry, type AiAccessGroup, useAiAccessSettings, useUpdateAiAccessSettings } from '../api/aiSettings'

type Matrix = Record<string, AiAccessEntry>

function boxes(groups: AiAccessGroup[]) {
  return groups.flatMap((group) => group.sections.flatMap((section) => [
    { key: section.key, mode: 'read' as const },
    ...(section.has_write ? [{ key: section.key, mode: 'write' as const }] : []),
  ]))
}

function setAll(groups: AiAccessGroup[], matrix: Matrix, value: boolean): Matrix {
  const next = { ...matrix }
  for (const section of groups.flatMap((group) => group.sections)) next[section.key] = { read: value, write: value && section.has_write }
  return next
}

/** Organization-wide limits on which data the OYUNS AI assistant may read or prepare changes in. */
export function AiAccessSettings() {
  const query = useAiAccessSettings()
  const update = useUpdateAiAccessSettings()
  const [draft, setDraft] = useState<Matrix | null>(null)

  useEffect(() => {
    if (query.data) setDraft(query.data.sections)
  }, [query.data])

  const groups = query.data?.groups ?? []
  const all = useMemo(() => boxes(groups), [groups])
  if (query.isLoading || !draft) return <Text type="supporting">Ачаалж байна…</Text>
  if (query.isError || !query.data) return <Banner status="error" title="AI туслахын эрхийг ачаалж чадсангүй" />

  const checked = all.filter((box) => draft[box.key]?.[box.mode]).length
  const dirty = JSON.stringify(draft) !== JSON.stringify(query.data.sections)

  const toggle = (key: string, mode: 'read' | 'write', value: boolean) => {
    const current = draft[key] ?? { read: false, write: false }
    // Preparing changes needs read access; removing read removes changes too.
    const next = mode === 'read' ? { read: value, write: value && current.write } : { read: current.read || value, write: value }
    setDraft({ ...draft, [key]: next })
  }

  const toggleGroup = (group: AiAccessGroup, value: boolean) => {
    setDraft(setAll([group], draft, value))
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Heading level={3}>AI туслахын хандах эрх</Heading>
        <Token size="sm" label={`${checked} / ${all.length}`} color={checked === all.length ? 'green' : checked === 0 ? 'red' : 'blue'} />
      </HStack>
      <Text type="supporting">
        OYUNS AI туслах (чат, Telegram, дуут дуудлага) аль хэсгийн өгөгдлийг унших, аль хэсэгт ноорог үүсгэж засахыг байгууллагын хэмжээнд тохируулна.
        Энэ тохиргоо зөвхөн хязгаарлана: хэрэглэгч бүр өөрийн эрхийн хүрээнээс илүүг AI-аар дамжуулж харахгүй.
      </Text>
      <HStack gap={2} wrap="wrap">
        <Button label="Бүгдийг сонгох" size="sm" isDisabled={checked === all.length} onClick={() => setDraft(setAll(groups, draft, true))} />
        <Button label="Бүгдийг цуцлах" size="sm" isDisabled={checked === 0} onClick={() => setDraft(setAll(groups, draft, false))} />
      </HStack>
      <Table density="compact">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Хэсэг</TableHeaderCell>
            <TableHeaderCell>Унших</TableHeaderCell>
            <TableHeaderCell>Үүсгэх ба засах</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.flatMap((group) => {
            const groupBoxes = boxes([group])
            const groupChecked = groupBoxes.filter((box) => draft[box.key]?.[box.mode]).length
            const groupValue = groupChecked === groupBoxes.length ? true : groupChecked === 0 ? false : 'indeterminate' as const
            return [
              <TableRow key={`group-${group.key}`}>
                <TableCell>
                  <CheckboxInput label={group.label.toUpperCase()} value={groupValue} onChange={() => toggleGroup(group, groupValue !== true)} />
                </TableCell>
                <TableCell>{null}</TableCell>
                <TableCell>{null}</TableCell>
              </TableRow>,
              ...group.sections.map((section) => <TableRow key={section.key}>
                <TableCell>
                  <VStack gap={0.5}>
                    <Text>{section.label}</Text>
                    <Text type="supporting">{section.description}</Text>
                  </VStack>
                </TableCell>
                <TableCell>
                  <CheckboxInput label={`${section.label}: унших`} isLabelHidden value={Boolean(draft[section.key]?.read)} onChange={(value) => toggle(section.key, 'read', value)} />
                </TableCell>
                <TableCell>
                  {section.has_write
                    ? <CheckboxInput label={`${section.label}: үүсгэх ба засах`} isLabelHidden value={Boolean(draft[section.key]?.write)} onChange={(value) => toggle(section.key, 'write', value)} />
                    : null}
                </TableCell>
              </TableRow>),
            ]
          })}
        </TableBody>
      </Table>
      {checked === 0 && <Banner status="warning" title="AI туслах компанийн өгөгдөл уншихгүй" description="Бүх хэсгийг хаавал OYUNS зөвхөн ерөнхий асуултад хариулна." />}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label="Хадгалах" variant="primary" isDisabled={!dirty} isLoading={update.isPending} onClick={() => update.mutate(draft)} />
        {dirty && <Button label="Буцаах" onClick={() => setDraft(query.data.sections)} />}
        {!query.data.configured && <Text type="supporting">Одоогоор бүх хэсэг нээлттэй (анхдагч).</Text>}
      </HStack>
    </VStack>
  </Card>
}
