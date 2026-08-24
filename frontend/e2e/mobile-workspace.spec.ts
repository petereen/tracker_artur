import { expect, Page, test } from '@playwright/test'

async function mockWorkspaceApi(page: Page) {
  const conversation = { id: 1, public_id: 'c1', kind: 'direct', title: 'Ану', avatar_urls: [], presence: 'online', members: [{ account_id: 2, employee_id: 2, name: 'Ану', email: 'anu@example.test', avatar_url: null, is_online: true, last_seen_at: new Date().toISOString(), role: 'member' }], member_count: 2, can_manage: false, last_message: { id: 1, body: 'Сайн байна уу?', sender_account_id: 2, sender_name: 'Ану', created_at: new Date().toISOString() }, unread_count: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'mobile-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'mobile@example.test', locale: 'mn', roles: ['member'], name: 'Mobile User' } })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path.endsWith('/workers')) return route.fulfill({ json: [] })
    if (path.endsWith('/erp/meta')) return route.fulfill({ json: { modules: {} } })
    if (path.endsWith('/chat/unread-count')) return route.fulfill({ json: { unread_count: 2 } })
    if (path.endsWith('/chat/contacts')) return route.fulfill({ json: [] })
    if (path.endsWith('/chat/conversations')) return route.fulfill({ json: { items: [conversation], next_cursor: null } })
    if (path.endsWith('/chat/conversations/c1/messages') && route.request().method() === 'GET') return route.fulfill({ json: { items: [{ id: 1, conversation_id: 1, sender: conversation.members[0], sender_account_id: 2, client_nonce: '00000000-0000-4000-8000-000000000001', body: 'Сайн байна уу?', created_at: new Date().toISOString(), is_mine: false, status: null, receipts: { total: 0, delivered: 0, read: 0 } }], next_before_id: null } })
    if (path.endsWith('/chat/conversations/c1/receipts')) return route.fulfill({ json: { acknowledged: true } })
    if (path.endsWith('/chat/conversations/c1')) return route.fulfill({ json: conversation })
    return route.fulfill({ json: {} })
  })
}

for (const width of [320, 393, 767]) {
  test(`mobile workspace chrome stays inside a ${width}px viewport`, async ({ page }) => {
    await mockWorkspaceApi(page)
    await page.setViewportSize({ width, height: 852 })
    await page.goto('/calendar')
    await expect(page.locator('.mobile-tabbar')).toBeVisible()
    await expect(page.locator('.mobile-calendar')).toBeVisible()
    const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }))
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width)
    const bar = await page.locator('.mobile-tabbar').boundingBox()
    expect(bar?.x).toBeGreaterThanOrEqual(0)
    expect((bar?.x ?? 0) + (bar?.width ?? 0)).toBeLessThanOrEqual(width)
    expect(await page.locator('.mobile-tabbar a, .mobile-tabbar button').count()).toBe(5)
  })
}

test('desktop calendar keeps sidebar and full month grid', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/calendar')
  await expect(page.locator('.workspace-sidebar')).toBeVisible()
  await expect(page.locator('.planning-calendar')).toBeVisible()
  await expect(page.locator('.mobile-calendar')).toBeHidden()
  await expect(page.locator('.period-filter-mobile-trigger')).toBeHidden()
})

test('mobile chat uses the direct tab destination and an interruptible conversation drawer', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.setViewportSize({ width: 320, height: 852 })
  await page.goto('/chat/c1')
  await expect(page.locator('.chat-thread-pane')).toBeVisible()
  await expect(page.locator('.mobile-tabbar')).toContainText('Чат')
  await expect(page.locator('.mobile-tabbar')).not.toContainText('Ажлын цаг')
  await page.getByRole('button', { name: 'Чатын жагсаалт нээх' }).click()
  await expect(page.locator('.chat-conversation-pane')).toBeVisible()
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width)
})

test('desktop chat collapses its 320px conversation pane without moving the thread offscreen', async ({ page }) => {
  await mockWorkspaceApi(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/chat/c1')
  const pane = page.locator('.chat-conversation-pane')
  await expect(pane).toBeVisible()
  expect((await pane.boundingBox())?.width).toBe(320)
  await page.getByRole('button', { name: 'Чатын жагсаалт нуух' }).click()
  await expect(page.locator('.chat-workspace')).toHaveClass(/sidebar-collapsed/)
  await expect(page.locator('.chat-thread-pane')).toBeVisible()
})
