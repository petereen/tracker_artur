import { expect, test } from '@playwright/test'

test('login remains keyboard accessible at desktop and mobile widths', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401, json: { detail: 'signed out' } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Илүү хурдан. Илүү хялбар.' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Нэвтрэх нэр')).toBeFocused()
  await page.getByLabel('Нэвтрэх нэр').fill('member')
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Нууц үг')).toBeFocused()
})

test('login remains inside the viewport without horizontal overflow', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401, json: { detail: 'signed out' } }))
  await page.goto('/')
  const dimensions = await page.locator('.login-card').evaluate((element) => ({ right: element.getBoundingClientRect().right, viewport: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.viewport)
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.viewport)
})

test('reduced motion removes long workspace transitions', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401, json: { detail: 'signed out' } }))
  await page.goto('/')
  const duration = await page.locator('.login-card').evaluate((element) => getComputedStyle(element).transitionDuration)
  expect(duration === '0s' || duration === '').toBeTruthy()
})

test('authenticated task collaboration is reachable with keyboard controls', async ({ page }) => {
  const task = {
    id: 41, public_id: 'task-41', project_id: null, parent_task_id: null,
    title: 'Release readiness', description: 'Verify the enterprise batch',
    workflow_status: 'in_progress', priority: 1, primary_owner_id: 7,
    primary_owner_name: 'Test Manager', reviewer_id: 7, reviewer_name: 'Test Manager',
    assignee_ids: [7], assignee_names: ['Test Manager'], project_name: null,
    start_at: '2026-08-10T08:00:00Z', deadline_at: '2026-08-11T08:00:00Z',
    estimate_minutes: 60, work_location_type: 'remote', work_location: null,
    sort_position: 1, version: 3, is_archived: false, is_overdue: false,
    created_by_id: 1,
  }
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'browser-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'manager@example.test', employee_id: 7, locale: 'mn', roles: ['manager'], name: 'Test Manager' } })
    if (path.endsWith('/tasks')) return route.fulfill({ json: [task] })
    if (path.endsWith('/workers')) return route.fulfill({ json: [{ id: 7, name: 'Test Manager', email: 'manager@example.test', roles: ['manager'] }] })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/tasks')
  await expect(page.getByRole('heading', { name: 'Миний даалгавар' })).toBeVisible()
  await page.locator('.task-card-body').filter({ hasText: 'Release readiness' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('navigation', { name: 'Даалгаврын дэлгэрэнгүй' })).toBeVisible()
  await page.getByRole('button', { name: 'Checklist', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByPlaceholder('Checklist нэмэх')).toBeVisible()
})
