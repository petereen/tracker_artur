import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { InlinePending, QueryRegion, RouteLoadErrorBoundary, Skeleton, combineQueryRegionStates, toQueryRegionState, useDelayedLoading, type QueryRegionState } from './Loading'

function Delayed({ pending }: { pending: boolean }) {
  return <div>{useDelayedLoading(pending) ? 'visible' : 'hidden'}</div>
}

function BrokenRoute(): ReactNode {
  throw new Error('chunk unavailable')
}

describe('loading primitives', () => {
  it('waits 150ms and keeps visible feedback for its minimum duration', () => {
    vi.useFakeTimers()
    const { rerender } = render(<Delayed pending />)
    expect(screen.getByText('hidden')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(149))
    expect(screen.getByText('hidden')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByText('visible')).toBeInTheDocument()
    rerender(<Delayed pending={false} />)
    expect(screen.getByText('visible')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(299))
    expect(screen.getByText('visible')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByText('hidden')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('provides accessible pending feedback and dimensioned skeleton markup', () => {
    render(<><InlinePending label="Хадгалж байна…" /><Skeleton variant="card" count={2} /></>)
    expect(screen.getByRole('status', { name: 'Хадгалж байна…' })).toBeInTheDocument()
    expect(document.querySelectorAll('.skeleton-card .skeleton')).toHaveLength(2)
  })

  it('normalizes cache misses, null data, and combined dependencies', () => {
    const retryA = vi.fn()
    const retryB = vi.fn()
    const miss = toQueryRegionState({ data: undefined, isLoading: true, isFetching: true, isError: false, refetch: retryA })
    const ready = toQueryRegionState({ data: null, isLoading: false, isFetching: true, isError: false, refetch: retryB })
    expect(miss).toMatchObject({ hasData: false, initialPending: true, refreshing: false })
    expect(ready).toMatchObject({ hasData: true, initialPending: false, refreshing: true })
    const combined = combineQueryRegionStates([miss, ready])
    expect(combined.initialPending).toBe(true)
    combined.retry()
    expect(retryA).toHaveBeenCalledOnce()
    expect(retryB).toHaveBeenCalledOnce()
  })

  it('keeps cached content visible during background refresh', () => {
    vi.useFakeTimers()
    const state: QueryRegionState = { hasData: true, initialPending: false, refreshing: true, initialError: null, refreshError: null, retry: vi.fn() }
    render(<QueryRegion state={state} skeleton={<Skeleton variant="table-row" />}><p>Live data</p></QueryRegion>)
    expect(screen.getByText('Live data')).toBeVisible()
    act(() => vi.advanceTimersByTime(250))
    expect(screen.getByText('Шинэчилж байна…')).toBeVisible()
    expect(document.querySelector('.query-region')).toHaveAttribute('aria-busy', 'true')
    vi.useRealTimers()
  })

  it('renders an initial error without exposing a skeleton', () => {
    const retry = vi.fn()
    const state: QueryRegionState<Error> = { hasData: false, initialPending: false, refreshing: false, initialError: new Error('offline'), refreshError: null, retry }
    render(<QueryRegion state={state} skeleton={<Skeleton variant="table-row" />}><p>Live data</p></QueryRegion>)
    expect(screen.getByRole('alert')).toBeVisible()
    expect(screen.queryByText('Live data')).not.toBeInTheDocument()
    screen.getByRole('button', { name: 'Дахин оролдох' }).click()
    expect(retry).toHaveBeenCalledOnce()
  })

  it('shows a recovery action when a route module fails to render', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(<RouteLoadErrorBoundary><BrokenRoute /></RouteLoadErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('Энэ хуудсыг ачаалж чадсангүй.')
    expect(screen.getByRole('button', { name: 'Дахин ачаалах' })).toBeInTheDocument()
    consoleError.mockRestore()
  })
})
