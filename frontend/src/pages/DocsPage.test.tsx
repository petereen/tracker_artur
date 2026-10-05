import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DocsPage } from './DocsPage'
import { DOCS_ARTICLES, DOCS_GROUPS, articleKey, docsArticle, groupKey } from '../components/docs/catalog'
import docs from '../locales/docs'

/** Width the page believes it has; the side navigation and outline appear on wide screens. */
let wide = false

beforeEach(() => {
  wide = false
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide && query.includes('min-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  }))
})

function Where() {
  return <output data-testid="path">{useLocation().pathname}</output>
}

function renderDocs(path = '/docs') {
  return render(<MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="docs" element={<DocsPage />} />
      <Route path="docs/:articleId" element={<DocsPage />} />
      <Route path="*" element={<div>Module page</div>} />
    </Routes>
    <Where />
  </MemoryRouter>)
}

describe('docs catalogue', () => {
  it('has a title, summary and body for every article and group in every language', () => {
    const missing: string[] = []
    for (const language of ['mn', 'ru', 'en'] as const) {
      const messages: Record<string, string> = docs[language]
      for (const article of DOCS_ARTICLES) {
        for (const part of ['title', 'summary', 'body'] as const) if (!messages[articleKey(article.id, part)]?.trim()) missing.push(`${language}:${articleKey(article.id, part)}`)
      }
      for (const group of DOCS_GROUPS) if (!messages[groupKey(group.id, 'title')]) missing.push(`${language}:${groupKey(group.id, 'title')}`)
    }
    expect(missing).toEqual([])
  })

  it('only links articles that exist, and every group has articles', () => {
    const broken: string[] = []
    for (const language of ['mn', 'ru', 'en'] as const) {
      const messages: Record<string, string> = docs[language]
      for (const article of DOCS_ARTICLES) {
        for (const [, id] of messages[articleKey(article.id, 'body')].matchAll(/\]\(\/docs\/([^)\s]+)\)/g)) if (!docsArticle(id)) broken.push(`${language}:${article.id} → ${id}`)
      }
    }
    expect(broken).toEqual([])
    expect(DOCS_GROUPS.every((group) => DOCS_ARTICLES.some((article) => article.group === group.id))).toBe(true)
  })
})

describe('DocsPage', () => {
  it('lists every topic on the docs home and opens an article', () => {
    renderDocs()
    expect(screen.getByRole('heading', { level: 1, name: 'Заавар' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Админ тохиргоо' })).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Ажлын цаг' })[0])
    expect(screen.getByTestId('path')).toHaveTextContent('/docs/worktime')
    expect(screen.getByRole('heading', { level: 1, name: 'Ажлын цаг' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Автомат цаг бүртгэл (гар утасны апп)' })).toBeInTheDocument()
    expect(screen.getByText('Бүх ажилтан')).toBeInTheDocument()
  })

  it('searches article bodies and shows an empty state when nothing matches', () => {
    renderDocs()
    const search = screen.getByRole('textbox', { name: 'Заавраас хайх' })
    fireEvent.change(search, { target: { value: 'pairing' } })
    expect(screen.getByText('Ажлын цаг ба процесс')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Бүх сэдэв' })).toBeNull()

    fireEvent.change(search, { target: { value: 'zzzz-no-such-topic' } })
    expect(screen.getByText('Илэрц олдсонгүй')).toBeInTheDocument()
  })

  it('moves between articles and opens the described screen', () => {
    renderDocs('/docs/overview')
    fireEvent.click(screen.getByRole('button', { name: 'Нэвтрэх ба аюулгүй байдал' }))
    expect(screen.getByTestId('path')).toHaveTextContent('/docs/sign-in')

    fireEvent.click(screen.getByRole('button', { name: 'OYUNS-ийн тойм' }))
    fireEvent.click(screen.getByRole('button', { name: 'Хуудсыг нээх' }))
    expect(screen.getByText('Module page')).toBeInTheDocument()
  })

  it('follows in-article links without leaving the app', () => {
    renderDocs('/docs/overview')
    const article = screen.getByRole('heading', { level: 1, name: 'OYUNS-ийн тойм' }).closest('.astryx-layout-content') ?? document.body
    fireEvent.click(within(article as HTMLElement).getByRole('link', { name: 'Хэрэглэгч ба эрх' }))
    expect(screen.getByTestId('path')).toHaveTextContent('/docs/admin-people')
  })

  it('shows the section navigation and page outline on wide screens', () => {
    wide = true
    renderDocs('/docs/tasks')
    const nav = screen.getByRole('navigation', { name: 'Зааврын бүлгүүд' })
    expect(within(nav).getByRole('button', { name: 'Даалгавар' }).closest('li')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('navigation', { name: 'Энэ хуудсанд' })).toHaveTextContent('Даалгавар үүсгэх')

    fireEvent.click(within(nav).getByRole('button', { name: 'Календарь' }))
    expect(screen.getByTestId('path')).toHaveTextContent('/docs/calendar')
  })

  it('sends unknown articles back to the docs home', () => {
    renderDocs('/docs/no-such-article')
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/docs$/)
  })
})
