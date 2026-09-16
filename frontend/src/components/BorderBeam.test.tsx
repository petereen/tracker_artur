import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BorderBeam } from './BorderBeam'

describe('BorderBeam', () => {
  it('keeps the wrapped surface accessible and exposes the selected beam variant', () => {
    render(<BorderBeam colorVariant="ocean" strength={0.7}><button>Ask OYUNS</button></BorderBeam>)

    expect(screen.getByRole('button', { name: 'Ask OYUNS' })).toBeInTheDocument()
    expect(document.querySelector('.border-beam')).toHaveAttribute('data-color', 'ocean')
    expect(document.querySelector('.border-beam')).toHaveClass('is-active')
  })
})
