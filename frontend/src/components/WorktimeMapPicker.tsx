import { useEffect, useMemo, useRef, useState } from 'react'

const TILE_SIZE = 256
const ZOOM = 16
const DEFAULT_CENTER = { latitude: 47.9184, longitude: 106.9177 }

interface Point {
  latitude: number
  longitude: number
}

interface WorktimeMapPickerProps {
  latitude: number | null
  longitude: number | null
  radiusMeters: number
  disabled?: boolean
  onChange: (point: Point) => void
}

function project(point: Point, zoom = ZOOM) {
  const scale = TILE_SIZE * 2 ** zoom
  const latitude = Math.max(-85.05112878, Math.min(85.05112878, point.latitude))
  const sin = Math.sin((latitude * Math.PI) / 180)
  return {
    x: ((point.longitude + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  }
}

function unproject(x: number, y: number, zoom = ZOOM): Point {
  const scale = TILE_SIZE * 2 ** zoom
  const longitude = (x / scale) * 360 - 180
  const latitude = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / scale))) * 180) / Math.PI
  return { latitude, longitude }
}

function metersPerPixel(latitude: number) {
  return (40_075_016.686 * Math.cos((latitude * Math.PI) / 180)) / (TILE_SIZE * 2 ** ZOOM)
}

export function WorktimeMapPicker({ latitude, longitude, radiusMeters, disabled = false, onChange }: WorktimeMapPickerProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const [mapSize, setMapSize] = useState({ width: 640, height: 320 })
  const [viewCenter, setViewCenter] = useState<Point>(() => ({
    latitude: latitude ?? DEFAULT_CENTER.latitude,
    longitude: longitude ?? DEFAULT_CENTER.longitude,
  }))
  const [dragging, setDragging] = useState(false)
  const selected = latitude != null && longitude != null ? { latitude, longitude } : null
  const centerWorld = useMemo(() => project(viewCenter), [viewCenter])

  useEffect(() => {
    if (latitude == null || longitude == null || dragging) return
    setViewCenter({ latitude, longitude })
  }, [dragging, latitude, longitude])

  useEffect(() => {
    const element = mapRef.current
    if (!element) return
    const updateSize = () => {
      const rect = element.getBoundingClientRect()
      if (rect.width && rect.height) setMapSize({ width: rect.width, height: rect.height })
    }
    updateSize()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(updateSize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const viewportLeft = centerWorld.x - mapSize.width / 2
  const viewportTop = centerWorld.y - mapSize.height / 2
  const tileCount = 2 ** ZOOM
  const tiles = useMemo(() => {
    const firstX = Math.floor(viewportLeft / TILE_SIZE) - 1
    const lastX = Math.ceil((viewportLeft + mapSize.width) / TILE_SIZE) + 1
    const firstY = Math.floor(viewportTop / TILE_SIZE) - 1
    const lastY = Math.ceil((viewportTop + mapSize.height) / TILE_SIZE) + 1
    return Array.from({ length: lastX - firstX + 1 }, (_, xIndex) => Array.from({ length: lastY - firstY + 1 }, (_, yIndex) => {
      const tileX = firstX + xIndex
      const tileY = firstY + yIndex
      return {
        key: `${tileX}:${tileY}`,
        x: tileX * TILE_SIZE - viewportLeft,
        y: tileY * TILE_SIZE - viewportTop,
        tileX: ((tileX % tileCount) + tileCount) % tileCount,
        tileY,
      }
    })).flat().filter((tile) => tile.tileY >= 0 && tile.tileY < tileCount)
  }, [mapSize.height, mapSize.width, tileCount, viewportLeft, viewportTop])

  const pointToScreen = (point: Point) => {
    const world = project(point)
    return { x: world.x - viewportLeft, y: world.y - viewportTop }
  }

  const screenToPoint = (clientX: number, clientY: number) => {
    const rect = mapRef.current?.getBoundingClientRect()
    if (!rect) return null
    return unproject(viewportLeft + clientX - rect.left, viewportTop + clientY - rect.top)
  }

  const choosePoint = (clientX: number, clientY: number) => {
    const point = screenToPoint(clientX, clientY)
    if (!point) return
    setViewCenter(point)
    onChange(point)
  }

  useEffect(() => {
    if (!dragging) return
    const handleMove = (event: PointerEvent) => {
      const point = screenToPoint(event.clientX, event.clientY)
      if (point) onChange(point)
    }
    const handleUp = () => setDragging(false)
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp, { once: true })
    return () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
    }
  }, [dragging, viewportLeft, viewportTop])

  const selectedScreen = selected ? pointToScreen(selected) : { x: mapSize.width / 2, y: mapSize.height / 2 }
  const radiusPixels = Math.max(10, radiusMeters / metersPerPixel(viewCenter.latitude))

  return <div className={`worktime-map-picker ${disabled ? 'disabled' : ''}`}>
    <div
      className="worktime-map"
      ref={mapRef}
      onClick={(event) => { if (!disabled && !dragging) choosePoint(event.clientX, event.clientY) }}
      role="application"
      aria-label="Оффисын байршил сонгох газрын зураг"
    >
      {tiles.map((tile) => <img key={tile.key} className="worktime-map-tile" src={`https://tile.openstreetmap.org/${ZOOM}/${tile.tileX}/${tile.tileY}.png`} alt="" aria-hidden="true" style={{ left: tile.x, top: tile.y }} />)}
      {selected && <div className="worktime-geofence-circle" style={{ left: selectedScreen.x - radiusPixels, top: selectedScreen.y - radiusPixels, width: radiusPixels * 2, height: radiusPixels * 2 }} aria-hidden="true" />}
      <button
        type="button"
        className={`worktime-map-pin ${dragging ? 'dragging' : ''}`}
        style={{ left: selectedScreen.x, top: selectedScreen.y }}
        disabled={disabled}
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => { event.stopPropagation(); event.preventDefault(); if (!disabled) setDragging(true) }}
        aria-label="Оффисын байршлын цэгийг зөөх"
      ><span /></button>
      <span className="worktime-map-attribution">© OpenStreetMap contributors</span>
      {!selected && <span className="worktime-map-hint">Газрын зураг дээр дарж оффисын цэгийг сонгоно уу</span>}
    </div>
  </div>
}

