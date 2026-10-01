import { Component, lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Check, LayoutGrid, Plus, RotateCcw } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import type { TodayWidgetState } from '../api/today'
import { useWorkspaceMode } from '../components/WorkspaceModeProvider'
import { findFreeSpot, normalizeLayout, placeItem, type GridItem } from '../components/today/gridEngine'
import { createWidgetId, defaultTodayWidgets, WIDGETS, WIDGETS_BY_TYPE } from '../components/today/registry'
import { GRID_COLUMNS, TodayCanvas, type TodayCanvasHandle } from '../components/today/TodayCanvas'
import type { WidgetContext, WidgetDefinition } from '../components/today/types'
import { useTodayLayout } from '../components/today/useTodayLayout'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import '../components/today/today.css'

// Only needed while arranging the canvas.
const WidgetLibrary = lazy(() => import('../components/today/WidgetLibrary').then((module) => ({ default: module.WidgetLibrary })))
const WidgetSettingsDialog = lazy(() => import('../components/today/WidgetSettingsDialog').then((module) => ({ default: module.WidgetSettingsDialog })))

/** Keeps one broken widget from taking the whole canvas down. */
class WidgetErrorBoundary extends Component<{ title: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    return <section className="today-widget today-widget-error" role="alert"><strong>{this.props.title}</strong><span>Виджет ачаалагдсангүй.</span><button type="button" className="today-widget-link" onClick={() => this.setState({ failed: false })}>Дахин оролдох</button></section>
  }
}

const WidgetHost = memo(function WidgetHost({ widget, definition, isEditing, onUpdateSettings }: {
  widget: TodayWidgetState
  definition: WidgetDefinition
  isEditing: boolean
  onUpdateSettings: (id: string, patch: Record<string, unknown>) => void
}) {
  const settings = useMemo(() => ({ ...definition.defaultSettings, ...widget.settings }), [definition.defaultSettings, widget.settings])
  const updateSettings = useCallback((patch: Record<string, unknown>) => onUpdateSettings(widget.id, patch), [onUpdateSettings, widget.id])
  const Widget = definition.Component
  return (
    <WidgetErrorBoundary title={definition.title}>
      <Widget id={widget.id} settings={settings} updateSettings={updateSettings} isEditing={isEditing} size={{ w: widget.w, h: widget.h }} />
    </WidgetErrorBoundary>
  )
})

const sameRect = (a: GridItem, b: GridItem) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h

/**
 * "Today": a customizable widget canvas. Long-press a widget or press
 * "Засварлах" to arrange (drag, resize, remove), add widgets from the
 * library, and open per-widget settings. The layout is saved per account.
 */
export function EnterpriseDashboardPage() {
  const { isManagerMode } = useWorkspaceMode()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const context: WidgetContext = useMemo(() => ({ isManagerMode, roles }), [isManagerMode, roles])
  const layout = useTodayLayout(defaultTodayWidgets)
  const [isEditing, setEditing] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [settingsId, setSettingsId] = useState<string | null>(null)
  const canvasRef = useRef<TodayCanvasHandle>(null)
  const widgetsRef = useRef(layout.widgets)
  widgetsRef.current = layout.widgets
  const setWidgets = layout.setWidgets

  const isShown = useCallback((widget: TodayWidgetState) => {
    const definition = WIDGETS_BY_TYPE.get(widget.type)
    return Boolean(definition && (!definition.isAvailable || definition.isAvailable(context)))
  }, [context])
  const shown = useMemo(() => layout.widgets.filter(isShown), [isShown, layout.widgets])
  const items = useMemo(() => normalizeLayout(shown.map(({ id, x, y, w, h }) => ({ id, x, y, w, h })), GRID_COLUMNS), [shown])
  const byId = useMemo(() => new Map(layout.widgets.map((widget) => [widget.id, widget])), [layout.widgets])
  const library = useMemo(() => WIDGETS.filter((definition) => !definition.isAvailable || definition.isAvailable(context)), [context])
  const placedTypes = useMemo(() => new Set(shown.map((widget) => widget.type)), [shown])

  /** Writes canvas positions back, keeping hidden widgets and untouched objects as they are. */
  const commitPositions = useCallback((next: GridItem[], extra: TodayWidgetState[] = []) => {
    const positions = new Map(next.map((item) => [item.id, item]))
    setWidgets([...widgetsRef.current.map((widget) => {
      const position = positions.get(widget.id)
      return position && !sameRect(widget, position) ? { ...widget, x: position.x, y: position.y, w: position.w, h: position.h } : widget
    }), ...extra.map((widget) => ({ ...widget, ...positions.get(widget.id) }))])
  }, [setWidgets])

  const updateSettings = useCallback((id: string, patch: Record<string, unknown>) => {
    setWidgets(widgetsRef.current.map((widget) => (widget.id === id ? { ...widget, settings: { ...widget.settings, ...patch } } : widget)))
  }, [setWidgets])

  const removeWidget = useCallback((id: string) => {
    setWidgets(widgetsRef.current.filter((widget) => widget.id !== id))
  }, [setWidgets])

  const addWidget = useCallback((definition: WidgetDefinition, cell?: { x: number; y: number }) => {
    const { w, h } = definition.defaultSize
    const spot = cell ?? findFreeSpot(items, w, h, GRID_COLUMNS)
    const widget: TodayWidgetState = { id: createWidgetId(definition.type), type: definition.type, ...spot, w, h, settings: { ...definition.defaultSettings } }
    commitPositions(placeItem(items, { id: widget.id, x: widget.x, y: widget.y, w, h }), [widget])
    window.requestAnimationFrame(() => document.querySelector(`[data-widget-id="${widget.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }, [commitPositions, items])

  const startEditing = useCallback(() => setEditing(true), [])
  const finishEditing = useCallback(() => { setEditing(false); setLibraryOpen(false) }, [])
  useEffect(() => {
    if (!isEditing || libraryOpen || settingsId) return
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') finishEditing() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [finishEditing, isEditing, libraryOpen, settingsId])

  const limitsFor = useCallback((id: string) => WIDGETS_BY_TYPE.get(byId.get(id)?.type ?? '')?.limits ?? { minW: 1, minH: 1, maxW: GRID_COLUMNS, maxH: 40 }, [byId])
  const labelFor = useCallback((id: string) => WIDGETS_BY_TYPE.get(byId.get(id)?.type ?? '')?.title ?? 'Виджет', [byId])
  const hasSettings = useCallback(() => true, [])
  const renderItem = useCallback((id: string) => {
    const widget = byId.get(id)
    const definition = widget && WIDGETS_BY_TYPE.get(widget.type)
    return widget && definition ? <WidgetHost widget={widget} definition={definition} isEditing={isEditing} onUpdateSettings={updateSettings} /> : null
  }, [byId, isEditing, updateSettings])

  const settingsWidget = settingsId ? byId.get(settingsId) : undefined
  const settingsDefinition = settingsWidget ? WIDGETS_BY_TYPE.get(settingsWidget.type) : undefined

  return (
    <div className={`today-page${libraryOpen ? ' has-library' : ''}`}>
      <div className="today-toolbar" role="toolbar" aria-label="Нүүр хуудасны байршил">
        {isEditing ? <>
          <span className="today-toolbar-hint">Виджетийг чирж зөөх, буланг нь чирж хэмжээг өөрчилнө</span>
          <Button label="Анхны байдал" size="sm" variant="ghost" icon={<RotateCcw size={14} />} onClick={() => { if (window.confirm('Нүүр хуудсыг анхны байдалд нь буцаах уу?')) layout.resetToDefault() }} isDisabled={!layout.isCustomized} />
          <Button label="Виджет нэмэх" size="sm" icon={<Plus size={14} />} onClick={() => setLibraryOpen(true)} />
          <Button label="Болсон" size="sm" variant="primary" icon={<Check size={14} />} onClick={finishEditing} />
        </> : (
          <Button label="Засварлах" size="sm" variant="ghost" icon={<LayoutGrid size={14} />} onClick={startEditing} tooltip="Виджет нэмэх, зөөх, хэмжээ өөрчлөх" />
        )}
      </div>
      {layout.isLoading ? (
        <div className="today-canvas-loading" aria-label="Нүүр хуудас ачаалж байна"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div>
      ) : items.length === 0 && !isEditing ? (
        <EmptyState title="Нүүр хуудас хоосон байна" description="Өдөр тутмын ажилдаа хэрэгтэй виджетүүдээ нэмээрэй." actions={<Button label="Виджет нэмэх" variant="primary" icon={<Plus size={14} />} onClick={() => { setEditing(true); setLibraryOpen(true) }} />} />
      ) : (
        <TodayCanvas
          ref={canvasRef}
          items={items}
          isEditing={isEditing}
          onRequestEdit={startEditing}
          onLayoutChange={commitPositions}
          onRemove={removeWidget}
          onOpenSettings={setSettingsId}
          hasSettings={hasSettings}
          limitsFor={limitsFor}
          labelFor={labelFor}
          renderItem={renderItem}
        />
      )}
      {libraryOpen && <Suspense fallback={null}>
        <WidgetLibrary
          widgets={library}
          placedTypes={placedTypes}
          onAdd={(definition) => addWidget(definition)}
          onDragMove={(x, y, definition) => canvasRef.current?.previewExternal(x, y, definition.defaultSize) ?? false}
          onDrop={(x, y, definition) => { const cell = canvasRef.current?.dropExternal(x, y, definition.defaultSize); if (cell) addWidget(definition, cell) }}
          onDragCancel={() => canvasRef.current?.clearExternal()}
          onClose={() => setLibraryOpen(false)}
        />
      </Suspense>}
      {settingsWidget && settingsDefinition && <Suspense fallback={null}>
        <WidgetSettingsDialog
          widget={settingsWidget}
          definition={settingsDefinition}
          onClose={() => setSettingsId(null)}
          onSave={({ settings, w, h }) => {
            const resized = { id: settingsWidget.id, x: Math.min(settingsWidget.x, GRID_COLUMNS - w), y: settingsWidget.y, w, h }
            const next = placeItem(items, resized)
            setWidgets(widgetsRef.current.map((widget) => {
              const position = next.find((item) => item.id === widget.id)
              const placed = position ? { ...widget, x: position.x, y: position.y, w: position.w, h: position.h } : widget
              return widget.id === settingsWidget.id ? { ...placed, settings } : placed
            }))
            setSettingsId(null)
          }}
        />
      </Suspense>}
    </div>
  )
}
