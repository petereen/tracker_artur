import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Check, GripVertical, Plus, X } from 'lucide-react'
import { TextInput } from '@astryxdesign/core/TextInput'
import { WIDGET_CATEGORIES, widgetDescriptionKey, widgetKeywordsKey, widgetTitleKey, type WidgetCategory, type WidgetDefinition } from './types'

const DRAG_THRESHOLD = 5

interface WidgetLibraryProps {
  widgets: WidgetDefinition[]
  /** Types that already sit on the canvas and allow only one copy. */
  placedTypes: Set<string>
  onAdd: (definition: WidgetDefinition) => void
  onDragMove: (clientX: number, clientY: number, definition: WidgetDefinition) => boolean
  onDrop: (clientX: number, clientY: number, definition: WidgetDefinition) => void
  onDragCancel: () => void
  onClose: () => void
}

type LibraryDrag = { definition: WidgetDefinition; pointerId: number; startX: number; startY: number; x: number; y: number; active: boolean; overCanvas: boolean }

/**
 * Non-modal side drawer (bottom sheet on phones) listing every widget.
 * Cards can be dragged onto the canvas or added with "+".
 */
export function WidgetLibrary({ widgets, placedTypes, onAdd, onDragMove, onDrop, onDragCancel, onClose }: WidgetLibraryProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<WidgetCategory | 'all'>('all')
  const [drag, setDrag] = useState<LibraryDrag | null>(null)
  const dragRef = useRef<LibraryDrag | null>(null)
  const handlers = useRef({ onDragMove, onDrop, onDragCancel })
  handlers.current = { onDragMove, onDrop, onDragCancel }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return widgets.filter((widget) => {
      if (category !== 'all' && widget.category !== category) return false
      if (!needle) return true
      return [t(widgetTitleKey(widget.type)), t(widgetDescriptionKey(widget.type)), t(widgetKeywordsKey(widget.type)), ...(widget.keywords ?? [])].join(' ').toLowerCase().includes(needle)
    })
  }, [category, query, t, widgets])

  useEffect(() => {
    const update = (next: LibraryDrag | null) => { dragRef.current = next; setDrag(next) }
    const move = (event: PointerEvent) => {
      const current = dragRef.current
      if (!current || current.pointerId !== event.pointerId) return
      const active = current.active || Math.hypot(event.clientX - current.startX, event.clientY - current.startY) > DRAG_THRESHOLD
      if (!active) return
      event.preventDefault()
      const overCanvas = handlers.current.onDragMove(event.clientX, event.clientY, current.definition)
      update({ ...current, active, x: event.clientX, y: event.clientY, overCanvas })
    }
    const end = (event: PointerEvent) => {
      const current = dragRef.current
      if (!current || current.pointerId !== event.pointerId) return
      update(null)
      if (current.active && event.type === 'pointerup') handlers.current.onDrop(event.clientX, event.clientY, current.definition)
      else handlers.current.onDragCancel()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (dragRef.current) { update(null); handlers.current.onDragCancel() } else onClose()
    }
    const touchMove = (event: TouchEvent) => { if (dragRef.current?.active) event.preventDefault() }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    window.addEventListener('keydown', escape)
    window.addEventListener('touchmove', touchMove, { passive: false })
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      window.removeEventListener('keydown', escape)
      window.removeEventListener('touchmove', touchMove)
    }
  }, [onClose])

  const startDrag = (event: ReactPointerEvent, definition: WidgetDefinition, disabled: boolean) => {
    if (disabled || event.button !== 0 || (event.target as Element).closest('button')) return
    const next = { definition, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, active: false, overCanvas: false }
    dragRef.current = next
    setDrag(next)
  }

  return createPortal(
    <>
      <aside className="today-library" role="complementary" aria-label={t('today.library.aria')}>
        <header className="today-library-header">
          <div><strong>{t('today.library.title')}</strong><small>{t('today.library.hint')}</small></div>
          <button type="button" onClick={onClose} aria-label={t('today.library.close')}><X size={17} /></button>
        </header>
        <TextInput label={t('today.library.search')} isLabelHidden placeholder={t('today.library.searchPlaceholder')} value={query} onChange={setQuery} hasClear size="sm" hasAutoFocus />
        <div className="today-library-categories" role="group" aria-label={t('today.library.categories')}>
          {(['all', ...WIDGET_CATEGORIES] as const).map((item) => (
            <button type="button" key={item} className={category === item ? 'active' : ''} aria-pressed={category === item} onClick={() => setCategory(item)}>{t(`today.category.${item}`)}</button>
          ))}
        </div>
        <div className="today-library-list">
          {WIDGET_CATEGORIES.filter((group) => filtered.some((widget) => widget.category === group)).map((group) => (
            <section key={group} aria-label={t(`today.category.${group}`)}>
              <h3>{t(`today.category.${group}`)}</h3>
              {filtered.filter((widget) => widget.category === group).map((widget) => {
                const title = t(widgetTitleKey(widget.type))
                const placed = !widget.allowMultiple && placedTypes.has(widget.type)
                const Icon = widget.icon
                return (
                  <article
                    key={widget.type}
                    className={`today-library-card${placed ? ' is-placed' : ''}${drag?.active && drag.definition.type === widget.type ? ' is-dragging' : ''}`}
                    onPointerDown={(event) => startDrag(event, widget, placed)}
                  >
                    {!placed && <GripVertical className="today-library-grip" size={14} aria-hidden />}
                    <span className="today-library-icon"><Icon size={17} aria-hidden /></span>
                    <span className="today-library-text">
                      <strong>{title}</strong>
                      <small>{t(widgetDescriptionKey(widget.type))}</small>
                    </span>
                    <span className="today-library-size" aria-label={t('today.library.size', { w: widget.defaultSize.w, h: widget.defaultSize.h })}>{widget.defaultSize.w}×{widget.defaultSize.h}</span>
                    <button type="button" className="today-library-add" onClick={() => onAdd(widget)} disabled={placed} aria-label={t(placed ? 'today.library.placedLabel' : 'today.library.addLabel', { title })} title={t(placed ? 'today.library.placed' : 'today.library.add')}>
                      {placed ? <Check size={15} /> : <Plus size={15} />}
                    </button>
                  </article>
                )
              })}
            </section>
          ))}
          {filtered.length === 0 && <p className="today-library-empty">{t('today.library.empty', { query })}</p>}
        </div>
      </aside>
      {drag?.active && (
        <div className={`today-library-ghost${drag.overCanvas ? ' is-over' : ''}`} style={{ transform: `translate3d(${drag.x + 12}px, ${drag.y + 12}px, 0)` }} aria-hidden>
          <drag.definition.icon size={15} />{t(widgetTitleKey(drag.definition.type))}
        </div>
      )}
    </>,
    document.body,
  )
}
