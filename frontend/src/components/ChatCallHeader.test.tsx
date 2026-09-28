import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatCallHeader } from './ChatCallHeader'

vi.mock('./CallProvider', () => ({ useOptionalCall: () => null }))
vi.mock('./OyunsVoiceCall', () => ({ OyunsVoiceCall: () => <div role="dialog" aria-label="OYUNS Agent дуудлага" /> }))

const agentConversation = {
  public_id: 'c1', kind: 'direct', presence: 'online',
  members: [{ account_id: 99, name: 'OYUNS Agent', is_agent: true }],
} as any

describe('ChatCallHeader', () => {
  it('offers a live voice call in the OYUNS agent conversation', async () => {
    render(<ChatCallHeader conversation={agentConversation} />)
    fireEvent.click(screen.getByRole('button', { name: 'OYUNS Agent руу залгах' }))
    expect(await screen.findByRole('dialog', { name: 'OYUNS Agent дуудлага' })).toBeInTheDocument()
  })

  it('shows no person-to-person call buttons without the call provider', () => {
    const { container } = render(<ChatCallHeader conversation={{ ...agentConversation, members: [{ account_id: 5, name: 'Сараа', is_agent: false }] }} />)
    expect(container).toBeEmptyDOMElement()
  })
})
