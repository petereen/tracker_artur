import { CDPSession, expect, Page, test } from '@playwright/test'

async function mockWorkspaceApi(page: Page, notificationFetches = { count: 0 }) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'mobile-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'mobile@example.test', locale: 'mn', roles: ['admin'], name: 'Mobile User' } })
    if (path.endsWith('/notifications')) { notificationFetches.count += 1; return route.fulfill({ json: { items: [], unread_count: 0 } }) }
    if (path.endsWith('/workers')) return route.fulfill({ json: [{ id: 2, name: 'Ану', presence: 'in_person', job_title: 'Designer' }] })
    if (path.endsWith('/erp/meta')) return route.fulfill({ json: { modules: {} } })
    if (path.endsWith('/chat/unread-count')) return route.fulfill({ json: { unread_count: 2 } })
    if (path.endsWith('/chat/conversations')) return route.fulfill({ json: { items: [], next_cursor: null } })
    if (path.endsWith('/tasks') || path.endsWith('/projects')) return route.fulfill({ json: [] })
    return route.fulfill({ status: 404, json: { detail: 'not mocked' } })
  })
  return notificationFetches
}

async function drag(cdp: CDPSession, x: number, fromY: number, toY: number) {
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: fromY, id: 1 }] })
  for (let y = fromY; y <= toY; y += 15) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y, id: 1 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
}

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile', 'touch-only behaviour')
  await page.setViewportSize({ width: 390, height: 844 })
})

test('app bar keeps the title clear of controls and moves secondary actions to the More sheet', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.goto('/tasks')
  const title = await page.locator('.workspace-header h1').boundingBox()
  const avatar = await page.locator('.header-avatar').boundingBox()
  expect((avatar?.x ?? 0) + (avatar?.width ?? 0)).toBeLessThanOrEqual(title?.x ?? 0)
  await expect(page.locator('.workspace-sidebar')).toBeHidden()
  await expect(page.locator('.header-actions .theme-toggle')).toBeHidden()
  await page.getByRole('button', { name: 'Бусад цэс нээх' }).click()
  const sheet = page.getByRole('dialog', { name: 'Бусад цэс' })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByRole('link', { name: 'Тайлан' })).toBeVisible()
  await expect(sheet.getByRole('switch', { name: /Харанхуй горим/ })).toBeVisible()
})

test('More sheet dismisses with a downward swipe', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Бусад цэс нээх' }).click()
  const grabber = await page.locator('.mobile-sheet-grabber').boundingBox()
  await drag(await page.context().newCDPSession(page), 195, (grabber?.y ?? 400) + 2, (grabber?.y ?? 400) + 200)
  await expect(page.locator('.mobile-more-sheet')).toHaveCount(0)
})

test('workers directory opens as a bottom sheet and closes from its scrim', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.goto('/')
  await expect(page.locator('.workers-toggle')).toBeHidden()
  await page.getByRole('button', { name: 'Бусад цэс нээх' }).click()
  await page.getByRole('button', { name: 'Ажилтнууд' }).click()
  await expect(page.locator('.workers-drawer.open')).toBeVisible()
  await expect(page.getByText('Ану')).toBeVisible()
  await page.locator('.workers-scrim').click({ position: { x: 20, y: 20 } })
  await expect(page.locator('.workers-drawer.open')).toHaveCount(0)
})

test('pull to refresh refetches active queries', async ({ page }) => {
  const fetches = await mockWorkspaceApi(page)
  await page.goto('/tasks')
  await expect(page.locator('.mobile-tabbar')).toBeVisible()
  await page.waitForTimeout(500)
  const before = fetches.count
  await drag(await page.context().newCDPSession(page), 200, 300, 520)
  await expect.poll(() => fetches.count).toBeGreaterThan(before)
})

test('tab bar hides only while the keyboard shrinks the viewport', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.goto('/chat')
  await expect(page.locator('.mobile-tabbar')).toBeVisible()
  const search = page.locator('.chat-conversation-pane input').first()
  await expect(search).toBeVisible()
  await search.focus()
  await expect(search).toBeFocused()
  await expect(page.locator('html')).not.toHaveClass(/keyboard-open/)
  await page.setViewportSize({ width: 390, height: 480 })
  await expect(page.locator('html')).toHaveClass(/keyboard-open/)
  await search.blur()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('html')).not.toHaveClass(/keyboard-open/)
})

test('detail routes keep their section title and report actions keep their labels', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.goto('/chat/unknown-conversation')
  await expect(page.locator('.workspace-header h1')).toHaveText('Чат')
  await page.goto('/reports')
  const create = page.getByRole('button', { name: 'Тайлан үүсгэх' })
  await expect(create).toBeVisible()
  expect((await create.boundingBox())?.height).toBeGreaterThanOrEqual(44)
  await expect(create).toHaveText('Тайлан үүсгэх')
})
