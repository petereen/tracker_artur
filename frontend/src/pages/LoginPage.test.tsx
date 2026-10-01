import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import * as axe from 'axe-core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { LoginPage } from './LoginPage'

const mutateAsync = vi.fn()

vi.mock('../api/enterprise', () => ({
  useEnterpriseLogin: () => ({ mutateAsync, isPending: false }),
  useAuthCapabilities: () => ({ data: { telegram_native: false }, isLoading: false }),
}))

function renderLogin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><LoginPage /></QueryClientProvider>)
}

describe('enterprise login', () => {
  beforeEach(() => mutateAsync.mockReset())
  afterEach(async () => { await i18n.changeLanguage('mn') })

  it('shows the browser Telegram login button', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /Telegram-аар нэвтрэх/ })).toBeEnabled()
  })

  it('has explicit labels and a clear submit action', () => {
    renderLogin()
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Таны ажилнэг дор, цэгцтэй, хялбар.')
    expect(screen.getByLabelText('Нэвтрэх нэр')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Нууц үг')).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByRole('button', { name: /Нэвтрэх/ })).toBeEnabled()
  })

  it('switches the page to Russian and remembers the choice', async () => {
    renderLogin()
    fireEvent.click(screen.getByRole('button', { name: 'Русский' }))
    expect(await screen.findByLabelText('Логин')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Пароль')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Войти через Telegram/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Русский' })).toHaveAttribute('aria-pressed', 'true')
    expect(document.documentElement.lang).toBe('ru')
    expect(window.localStorage.getItem('oyuns.language')).toBe('ru')
  })

  it('has no automatically detectable accessibility violations', async () => {
    const { container } = renderLogin()
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations).toEqual([])
  })
})
