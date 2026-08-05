import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import * as axe from 'axe-core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'

const mutateAsync = vi.fn()

vi.mock('../api/enterprise', () => ({
  useEnterpriseLogin: () => ({ mutateAsync, isPending: false }),
}))

function renderLogin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><LoginPage /></QueryClientProvider>)
}

describe('enterprise login', () => {
  beforeEach(() => mutateAsync.mockReset())

  it('has explicit labels and a clear submit action', () => {
    renderLogin()
    expect(screen.getByRole('heading', { name: 'Ажлаа нэг хэмнэлд оруул.' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Нууц үг')).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByRole('button', { name: /Нэвтрэх/ })).toBeEnabled()
  })

  it('has no automatically detectable accessibility violations', async () => {
    const { container } = renderLogin()
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations).toEqual([])
  })
})
