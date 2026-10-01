import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'
import type { SizeLimits } from './gridEngine'

export type WidgetCategory = 'modules' | 'functions' | 'productivity' | 'stats'

/** Display order of the library groups; labels live in `today.category.<key>`. */
export const WIDGET_CATEGORIES: WidgetCategory[] = ['modules', 'functions', 'productivity', 'stats']

/** Titles and descriptions are resolved at render time so they follow the UI language. */
export const widgetTitleKey = (type: string) => `today.widget.${type}.title`
export const widgetDescriptionKey = (type: string) => `today.widget.${type}.description`
export const widgetKeywordsKey = (type: string) => `today.widget.${type}.keywords`

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
  category: WidgetCategory
  icon: LucideIcon
  /** Extra English search terms; localized ones come from `today.widget.<type>.keywords`. */
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
