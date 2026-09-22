import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Btn, Input, Modal, Toggle } from './ui'

describe('shared OYUNS primitives', () => {
  it('associates input labels and inline descriptions', () => {
    render(<Input label="Нэр" value="" onChange={() => undefined} required helpText="Овог нэрээ оруулна уу" />)
    const input = screen.getByLabelText('Нэр *')
    expect(input).toHaveAttribute('aria-describedby')
    expect(input).toHaveAttribute('required')
    expect(screen.getByText('Овог нэрээ оруулна уу')).toBeInTheDocument()
  })

  it('keeps the toggle as a keyboard-accessible switch', () => {
    const onChange = vi.fn()
    render(<Toggle checked={false} onChange={onChange} aria-label="Мэдэгдэл" />)
    const toggle = screen.getByRole('switch', { name: 'Мэдэгдэл' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('exposes button disabled state without dropping its accessible name', () => {
    render(<Btn variant="primary" disabled>Хадгалах</Btn>)
    expect(screen.getByRole('button', { name: 'Хадгалах' })).toBeDisabled()
  })

  it('labels modal content and close action', () => {
    const onClose = vi.fn()
    render(<Modal title="Тохиргоо" onClose={onClose}><p>Талбарууд</p></Modal>)
    expect(screen.getByRole('dialog', { name: 'Тохиргоо' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Хаах' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
