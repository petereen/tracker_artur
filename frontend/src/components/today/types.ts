import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'
import type { SizeLimits } from './gridEngine'

export type WidgetCategory = 'modules' | 'functions' | 'productivity' | 'stats'

export const WIDGET_CATEGORIES: { key: WidgetCategory; label: string }[] = [
  { key: 'modules', label: 'Модулиуд' },
  { key: 'functions', label: 'Функцүүд' },
  { key: 'productivity', label: 'Бүтээмж' },
  { key: 'stats', label: 'Статистик' },
]

/** Who is looking at the canvas: widgets use it to decide whether they apply. */
export interface WidgetContext {
  isManagerMode: boolean
  roles: string[]
}

export interface WidgetProps<S> {
  id: string
  settings: S
  /** Merges into this widget's persisted settings. */
  updateSettings: (patch: Partial<S>) => void
  isEditing: boolean
  size: { w: number; h: number }
}

export interface WidgetSettingsProps<S> {
  settings: S
  onChange: (next: S) => void
}

export interface WidgetDefinition<S = any> {
  type: string
  title: string
  description: string
  category: WidgetCategory
  icon: LucideIcon
  keywords?: string[]
  defaultSize: { w: number; h: number }
  limits: SizeLimits
  defaultSettings: S
  /** Several copies may live on the canvas (notes, timers…). */
  allowMultiple?: boolean
  isAvailable?: (context: WidgetContext) => boolean
  Component: ComponentType<WidgetProps<S>>
  SettingsForm?: ComponentType<WidgetSettingsProps<S>>
}
