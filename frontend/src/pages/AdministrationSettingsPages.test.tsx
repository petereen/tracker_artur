import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DomainSettingsPage, LicenseSettingsPage, OyunsAssistantSettingsPage, ReportSettingsPage } from './AdministrationSettingsPages'
import { useAuthStore } from '../store/auth'

vi.mock('../components/ReportPolicySettings', () => ({ ReportPolicySettings: () => <p>report-policy</p> }))
vi.mock('../components/TenantLicenseSettings', () => ({ TenantLicenseSettings: () => <p>license</p>, SeatMeter: () => null }))
vi.mock('../components/TenantDomainSettings', () => ({ TenantDomainSettings: () => <p>domains</p> }))
vi.mock('../components/AiAgentSettings', () => ({ AiAgentSettings: () => <p>ai-agent</p> }))
vi.mock('../components/AiAccessSettings', () => ({ AiAccessSettings: () => <p>ai-access</p> }))
vi.mock('./KnowledgePage', () => ({ KnowledgePage: () => <p>knowledge</p> }))
vi.mock('./DeveloperPage', () => ({ DeveloperPage: () => <p>developer</p> }))

const renderPage = (page: JSX.Element) => render(<MemoryRouter>{page}</MemoryRouter>)

describe('Administration settings', () => {
  it('renders every settings section collapsed until the admin opens it', () => {
    useAuthStore.setState({ actor: { roles: ['admin'], account_roles: ['admin'] } as never })
    for (const page of [<ReportSettingsPage />, <LicenseSettingsPage />, <DomainSettingsPage />, <OyunsAssistantSettingsPage />]) {
      const { container, unmount } = renderPage(page)
      const sections = container.querySelectorAll('details.settings-section')
      expect(sections.length).toBeGreaterThan(0)
      expect(container.querySelectorAll('details.settings-section[open]')).toHaveLength(0)
      unmount()
    }
  })

  it('lists the custom domain tab for administrators', () => {
    useAuthStore.setState({ actor: { roles: ['admin'], account_roles: ['admin'] } as never })
    renderPage(<DomainSettingsPage />)
    expect(screen.getByRole('link', { name: 'Өөрийн домэйн' })).toBeInTheDocument()
    expect(screen.getByText('Өөрийн домэйн (Cloudflare)')).toBeInTheDocument()
  })
})
