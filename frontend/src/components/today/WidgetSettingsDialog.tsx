import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@astryxdesign/core/Button'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { Divider } from '@astryxdesign/core/Divider'
import { HStack } from '@astryxdesign/core/HStack'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import type { TodayWidgetState } from '../../api/today'
import { DialogScrollBody } from '../DialogScrollBody'
import { clampSize } from './gridEngine'
import { GRID_COLUMNS } from './TodayCanvas'
import { widgetTitleKey, type WidgetDefinition } from './types'

interface WidgetSettingsDialogProps {
  widget: TodayWidgetState
  definition: WidgetDefinition
  onSave: (next: { settings: Record<string, unknown>; w: number; h: number }) => void
  onClose: () => void
}

/** Edits one widget: its own settings form plus its size in grid cells. */
export function WidgetSettingsDialog({ widget, definition, onSave, onClose }: WidgetSettingsDialogProps) {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<Record<string, unknown>>({ ...definition.defaultSettings, ...widget.settings })
  const [size, setSize] = useState({ w: widget.w, h: widget.h })
  const { limits } = definition
  const maxW = Math.min(limits.maxW, GRID_COLUMNS)
  const Form = definition.SettingsForm
  const close = (open: boolean) => { if (!open) onClose() }
  const save = () => {
    const clamped = clampSize(size.w, size.h, limits, GRID_COLUMNS)
    onSave({ settings, ...clamped })
  }

  return (
    <Dialog isOpen onOpenChange={close} width={460} purpose="form" maxHeight="85dvh">
      <DialogHeader title={t(widgetTitleKey(definition.type))} subtitle={t('today.settings.subtitle')} onOpenChange={close} />
      <DialogScrollBody
        label={t('today.settings.subtitle')}
        actions={<>
          <Button label={t('today.settings.cancel')} variant="ghost" onClick={onClose} />
          <Button label={t('today.settings.save')} variant="primary" onClick={save} />
        </>}
      >
        {Form && <Form settings={settings} onChange={setSettings} />}
        {Form && <Divider />}
        <HStack gap={3}>
          <NumberInput label={t('today.settings.width')} value={size.w} min={limits.minW} max={maxW} isIntegerOnly hasNumberSteppers onChange={(w) => setSize({ ...size, w })} description={`${limits.minW}–${maxW}`} />
          <NumberInput label={t('today.settings.height')} value={size.h} min={limits.minH} max={limits.maxH} isIntegerOnly hasNumberSteppers onChange={(h) => setSize({ ...size, h })} description={`${limits.minH}–${limits.maxH}`} />
        </HStack>
      </DialogScrollBody>
    </Dialog>
  )
}
