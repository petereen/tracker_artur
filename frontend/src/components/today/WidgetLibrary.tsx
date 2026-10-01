import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, GripVertical, Plus, X } from 'lucide-react'
import { TextInput } from '@astryxdesign/core/TextInput'
import { WIDGET_CATEGORIES, type WidgetCategory, type WidgetDefinition } from './types'

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
      return [widget.title, widget.description, ...(widget.keywords ?? [])].join(' ').toLowerCase().includes(needle)
    })
  }, [category, query, widgets])

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
      <aside className="today-library" role="complementary" aria-label="Виджетийн сан">
        <header className="today-library-header">
          <div><strong>Виджет нэмэх</strong><small>Чирж байршуулах эсвэл + дарна уу</small></div>
          <button type="button" onClick={onClose} aria-label="Виджетийн санг хаах"><X size={17} /></button>
        </header>
        <TextInput label="Виджет хайх" isLabelHidden placeholder="Виджет хайх…" value={query} onChange={setQuery} hasClear size="sm" hasAutoFocus />
        <div className="today-library-categories" role="group" aria-label="Ангилал">
          {[{ key: 'all' as const, label: 'Бүгд' }, ...WIDGET_CATEGORIES].map((item) => (
            <button type="button" key={item.key} className={category === item.key ? 'active' : ''} aria-pressed={category === item.key} onClick={() => setCategory(item.key)}>{item.label}</button>
          ))}
        </div>
        <div className="today-library-list">
          {WIDGET_CATEGORIES.filter((group) => filtered.some((widget) => widget.category === group.key)).map((group) => (
            <section key={group.key} aria-label={group.label}>
              <h3>{group.label}</h3>
              {filtered.filter((widget) => widget.category === group.key).map((widget) => {
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
                      <strong>{widget.title}</strong>
                      <small>{widget.description}</small>
                    </span>
                    <span className="today-library-size" aria-label={`Хэмжээ ${widget.defaultSize.w}×${widget.defaultSize.h}`}>{widget.defaultSize.w}×{widget.defaultSize.h}</span>
                    <button type="button" className="today-library-add" onClick={() => onAdd(widget)} disabled={placed} aria-label={placed ? `${widget.title} нэмэгдсэн` : `${widget.title} нэмэх`} title={placed ? 'Нэмэгдсэн' : 'Нэмэх'}>
                      {placed ? <Check size={15} /> : <Plus size={15} />}
                    </button>
                  </article>
                )
              })}
            </section>
          ))}
          {filtered.length === 0 && <p className="today-library-empty">“{query}” гэсэн виджет олдсонгүй.</p>}
        </div>
      </aside>
      {drag?.active && (
        <div className={`today-library-ghost${drag.overCanvas ? ' is-over' : ''}`} style={{ transform: `translate3d(${drag.x + 12}px, ${drag.y + 12}px, 0)` }} aria-hidden>
          <drag.definition.icon size={15} />{drag.definition.title}
        </div>
      )}
    </>,
    document.body,
  )
}
