import {
  BookOpen, CalendarCheck2, Layers3, LifeBuoy, Settings2, Sparkles, UsersRound, type LucideIcon,
} from 'lucide-react'

/**
 * Table of contents for the in-app documentation (`/docs`).
 *
 * Text lives in the `docs` locale domain: a group has `docs.group.<id>.title|description`,
 * an article has `docs.article.<id>.title|summary|body` (body is Markdown, `##` sections
 * feed the page outline). Adding an article = one entry here + its three keys in every language.
 */
export type DocsGroupId = 'start' | 'daily' | 'ai' | 'management' | 'erp' | 'admin' | 'help'
/** Who the article is written for; shown as a token, never used to hide the article. */
export type DocsAudience = 'everyone' | 'managers' | 'admins'

export interface DocsGroup { id: DocsGroupId; icon: LucideIcon }
export interface DocsArticle {
  id: string
  group: DocsGroupId
  audience: DocsAudience
  /** The app screen the article describes, offered as an “open” button. */
  route?: string
}

export const DOCS_GROUPS: DocsGroup[] = [
  { id: 'start', icon: BookOpen },
  { id: 'daily', icon: CalendarCheck2 },
  { id: 'ai', icon: Sparkles },
  { id: 'management', icon: UsersRound },
  { id: 'erp', icon: Layers3 },
  { id: 'admin', icon: Settings2 },
  { id: 'help', icon: LifeBuoy },
]

/** Reading order: the previous/next links at the foot of an article follow this list. */
export const DOCS_ARTICLES: DocsArticle[] = [
  { id: 'overview', group: 'start', audience: 'everyone', route: '/' },
  { id: 'sign-in', group: 'start', audience: 'everyone' },
  { id: 'navigation', group: 'start', audience: 'everyone' },
  { id: 'profile', group: 'start', audience: 'everyone', route: '/profile' },

  { id: 'today', group: 'daily', audience: 'everyone', route: '/' },
  { id: 'worktime', group: 'daily', audience: 'everyone', route: '/worktime' },
  { id: 'tasks', group: 'daily', audience: 'everyone', route: '/tasks' },
  { id: 'calendar', group: 'daily', audience: 'everyone', route: '/calendar' },
  { id: 'chat', group: 'daily', audience: 'everyone', route: '/chat' },
  { id: 'reports', group: 'daily', audience: 'everyone', route: '/reports' },
  { id: 'plans-projects', group: 'daily', audience: 'everyone', route: '/plans' },
  { id: 'news-files', group: 'daily', audience: 'everyone', route: '/company-files' },

  { id: 'assistant', group: 'ai', audience: 'everyone' },
  { id: 'telegram', group: 'ai', audience: 'everyone' },

  { id: 'hr', group: 'management', audience: 'managers', route: '/hr' },
  { id: 'analytics', group: 'management', audience: 'managers', route: '/analytics' },
  { id: 'contracts', group: 'management', audience: 'everyone', route: '/contracts' },

  { id: 'crm', group: 'erp', audience: 'everyone', route: '/erp/crm' },
  { id: 'budget', group: 'erp', audience: 'managers', route: '/erp/budget' },
  { id: 'accounts', group: 'erp', audience: 'managers', route: '/erp/accounts' },
  { id: 'payroll', group: 'erp', audience: 'admins', route: '/erp/payroll' },

  { id: 'admin-organization', group: 'admin', audience: 'admins', route: '/administration/organization/profile' },
  { id: 'admin-people', group: 'admin', audience: 'admins', route: '/administration/people/users' },
  { id: 'admin-worktime', group: 'admin', audience: 'admins', route: '/administration/workflows/worktime' },
  { id: 'admin-integrations', group: 'admin', audience: 'admins', route: '/administration/integrations/overview' },
  { id: 'admin-ai', group: 'admin', audience: 'admins', route: '/administration/ai/knowledge' },
  { id: 'admin-security', group: 'admin', audience: 'admins', route: '/administration/security/authentication' },

  { id: 'faq', group: 'help', audience: 'everyone' },
]

/** Articles a newcomer should read first; shown on the docs home page. */
export const DOCS_FEATURED = ['overview', 'navigation', 'worktime'] as const

export const docsArticle = (id: string | undefined) => DOCS_ARTICLES.find((article) => article.id === id)
export const docsGroupArticles = (group: DocsGroupId) => DOCS_ARTICLES.filter((article) => article.group === group)

export const articleKey = (id: string, part: 'title' | 'summary' | 'body') => `docs.article.${id}.${part}`
export const groupKey = (id: DocsGroupId, part: 'title' | 'description') => `docs.group.${id}.${part}`
