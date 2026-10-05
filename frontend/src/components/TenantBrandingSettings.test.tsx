import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TenantBrandingSettings } from './TenantBrandingSettings'
import { useAuthStore } from '../store/auth'

const mocks = vi.hoisted(() => ({
  save: vi.fn(),
  settings: {
    isLoading: false,
    isError: false,
    data: {
      branding: { display_name: null, logo_url: null, favicon_url: null, primary_color: '#2d62ec', secondary_color: null },
      preview: { slug: 'acme', name: 'Acme', logo_url: '/favicon.png', dark_logo_url: '/oyuns-aio-logo.png', favicon_url: '/favicon.png', primary_color: '#2d62ec', secondary_color: null },
    },
  },
}))

vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantBrandingSettings: () => mocks.settings,
  useUpdateTenantBranding: () => ({ mutateAsync: mocks.save, isPending: false }),
}))

const PNG = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'logo.png', { type: 'image/png' })

describe('TenantBrandingSettings', () => {
  beforeEach(() => {
    mocks.save.mockReset().mockResolvedValue({})
    useAuthStore.setState({ actor: { roles: ['admin'] } as never })
  })

  it('offers file, URL and icon-only delete buttons and no "Optional" labels', () => {
    render(<TenantBrandingSettings />)
    expect(screen.getAllByRole('button', { name: 'Файл хавсаргах' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'URL' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Устгах' })).toHaveLength(2)
    expect(screen.queryByText(/optional|заавал биш/i)).toBeNull()
  })

  it('shows light and dark previews', () => {
    render(<TenantBrandingSettings />)
    expect(screen.getByTestId('brand-preview-light')).toBeTruthy()
    expect(screen.getByTestId('brand-preview-dark')).toBeTruthy()
  })

  it('attaches a file as a data URL and saves it', async () => {
    const { container } = render(<TenantBrandingSettings />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [PNG] } })
    await waitFor(() => expect(screen.getByText(/Хавсаргасан файл/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalled())
    expect((mocks.save.mock.calls[0][0] as { logo_url: string }).logo_url).toMatch(/^data:image\/png;base64,/)
  })
})
