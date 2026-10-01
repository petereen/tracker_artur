import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnnouncementsPage } from './AnnouncementsPage'

const post = (overrides: Record<string, unknown>) => ({
  id: 1, title: 'Шинэ журам', summary: 'Ажлын цагийн журам шинэчлэгдлээ', body: 'Агуулга', cover_url: null, image_urls: [], author_name: 'Бат', category: 'HR',
  is_pinned: false, status: 'published', published_at: '2026-10-01T03:00:00Z', author_account_id: 1, created_at: '2026-10-01T03:00:00Z', updated_at: '2026-10-01T03:00:00Z', can_edit: true,
  ...overrides,
})

const mocks = vi.hoisted(() => ({
  save: vi.fn(),
  remove: vi.fn(),
  upload: vi.fn(),
  roles: ['admin'] as string[],
  list: { isLoading: false, isError: false, error: null, data: [] as any[] },
}))

vi.mock('../api/announcements', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/announcements')>()),
  useManagedAnnouncements: () => mocks.list,
  useSaveAnnouncement: () => ({ mutateAsync: mocks.save, isPending: false }),
  useDeleteAnnouncement: () => ({ mutateAsync: mocks.remove, isPending: false }),
  uploadAnnouncementImage: mocks.upload,
}))
vi.mock('../api/enterprise', () => ({ useActor: () => ({ data: { id: 1, roles: mocks.roles } }) }))

describe('AnnouncementsPage', () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
    mocks.save.mockReset().mockResolvedValue({})
    mocks.remove.mockReset().mockResolvedValue({})
    mocks.upload.mockReset().mockResolvedValue('/api/v1/announcements/media/' + 'a'.repeat(32) + '.jpg')
    mocks.roles = ['admin']
    mocks.list.data = [post({}), post({ id: 2, title: 'Ноорог мэдээ', status: 'draft', published_at: null, summary: null }), post({ id: 3, title: 'Бусдын мэдээ', can_edit: false })]
  })

  it('lists posts with their status and filters by it', () => {
    render(<AnnouncementsPage />)
    expect(screen.getByText('Шинэ журам')).toBeInTheDocument()
    expect(screen.getByText('Ноорог мэдээ')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Ноорог (1)' }))
    expect(screen.queryByText('Шинэ журам')).not.toBeInTheDocument()
    expect(screen.getByText('Ноорог мэдээ')).toBeInTheDocument()
  })

  it('offers row actions only for posts the user may edit', async () => {
    render(<AnnouncementsPage />)
    expect(screen.getAllByRole('button', { name: 'Засах' })).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Нийтлэх' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ id: 2, input: { status: 'published' } }))
    fireEvent.click(screen.getByRole('button', { name: 'Архивлах' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ id: 1, input: { status: 'archived' } }))
  })

  it('writes a post with the toolbar and publishes it', async () => {
    mocks.list.data = []
    render(<AnnouncementsPage />)
    fireEvent.click(screen.getByRole('button', { name: /Мэдээ нэмэх/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Нийтлэх' })).toBeDisabled()
    fireEvent.change(within(dialog).getByRole('textbox', { name: /^Гарчиг/ }), { target: { value: '  Амралтын хуваарь ' } })
    const body = within(dialog).getByLabelText('Агуулга') as HTMLTextAreaElement
    fireEvent.change(body, { target: { value: 'чухал' } })
    body.setSelectionRange(0, 5)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Тод' }))
    await waitFor(() => expect(body.value).toBe('**чухал**'))
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Урьдчилан харах' }))
    expect(within(dialog).getByText('чухал').closest('strong')).not.toBeNull()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Нийтлэх' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({
      id: undefined,
      input: { title: 'Амралтын хуваарь', summary: null, body: '**чухал**', cover_url: null, image_urls: [], category: null, is_pinned: false, status: 'published' },
    }))
  })

  it('lets only admins and managers pin a post', async () => {
    mocks.roles = ['team_lead']
    render(<AnnouncementsPage />)
    fireEvent.click(screen.getByRole('button', { name: /Мэдээ нэмэх/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByLabelText(/Онцлох/)).not.toBeInTheDocument()
  })

  it('uploads attached images and saves their URLs', async () => {
    render(<AnnouncementsPage />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Засах' })[0])
    const dialog = await screen.findByRole('dialog')
    const inputs = dialog.querySelectorAll<HTMLInputElement>('input[type="file"]')
    expect(inputs).toHaveLength(2)
    fireEvent.change(inputs[0], { target: { files: [new File(['x'], 'cover.png', { type: 'image/png' })] } })
    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(within(dialog).getByRole('img', { name: 'Нүүр зураг' })).toBeInTheDocument())
    fireEvent.click(within(dialog).getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ id: 1, input: expect.objectContaining({ cover_url: expect.stringContaining('/api/v1/announcements/media/'), status: 'published' }) }))
  })
})
