import { BarChart3, CalendarDays, ClipboardCheck, Clock3, Gauge, Hourglass, ListChecks, Megaphone, NotebookPen, Timer, Zap } from 'lucide-react'
import type { TodayWidgetState } from '../../api/today'
import { WorldClockStrip } from '../WorldClockWidget'
import type { WidgetDefinition } from './types'
import { CheckinWidget } from './widgets/CheckinWidget'
import { DEFAULT_KPI_SETTINGS, DEFAULT_SINGLE_KPI_SETTINGS, KpiSettingsForm, KpiWidget, SingleKpiSettingsForm, SingleKpiWidget } from './widgets/KpiWidgets'
import { MiniCalendarWidget } from './widgets/MiniCalendarWidget'
import { NewsWidget } from './widgets/NewsWidget'
import { DEFAULT_TIMER_SETTINGS, NotesWidget, TimerSettingsForm, TimerWidget } from './widgets/ProductivityWidgets'
import { DEFAULT_QUICK_ACTIONS_SETTINGS, QuickActionsSettingsForm, QuickActionsWidget } from './widgets/QuickActionsWidget'
import { TasksWidget } from './widgets/TasksWidget'
import { WorktimeWidget } from './widgets/WorktimeWidget'

/**
 * Every widget the Today canvas can show. Adding a widget = one entry here;
 * the grid engine and canvas never import widget code.
 */
export const WIDGETS: WidgetDefinition[] = [
  {
    type: 'world-clock', title: 'Дэлхийн цаг', description: 'Хотуудын цагийг нэг мөрөнд харуулна.', category: 'functions', icon: Clock3,
    keywords: ['world clock', 'timezone', 'цагийн бүс'],
    defaultSize: { w: 12, h: 1 }, limits: { minW: 3, minH: 1, maxW: 12, maxH: 2 }, defaultSettings: {},
    Component: () => <WorldClockStrip />,
  },
  {
    type: 'worktime', title: 'Ажлын цаг', description: 'Өнөөдрийн ажлын цаг, эхлэх, завсарлах, дуусгах.', category: 'functions', icon: Timer,
    keywords: ['clock', 'attendance', 'ирц'],
    defaultSize: { w: 5, h: 6 }, limits: { minW: 4, minH: 5, maxW: 12, maxH: 10 }, defaultSettings: {},
    Component: WorktimeWidget,
  },
  {
    type: 'kpi', title: 'Гүйцэтгэлийн үзүүлэлт', description: 'Гол үзүүлэлтүүд, өмнөх 7 хоногтой харьцуулалт, чиг хандлага.', category: 'stats', icon: BarChart3,
    keywords: ['kpi', 'stats', 'metrics', 'статистик'],
    defaultSize: { w: 4, h: 6 }, limits: { minW: 3, minH: 3, maxW: 12, maxH: 10 }, defaultSettings: DEFAULT_KPI_SETTINGS,
    Component: KpiWidget, SettingsForm: KpiSettingsForm,
  },
  {
    type: 'kpi-single', title: 'Нэг үзүүлэлт', description: 'Сонгосон нэг үзүүлэлтийг том харуулна.', category: 'stats', icon: Gauge,
    keywords: ['kpi', 'metric', 'sparkline'],
    defaultSize: { w: 3, h: 3 }, limits: { minW: 2, minH: 3, maxW: 6, maxH: 6 }, defaultSettings: DEFAULT_SINGLE_KPI_SETTINGS, allowMultiple: true,
    Component: SingleKpiWidget, SettingsForm: SingleKpiSettingsForm,
  },
  {
    type: 'quick-actions', title: 'Шуурхай үйлдэл', description: 'Модуль, функц руу нэг товшилтоор.', category: 'functions', icon: Zap,
    keywords: ['shortcuts', 'товчлол'],
    defaultSize: { w: 3, h: 6 }, limits: { minW: 2, minH: 3, maxW: 12, maxH: 8 }, defaultSettings: DEFAULT_QUICK_ACTIONS_SETTINGS,
    Component: QuickActionsWidget, SettingsForm: QuickActionsSettingsForm,
  },
  {
    type: 'tasks', title: 'Хийх даалгаврууд', description: 'Надад өгсөн, миний өгсөн, байгууллагын даалгавар.', category: 'modules', icon: ListChecks,
    keywords: ['tasks', 'todo'],
    defaultSize: { w: 5, h: 8 }, limits: { minW: 3, minH: 4, maxW: 12, maxH: 16 }, defaultSettings: {},
    Component: TasksWidget,
  },
  {
    type: 'news', title: 'Мэдээ, мэдэгдэл', description: 'Байгууллагын мэдээ, зарлал.', category: 'modules', icon: Megaphone,
    keywords: ['news', 'announcements', 'зарлал'],
    defaultSize: { w: 4, h: 8 }, limits: { minW: 3, minH: 4, maxW: 12, maxH: 16 }, defaultSettings: {},
    Component: NewsWidget,
  },
  {
    type: 'mini-calendar', title: 'Календарь', description: 'Сарын тойм: даалгавар, үйл явдал, сануулга.', category: 'modules', icon: CalendarDays,
    keywords: ['calendar', 'month'],
    defaultSize: { w: 3, h: 8 }, limits: { minW: 3, minH: 7, maxW: 6, maxH: 10 }, defaultSettings: {},
    Component: MiniCalendarWidget,
  },
  {
    type: 'checkin', title: 'Өдрийн check-in', description: 'Өнөөдрийн төлөвлөгөө, check-in асуулга.', category: 'functions', icon: ClipboardCheck,
    keywords: ['check-in', 'attendance', 'төлөвлөгөө'],
    defaultSize: { w: 4, h: 7 }, limits: { minW: 3, minH: 5, maxW: 12, maxH: 14 }, defaultSettings: {},
    Component: CheckinWidget,
  },
  {
    type: 'timer', title: 'Цаг хэмжигч', description: 'Төвлөрөл (pomodoro), тоолуур, секундомер.', category: 'productivity', icon: Hourglass,
    keywords: ['timer', 'pomodoro', 'stopwatch', 'focus'],
    defaultSize: { w: 3, h: 5 }, limits: { minW: 3, minH: 4, maxW: 6, maxH: 8 }, defaultSettings: DEFAULT_TIMER_SETTINGS, allowMultiple: true,
    Component: TimerWidget, SettingsForm: TimerSettingsForm,
  },
  {
    type: 'notes', title: 'Тэмдэглэл', description: 'Автоматаар хадгалагдах жижиг тэмдэглэл.', category: 'productivity', icon: NotebookPen,
    keywords: ['notes', 'scratchpad', 'memo'],
    defaultSize: { w: 3, h: 5 }, limits: { minW: 2, minH: 3, maxW: 12, maxH: 14 }, defaultSettings: { text: '' }, allowMultiple: true,
    Component: NotesWidget,
  },
]

export const WIDGETS_BY_TYPE = new Map(WIDGETS.map((widget) => [widget.type, widget]))

export function createWidgetId(type: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).slice(2, 10)
  return `${type}-${random}`
}

/** Default canvas for everyone. The check-in box is intentionally left out — add it from the library. */
export function defaultTodayWidgets(): TodayWidgetState[] {
  const place = (type: string, x: number, y: number, w: number, h: number): TodayWidgetState => ({
    id: `${type}-default`, type, x, y, w, h, settings: { ...WIDGETS_BY_TYPE.get(type)!.defaultSettings },
  })
  return [
    place('world-clock', 0, 0, 12, 1),
    place('worktime', 0, 1, 5, 6),
    place('kpi', 5, 1, 4, 6),
    place('quick-actions', 9, 1, 3, 6),
    place('tasks', 0, 7, 5, 8),
    place('news', 5, 7, 4, 8),
    place('mini-calendar', 9, 7, 3, 8),
  ]
}
