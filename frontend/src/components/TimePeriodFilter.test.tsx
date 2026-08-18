import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TimePeriodFilter } from './TimePeriodFilter'

describe('TimePeriodFilter mobile interaction', () => {
  it('applies a preset from the mobile sheet and restores focus', () => {
    const onChange = vi.fn()
    render(<TimePeriodFilter preset="week" period={{ date_from: '2026-08-12', date_to: '2026-08-18' }} onChange={onChange} />)
    const trigger = screen.getByRole('button', { name: /Хугацаа/ })
    fireEvent.click(trigger)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '30 хоног' }))
    expect(onChange).toHaveBeenCalledWith('month', expect.objectContaining({ date_from: expect.any(String), date_to: expect.any(String) }))
    expect(trigger).toHaveFocus()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('rejects an invalid custom range and applies a valid range', () => {
    const onChange = vi.fn()
    render(<TimePeriodFilter preset="week" period={{ date_from: '2026-08-12', date_to: '2026-08-18' }} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /Хугацаа/ }))
    const dates = screen.getAllByDisplayValue(/2026-08-/)
    fireEvent.change(dates[2], { target: { value: '2026-08-20' } })
    fireEvent.change(dates[3], { target: { value: '2026-08-10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Хэрэглэх' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Эхлэх огноо')
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(dates[3], { target: { value: '2026-08-22' } })
    fireEvent.click(screen.getByRole('button', { name: 'Хэрэглэх' }))
    expect(onChange).toHaveBeenCalledWith('custom', { date_from: '2026-08-20', date_to: '2026-08-22' })
  })

  it('dismisses the mobile sheet with Escape', () => {
    render(<TimePeriodFilter preset="today" period={{ date_from: '2026-08-18', date_to: '2026-08-18' }} onChange={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /Хугацаа/ })
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
