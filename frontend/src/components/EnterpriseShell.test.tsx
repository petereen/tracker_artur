import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '../i18n'
import { EnterpriseShell } from './EnterpriseShell'

const mocks = vi.hoisted(() => ({
  workers: [] as any[],
  profile: null as any,
  openDirect: vi.fn(async () => ({ public_id: 'direct-1' })),
}))

vi.mock('../api/enterprise', () => ({
  useActor: () => ({ data: { name: 'Manager', email: 'manager@example.com', roles: ['manager'], locale: 'mn', avatar_url: null } }),
  useBrandingSettings: () => ({ data: {} }),
  useERPMetadata: () => ({ data: { modules: {}, module_labels: {}, document_modules: {}, actions: [], currency: 'MNT', custom_fields: [], roles: [], module_visibility_is_not_authorization: true }, isLoading: false }),
  useEnterpriseLogout: () => ({ mutate: vi.fn() }),
  useWorkerDirectory: () => ({ data: mocks.workers }),
  useWorkerPerformance: () => ({ data: {} }),
  useWorkerProfile: () => ({ data: mocks.profile, isLoading: false }),
  useChatUnreadCount: () => ({ data: { unread_count: 3 } }),
  useOpenDirectConversation: () => ({ mutateAsync: mocks.openDirect, isPending: false }),
  acknowledgeChatReceipt: vi.fn(),
  useGlobalSearch: () => ({ data: undefined, isFetching: false }),
  useWorkspaceModePreferences: () => ({ data: { mode: 'manager' }, isLoading: false, isError: false }),
  useUpdateWorkspaceModePreferences: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('./NotificationCenter', () => ({ NotificationCenter: () => null }))
vi.mock('./OyunsAssistant', () => ({ OyunsAssistant: () => null }))
vi.mock('./Loading', () => ({ WorkspaceSkeleton: () => null }))

describe('enterprise sidebar', () => {
  beforeEach(() => { mocks.workers = []; mocks.profile = null; mocks.openDirect.mockClear() })
  it('places company files immediately above the profile and logout controls', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const link = screen.getByRole('link', { name: 'Компаний файлууд' })
    const profile = container.querySelector('.sidebar-profile')
    expect(profile).not.toBeNull()
    expect(link.compareDocumentPosition(profile as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(link.parentElement).toHaveClass('sidebar-footer')
  })

  it('keeps five thumb-reachable mobile destinations and a More control', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const tabbar = container.querySelector('.mobile-tabbar')
    expect(tabbar).not.toBeNull()
    expect(tabbar?.querySelectorAll('a')).toHaveLength(4)
    expect(tabbar?.querySelector('button')).toHaveAccessibleName('Бусад цэс нээх')
    expect(tabbar?.textContent).toContain('Өнөөдөр')
    expect(tabbar?.textContent).toContain('Календарь')
    expect(tabbar?.textContent).toContain('Даалгавар')
    expect(tabbar?.textContent).toContain('Чат')
    expect(tabbar?.textContent).not.toContain('Ажлын цаг')
    expect(tabbar?.querySelector('.nav-unread-badge')).toHaveTextContent('3')
  })

  it('shows Chat in the main navigation with an unread badge', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const chatLinks = screen.getAllByRole('link', { name: /Чат/ })
    expect(chatLinks.length).toBeGreaterThan(0)
    expect(chatLinks[0].querySelector('.nav-unread-badge')).toHaveTextContent('3')
  })

  it('keeps Chat below Worktime and starts the Reports project section', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const sidebarNav = container.querySelector('.workspace-sidebar nav')
    const links = Array.from(sidebarNav?.querySelectorAll<HTMLAnchorElement>('.nav-item') ?? [])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/', '/worktime', '/chat', '/calendar', '/tasks', '/reports', '/projects', '/plans', '/contracts', '/analytics', '/administration',
    ])
    expect(links[2].parentElement).not.toHaveClass('nav-group-break')
    expect(links[5].parentElement).toHaveClass('nav-group-break')
    expect(links[6].parentElement).not.toHaveClass('nav-group-break')
    expect(links[7].parentElement).not.toHaveClass('nav-group-break')
    expect(links[8].parentElement).not.toHaveClass('nav-group-break')
  })

  it('uses a full in-app chat action and an icon-only Telegram squircle for workers', () => {
    mocks.workers = [{ id: 7, name: 'Бат', avatar_url: null, job_title: 'Engineer', telegram_username: '@bat', presence: 'offline' }]
    mocks.profile = { id: 7, name: 'Бат', chat_available: true, telegram_chat_url: 'https://t.me/bat' }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Ажилтны жагсаалт нээх' }))
    fireEvent.click(screen.getByRole('button', { name: /Бат/ }))
    expect(screen.getByRole('button', { name: 'Чатлах' })).toBeEnabled()
    const telegram = screen.getByRole('link', { name: 'Telegram-аар чатлах' })
    expect(telegram).toHaveClass('telegram-chat-action')
    expect(telegram.textContent).toBe('')
    expect(container.querySelector('.worker-chat-actions')).not.toBeNull()
  })

  it('keeps in-app chat visible but disabled until a worker has workspace access', () => {
    mocks.workers = [{ id: 8, name: 'Сараа', avatar_url: null, job_title: null, telegram_username: '@saraa', presence: 'offline' }]
    mocks.profile = { id: 8, name: 'Сараа', chat_available: false, telegram_chat_url: 'https://t.me/saraa' }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Ажилтны жагсаалт нээх' }))
    fireEvent.click(screen.getByRole('button', { name: /Сараа/ }))
    expect(screen.getByRole('button', { name: 'Чатлах' })).toBeDisabled()
    expect(screen.getByText(/Workspace хандалт холбосны дараа/)).toBeInTheDocument()
  })
})
