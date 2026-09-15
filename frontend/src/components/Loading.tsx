import { Component, lazy, useEffect, useRef, useState, type ComponentType, type ErrorInfo, type ReactNode } from 'react'

export type SkeletonVariant = 'text' | 'card' | 'table-row' | 'calendar-cell' | 'kanban-card' | 'chart' | 'sheet'

export interface QueryRegionState<E = unknown> {
  hasData: boolean
  initialPending: boolean
  refreshing: boolean
  initialError: E | null
  refreshError: E | null
  retry: () => void
}

type QueryLike<T, E> = {
  data: T | undefined
  isLoading: boolean
  isFetching: boolean
  isError?: boolean
  error?: E | null
  refetch?: () => unknown
}

export function toQueryRegionState<T, E>(query: QueryLike<T, E>): QueryRegionState<E> {
  const hasData = query.data !== undefined
  return {
    hasData,
    initialPending: !hasData && query.isLoading,
    refreshing: hasData && query.isFetching,
    initialError: !hasData && query.isError ? query.error ?? null : null,
    refreshError: hasData && query.isError ? query.error ?? null : null,
    retry: () => { void query.refetch?.() },
  }
}

export function combineQueryRegionStates<E>(states: QueryRegionState<E>[]): QueryRegionState<E> {
  const firstError = states.find((state) => state.initialError || state.refreshError)
  const hasData = states.length > 0 && states.every((state) => state.hasData)
  return {
    hasData,
    initialPending: !hasData && states.some((state) => state.initialPending),
    refreshing: hasData && states.some((state) => state.refreshing),
    initialError: !hasData ? firstError?.initialError ?? null : null,
    refreshError: hasData ? firstError?.refreshError ?? null : null,
    retry: () => states.forEach((state) => state.retry()),
  }
}

export function useDelayedLoading(pending: boolean, { delay = 150, minDuration = 300 }: { delay?: number; minDuration?: number } = {}) {
  const [visible, setVisible] = useState(false)
  const visibleRef = useRef(false)
  const shownAtRef = useRef(0)

  useEffect(() => {
    let timer: number | undefined
    if (pending && !visibleRef.current) {
      timer = window.setTimeout(() => {
        visibleRef.current = true
        shownAtRef.current = performance.now()
        setVisible(true)
      }, delay)
    } else if (!pending && visibleRef.current) {
      const elapsed = performance.now() - shownAtRef.current
      timer = window.setTimeout(() => {
        visibleRef.current = false
        setVisible(false)
      }, Math.max(0, minDuration - elapsed))
    }
    return () => { if (timer !== undefined) window.clearTimeout(timer) }
  }, [delay, minDuration, pending])

  return visible
}

export const useDelayedPending = useDelayedLoading

interface RouteLoadErrorBoundaryProps {
  children: ReactNode
}

interface RouteLoadErrorBoundaryState {
  hasError: boolean
}

/**
 * A failed dynamic route import must not turn the whole SPA into a blank page.
 * Reloading also lets the browser pick up a fresh index.html after a deploy
 * when an older tab is holding stale chunk references.
 */
export class RouteLoadErrorBoundary extends Component<RouteLoadErrorBoundaryProps, RouteLoadErrorBoundaryState> {
  state: RouteLoadErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): RouteLoadErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Failed to load a workspace route.', error, info)
  }

  reload = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return <main className="workspace-bootstrap-error" role="alert">
      <div className="query-region-state query-region-error">
        <strong>Энэ хуудсыг ачаалж чадсангүй.</strong>
        <span>Түр зуурын сүлжээний алдаа гарсан байж болно.</span>
        <button className="secondary-action" type="button" onClick={this.reload}>Дахин ачаалах</button>
      </div>
    </main>
  }
}

export function lazyWithPreload<T extends ComponentType<any>>(loader: () => Promise<{ default: T }>, { delay = 150, minDuration = 300 } = {}) {
  let promise: Promise<{ default: T }> | undefined
  const load = () => {
    const startedAt = performance.now()
    promise ||= loader()
    return promise.then((module) => {
      const elapsed = performance.now() - startedAt
      const wait = elapsed > delay ? Math.max(0, delay + minDuration - elapsed) : 0
      return wait ? new Promise<{ default: T }>((resolve) => window.setTimeout(() => resolve(module), wait)) : module
    })
  }
  const component = lazy(load)
  return Object.assign(component, { preload: () => { void (promise ||= loader()) } })
}

function useRetainedSkeleton(visible: boolean, resolved: boolean, exitDuration = 160) {
  const [mounted, setMounted] = useState(false)
  const wasVisible = useRef(false)
  useEffect(() => {
    if (visible) {
      wasVisible.current = true
      setMounted(true)
      return
    }
    if (!resolved || !wasVisible.current) return
    const timer = window.setTimeout(() => {
      wasVisible.current = false
      setMounted(false)
    }, exitDuration)
    return () => window.clearTimeout(timer)
  }, [exitDuration, resolved, visible])
  return mounted
}

export function Skeleton({ variant = 'text', className = '', count = 1 }: { variant?: SkeletonVariant; className?: string; count?: number }) {
  return <div className={`skeleton-group skeleton-${variant} ${className}`.trim()} aria-hidden="true">
    {Array.from({ length: count }, (_, index) => <span className="skeleton" key={index} />)}
  </div>
}

export function SkeletonBox({ className = '', ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span {...props} className={`skeleton-box skeleton ${className}`.trim()} aria-hidden="true" />
}

export function SkeletonText({ lines = 1, className = '' }: { lines?: number; className?: string }) {
  return <span className={`skeleton-text-lines ${className}`.trim()} aria-hidden="true">
    {Array.from({ length: lines }, (_, index) => <span className="skeleton-text-line skeleton" key={index} />)}
  </span>
}

export function SkeletonRow({ columns = 4, className = '' }: { columns?: number; className?: string }) {
  return <div className={`skeleton-row ${className}`.trim()} aria-hidden="true">
    {Array.from({ length: columns }, (_, index) => <span className="skeleton" key={index} />)}
  </div>
}

export function InlinePending({ label = 'Ачаалж байна…', size = 20 }: { label?: string; size?: number }) {
  return <span className="inline-pending" role="status" aria-live="polite" aria-label={label} style={{ '--inline-pending-size': `${size}px` } as React.CSSProperties}>
    <span className="inline-pending-spinner" aria-hidden="true" />
    <span className="sr-only">{label}</span>
  </span>
}

export function QueryRegion<E = unknown>({ state, children, skeleton, empty = false, emptyFallback = null, errorFallback, refreshLabel = 'Шинэчилж байна…', className = '' }: QueryRegionProps<E>) {
  const showLoading = useDelayedLoading(state.initialPending)
  const showRefreshing = useDelayedLoading(state.refreshing, { delay: 250, minDuration: 300 })
  const resolved = !state.initialPending && (state.hasData || state.initialError !== null)
  const retainedSkeleton = useRetainedSkeleton(showLoading, resolved)
  const reserveSkeleton = state.initialPending || showLoading || retainedSkeleton
  const initialError = state.initialError
  const result = initialError !== null
    ? (errorFallback ? errorFallback(initialError, state.retry) : <QueryErrorState onRetry={state.retry} />)
    : empty ? emptyFallback : children

  return <div className={`query-region ${className}`.trim()} aria-busy={reserveSkeleton || state.refreshing}>
    <div className="query-region__layers">
      {reserveSkeleton && <div aria-hidden="true" className={`query-region__layer query-region__skeleton-layer ${showLoading ? 'is-visible' : retainedSkeleton ? 'is-exiting' : 'is-reserved'}`}>{skeleton}</div>}
      {resolved && <div className={`query-region__layer query-region__result-layer ${showLoading ? 'is-hidden' : 'is-visible'}`}>{result}</div>}
    </div>
    {showRefreshing && <span className="query-region__refresh" role="status" aria-live="polite"><span className="inline-pending-spinner" aria-hidden="true" />{refreshLabel}</span>}
    {state.refreshError !== null && <button type="button" className="query-region__refresh-error" onClick={state.retry}>Шинэчлэхэд алдаа гарлаа · Дахин оролдох</button>}
  </div>
}

export interface QueryRegionProps<E = unknown> {
  state: QueryRegionState<E>
  skeleton: React.ReactNode
  children: React.ReactNode
  empty?: boolean
  emptyFallback?: React.ReactNode
  errorFallback?: (error: E, retry: () => void) => React.ReactNode
  refreshLabel?: string
  className?: string
}

export function QueryErrorState({ onRetry }: { onRetry: () => void }) {
  return <div className="query-region-state query-region-error" role="alert"><strong>Агуулгыг ачаалж чадсангүй.</strong><button type="button" className="secondary-action" onClick={onRetry}>Дахин оролдох</button></div>
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return <div className="table-skeleton" aria-label="Агуулга ачаалж байна"><Skeleton variant="table-row" count={rows} /></div>
}

export function KanbanSkeleton() {
  return <div className="kanban-board kanban-skeleton" aria-label="Даалгаврууд ачаалж байна">{Array.from({ length: 5 }, (_, index) => <section className="kanban-column" key={index}><Skeleton variant="text" /><div className="kanban-dropzone"><Skeleton variant="kanban-card" count={3} /></div></section>)}</div>
}

export function CalendarSkeleton() {
  return <div className="planning-calendar panel calendar-skeleton" aria-label="Календарь ачаалж байна"><Skeleton variant="calendar-cell" count={42} /></div>
}

export function WorkspaceSkeleton() {
  return <main className="workspace-loading" aria-label="Хуудас ачаалж байна"><Skeleton variant="text" count={3} /></main>
}

export function WorkspaceRouteSkeleton({ pathname }: { pathname: string }) {
  if (pathname.startsWith('/calendar')) return <div className="route-skeleton"><CalendarSkeleton /></div>
  if (pathname.startsWith('/tasks')) return <div className="route-skeleton"><KanbanSkeleton /></div>
  if (pathname.startsWith('/projects')) return <div className="route-skeleton"><div className="project-grid"><Skeleton variant="card" count={6} /></div></div>
  if (pathname.startsWith('/reports') || pathname.startsWith('/capacity')) return <div className="route-skeleton"><section className="panel"><TableSkeleton rows={6} /></section></div>
  if (pathname.startsWith('/analytics')) return <div className="route-skeleton"><div className="metrics-grid"><Skeleton variant="card" count={4} /></div><section className="panel"><Skeleton variant="chart" /></section></div>
  if (pathname.startsWith('/chat')) return <div className="route-skeleton"><Skeleton variant="sheet" count={8} /></div>
  return <div className="route-skeleton workspace-skeleton"><Skeleton variant="text" count={2} /><div className="workspace-skeleton-grid"><Skeleton variant="card" count={4} /></div><Skeleton variant="chart" /></div>
}

export function InitialWorkspaceSkeleton() {
  return <div className="workspace-shell initial-workspace-skeleton" aria-label="Ажлын орон зайг ачаалж байна">
    <aside className="workspace-sidebar" aria-hidden="true"><div className="sidebar-brand"><img src="/favicon.png" alt="" /></div><nav className="initial-nav-skeleton">{Array.from({ length: 11 }, (_, index) => <Skeleton key={index} variant="text" />)}</nav><div className="sidebar-footer"><Skeleton variant="text" /><Skeleton variant="text" /></div></aside>
    <main className="workspace-main"><header className="workspace-header"><Skeleton variant="text" /></header><div className="workspace-content"><WorkspaceSkeleton /></div></main>
  </div>
}
