import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { choice, TypeSafeClient } from '@typesafe-ai/sdk'

export const ROUTES = [
  'knowledge_search',
  'employee_lookup',
  'employee_count',
  'tasks_lookup',
  'projects_lookup',
  'calendar_lookup',
  'stats_lookup',
  'erp_lookup',
  'exchange_rate_lookup',
  'frontier_reasoning',
  'unsupported_lookup',
] as const

export type Route = typeof ROUTES[number]
export type LocalRoute = Exclude<Route, 'frontier_reasoning' | 'unsupported_lookup'>
export type Channel = 'web' | 'telegram'

export interface HistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export interface EvaluateRequest {
  message: string
  history?: HistoryItem[]
  channel: Channel
  locale: 'mn' | 'en' | 'ru' | 'other'
  timezone?: string
  current_time?: string
  allowed_handlers?: LocalRoute[]
  currency_candidates?: string[]
}

export interface EvaluateResponse {
  route: Route
  confidence: number
  probabilities: Record<string, number>
  arguments: Record<string, unknown>
  model: string
  usage: Record<string, unknown>
}

const port = Number(process.env.PORT || 8030)
const sharedSecret = process.env.JEV_ROUTER_SHARED_SECRET || ''
const model = process.env.TYPESAFE_MODEL || 'jev-1.13.0'
const timeout = Math.max(250, Number(process.env.TYPESAFE_TIMEOUT_MS || 2500))
const maxAttempts = Math.max(1, Math.min(3, Number(process.env.TYPESAFE_MAX_ATTEMPTS || 2)))

const routeDescriptions: Record<Route, string> = {
  knowledge_search: 'Search authorized company knowledge or files and return matching passages or file references without synthesizing an answer.',
  employee_lookup: 'Look up one or more employees or their basic directory fields.',
  employee_count: 'Count or group authorized employees, such as active employees or employees by job title.',
  tasks_lookup: 'List authorized tasks, blockers, or task status for the caller or an explicitly requested scope.',
  projects_lookup: 'List authorized projects, plans, or milestones.',
  calendar_lookup: 'Read authorized calendar events, availability, or schedules.',
  stats_lookup: 'Read one governed OYUNS statistic for a standard time window.',
  erp_lookup: 'Read the ERP dashboard or a bounded list of ERP documents.',
  exchange_rate_lookup: 'Read a current configured exchange rate or published rate set.',
  frontier_reasoning: 'Requires synthesis, comparison, writing, ambiguity resolution, a mutation, or another generative reasoning model.',
  unsupported_lookup: 'Looks like a lookup, but no supported deterministic local handler can safely answer it.',
}

const timeframeCriteria = {
  today: 'The user explicitly asks for today or the current day.',
  this_week: 'The user explicitly asks for this week or the current work week.',
  this_month: 'The user explicitly asks for this month.',
  custom: 'The user supplies a concrete custom date or date range that the application can resolve.',
  unspecified: 'No time window is stated; the handler default is safe to use.',
}

const scopeCriteria = {
  self: 'The request is explicitly about the caller, using the caller identity already supplied by the application.',
  team: 'The request explicitly asks for the caller’s team or permitted team scope.',
  organization: 'The request explicitly asks for the whole organization and the application may authorize it.',
  unspecified: 'No scope is stated; the handler default is safe to use.',
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function answerOf(result: any, key: string): any {
  return result?.answers?.[key]
}

function choiceValue(result: any, key: string, fallback: string): string {
  const value = answerOf(result, key)?.choice
  return typeof value === 'string' ? value : fallback
}

function confidenceOf(result: any, key: string): number {
  return finiteNumber(answerOf(result, key)?.confidence, 0)
}

function probabilitiesOf(result: any, key: string): Record<string, number> {
  const probabilities = answerOf(result, key)?.probabilities
  if (!probabilities || typeof probabilities !== 'object') return {}
  return Object.fromEntries(Object.entries(probabilities).map(([label, value]) => [label, finiteNumber(value)]))
}

export function validateRequest(value: unknown): EvaluateRequest {
  if (!value || typeof value !== 'object') throw new Error('invalid_request')
  const input = value as Record<string, unknown>
  const message = typeof input.message === 'string' ? input.message.trim() : ''
  if (!message || message.length > 32_000) throw new Error('invalid_message')
  if (input.channel !== 'web' && input.channel !== 'telegram') throw new Error('invalid_channel')
  const locale = input.locale === 'mn' || input.locale === 'en' || input.locale === 'ru' ? input.locale : 'other'
  const history = Array.isArray(input.history)
    ? input.history.slice(-8).map((item) => {
        if (!item || typeof item !== 'object') throw new Error('invalid_history')
        const row = item as Record<string, unknown>
        if ((row.role !== 'user' && row.role !== 'assistant') || typeof row.content !== 'string' || row.content.length > 8_000) throw new Error('invalid_history')
        return { role: row.role, content: row.content } as HistoryItem
      })
    : []
  const allowed = Array.isArray(input.allowed_handlers)
    ? input.allowed_handlers.filter((item): item is LocalRoute => typeof item === 'string' && ROUTES.includes(item as Route) && item !== 'frontier_reasoning' && item !== 'unsupported_lookup')
    : ROUTES.filter((item): item is LocalRoute => item !== 'frontier_reasoning' && item !== 'unsupported_lookup')
  const currencyCandidates = Array.isArray(input.currency_candidates)
    ? input.currency_candidates.filter((item): item is string => typeof item === 'string' && item.length > 0 && item.length <= 32).slice(0, 20)
    : []
  return {
    message,
    history,
    channel: input.channel,
    locale,
    timezone: typeof input.timezone === 'string' ? input.timezone.slice(0, 64) : undefined,
    current_time: typeof input.current_time === 'string' ? input.current_time.slice(0, 80) : undefined,
    allowed_handlers: allowed,
    currency_candidates: currencyCandidates,
  }
}

export function buildQuestions(request: EvaluateRequest) {
  const allowed = new Set(request.allowed_handlers)
  const routeCriteria = Object.fromEntries([
    ...request.allowed_handlers!.map((route) => [route, routeDescriptions[route]]),
    ['frontier_reasoning', routeDescriptions.frontier_reasoning],
    ['unsupported_lookup', routeDescriptions.unsupported_lookup],
  ])
  const questions: Record<string, any> = {
    route: choice(
      'Which single handler can safely answer the user request without generative synthesis? Choose frontier_reasoning for any mutation, ambiguity, comparison, writing, multi-step reasoning, or request outside the listed local handlers.',
      routeCriteria,
    ),
    timeframe: choice('What time window does the request explicitly specify?', timeframeCriteria),
    scope: choice('What authorized scope does the request explicitly specify?', scopeCriteria),
    completion_state: choice('What task or project completion state does the request explicitly ask for?', {
      open: 'Open, unfinished, or outstanding work.',
      completed: 'Completed work.',
      all: 'Both open and completed work.',
      unspecified: 'No completion state is stated; a safe handler default is acceptable.',
    }),
    project_entity: choice('Which project-management entity does the request explicitly ask to list?', {
      projects: 'Projects.', plans: 'Plans.', milestones: 'Milestones.', unspecified: 'No entity is stated; projects are the safe default.',
    }),
    calendar_intent: choice('What calendar operation does the request explicitly ask for?', {
      events: 'List events.', schedule: 'Read a schedule.', availability: 'Read free/busy availability.', unspecified: 'No operation is stated; availability is the safe default.',
    }),
    stats_metric: choice('Which single governed OYUNS statistic is requested?', {
      task_completion: 'Task completion percentage.', deadline_health: 'Deadline health percentage.', work_hours: 'Worked hours.', utilization: 'Utilization percentage.', billable_ratio: 'Billable ratio.', report_compliance: 'Report compliance percentage.', active_projects: 'Active project count.', budget_burn: 'Budget burn percentage.', unspecified: 'No supported single statistic is explicit.',
    }),
    erp_resource: choice('Which ERP read resource is requested?', {
      dashboard: 'ERP dashboard totals.', documents: 'A bounded list of ERP documents.', unspecified: 'No supported ERP read resource is explicit.',
    }),
    exchange_request_type: choice('What exchange-rate result is requested?', {
      single: 'One provider and currency pair.', all: 'All published rates.', calculated: 'Calculated rates.', unspecified: 'No supported rate result is explicit.',
    }),
  }
  if (request.currency_candidates?.length) {
    questions.currency_pair = choice('Which currency pair did the user request?', {
      ...Object.fromEntries(request.currency_candidates.map((candidate) => [candidate, `The exact currency pair candidate ${candidate}.`])),
      unspecified: 'No currency pair candidate is explicit.',
    })
  }
  // The set is intentionally kept in the request contract for observability;
  // the application still rechecks authorization and argument validity.
  void allowed
  return questions
}

export function evaluateAnswers(request: EvaluateRequest, result: any): EvaluateResponse {
  const routeAnswer = answerOf(result, 'route')
  const route = ROUTES.includes(routeAnswer?.choice) ? routeAnswer.choice as Route : 'frontier_reasoning'
  const relevant = ['route']
  if (route === 'tasks_lookup' || route === 'projects_lookup' || route === 'calendar_lookup' || route === 'stats_lookup') relevant.push('timeframe')
  if (route === 'tasks_lookup' || route === 'projects_lookup' || route === 'calendar_lookup') relevant.push('scope')
  if (route === 'tasks_lookup' || route === 'projects_lookup') relevant.push('completion_state')
  if (route === 'projects_lookup') relevant.push('project_entity')
  if (route === 'calendar_lookup') relevant.push('calendar_intent')
  if (route === 'stats_lookup') relevant.push('stats_metric')
  if (route === 'erp_lookup') relevant.push('erp_resource')
  if (route === 'exchange_rate_lookup') relevant.push('exchange_request_type')
  if (route === 'exchange_rate_lookup' && request.currency_candidates?.length) relevant.push('currency_pair')
  const confidence = Math.min(...relevant.map((key) => confidenceOf(result, key)))
  const probabilities = probabilitiesOf(result, 'route')
  const args: Record<string, unknown> = {
    timeframe: choiceValue(result, 'timeframe', 'unspecified'),
    scope: choiceValue(result, 'scope', 'unspecified'),
    completion_state: choiceValue(result, 'completion_state', 'unspecified'),
    project_entity: choiceValue(result, 'project_entity', 'unspecified'),
    calendar_intent: choiceValue(result, 'calendar_intent', 'unspecified'),
    stats_metric: choiceValue(result, 'stats_metric', 'unspecified'),
    erp_resource: choiceValue(result, 'erp_resource', 'unspecified'),
    exchange_request_type: choiceValue(result, 'exchange_request_type', 'unspecified'),
    currency_pair: request.currency_candidates?.length ? choiceValue(result, 'currency_pair', 'unspecified') : undefined,
  }
  return {
    route,
    confidence,
    probabilities,
    arguments: args,
    model: typeof result?.model === 'string' ? result.model : model,
    usage: result?.usage && typeof result.usage === 'object' ? result.usage : {},
  }
}

let client: TypeSafeClient | null | undefined
function getClient(): TypeSafeClient {
  if (client) return client
  if (client === null || !process.env.TYPESAFE_API_KEY?.trim()) throw new Error('typesafe_not_configured')
  try {
    client = new TypeSafeClient({
      apiKey: process.env.TYPESAFE_API_KEY,
      baseURL: process.env.TYPESAFE_BASE_URL,
      defaultModel: model,
      timeout,
      retry: { maxRetries: Math.max(0, maxAttempts - 1) },
      logLevel: 'warn',
    } as any)
    return client
  } catch (error) {
    client = null
    throw error
  }
}

export async function evaluate(request: EvaluateRequest): Promise<EvaluateResponse> {
  const safe = validateRequest(request)
  const state = {
    message: safe.message,
    recent_history: safe.history,
    channel: safe.channel,
    locale: safe.locale,
    timezone: safe.timezone,
    current_time: safe.current_time,
  }
  const result = await getClient().systemOne({ model, state, questions: buildQuestions(safe) } as any)
  return evaluateAnswers(safe, result)
}

async function readBody(request: IncomingMessage): Promise<string> {
  let body = ''
  for await (const chunk of request) {
    body += chunk.toString()
    if (body.length > 200_000) throw new Error('body_too_large')
  }
  return body
}

function json(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
  response.end(JSON.stringify(body))
}

export function isAuthorized(value: unknown, secret = sharedSecret): boolean {
  return Boolean(secret) && typeof value === 'string' && value === secret
}

export const server = createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    return json(response, 200, { status: 'ok', configured: Boolean(process.env.TYPESAFE_API_KEY?.trim()) })
  }
  if (request.method !== 'POST' || request.url !== '/v1/evaluate') return json(response, 404, { error: 'not_found' })
  if (!isAuthorized(request.headers['x-jev-router-secret'])) return json(response, 401, { error: 'unauthorized' })
  try {
    const body = JSON.parse(await readBody(request))
    const result = await evaluate(body)
    return json(response, 200, result)
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'evaluation_failed'
    const status = detail.startsWith('invalid_') || detail === 'body_too_large' ? 400 : 503
    return json(response, status, { error: status === 400 ? detail : 'evaluation_unavailable' })
  }
})

if (process.env.NODE_ENV !== 'test') server.listen(port)

const shutdown = () => server.close(() => process.exit(0))
process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
