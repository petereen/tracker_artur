import { useEffect, useState } from 'react'
import { Bouncy } from 'ldrs/react'
import 'ldrs/react/Bouncy.css'

export type SkeletonVariant = 'text' | 'card' | 'table-row' | 'calendar-cell' | 'kanban-card' | 'chart' | 'sheet'

export function useDelayedPending(pending: boolean, delay = 150) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!pending) {
      setVisible(false)
      return
    }
    const timer = window.setTimeout(() => setVisible(true), delay)
    return () => window.clearTimeout(timer)
  }, [delay, pending])

  return visible
}

export function Skeleton({ variant = 'text', className = '', count = 1 }: { variant?: SkeletonVariant; className?: string; count?: number }) {
  return <div className={`skeleton-group skeleton-${variant} ${className}`.trim()} aria-hidden="true">
    {Array.from({ length: count }, (_, index) => <span className="skeleton" key={index} />)}
  </div>
}

export function InlinePending({ label = 'Ачаалж байна…', size = 20 }: { label?: string; size?: number }) {
  return <span className="inline-pending" role="status" aria-live="polite" aria-label={label}>
    <Bouncy size={String(size)} speed="1.75" color="currentColor" />
    <span className="sr-only">{label}</span>
  </span>
}

export function QueryRegion({ pending, children, skeleton, className = '' }: { pending: boolean; children: React.ReactNode; skeleton: React.ReactNode; className?: string }) {
  const showLoading = useDelayedPending(pending)
  return <div className={`query-region ${className}`.trim()} aria-busy={showLoading}>{showLoading ? skeleton : children}</div>
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
  return <main className="workspace-skeleton" aria-label="Хуудас ачаалж байна"><Skeleton variant="text" className="workspace-skeleton-heading" /><div className="workspace-skeleton-grid"><Skeleton variant="card" count={4} /></div><Skeleton variant="chart" /></main>
}
