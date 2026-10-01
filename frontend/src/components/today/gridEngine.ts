/**
 * Grid engine for the "Today" canvas.
 *
 * Pure functions over cell rectangles: no React, no DOM, no knowledge of
 * widgets. Layouts use vertical gravity (like an iOS home screen): after any
 * change items float up until they touch another item, and collisions push
 * the other item down (or swap it above the moved one when the freed space
 * fits it).
 */

export interface GridRect {
  x: number
  y: number
  w: number
  h: number
}

export interface GridItem extends GridRect {
  id: string
}

export interface SizeLimits {
  minW: number
  minH: number
  maxW: number
  maxH: number
}

export const collides = (a: GridItem, b: GridItem) =>
  a.id !== b.id && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h

export const sortByPosition = <T extends GridItem>(items: readonly T[]) =>
  [...items].sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id))

const clampNumber = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

export function clampSize(w: number, h: number, limits: SizeLimits, cols: number) {
  return {
    w: clampNumber(Math.round(w), Math.max(1, limits.minW), Math.min(cols, limits.maxW)),
    h: clampNumber(Math.round(h), Math.max(1, limits.minH), limits.maxH),
  }
}

/** Keeps an item inside the grid: whole cells, at least 1×1, never past the last column. */
export function clampToGrid<T extends GridItem>(item: T, cols: number): T {
  const w = clampNumber(Math.round(item.w) || 1, 1, cols)
  const h = Math.max(1, Math.round(item.h) || 1)
  return {
    ...item,
    w,
    h,
    x: clampNumber(Math.round(item.x) || 0, 0, cols - w),
    y: Math.max(0, Math.round(item.y) || 0),
  }
}

/** Vertical gravity: every item floats up until it touches another item or the top. */
export function compact<T extends GridItem>(items: readonly T[]): T[] {
  const placed: T[] = []
  for (const item of sortByPosition(items)) {
    let y = item.y
    while (y > 0 && !placed.some((other) => collides({ ...item, y: y - 1 }, other))) y -= 1
    placed.push(y === item.y ? item : { ...item, y })
  }
  return placed
}

/**
 * Puts `moved` exactly where it is and resolves every collision around it,
 * then compacts. An item hit by `moved` first tries the space just above it
 * (so dragging a widget down past a neighbour swaps them); otherwise it is
 * pushed down until it fits.
 */
export function placeItem<T extends GridItem>(items: readonly T[], moved: T): T[] {
  const placed: T[] = [moved]
  for (const item of sortByPosition(items.filter((entry) => entry.id !== moved.id))) {
    let candidate = item
    if (placed.some((other) => collides(candidate, other))) {
      if (collides(candidate, moved)) {
        const above = { ...candidate, y: moved.y - candidate.h }
        if (above.y >= 0 && !placed.some((other) => collides(above, other))) candidate = above
      }
      while (placed.some((other) => collides(candidate, other))) candidate = { ...candidate, y: candidate.y + 1 }
    }
    placed.push(candidate)
  }
  return compact(placed)
}

export function moveItem<T extends GridItem>(items: readonly T[], id: string, x: number, y: number, cols: number): T[] {
  const item = items.find((entry) => entry.id === id)
  if (!item) return [...items]
  return placeItem(items, clampToGrid({ ...item, x, y }, cols))
}

export function resizeItem<T extends GridItem>(items: readonly T[], id: string, w: number, h: number, cols: number): T[] {
  const item = items.find((entry) => entry.id === id)
  if (!item) return [...items]
  const width = clampNumber(Math.round(w), 1, cols - item.x)
  return placeItem(items, clampToGrid({ ...item, w: width, h }, cols))
}

/** Repairs any stored layout: clamps to the grid, removes overlaps (top-left wins), compacts. */
export function normalizeLayout<T extends GridItem>(items: readonly T[], cols: number): T[] {
  const placed: T[] = []
  for (const item of sortByPosition(items.map((entry) => clampToGrid(entry, cols)))) {
    let candidate = item
    while (placed.some((other) => collides(candidate, other))) candidate = { ...candidate, y: candidate.y + 1 }
    placed.push(candidate)
  }
  return compact(placed)
}

/** First top-left slot (row by row) where a w×h item fits without overlapping anything. */
export function findFreeSpot(items: readonly GridItem[], w: number, h: number, cols: number) {
  const width = clampNumber(w, 1, cols)
  const bottom = layoutRows(items)
  for (let y = 0; y <= bottom; y += 1) {
    for (let x = 0; x + width <= cols; x += 1) {
      const probe = { id: '\u0000probe', x, y, w: width, h }
      if (!items.some((item) => collides(probe, item))) return { x, y }
    }
  }
  return { x: 0, y: bottom }
}

/** Number of rows the layout occupies. */
export const layoutRows = (items: readonly GridItem[]) => items.reduce((rows, item) => Math.max(rows, item.y + item.h), 0)

/** Swaps an item with its neighbour in reading order (used where dragging is unavailable). */
export function shiftInReadingOrder<T extends GridItem>(items: readonly T[], id: string, direction: -1 | 1, cols: number): T[] {
  const ordered = sortByPosition(items)
  const index = ordered.findIndex((item) => item.id === id)
  const target = ordered[index + direction]
  if (index < 0 || !target) return [...items]
  const current = ordered[index]
  if (current.y === target.y) {
    // Same row: swap horizontally, keeping the pair's outer edges.
    const [left, right] = direction > 0 ? [current, target] : [target, current]
    const swapped = items.map((item) =>
      item.id === right.id ? { ...item, x: left.x } : item.id === left.id ? { ...item, x: right.x + right.w - left.w } : item,
    )
    return normalizeLayout(swapped, cols)
  }
  // Different rows: land on the neighbour's top edge (before it) or just below it (after it).
  const moved = clampToGrid({ ...current, x: target.x, y: direction < 0 ? target.y : target.y + target.h }, cols)
  return placeItem(items, moved)
}

/**
 * Keyboard up/down under gravity: hop over the nearest widget that shares
 * columns in that direction (a plain one-row nudge would just float back).
 */
export function nudgeVertical<T extends GridItem>(items: readonly T[], id: string, direction: -1 | 1, cols: number): T[] {
  const item = items.find((entry) => entry.id === id)
  if (!item) return [...items]
  const sharesColumns = (other: GridItem) => other.id !== id && other.x < item.x + item.w && item.x < other.x + other.w
  if (direction > 0) {
    const below = items.filter((other) => sharesColumns(other) && other.y >= item.y + item.h).sort((a, b) => a.y - b.y)[0]
    return below ? moveItem(items, id, item.x, below.y + below.h, cols) : [...items]
  }
  const above = items.filter((other) => sharesColumns(other) && other.y + other.h <= item.y).sort((a, b) => b.y + b.h - (a.y + a.h))[0]
  return moveItem(items, id, item.x, above ? above.y : item.y - 1, cols)
}
