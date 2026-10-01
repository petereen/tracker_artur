import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { ArrowDown, ArrowUp, Settings2, X } from 'lucide-react'
import {
  clampSize,
  layoutRows,
  moveItem,
  nudgeVertical,
  placeItem,
  resizeItem,
  shiftInReadingOrder,
  sortByPosition,
  type GridItem,
  type SizeLimits,
} from './gridEngine'

export const GRID_COLUMNS = 12
export const ROW_HEIGHT = 44
export const GRID_GAP = 12
/** Below this canvas width widgets stack in one column (reading order). */
export const STACK_BREAKPOINT = 720
const DRAG_THRESHOLD = 4
const LONG_PRESS_MS = 450
const EDGE_SCROLL_ZONE = 64
const EXTERNAL_ID = '__today-new__'
const INTERACTIVE = 'a, button, input, textarea, select, label, summary, [role="button"], [role="tab"], [role="option"], [contenteditable="true"], [data-today-interactive]'

export interface TodayCanvasHandle {
  /** Shows where a widget dragged in from outside would land. Returns false when the pointer is off the canvas. */
  previewExternal: (clientX: number, clientY: number, size: { w: number; h: number }) => boolean
  /** Final cell for a widget dropped from outside, or null when dropped off the canvas. */
  dropExternal: (clientX: number, clientY: number, size: { w: number; h: number }) => { x: number; y: number } | null
  clearExternal: () => void
}

interface TodayCanvasProps {
  items: GridItem[]
  isEditing: boolean
  onRequestEdit: () => void
  onLayoutChange: (next: GridItem[]) => void
  onRemove: (id: string) => void
  onOpenSettings: (id: string) => void
  hasSettings: (id: string) => boolean
  limitsFor: (id: string) => SizeLimits
  labelFor: (id: string) => string
  renderItem: (id: string) => ReactNode
}

type Interaction = {
  kind: 'drag' | 'resize'
  id: string
  pointerId: number
  startX: number
  startY: number
  /** Pointer offset inside the item (drag) or the item's start size in px (resize). */
  offsetX: number
  offsetY: number
  active: boolean
  left: number
  top: number
  width: number
  height: number
  target: { a: number; b: number }
  preview: GridItem[]
}

function scrollParentOf(node: HTMLElement | null): HTMLElement {
  for (let current = node?.parentElement; current; current = current.parentElement) {
    const { overflowY } = window.getComputedStyle(current)
    if ((overflowY === 'auto' || overflowY === 'scroll') && current.scrollHeight > current.clientHeight) return current
  }
  return (document.scrollingElement as HTMLElement | null) ?? document.documentElement
}

export const TodayCanvas = forwardRef<TodayCanvasHandle, TodayCanvasProps>(function TodayCanvas(
  { items, isEditing, onRequestEdit, onLayoutChange, onRemove, onOpenSettings, hasSettings, limitsFor, labelFor, renderItem },
  ref,
) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [interaction, setInteraction] = useState<Interaction | null>(null)
  const [external, setExternal] = useState<GridItem[] | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const interactionRef = useRef<Interaction | null>(null)
  const pointerRef = useRef<{ x: number; y: number } | null>(null)
  const frameRef = useRef<number | undefined>(undefined)
  const scrollFrameRef = useRef<number | undefined>(undefined)
  const longPressRef = useRef<{ timer: number; id: string; pointerId: number; x: number; y: number } | null>(null)
  const itemsRef = useRef(items)
  itemsRef.current = items

  useLayoutEffect(() => {
    const node = containerRef.current
    if (!node) return
    setWidth(node.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  // Unmeasured (first render, tests) behaves like a narrow canvas: plain flow.
  const stacked = width < STACK_BREAKPOINT
  const colWidth = width > 0 ? (width - GRID_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS : 0
  const stepX = colWidth + GRID_GAP
  const stepY = ROW_HEIGHT + GRID_GAP
  const rectOf = useCallback((item: GridItem) => ({
    left: item.x * stepX,
    top: item.y * stepY,
    width: item.w * colWidth + (item.w - 1) * GRID_GAP,
    height: item.h * ROW_HEIGHT + (item.h - 1) * GRID_GAP,
  }), [colWidth, stepX, stepY])

  const layout = interaction?.active ? interaction.preview : external ?? items
  const positions = useMemo(() => new Map(layout.map((item) => [item.id, item])), [layout])
  const rows = layoutRows(layout)
  const canvasRows = isEditing && !stacked ? Math.max(rows + 3, 8) : rows
  const canvasHeight = canvasRows > 0 ? canvasRows * stepY - GRID_GAP : 0

  const updateInteraction = useCallback((next: Interaction | null) => {
    interactionRef.current = next
    setInteraction(next)
  }, [])

  // ---- pointer drag / resize -------------------------------------------------
  const processPointer = useCallback(() => {
    frameRef.current = undefined
    const current = interactionRef.current
    const pointer = pointerRef.current
    const node = containerRef.current
    if (!current || !pointer || !node) return
    const distance = Math.hypot(pointer.x - current.startX, pointer.y - current.startY)
    if (!current.active && distance < DRAG_THRESHOLD) return
    const bounds = node.getBoundingClientRect()
    const item = itemsRef.current.find((entry) => entry.id === current.id)
    if (!item) return
    let next: Interaction
    if (current.kind === 'drag') {
      const size = rectOf(item)
      const left = Math.min(Math.max(0, pointer.x - bounds.left - current.offsetX), Math.max(0, width - size.width))
      const top = Math.max(0, pointer.y - bounds.top - current.offsetY)
      const x = Math.round(left / stepX)
      const y = Math.round(top / stepY)
      const changed = x !== current.target.a || y !== current.target.b || !current.active
      next = { ...current, active: true, left, top, target: { a: x, b: y }, preview: changed ? moveItem(itemsRef.current, item.id, x, y, GRID_COLUMNS) : current.preview }
    } else {
      const limits = limitsFor(item.id)
      const minPx = { width: colWidth, height: ROW_HEIGHT }
      const widthPx = Math.max(minPx.width, current.offsetX + pointer.x - current.startX)
      const heightPx = Math.max(minPx.height, current.offsetY + pointer.y - current.startY)
      const snapped = clampSize(Math.round((widthPx + GRID_GAP) / stepX), Math.round((heightPx + GRID_GAP) / stepY), { ...limits, maxW: Math.min(limits.maxW, GRID_COLUMNS - item.x) }, GRID_COLUMNS)
      const changed = snapped.w !== current.target.a || snapped.h !== current.target.b || !current.active
      next = { ...current, active: true, width: widthPx, height: heightPx, target: { a: snapped.w, b: snapped.h }, preview: changed ? resizeItem(itemsRef.current, item.id, snapped.w, snapped.h, GRID_COLUMNS) : current.preview }
    }
    updateInteraction(next)
  }, [colWidth, limitsFor, rectOf, stepX, stepY, updateInteraction, width])

  const schedule = useCallback(() => {
    if (frameRef.current === undefined) frameRef.current = window.requestAnimationFrame(processPointer)
  }, [processPointer])

  // Scroll the page while a widget is held near the top/bottom edge.
  const autoScroll = useCallback(() => {
    scrollFrameRef.current = undefined
    const pointer = pointerRef.current
    if (!interactionRef.current?.active || !pointer) return
    const scroller = scrollParentOf(containerRef.current)
    const top = scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top
    const bottom = scroller === document.scrollingElement ? window.innerHeight : scroller.getBoundingClientRect().bottom
    const speed = pointer.y < top + EDGE_SCROLL_ZONE ? -(top + EDGE_SCROLL_ZONE - pointer.y) / 4 : pointer.y > bottom - EDGE_SCROLL_ZONE ? (pointer.y - bottom + EDGE_SCROLL_ZONE) / 4 : 0
    if (!speed) return
    scroller.scrollBy(0, speed)
    schedule()
    scrollFrameRef.current = window.requestAnimationFrame(autoScroll)
  }, [schedule])

  const startInteraction = useCallback((kind: Interaction['kind'], item: GridItem, pointerId: number, clientX: number, clientY: number) => {
    const node = containerRef.current
    if (!node) return
    const bounds = node.getBoundingClientRect()
    const rect = rectOf(item)
    pointerRef.current = { x: clientX, y: clientY }
    updateInteraction({
      kind,
      id: item.id,
      pointerId,
      startX: clientX,
      startY: clientY,
      offsetX: kind === 'drag' ? clientX - bounds.left - rect.left : rect.width,
      offsetY: kind === 'drag' ? clientY - bounds.top - rect.top : rect.height,
      active: false,
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      target: kind === 'drag' ? { a: item.x, b: item.y } : { a: item.w, b: item.h },
      preview: itemsRef.current,
    })
  }, [rectOf, updateInteraction])

  const cancelLongPress = useCallback(() => {
    if (longPressRef.current) window.clearTimeout(longPressRef.current.timer)
    longPressRef.current = null
  }, [])

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const pending = longPressRef.current
      if (pending && pending.pointerId === event.pointerId && Math.hypot(event.clientX - pending.x, event.clientY - pending.y) > 8) cancelLongPress()
      const current = interactionRef.current
      if (!current || current.pointerId !== event.pointerId) return
      if (current.active) event.preventDefault()
      pointerRef.current = { x: event.clientX, y: event.clientY }
      schedule()
      if (current.active && scrollFrameRef.current === undefined) scrollFrameRef.current = window.requestAnimationFrame(autoScroll)
    }
    const end = (event: PointerEvent) => {
      if (longPressRef.current?.pointerId === event.pointerId) cancelLongPress()
      const current = interactionRef.current
      if (!current || current.pointerId !== event.pointerId) return
      if (frameRef.current !== undefined) { window.cancelAnimationFrame(frameRef.current); frameRef.current = undefined }
      processPointer()
      const finished = interactionRef.current ?? current
      updateInteraction(null)
      if (event.type === 'pointercancel') return
      if (finished.active) {
        const before = itemsRef.current.find((item) => item.id === finished.id)
        const after = finished.preview.find((item) => item.id === finished.id)
        if (before && after && (before.x !== after.x || before.y !== after.y || before.w !== after.w || before.h !== after.h)) {
          onLayoutChange(finished.preview)
          setAnnouncement(i18n.t('today.canvas.position', { label: labelFor(finished.id), row: after.y + 1, col: after.x + 1, w: after.w, h: after.h }))
        }
      } else if (finished.kind === 'drag' && hasSettings(finished.id)) {
        // A tap (no movement) on a jiggling widget opens its settings.
        onOpenSettings(finished.id)
      }
    }
    // Once a widget is held, touch moves drag it instead of panning the page.
    const touchMove = (event: TouchEvent) => { if (interactionRef.current) event.preventDefault() }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    window.addEventListener('touchmove', touchMove, { passive: false })
    return () => {
      window.removeEventListener('touchmove', touchMove)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
    }
  }, [autoScroll, cancelLongPress, hasSettings, labelFor, onLayoutChange, onOpenSettings, processPointer, schedule, updateInteraction])

  useEffect(() => () => {
    cancelLongPress()
    if (frameRef.current !== undefined) window.cancelAnimationFrame(frameRef.current)
    if (scrollFrameRef.current !== undefined) window.cancelAnimationFrame(scrollFrameRef.current)
  }, [cancelLongPress])

  const onItemPointerDown = (event: ReactPointerEvent, item: GridItem) => {
    if (event.button !== 0 || interactionRef.current) return
    const target = event.target as Element
    if (target.closest('[data-today-control]')) return
    if (!isEditing) {
      // iOS-style: press and hold anywhere that is not a control to start arranging.
      if (target.closest(INTERACTIVE)) return
      const { pointerId, clientX, clientY } = event
      cancelLongPress()
      longPressRef.current = {
        id: item.id,
        pointerId,
        x: clientX,
        y: clientY,
        timer: window.setTimeout(() => {
          longPressRef.current = null
          onRequestEdit()
          if (!stacked) startInteraction('drag', item, pointerId, clientX, clientY)
        }, LONG_PRESS_MS),
      }
      return
    }
    if (stacked) return
    event.preventDefault()
    startInteraction('drag', item, event.pointerId, event.clientX, event.clientY)
  }

  const onResizePointerDown = (event: ReactPointerEvent, item: GridItem) => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    startInteraction('resize', item, event.pointerId, event.clientX, event.clientY)
  }

  // ---- keyboard arranging --------------------------------------------------
  const onItemKeyDown = (event: ReactKeyboardEvent, item: GridItem) => {
    if (!isEditing || event.target !== event.currentTarget) return
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key]
    if (step) {
      event.preventDefault()
      let next: GridItem[]
      if (stacked) {
        if (!step[1]) return
        next = shiftInReadingOrder(items, item.id, step[1] as -1 | 1, GRID_COLUMNS)
      } else if (event.shiftKey) {
        const limits = limitsFor(item.id)
        const size = clampSize(item.w + step[0], item.h + step[1], { ...limits, maxW: Math.min(limits.maxW, GRID_COLUMNS - item.x) }, GRID_COLUMNS)
        next = resizeItem(items, item.id, size.w, size.h, GRID_COLUMNS)
      } else if (step[1]) {
        next = nudgeVertical(items, item.id, step[1] as -1 | 1, GRID_COLUMNS)
      } else {
        next = moveItem(items, item.id, item.x + step[0], item.y, GRID_COLUMNS)
      }
      const moved = next.find((entry) => entry.id === item.id)
      const changed = next.some((entry) => {
        const before = items.find((original) => original.id === entry.id)
        return !before || before.x !== entry.x || before.y !== entry.y || before.w !== entry.w || before.h !== entry.h
      })
      if (!changed) return
      onLayoutChange(next)
      if (moved) setAnnouncement(i18n.t('today.canvas.position', { label: labelFor(item.id), row: moved.y + 1, col: moved.x + 1, w: moved.w, h: moved.h }))
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault()
      onRemove(item.id)
    } else if (event.key === 'Enter' && hasSettings(item.id)) {
      event.preventDefault()
      onOpenSettings(item.id)
    }
  }

  // ---- drops from the widget library ----------------------------------------
  const externalCell = useCallback((clientX: number, clientY: number, size: { w: number; h: number }) => {
    const node = containerRef.current
    if (!node || stacked || colWidth <= 0) return null
    const bounds = node.getBoundingClientRect()
    const bottom = Math.max(bounds.bottom, bounds.top + canvasHeight) + stepY * 2
    if (clientX < bounds.left || clientX > bounds.right || clientY < bounds.top - stepY || clientY > bottom) return null
    const w = Math.min(size.w, GRID_COLUMNS)
    const pixelWidth = w * colWidth + (w - 1) * GRID_GAP
    const x = Math.round((clientX - bounds.left - pixelWidth / 2) / stepX)
    const y = Math.round((clientY - bounds.top - ROW_HEIGHT / 2) / stepY)
    return placeItem(itemsRef.current, { id: EXTERNAL_ID, x: Math.min(Math.max(0, x), GRID_COLUMNS - w), y: Math.max(0, y), w, h: size.h })
  }, [canvasHeight, colWidth, stacked, stepX, stepY])

  useImperativeHandle(ref, () => ({
    previewExternal: (clientX, clientY, size) => {
      const preview = externalCell(clientX, clientY, size)
      setExternal(preview)
      return Boolean(preview)
    },
    dropExternal: (clientX, clientY, size) => {
      const preview = externalCell(clientX, clientY, size)
      setExternal(null)
      const placed = preview?.find((item) => item.id === EXTERNAL_ID)
      return placed ? { x: placed.x, y: placed.y } : null
    },
    clearExternal: () => setExternal(null),
  }), [externalCell])

  // ---- render ----------------------------------------------------------------
  const placeholder = interaction?.active
    ? positions.get(interaction.id)
    : external?.find((item) => item.id === EXTERNAL_ID)
  const ordered = stacked ? sortByPosition(items) : items

  const controls = (item: GridItem, index: number) => isEditing && <>
    <button type="button" className="today-widget-remove" data-today-control onClick={() => onRemove(item.id)} aria-label={t('today.canvas.removeLabel', { label: labelFor(item.id) })} title={t('today.canvas.remove')}><X size={13} strokeWidth={3} /></button>
    {hasSettings(item.id) && <button type="button" className="today-widget-gear" data-today-control onClick={() => onOpenSettings(item.id)} aria-label={t('today.canvas.settingsLabel', { label: labelFor(item.id) })} title={t('today.canvas.settings')}><Settings2 size={13} /></button>}
    {stacked ? <span className="today-widget-order" data-today-control>
      <button type="button" onClick={() => onLayoutChange(shiftInReadingOrder(items, item.id, -1, GRID_COLUMNS))} disabled={index === 0} aria-label={t('today.canvas.up', { label: labelFor(item.id) })}><ArrowUp size={14} /></button>
      <button type="button" onClick={() => onLayoutChange(shiftInReadingOrder(items, item.id, 1, GRID_COLUMNS))} disabled={index === ordered.length - 1} aria-label={t('today.canvas.down', { label: labelFor(item.id) })}><ArrowDown size={14} /></button>
    </span> : <span className="today-widget-resize" data-today-control onPointerDown={(event) => onResizePointerDown(event, item)} aria-hidden title={t('today.canvas.resize')} />}
  </>

  return (
    <div
      ref={containerRef}
      className={`today-canvas${isEditing ? ' is-editing' : ''}${stacked ? ' is-stacked' : ''}${interaction?.active ? ' is-interacting' : ''}`}
      style={stacked ? undefined : { height: canvasHeight }}
      role="list"
      aria-label={t('today.canvas.aria')}
    >
      {isEditing && !stacked && width > 0 && <div className="today-grid-overlay" aria-hidden style={{ '--today-cols': GRID_COLUMNS, '--today-row': `${ROW_HEIGHT}px`, '--today-gap': `${GRID_GAP}px` } as CSSProperties}>
        {Array.from({ length: canvasRows * GRID_COLUMNS }, (_, index) => <span key={index} />)}
      </div>}
      {placeholder && !stacked && <div className="today-drop-placeholder" aria-hidden style={(() => { const rect = rectOf(placeholder); return { transform: `translate3d(${rect.left}px, ${rect.top}px, 0)`, width: rect.width, height: rect.height } })()} />}
      {ordered.map((item, index) => {
        const position = positions.get(item.id) ?? item
        const isActive = interaction?.active && interaction.id === item.id
        let style: CSSProperties | undefined
        if (stacked) {
          // Narrow screens: size to content, capped at the widget's cell height (lists scroll inside).
          style = { maxHeight: item.h * ROW_HEIGHT + (item.h - 1) * GRID_GAP, '--today-jiggle-delay': `${(index % 4) * -0.11}s` } as CSSProperties
        } else {
          const rect = rectOf(isActive && interaction?.kind === 'resize' ? item : position)
          const left = isActive && interaction?.kind === 'drag' ? interaction.left : rect.left
          const top = isActive && interaction?.kind === 'drag' ? interaction.top : rect.top
          style = {
            transform: `translate3d(${left}px, ${top}px, 0)`,
            width: isActive && interaction?.kind === 'resize' ? interaction.width : rect.width,
            height: isActive && interaction?.kind === 'resize' ? interaction.height : rect.height,
            '--today-jiggle-delay': `${(index % 4) * -0.11}s`,
          } as CSSProperties
        }
        return (
          <div
            key={item.id}
            role="listitem"
            className={`today-widget-slot${isActive ? ` is-${interaction?.kind}` : ''}`}
            style={style}
            data-widget-id={item.id}
            tabIndex={isEditing ? 0 : undefined}
            aria-label={isEditing ? t('today.canvas.editHint', { label: labelFor(item.id) }) : undefined}
            onPointerDown={(event) => onItemPointerDown(event, item)}
            onKeyDown={(event) => onItemKeyDown(event, item)}
            onContextMenu={(event) => { if (isEditing || longPressRef.current) event.preventDefault() }}
          >
            <div className="today-widget-card">
              {renderItem(item.id)}
              {isEditing && <div className="today-widget-shield" aria-hidden />}
            </div>
            {controls(item, index)}
          </div>
        )
      })}
      <div className="sr-only" aria-live="polite">{announcement}</div>
    </div>
  )
})
