import { createRef } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GridItem } from './gridEngine'
import { TodayCanvas, type TodayCanvasHandle } from './TodayCanvas'

// 1188px wide → 12 columns of 88px + 11 gaps of 12px: one column step = 100px, one row step = 56px.
const WIDTH = 1188

const items: GridItem[] = [
  { id: 'a', x: 0, y: 0, w: 4, h: 2 },
  { id: 'b', x: 4, y: 0, w: 4, h: 2 },
]

function setup(overrides: { items?: GridItem[]; isEditing?: boolean } = {}) {
  const props = {
    items,
    isEditing: true,
    onRequestEdit: vi.fn(),
    onLayoutChange: vi.fn<(next: GridItem[]) => void>(),
    onRemove: vi.fn<(id: string) => void>(),
    onOpenSettings: vi.fn<(id: string) => void>(),
    hasSettings: () => true,
    limitsFor: () => ({ minW: 2, minH: 1, maxW: 12, maxH: 10 }),
    labelFor: (id: string) => `Widget ${id}`,
    renderItem: (id: string) => <section>Content {id}</section>,
    ...overrides,
  }
  const ref = createRef<TodayCanvasHandle>()
  const view = render(<TodayCanvas ref={ref} {...props} />)
  return { ...view, props, ref }
}

const slot = (id: string) => document.querySelector(`[data-widget-id="${id}"]`) as HTMLElement
const nextFrame = () => act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))

describe('TodayCanvas', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      constructor(private callback: ResizeObserverCallback) {}
      observe() { this.callback([{ contentRect: { width: WIDTH } } as ResizeObserverEntry], this as unknown as ResizeObserver) }
      unobserve() {}
      disconnect() {}
    })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: WIDTH, bottom: 600, width: WIDTH, height: 600, x: 0, y: 0, toJSON: () => ({}) })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('positions widgets with GPU transforms and shows the slot grid while editing', () => {
    const { container } = setup()
    expect(slot('b').style.transform).toBe('translate3d(400px, 0px, 0)')
    expect(slot('a').style.width).toBe('388px')
    expect(container.querySelector('.today-grid-overlay')).toBeInTheDocument()
    expect(container.querySelector('.today-canvas.is-stacked')).not.toBeInTheDocument()
  })

  it('drags a widget to a new cell with a live placeholder and commits on drop', async () => {
    const { container, props } = setup()
    fireEvent.pointerDown(slot('a'), { button: 0, pointerId: 1, clientX: 50, clientY: 20 })
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 850, clientY: 20 })
    await nextFrame()
    expect(container.querySelector('.today-drop-placeholder')).toBeInTheDocument()
    expect(slot('a')).toHaveClass('is-drag')
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 850, clientY: 20 })
    expect(props.onLayoutChange).toHaveBeenCalledTimes(1)
    const next = props.onLayoutChange.mock.calls[0][0] as GridItem[]
    expect(next.find((item) => item.id === 'a')).toMatchObject({ x: 8, y: 0 })
    expect(next.find((item) => item.id === 'b')).toMatchObject({ x: 4, y: 0 })
  })

  it('opens settings when a jiggling widget is tapped without moving', () => {
    const { props } = setup()
    fireEvent.pointerDown(slot('b'), { button: 0, pointerId: 2, clientX: 450, clientY: 20 })
    fireEvent.pointerUp(window, { pointerId: 2, clientX: 451, clientY: 20 })
    expect(props.onOpenSettings).toHaveBeenCalledWith('b')
    expect(props.onLayoutChange).not.toHaveBeenCalled()
  })

  it('resizes from the corner handle in whole cells', async () => {
    const { props } = setup()
    const handle = slot('a').querySelector('.today-widget-resize') as HTMLElement
    fireEvent.pointerDown(handle, { button: 0, pointerId: 3, clientX: 388, clientY: 100 })
    fireEvent.pointerMove(window, { pointerId: 3, clientX: 388, clientY: 215 })
    await nextFrame()
    fireEvent.pointerUp(window, { pointerId: 3, clientX: 388, clientY: 215 })
    const next = props.onLayoutChange.mock.calls[0][0] as GridItem[]
    expect(next.find((item) => item.id === 'a')).toMatchObject({ w: 4, h: 4 })
  })

  it('enters edit mode on long press outside controls', () => {
    vi.useFakeTimers()
    const { props } = setup({ isEditing: false })
    expect(document.querySelector('.today-widget-remove')).not.toBeInTheDocument()
    fireEvent.pointerDown(screen.getByText('Content a'), { button: 0, pointerId: 4, clientX: 50, clientY: 20 })
    act(() => vi.advanceTimersByTime(500))
    expect(props.onRequestEdit).toHaveBeenCalledTimes(1)
  })

  it('cancels the long press when the pointer moves away (scrolling)', () => {
    vi.useFakeTimers()
    const { props } = setup({ isEditing: false })
    fireEvent.pointerDown(screen.getByText('Content a'), { button: 0, pointerId: 5, clientX: 50, clientY: 20 })
    fireEvent.pointerMove(window, { pointerId: 5, clientX: 50, clientY: 80 })
    act(() => vi.advanceTimersByTime(500))
    expect(props.onRequestEdit).not.toHaveBeenCalled()
  })

  it('removes, moves and resizes with the keyboard', () => {
    const { props } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Widget b хасах' }))
    expect(props.onRemove).toHaveBeenCalledWith('b')
    // Nothing below `a`: gravity would undo the move, so nothing is committed.
    fireEvent.keyDown(slot('a'), { key: 'ArrowDown' })
    expect(props.onLayoutChange).not.toHaveBeenCalled()
    fireEvent.keyDown(slot('a'), { key: 'ArrowRight', shiftKey: true })
    expect((props.onLayoutChange.mock.calls[0][0] as GridItem[]).find((item) => item.id === 'a')).toMatchObject({ w: 5 })
    fireEvent.keyDown(slot('a'), { key: 'ArrowRight' })
    expect((props.onLayoutChange.mock.calls[1][0] as GridItem[]).find((item) => item.id === 'a')).toMatchObject({ x: 1 })
    fireEvent.keyDown(slot('a'), { key: 'Delete' })
    expect(props.onRemove).toHaveBeenCalledWith('a')
  })

  it('hops over the neighbour below on ArrowDown', () => {
    const { props } = setup({ items: [{ id: 'a', x: 0, y: 0, w: 4, h: 2 }, { id: 'c', x: 0, y: 2, w: 6, h: 3 }] })
    fireEvent.keyDown(slot('a'), { key: 'ArrowDown' })
    const next = props.onLayoutChange.mock.calls[0][0] as GridItem[]
    expect(next.find((item) => item.id === 'c')).toMatchObject({ y: 0 })
    expect(next.find((item) => item.id === 'a')).toMatchObject({ y: 3 })
  })

  it('previews and resolves drops coming from the widget library', () => {
    const { ref, container } = setup()
    let accepted = false
    act(() => { accepted = ref.current!.previewExternal(1000, 30, { w: 4, h: 2 }) })
    expect(accepted).toBe(true)
    expect(container.querySelector('.today-drop-placeholder')).toBeInTheDocument()
    let cell: { x: number; y: number } | null = null
    act(() => { cell = ref.current!.dropExternal(1000, 30, { w: 4, h: 2 }) })
    expect(cell).toEqual({ x: 8, y: 0 })
    act(() => { accepted = ref.current!.previewExternal(1000, 5000, { w: 4, h: 2 }) })
    expect(accepted).toBe(false)
  })
})
