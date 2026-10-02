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
import { useTranslation } from 'react-i18next'
import { type AiAccessEntry, type AiAccessGroup, useAiAccessSettings, useUpdateAiAccessSettings } from '../api/aiSettings'
import { catalogText } from '../utils/labelMap'

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
  const { t } = useTranslation()
  const query = useAiAccessSettings()
  const update = useUpdateAiAccessSettings()
  const [draft, setDraft] = useState<Matrix | null>(null)

  useEffect(() => {
    if (query.data) setDraft(query.data.sections)
  }, [query.data])

  const groups = query.data?.groups ?? []
  const all = useMemo(() => boxes(groups), [groups])
  if (query.isLoading || !draft) return <Text type="supporting">{t('st.common.loading')}</Text>
  if (query.isError || !query.data) return <Banner status="error" title={t('st.aiAccess.loadFailed')} />

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
        <Heading level={3}>{t('st.adm.aiAccess')}</Heading>
        <Token size="sm" label={`${checked} / ${all.length}`} color={checked === all.length ? 'green' : checked === 0 ? 'red' : 'blue'} />
      </HStack>
      <Text type="supporting">{t('st.aiAccess.intro')}</Text>
      <HStack gap={2} wrap="wrap">
        <Button label={t('st.aiAccess.selectAll')} size="sm" isDisabled={checked === all.length} onClick={() => setDraft(setAll(groups, draft, true))} />
        <Button label={t('st.aiAccess.clearAll')} size="sm" isDisabled={checked === 0} onClick={() => setDraft(setAll(groups, draft, false))} />
      </HStack>
      <Table density="compact">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{t('st.aiAccess.section')}</TableHeaderCell>
            <TableHeaderCell>{t('st.aiAccess.read')}</TableHeaderCell>
            <TableHeaderCell>{t('st.aiAccess.write')}</TableHeaderCell>
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
                  <CheckboxInput label={catalogText(`cat.aiGroup.${group.key}`, group.label).toUpperCase()} value={groupValue} onChange={() => toggleGroup(group, groupValue !== true)} />
                </TableCell>
                <TableCell>{null}</TableCell>
                <TableCell>{null}</TableCell>
              </TableRow>,
              ...group.sections.map((section) => <TableRow key={section.key}>
                <TableCell>
                  <VStack gap={0.5}>
                    <Text>{catalogText(`cat.aiSection.${section.key}.label`, section.label)}</Text>
                    <Text type="supporting">{catalogText(`cat.aiSection.${section.key}.description`, section.description)}</Text>
                  </VStack>
                </TableCell>
                <TableCell>
                  <CheckboxInput label={t('st.aiAccess.readAria', { label: catalogText(`cat.aiSection.${section.key}.label`, section.label) })} isLabelHidden value={Boolean(draft[section.key]?.read)} onChange={(value) => toggle(section.key, 'read', value)} />
                </TableCell>
                <TableCell>
                  {section.has_write
                    ? <CheckboxInput label={t('st.aiAccess.writeAria', { label: catalogText(`cat.aiSection.${section.key}.label`, section.label) })} isLabelHidden value={Boolean(draft[section.key]?.write)} onChange={(value) => toggle(section.key, 'write', value)} />
                    : null}
                </TableCell>
              </TableRow>),
            ]
          })}
        </TableBody>
      </Table>
      {checked === 0 && <Banner status="warning" title={t('st.aiAccess.noneTitle')} description={t('st.aiAccess.noneDesc')} />}
      <HStack gap={2} vAlign="center" wrap="wrap">
        <Button label={t('st.common.save')} variant="primary" isDisabled={!dirty} isLoading={update.isPending} onClick={() => update.mutate(draft)} />
        {dirty && <Button label={t('st.common.revert')} onClick={() => setDraft(query.data.sections)} />}
        {!query.data.configured && <Text type="supporting">{t('st.aiAccess.allOpen')}</Text>}
      </HStack>
    </VStack>
  </Card>
}
