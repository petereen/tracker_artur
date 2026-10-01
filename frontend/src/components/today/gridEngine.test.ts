import { describe, expect, it } from 'vitest'
import {
  clampToGrid,
  collides,
  compact,
  findFreeSpot,
  layoutRows,
  moveItem,
  normalizeLayout,
  nudgeVertical,
  resizeItem,
  shiftInReadingOrder,
  type GridItem,
} from './gridEngine'

const item = (id: string, x: number, y: number, w: number, h: number): GridItem => ({ id, x, y, w, h })
const byId = (items: GridItem[]) => Object.fromEntries(items.map((entry) => [entry.id, entry]))
const noOverlaps = (items: GridItem[]) => items.every((a) => items.every((b) => !collides(a, b)))

describe('gridEngine', () => {
  it('detects overlap but not touching edges', () => {
    expect(collides(item('a', 0, 0, 2, 2), item('b', 1, 1, 2, 2))).toBe(true)
    expect(collides(item('a', 0, 0, 2, 2), item('b', 2, 0, 2, 2))).toBe(false)
    expect(collides(item('a', 0, 0, 2, 2), item('a', 0, 0, 2, 2))).toBe(false)
  })

  it('clamps items into the grid', () => {
    expect(clampToGrid(item('a', 11, -3, 4, 0), 12)).toEqual(item('a', 8, 0, 4, 1))
    expect(clampToGrid(item('a', 0, 0, 20, 2), 12)).toEqual(item('a', 0, 0, 12, 2))
  })

  it('floats items up with vertical gravity', () => {
    const result = byId(compact([item('a', 0, 4, 6, 2), item('b', 0, 9, 6, 3), item('c', 6, 7, 6, 1)]))
    expect(result.a.y).toBe(0)
    expect(result.b.y).toBe(2)
    expect(result.c.y).toBe(0)
  })

  it('pushes colliding items down when a widget moves onto them', () => {
    const layout = [item('a', 0, 0, 6, 4), item('b', 6, 0, 6, 4), item('c', 0, 4, 6, 2)]
    const result = moveItem(layout, 'c', 3, 0, 12)
    expect(noOverlaps(result)).toBe(true)
    expect(byId(result).c).toMatchObject({ x: 3, y: 0 })
  })

  it('swaps vertical neighbours when a widget is dragged down past another', () => {
    const layout = [item('a', 0, 0, 12, 2), item('b', 0, 2, 12, 2)]
    const result = byId(moveItem(layout, 'a', 0, 2, 12))
    expect(result.b.y).toBe(0)
    expect(result.a.y).toBe(2)
  })

  it('resizes within column bounds and keeps the layout overlap-free', () => {
    const layout = [item('a', 8, 0, 4, 2), item('b', 0, 2, 12, 2)]
    const result = resizeItem(layout, 'a', 10, 4, 12)
    expect(byId(result).a).toMatchObject({ x: 8, w: 4, h: 4 })
    expect(byId(result).b.y).toBe(4)
    expect(noOverlaps(result)).toBe(true)
  })

  it('repairs overlapping stored layouts', () => {
    const result = normalizeLayout([item('a', 0, 0, 6, 3), item('b', 2, 1, 6, 3), item('c', 14, 2, 3, 1)], 12)
    expect(noOverlaps(result)).toBe(true)
    expect(byId(result).c.x).toBe(9)
    expect(layoutRows(result)).toBe(6)
  })

  it('finds the first free slot for a new widget', () => {
    const layout = [item('a', 0, 0, 8, 2), item('b', 0, 2, 12, 2)]
    expect(findFreeSpot(layout, 4, 2, 12)).toEqual({ x: 8, y: 0 })
    expect(findFreeSpot(layout, 6, 2, 12)).toEqual({ x: 0, y: 4 })
    expect(findFreeSpot([], 4, 2, 12)).toEqual({ x: 0, y: 0 })
  })

  it('reorders in reading order for keyboard and narrow screens', () => {
    const layout = [item('a', 0, 0, 12, 1), item('b', 0, 1, 12, 3), item('c', 0, 4, 12, 2)]
    const up = byId(shiftInReadingOrder(layout, 'c', -1, 12))
    expect(up.c.y).toBeLessThan(up.b.y)
    const down = byId(shiftInReadingOrder(layout, 'a', 1, 12))
    expect(down.b.y).toBeLessThan(down.a.y)
    expect(shiftInReadingOrder(layout, 'a', -1, 12)).toEqual(layout)
    const row = byId(shiftInReadingOrder([item('a', 0, 0, 4, 2), item('b', 4, 0, 8, 2)], 'a', 1, 12))
    expect(row.b.x).toBe(0)
    expect(row.a).toMatchObject({ x: 8, y: 0 })
  })

  it('nudges vertically past the nearest neighbour sharing columns', () => {
    const layout = [item('a', 0, 0, 6, 2), item('b', 0, 2, 12, 3), item('c', 6, 0, 6, 1)]
    const down = byId(nudgeVertical(layout, 'a', 1, 12))
    expect(down.b.y).toBeLessThan(down.a.y)
    const up = byId(nudgeVertical(Object.values(down), 'a', -1, 12))
    expect(up.a.y).toBeLessThan(up.b.y)
    expect(noOverlaps(Object.values(up))).toBe(true)
  })
})
