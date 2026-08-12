import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OyunsAssistant } from './OyunsAssistant'

const chat = vi.fn()
const confirm = vi.fn()

vi.mock('../api/enterprise', () => ({
  useAssistantChat: () => ({ mutateAsync: chat, isPending: false }),
  useConfirmAssistantAction: () => ({ mutateAsync: confirm, isPending: false }),
  transcribeAssistantVoice: vi.fn(),
  synthesizeAssistantSpeech: vi.fn().mockResolvedValue(undefined),
}))

describe('OYUNS assistant actions', () => {
  beforeEach(() => {
    chat.mockReset()
    confirm.mockReset()
  })

  it('confirms the server-issued action token instead of posting a task directly', async () => {
    chat.mockResolvedValue({
      conversation_id: 7,
      message: {
        content: 'Please confirm this task.',
        action: { type: 'task_action_preview', payload: { token: 'server-token-1234567890', title: 'Prepare access review', action_type: 'create_task' } },
        sources: [],
      },
    })
    confirm.mockResolvedValue({ status: 'ok', data: { created: { title: 'Prepare access review' } } })

    render(<OyunsAssistant open onClose={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('Компаний журам, миний ажил, эсвэл даалгаврын талаар асуу…'), { target: { value: 'Create an access review task' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Илгээх' }).parentElement!)

    const confirmButton = await screen.findByRole('button', { name: 'ERP-д үүсгэх' })
    fireEvent.click(confirmButton)

    await waitFor(() => expect(confirm).toHaveBeenCalledWith('server-token-1234567890'))
    expect(screen.getByText('Даалгаврыг ERP-д үүсгэлээ: “Prepare access review”.')).toBeInTheDocument()
  })
})
