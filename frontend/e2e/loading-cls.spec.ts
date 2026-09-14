import { expect, test } from '@playwright/test'

test.describe('CLS loading budgets', () => {
  test.skip(({ isMobile }) => isMobile, 'desktop shell geometry is the reference contract for this smoke budget')

test('calendar loading transition stays within the CLS budget', async ({ page }) => {
  await page.addInitScript(() => {
    let value = 0
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & { hadRecentInput?: boolean; value?: number }
        if (!shift.hadRecentInput) value += shift.value || 0
      }
    })
    observer.observe({ type: 'layout-shift', buffered: true })
    ;(window as Window & { __oyunsCLS?: () => number }).__oyunsCLS = () => value
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'cls-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'cls@example.test', employee_id: 1, locale: 'mn', roles: ['member'], name: 'CLS Test' } })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path.endsWith('/workers')) return route.fulfill({ json: [] })
    if (path.includes('/calendar/events')) return route.fulfill({ json: { tasks: [], projects: [], plans: [], entries: [], holidays: [], time_blocks: [] } })
    if (path.includes('/calendar/holiday-settings') || path.includes('/holidays')) return route.fulfill({ json: { country: 'MN', countries: [] } })
    return route.fulfill({ json: {} })
  })

  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/calendar')
  await expect(page.locator('.planning-calendar')).toBeVisible()
  await page.waitForTimeout(500)
  const cls = await page.evaluate(() => (window as Window & { __oyunsCLS?: () => number }).__oyunsCLS?.() || 0)
  expect(cls).toBeLessThan(0.1)
})
})
