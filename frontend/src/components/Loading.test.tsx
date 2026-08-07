import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InlinePending, Skeleton, useDelayedPending } from './Loading'

function Delayed({ pending }: { pending: boolean }) {
  return <div>{useDelayedPending(pending) ? 'visible' : 'hidden'}</div>
}

describe('loading primitives', () => {
  it('waits 150ms before showing pending feedback and clears immediately', () => {
    vi.useFakeTimers()
    const { rerender } = render(<Delayed pending />)
    expect(screen.getByText('hidden')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(149))
    expect(screen.getByText('hidden')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByText('visible')).toBeInTheDocument()
    rerender(<Delayed pending={false} />)
    expect(screen.getByText('hidden')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('provides accessible pending feedback and dimensioned skeleton markup', () => {
    render(<><InlinePending label="Хадгалж байна…" /><Skeleton variant="card" count={2} /></>)
    expect(screen.getByRole('status', { name: 'Хадгалж байна…' })).toBeInTheDocument()
    expect(document.querySelectorAll('.skeleton-card .skeleton')).toHaveLength(2)
  })
})
