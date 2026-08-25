import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceModeToggle } from './WorkspaceModeToggle'

const state = vi.hoisted(() => ({
  eligible: true,
  manager: true,
  setMode: vi.fn(async () => undefined),
}))

vi.mock('./WorkspaceModeProvider', () => ({
  useWorkspaceMode: () => ({
    isEligible: state.eligible,
    isManagerMode: state.manager,
    isLoading: false,
    isSaving: false,
    setMode: state.setMode,
  }),
}))

describe('WorkspaceModeToggle', () => {
  it('is an accessible switch and changes from Manager Mode to Member Mode', () => {
    render(<WorkspaceModeToggle />)
    const toggle = screen.getByRole('switch', { name: 'Switch workspace mode' })
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(toggle).toHaveTextContent('Manager Mode')
    fireEvent.click(toggle)
    expect(state.setMode).toHaveBeenCalledWith('member')
  })

  it('does not render for ineligible roles', () => {
    state.eligible = false
    const { container } = render(<WorkspaceModeToggle />)
    expect(container).toBeEmptyDOMElement()
    state.eligible = true
  })
})
