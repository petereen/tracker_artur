import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { EnterpriseShell } from './EnterpriseShell'

const mocks = vi.hoisted(() => ({
  workers: [] as any[],
  profile: null as any,
  payrollVisible: false,
  accountsVisible: false,
  roles: ['manager'] as string[],
  locale: 'mn',
  openDirect: vi.fn(async () => ({ public_id: 'direct-1' })),
}))

vi.mock('../api/enterprise', () => ({
  useActor: () => ({ data: { name: 'Manager', email: 'manager@example.com', roles: mocks.roles, locale: mocks.locale, avatar_url: null } }),
  useBrandingSettings: () => ({ data: {} }),
  useERPMetadata: () => ({ data: { modules: { payroll: mocks.payrollVisible }, module_labels: {}, document_modules: {}, actions: [], currency: 'MNT', custom_fields: [], roles: [], module_visibility_is_not_authorization: true }, isLoading: false }),
  useERPAccountPermissions: () => ({ data: { view: mocks.accountsVisible, create: false, edit: false, administer: false } }),
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
vi.mock('./Loading', () => ({ WorkspaceRouteSkeleton: () => null }))

describe('enterprise sidebar', () => {
  beforeEach(() => { mocks.workers = []; mocks.profile = null; mocks.payrollVisible = false; mocks.accountsVisible = false; mocks.roles = ['manager']; mocks.locale = 'mn'; mocks.openDirect.mockClear() })
  it('places company files immediately above the profile and logout controls', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const link = screen.getByRole('link', { name: 'Компаний файлууд' })
    const profile = container.querySelector('.sidebar-profile')
    expect(profile).not.toBeNull()
    expect(link.compareDocumentPosition(profile as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(link.parentElement).toHaveClass('sidebar-footer')
  })

  it('opens the account menu with theme switch, profile, docs and log out', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /><Route path="profile" element={<div>Profile page</div>} /><Route path="docs" element={<div>Docs page</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    expect(container.querySelector('.workspace-header .theme-toggle')).toBeNull()
    const trigger = screen.getByRole('button', { name: 'Бүртгэлийн цэс нээх' })
    expect(trigger).toHaveTextContent('Manager')
    expect(trigger.querySelector('.avatar')).toHaveTextContent('M')
    fireEvent.click(trigger)
    const menu = screen.getByRole('menu', { name: 'Миний бүртгэл' })
    expect(within(menu).getByRole('menuitem', { name: 'Профайл' })).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: 'Заавар' })).not.toHaveAttribute('aria-disabled')
    expect(within(menu).getByRole('menuitem', { name: 'Гарах' })).toBeInTheDocument()
    expect(within(menu).getByRole('button', { name: /Харанхуй горимд шилжих|Гэрэлтэй горимд шилжих/ })).toBeInTheDocument()

    // The shell follows the account locale, so the mocked account switches language with the UI.
    mocks.locale = 'ru'
    await act(async () => { await i18n.changeLanguage('ru') })
    expect(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Профиль' })).toBeInTheDocument()
    expect(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Выйти' })).toBeInTheDocument()
    mocks.locale = 'mn'
    await act(async () => { await i18n.changeLanguage('mn') })

    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Профайл' }))
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByText('Profile page')).toBeInTheDocument()

    fireEvent.click(trigger)
    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Заавар' }))
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByText('Docs page')).toBeInTheDocument()
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

  it('exposes the active route semantics used by the compact navigation treatment', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/tasks']}><Routes><Route element={<EnterpriseShell />}><Route path="tasks" element={<div>Tasks</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const active = container.querySelector('.workspace-sidebar .nav-item.active')
    expect(active).not.toBeNull()
    expect(active).toHaveAttribute('aria-current', 'page')
    expect(active?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('keeps HR directly below Worktime and Chat starts the next section', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const sidebarNav = container.querySelector('.workspace-sidebar nav')
    const links = Array.from(sidebarNav?.querySelectorAll<HTMLAnchorElement>('.nav-item') ?? [])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/', '/worktime', '/hr', '/chat', '/calendar', '/tasks', '/reports', '/projects', '/plans', '/contracts', '/analytics', '/administration',
    ])
    expect(links[3].parentElement).not.toHaveClass('nav-group-break')
    expect(links[6].parentElement).toHaveClass('nav-group-break')
    expect(links[7].parentElement).not.toHaveClass('nav-group-break')
    expect(links[8].parentElement).not.toHaveClass('nav-group-break')
    expect(links[9].parentElement).not.toHaveClass('nav-group-break')
    expect(links[10].parentElement).toHaveClass('nav-group-break')
  })

  it('links the chart of accounts when the actor may view accounts', () => {
    mocks.accountsVisible = true
    mocks.roles = ['admin']
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/erp/accounts']}><Routes><Route element={<EnterpriseShell />}><Route path="erp/accounts" element={<div>Accounts</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('link', { name: 'Данс' })).toHaveAttribute('href', '/erp/accounts')
    expect(screen.getByRole('link', { name: 'Данс' })).toHaveClass('active')
  })

  it('never lists an ERP hub entry; Payroll stays a direct link', () => {
    mocks.payrollVisible = true
    mocks.roles = ['admin']
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/erp/payroll']}><Routes><Route element={<EnterpriseShell />}><Route path="erp/payroll" element={<div>Payroll</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    expect(screen.queryByRole('link', { name: 'ERP' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Цалин' })).toHaveClass('active')
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
