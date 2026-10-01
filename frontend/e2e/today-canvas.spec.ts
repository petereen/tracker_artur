import { expect, Page, test } from '@playwright/test'

const SHOTS = process.env.TODAY_SCREENSHOT_DIR

type Layout = { widgets: any[] | null; updated_at: number | null }

async function mockTodayApi(page: Page) {
  const saved: Layout[] = []
  let layout: Layout = { widgets: null, updated_at: null }
  const now = new Date()
  const iso = (offsetMinutes: number) => new Date(now.getTime() + offsetMinutes * 60_000).toISOString()
  const days = Array.from({ length: 7 }, (_, index) => ({ date: `2026-09-${String(22 + index).padStart(2, '0')}`, worked_minutes: [420, 480, 390, 510, 450, 0, 0][index], completed_tasks: [3, 5, 2, 6, 4, 0, 1][index] }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'today-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'manager@example.test', employee_id: 1, locale: 'mn', roles: ['admin', 'manager'], account_roles: ['admin', 'manager'], workspace_mode: 'manager', name: 'Оюун' } })
    if (path.endsWith('/auth/preferences/today-layout')) {
      if (request.method() === 'PUT') { layout = request.postDataJSON(); saved.push(layout); return route.fulfill({ json: layout }) }
      return route.fulfill({ json: layout })
    }
    if (path.endsWith('/auth/preferences/world-clock')) return route.fulfill({ json: { clocks: ['Asia/Ulaanbaatar', 'Asia/Tokyo', 'Europe/London', 'America/New_York'], display_mode: 'digital', hour_format: '24' } })
    if (path.endsWith('/auth/preferences/workspace-mode')) return route.fulfill({ json: { mode: 'manager' } })
    if (path.endsWith('/clock/status')) return route.fulfill({ json: { active: { id: 9, employee_id: 1, local_work_date: now.toISOString().slice(0, 10), project_id: null, task_id: null, entry_type: 'work', mode: 'in_person', started_at: iso(-135), ended_at: null }, today_entries: [{ id: 9, employee_id: 1, local_work_date: now.toISOString().slice(0, 10), project_id: null, task_id: null, entry_type: 'work', mode: 'in_person', started_at: iso(-135), ended_at: null }], timezone: 'Asia/Ulaanbaatar', server_time: now.toISOString() } })
    if (path.endsWith('/analytics/summary')) return route.fulfill({ json: { active_projects: 6, completed_tasks: 21, completion_rate: 72.4, worked_minutes: 2250, average_work_minutes: 450, report_submission_rate: 88.0 } })
    if (path.endsWith('/analytics/daily')) return route.fulfill({ json: { days } })
    if (path.endsWith('/announcements')) return route.fulfill({ json: [
      { id: 1, title: 'Шинэ ээлжийн амралтын журам батлагдлаа', body: '## Гол өөрчлөлт\n\nАмралтын хүсэлтийг **14 хоногийн өмнө** гаргана.', is_pinned: true, published_at: iso(-60 * 24), author_name: 'Хүний нөөц' },
      { id: 2, title: 'Сарын нэгдсэн хурал баасан гарагт 16:00', published_at: iso(-60 * 5), author_name: 'Удирдлага', body: 'Хурлын танхимд.' },
      { id: 3, title: 'ERP системийн шинэчлэл: нүүр хуудас виджеттэй боллоо', published_at: iso(-60 * 30), body: 'Long-press хийж засварлана.' },
      { id: 4, title: 'Оффисын интернэт засвар Бямба гарагт', published_at: iso(-60 * 50), body: '…' },
      { id: 5, title: 'Шинэ ажилтнуудаа угтъя', published_at: iso(-60 * 80), body: '…' },
      { id: 6, title: 'Q3 төсвийн гүйцэтгэлийн тайлан', published_at: iso(-60 * 120), body: '…' },
    ] })
    if (path.endsWith('/tasks')) return route.fulfill({ json: [
      { id: 11, title: 'Нийлүүлэгчийн гэрээ хянах', description: null, workflow_status: 'in_progress', priority: 1, primary_owner_id: 1, primary_owner_name: 'Оюун', assignee_ids: [1], assignee_names: ['Оюун'], start_at: null, deadline_at: iso(120), work_location: null, version: 1 },
      { id: 12, title: 'Сарын тайлан бэлтгэх', description: null, workflow_status: 'to_do', priority: 2, primary_owner_id: 1, primary_owner_name: 'Оюун', assignee_ids: [1], assignee_names: ['Оюун'], start_at: null, deadline_at: iso(300), work_location: null, version: 1 },
    ] })
    if (path.endsWith('/checkins/today')) return route.fulfill({ json: { template: { id: 1, questions: [{ id: 1, prompt: { mn: 'Өнөөдрийн хамгийн чухал ажил?' }, answer_type: 'text', is_required: true }] }, checkin: null } })
    if (path.endsWith('/workers')) return route.fulfill({ json: [] })
    if (path.endsWith('/erp/meta')) return route.fulfill({ json: { modules: {} } })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path.endsWith('/chat/unread-count')) return route.fulfill({ json: { unread_count: 0 } })
    if (path.includes('/calendar')) return route.fulfill({ json: { tasks: [], entries: [], time_blocks: [] } })
    if (path.endsWith('/projects')) return route.fulfill({ json: [] })
    return route.fulfill({ status: 404, json: { detail: 'not mocked' } })
  })
  return { saved }
}

const box = async (page: Page, selector: string) => (await page.locator(selector).boundingBox())!

test.describe('desktop grid', () => {
test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'pointer drag on the desktop grid')
  await page.setViewportSize({ width: 1440, height: 1000 })
})

test('default canvas: compact clock strip, no legacy headers, check-in hidden', async ({ page }) => {
  await mockTodayApi(page)
  await page.goto('/')
  await expect(page.locator('.today-canvas:not(.is-stacked)')).toBeVisible()
  await expect(page.locator('.world-clock-chip')).toHaveCount(4)
  await expect(page.locator('.today-news-row')).toHaveCount(6)
  await expect(page.locator('.today-kpi-tile')).toHaveCount(4)
  await expect(page.getByText('Байгууллагын тойм')).toHaveCount(0)
  await expect(page.getByText('Нийт гүйцэтгэлийн үзүүлэлт')).toHaveCount(0)
  await expect(page.locator('.period-filter, .daily-focus')).toHaveCount(0)
  const strip = await box(page, '[data-widget-id="world-clock-default"]')
  expect(strip.height).toBeLessThanOrEqual(48)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-default.png`, fullPage: true })

  await page.getByRole('button', { name: /Шинэ ээлжийн амралтын журам/ }).click()
  await expect(page.getByRole('dialog').getByText('Гол өөрчлөлт')).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-news-dialog.png` })
})

test('edit mode: drag to move, corner to resize, library drag to add — all persisted', async ({ page }) => {
  const api = await mockTodayApi(page)
  await page.goto('/')
  await expect(page.locator('.today-canvas:not(.is-stacked)')).toBeVisible()
  await page.getByRole('button', { name: 'Засварлах' }).click()
  await expect(page.locator('.today-grid-overlay')).toBeVisible()
  await expect(page.locator('.today-widget-remove')).toHaveCount(7)

  // Move the calendar (top-right of the lower row) to the far left of that row.
  const calendar = await box(page, '[data-widget-id="mini-calendar-default"]')
  const tasks = await box(page, '[data-widget-id="tasks-default"]')
  await page.mouse.move(calendar.x + 40, calendar.y + 60)
  await page.mouse.down()
  for (let step = 1; step <= 12; step += 1) await page.mouse.move(calendar.x + 40 - ((calendar.x - tasks.x) * step) / 12, calendar.y + 60)
  await expect(page.locator('.today-drop-placeholder')).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-dragging.png` })
  await page.mouse.up()
  await expect.poll(() => api.saved.length).toBeGreaterThan(0)
  const moved = api.saved.at(-1)!.widgets!.find((widget) => widget.type === 'mini-calendar')
  expect(moved.x).toBe(0)

  // Resize the KPI widget one column wider... after the move it may have shifted, so read it fresh.
  const kpiBefore = api.saved.at(-1)!.widgets!.find((widget) => widget.type === 'kpi')
  const handle = await box(page, '[data-widget-id="kpi-default"] .today-widget-resize')
  await page.mouse.move(handle.x + 7, handle.y + 7)
  await page.mouse.down()
  await page.mouse.move(handle.x + 60, handle.y + 70, { steps: 8 })
  await page.mouse.up()
  await expect.poll(() => api.saved.at(-1)!.widgets!.find((widget) => widget.type === 'kpi').h).toBeGreaterThan(kpiBefore.h)

  // Drag a Notes widget in from the library.
  await page.getByRole('button', { name: 'Виджет нэмэх' }).click()
  const library = page.getByRole('complementary', { name: 'Виджетийн сан' })
  await expect(library).toBeVisible()
  await page.waitForTimeout(300) // let the slide-in finish before capturing
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-library.png` })
  const card = await library.locator('.today-library-card', { hasText: 'Тэмдэглэл' }).boundingBox()
  const canvas = await box(page, '.today-canvas')
  await page.mouse.move(card!.x + 60, card!.y + 20)
  await page.mouse.down()
  await page.mouse.move(canvas.x + 200, canvas.y + 80, { steps: 15 })
  await expect(page.locator('.today-library-ghost.is-over')).toBeVisible()
  await page.mouse.up()
  await expect(page.locator('.today-notes')).toBeVisible()
  await expect.poll(() => api.saved.at(-1)!.widgets!.some((widget) => widget.type === 'notes')).toBe(true)

  await page.getByRole('button', { name: 'Виджетийн санг хаах' }).click()
  await page.getByRole('button', { name: 'Болсон' }).click()
  await expect(page.locator('.today-canvas.is-editing')).toHaveCount(0)
  await page.locator('.today-notes-input').fill('Ирэх долоо хоногт: нийлүүлэгчтэй уулзах')
  await expect.poll(() => api.saved.at(-1)!.widgets!.find((widget) => widget.type === 'notes').settings.text, { timeout: 4000 }).toContain('нийлүүлэгчтэй')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-after-edit.png`, fullPage: true })
})

test('widget settings switch the KPI period to the previous week', async ({ page }) => {
  const api = await mockTodayApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Засварлах' }).click()
  await page.getByRole('button', { name: 'Гүйцэтгэлийн үзүүлэлт тохиргоо' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByText('Өмнөх долоо хоног').click()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-settings.png` })
  await dialog.getByRole('button', { name: 'Хадгалах' }).click()
  await expect(page.locator('.today-kpi .today-widget-meta')).toHaveText('Өмнөх долоо хоног')
  await expect.poll(() => api.saved.at(-1)?.widgets?.find((widget) => widget.type === 'kpi').settings.period).toBe('previous_week')
})

test('dark theme keeps widgets legible', async ({ page }) => {
  await mockTodayApi(page)
  await page.addInitScript(() => localStorage.setItem('oyuns-theme', 'dark'))
  await page.goto('/')
  await expect(page.locator('html[data-theme="dark"]')).toHaveCount(1)
  await expect(page.locator('.today-kpi-tile')).toHaveCount(4)
  await page.getByRole('button', { name: 'Засварлах' }).click()
  await page.waitForTimeout(300) // controls pop in
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-dark-edit.png` })
})
})

test.describe('phone', () => {
  test.beforeEach(async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'stacked phone layout')
    await page.setViewportSize({ width: 390, height: 844 })
  })

  test('stacks widgets in reading order and reorders with arrow buttons in edit mode', async ({ page }) => {
    const api = await mockTodayApi(page)
    await page.goto('/')
    await expect(page.locator('.today-canvas.is-stacked')).toBeVisible()
    const order = () => page.locator('.today-widget-slot').evaluateAll((slots) => slots.map((slot) => slot.getAttribute('data-widget-id')))
    expect((await order()).slice(0, 3)).toEqual(['world-clock-default', 'worktime-default', 'kpi-default'])
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-phone.png` })
    await page.getByRole('button', { name: 'Засварлах' }).click()
    await page.getByRole('button', { name: 'Гүйцэтгэлийн үзүүлэлт дээш' }).click()
    expect((await order()).slice(0, 3)).toEqual(['world-clock-default', 'kpi-default', 'worktime-default'])
    await expect.poll(() => api.saved.length).toBeGreaterThan(0)
    // Widgets size to their content on phones (no empty space under the clock buttons).
    const worktime = await page.locator('[data-widget-id="worktime-default"] .today-widget-card').boundingBox()
    expect(worktime!.height).toBeLessThan(324)
    await page.waitForTimeout(300)
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/today-phone-edit.png` })
  })
})
