import { expect, Page, test } from '@playwright/test'

async function mockWorkspaceApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'mobile-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'mobile@example.test', locale: 'mn', roles: ['member'], name: 'Mobile User' } })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path.endsWith('/workers')) return route.fulfill({ json: [] })
    if (path.endsWith('/erp/meta')) return route.fulfill({ json: { modules: {} } })
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
