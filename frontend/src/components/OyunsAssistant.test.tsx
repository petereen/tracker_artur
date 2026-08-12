import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OyunsAssistant } from './OyunsAssistant'

const { chat, confirm, download } = vi.hoisted(() => ({ chat: vi.fn(), confirm: vi.fn(), download: vi.fn() }))

vi.mock('../api/enterprise', () => ({
  useAssistantChat: () => ({ mutateAsync: chat, isPending: false }),
  useConfirmAssistantAction: () => ({ mutateAsync: confirm, isPending: false }),
  downloadAssistantAttachment: download,
  transcribeAssistantVoice: vi.fn(),
  synthesizeAssistantSpeech: vi.fn().mockResolvedValue(undefined),
}))

describe('OYUNS assistant actions', () => {
  beforeEach(() => {
    chat.mockReset()
    confirm.mockReset()
    download.mockReset()
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

  it('shows company files attached by the assistant and downloads them through the authenticated API', async () => {
    const attachment = { item_id: 42, filename: 'leave-policy.pdf', content_type: 'application/pdf', size: 2048, download_url: '/v1/company-files/42/download' }
    chat.mockResolvedValue({
      conversation_id: 8,
      message: { content: 'Файлыг хавсаргалаа.', action: null, sources: [], attachments: [attachment] },
    })

    render(<OyunsAssistant open onClose={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('Компаний журам, миний ажил, эсвэл даалгаврын талаар асуу…'), { target: { value: 'Надад leave policy файлыг хавсарга' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Илгээх' }).parentElement!)

    const fileButton = await screen.findByRole('button', { name: 'leave-policy.pdf' })
    fireEvent.click(fileButton)

    await waitFor(() => expect(download).toHaveBeenCalledWith(attachment))
  })
})
