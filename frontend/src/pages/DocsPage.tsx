import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, ArrowUpRight, Search } from 'lucide-react'
import { Breadcrumbs, BreadcrumbItem } from '@astryxdesign/core/Breadcrumbs'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Divider } from '@astryxdesign/core/Divider'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { Layout, LayoutContent, LayoutPanel } from '@astryxdesign/core/Layout'
import { List, ListItem } from '@astryxdesign/core/List'
import { Markdown } from '@astryxdesign/core/Markdown'
import { Outline, useOutlineFromMarkdown } from '@astryxdesign/core/Outline'
import { Selector } from '@astryxdesign/core/Selector'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  DOCS_ARTICLES, DOCS_FEATURED, DOCS_GROUPS, articleKey, docsArticle, docsGroupArticles, groupKey,
  type DocsArticle, type DocsAudience,
} from '../components/docs/catalog'
import { registerDocsMessages } from '../locales/docs'

registerDocsMessages()

/** Sticky app header height: the outline lands headings below it. */
const HEADER_OFFSET = 88
const NAV_QUERY = '(min-width: 1100px)'
const OUTLINE_QUERY = '(min-width: 1440px)'

const AUDIENCE_COLOR: Record<DocsAudience, 'gray' | 'blue' | 'purple'> = { everyone: 'gray', managers: 'blue', admins: 'purple' }

function useMedia(query: string) {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && Boolean(window.matchMedia?.(query).matches))
  useEffect(() => {
    const media = window.matchMedia?.(query)
    if (!media) return
    const onChange = () => setMatches(media.matches)
    onChange()
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])
  return matches
}

/** Plain text of a Markdown body, for search. */
const searchable = (markdown: string) => markdown.replace(/[#>*_`|[\]()-]/g, ' ').replace(/\s+/g, ' ').toLowerCase()

function useDocsSearch(query: string) {
  const { t, i18n } = useTranslation()
  return useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return null
    const terms = needle.split(/\s+/)
    return DOCS_ARTICLES
      .map((article) => {
        const title = t(articleKey(article.id, 'title')).toLowerCase()
        const summary = t(articleKey(article.id, 'summary')).toLowerCase()
        const body = searchable(t(articleKey(article.id, 'body')))
        if (!terms.every((term) => title.includes(term) || summary.includes(term) || body.includes(term))) return null
        const score = terms.reduce((sum, term) => sum + (title.includes(term) ? 4 : 0) + (summary.includes(term) ? 2 : 0) + (body.includes(term) ? 1 : 0), 0)
        return { article, score }
      })
      .filter((hit): hit is { article: DocsArticle; score: number } => hit !== null)
      .sort((a, b) => b.score - a.score)
      .map((hit) => hit.article)
    // The catalogue is static; results only change with the query or the UI language.
  }, [query, t, i18n.language])
}

/** In-app documentation: a docs home and one page per article, at `/docs` and `/docs/:articleId`. */
export function DocsPage() {
  const { t } = useTranslation()
  const { articleId } = useParams()
  const navigate = useNavigate()
  const showNav = useMedia(NAV_QUERY)
  const showOutline = useMedia(OUTLINE_QUERY)
  const [query, setQuery] = useState('')
  const results = useDocsSearch(query)
  const article = docsArticle(articleId)

  useEffect(() => { window.scrollTo?.({ top: 0 }) }, [articleId])

  if (articleId && !article) return <Navigate to="/docs" replace />

  const open = (id: string) => { setQuery(''); navigate(`/docs/${id}`) }

  const search = <TextInput
    label={t('docs.search.label')} isLabelHidden value={query} onChange={setQuery}
    placeholder={t('docs.search.placeholder')} startIcon={Search} hasClear width="100%"
  />

  return <Layout
    height="auto"
    start={showNav ? <LayoutPanel width={264} hasDivider role="navigation" label={t('docs.nav.label')} isScrollable={false} padding={0} className="docs-rail">
      <VStack gap={3}>
        {article && search}
        <DocsNav activeId={article?.id} results={results} onOpen={open} />
      </VStack>
    </LayoutPanel> : undefined}
    content={<LayoutContent padding={0} isScrollable={false} className={showNav ? 'docs-main' : undefined}>
      {article
        ? <DocsArticleView article={article} showOutline={showOutline} compactNav={showNav ? null : search} results={showNav ? null : results} onOpen={open} />
        : <DocsHome search={search} results={results} onOpen={open} />}
    </LayoutContent>}
  />
}

function DocsNav({ activeId, results, onOpen }: { activeId?: string; results: DocsArticle[] | null; onOpen: (id: string) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  if (results) return <SearchResults results={results} onOpen={onOpen} />
  return <VStack gap={3}>
    <List density="compact">
      <ListItem label={t('docs.home')} isSelected={!activeId} onClick={() => navigate('/docs')} />
    </List>
    {DOCS_GROUPS.map((group) => <List key={group.id} density="compact" header={<Text type="label" color="secondary">{t(groupKey(group.id, 'title'))}</Text>}>
      {docsGroupArticles(group.id).map((article) => <ListItem key={article.id} label={t(articleKey(article.id, 'title'))} isSelected={article.id === activeId} onClick={() => onOpen(article.id)} />)}
    </List>)}
  </VStack>
}

function SearchResults({ results, onOpen }: { results: DocsArticle[]; onOpen: (id: string) => void }) {
  const { t } = useTranslation()
  if (!results.length) return <EmptyState title={t('docs.search.emptyTitle')} description={t('docs.search.emptyDescription')} />
  return <List density="compact" hasDividers header={<Text type="label" color="secondary">{t('docs.search.results', { n: results.length })}</Text>}>
    {results.map((article) => <ListItem key={article.id} label={t(articleKey(article.id, 'title'))} description={t(groupKey(article.group, 'title'))} onClick={() => onOpen(article.id)} />)}
  </List>
}

function AudienceToken({ audience }: { audience: DocsAudience }) {
  const { t } = useTranslation()
  return <Token size="sm" color={AUDIENCE_COLOR[audience]} label={t(`docs.audience.${audience}`)} />
}

function DocsHome({ search, results, onOpen }: { search: ReactNode; results: DocsArticle[] | null; onOpen: (id: string) => void }) {
  const { t } = useTranslation()
  return <VStack gap={6}>
    <VStack gap={2}>
      <Text type="label" color="accent">{t('docs.kicker')}</Text>
      <Heading level={1}>{t('docs.title')}</Heading>
      <Text color="secondary">{t('docs.subtitle')}</Text>
    </VStack>
    {search}
    {results
      ? <Card padding={2}><SearchResults results={results} onOpen={onOpen} /></Card>
      : <>
        <VStack gap={3}>
          <Heading level={2}>{t('docs.featured')}</Heading>
          <Grid columns={{ minWidth: 220, repeat: 'fit' }} gap={3}>
            {DOCS_FEATURED.map((id) => <Card key={id} padding={4}>
              <VStack gap={2}>
                <Heading level={3}>{t(articleKey(id, 'title'))}</Heading>
                <Text color="secondary">{t(articleKey(id, 'summary'))}</Text>
                <HStack><Button label={t('docs.read')} variant="secondary" size="sm" endContent={<ArrowRight size={14} />} onClick={() => onOpen(id)} /></HStack>
              </VStack>
            </Card>)}
          </Grid>
        </VStack>
        <VStack gap={3}>
          <Heading level={2}>{t('docs.allTopics')}</Heading>
          <Grid columns={{ minWidth: 300, repeat: 'fit' }} gap={3}>
            {DOCS_GROUPS.map((group) => {
              const Icon = group.icon
              return <Card key={group.id} padding={4}>
                <VStack gap={2}>
                  <HStack gap={2} vAlign="center">
                    <Icon size={18} strokeWidth={1.8} aria-hidden />
                    <Heading level={3}>{t(groupKey(group.id, 'title'))}</Heading>
                  </HStack>
                  <Text type="supporting">{t(groupKey(group.id, 'description'))}</Text>
                  <List density="compact">
                    {docsGroupArticles(group.id).map((article) => <ListItem key={article.id} label={t(articleKey(article.id, 'title'))} onClick={() => onOpen(article.id)} />)}
                  </List>
                </VStack>
              </Card>
            })}
          </Grid>
        </VStack>
      </>}
  </VStack>
}

function DocsArticleView({ article, showOutline, compactNav, results, onOpen }: {
  article: DocsArticle
  showOutline: boolean
  /** Search field shown above the article when the side navigation is hidden. */
  compactNav: ReactNode | null
  results: DocsArticle[] | null
  onOpen: (id: string) => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const body = t(articleKey(article.id, 'body'))
  const outline = useOutlineFromMarkdown(body)
  const index = DOCS_ARTICLES.indexOf(article)
  const previous = DOCS_ARTICLES[index - 1]
  const next = DOCS_ARTICLES[index + 1]
  const group = t(groupKey(article.group, 'title'))

  const articleOptions = useMemo(() => DOCS_GROUPS.map((item) => ({
    type: 'section' as const,
    title: t(groupKey(item.id, 'title')),
    options: docsGroupArticles(item.id).map((entry) => ({ value: entry.id, label: t(articleKey(entry.id, 'title')) })),
  })), [t])

  // Links inside an article stay in the app: `/docs/…` and module routes open without a reload.
  const onLinkClick = (href: string, event: MouseEvent) => {
    if (!href.startsWith('/')) return
    event.preventDefault()
    navigate(href)
    return false
  }

  const content = <VStack gap={5}>
    {compactNav && <VStack gap={2}>
      <HStack gap={2}>
        <Selector label={t('docs.nav.jump')} isLabelHidden options={articleOptions} value={article.id} onChange={onOpen} width="100%" />
      </HStack>
      {compactNav}
      {results && <Card padding={2}><SearchResults results={results} onOpen={onOpen} /></Card>}
    </VStack>}

    <VStack gap={3}>
      <Breadcrumbs variant="supporting" label={t('docs.breadcrumbs')}>
        <BreadcrumbItem onClick={() => navigate('/docs')}>{t('docs.title')}</BreadcrumbItem>
        <BreadcrumbItem isCurrent={false}>{group}</BreadcrumbItem>
        <BreadcrumbItem isCurrent>{t(articleKey(article.id, 'title'))}</BreadcrumbItem>
      </Breadcrumbs>
      <Heading level={1}>{t(articleKey(article.id, 'title'))}</Heading>
      <Text type="large" color="secondary">{t(articleKey(article.id, 'summary'))}</Text>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <AudienceToken audience={article.audience} />
        {article.route && <Button label={t('docs.openPage')} variant="secondary" size="sm" endContent={<ArrowUpRight size={14} />} onClick={() => navigate(article.route as string)} />}
      </HStack>
    </VStack>

    <Divider />
    <Markdown headingLevelStart={1} contentWidth={720} onLinkClick={onLinkClick}>{body}</Markdown>
    <Divider />

    <HStack gap={3} hAlign={previous ? 'between' : 'end'} wrap="wrap">
      {previous && <Button label={t(articleKey(previous.id, 'title'))} variant="ghost" icon={<ArrowLeft size={15} />} onClick={() => onOpen(previous.id)} tooltip={t('docs.previous')} />}
      {next && <Button label={t(articleKey(next.id, 'title'))} variant="ghost" endContent={<ArrowRight size={15} />} onClick={() => onOpen(next.id)} tooltip={t('docs.next')} />}
    </HStack>
  </VStack>

  if (!showOutline || outline.length < 2) return content
  return <Layout
    height="auto"
    content={<LayoutContent padding={0} isScrollable={false}>{content}</LayoutContent>}
    end={<LayoutPanel width={232} isScrollable={false} padding={0} className="docs-rail docs-outline" label={t('docs.outline')}>
      <VStack gap={2}>
        <Text type="label" color="secondary">{t('docs.outline')}</Text>
        <Outline key={article.id} items={outline} density="compact" label={t('docs.outline')} offset={HEADER_OFFSET} />
      </VStack>
    </LayoutPanel>}
  />
}
