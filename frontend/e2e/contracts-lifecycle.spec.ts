import { expect, test } from '@playwright/test'

test('contract lifecycle reaches signed and stamped archive', async ({ page }) => {
  let status = 'DRAFT'
  let finalUploaded = false
  const detail = () => ({
    id: 1, public_id: '11111111-1111-4111-8111-111111111111', title: 'Туршилтын үйлчилгээний гэрээ', document_type: 'contract', status,
    author_account_id: 1, author_name: 'Test Author', project_id: null, task_id: null, effective_start_on: null, effective_end_on: null,
    submission_round: status === 'DRAFT' ? 0 : 1, version: status === 'DRAFT' ? 2 : 3, current_revision_id: 1, approved_revision_id: status === 'DRAFT' ? null : 1,
    approved_at: status === 'DRAFT' ? null : '2026-08-17T01:00:00Z', signed_at: status === 'SIGNED_AND_STAMPED' ? '2026-08-17T02:00:00Z' : null,
    created_at: '2026-08-17T00:00:00Z', updated_at: '2026-08-17T01:00:00Z', body_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Гэрээний нөхцөл' }] }] }, approved_body_json: status === 'DRAFT' ? null : { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Гэрээний нөхцөл' }] }] }, reviewer_account_ids: [1],
    revisions: [{ id: 1, revision_number: 1, title: 'Туршилтын үйлчилгээний гэрээ', body_json: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Гэрээний нөхцөл' }] }] }, plain_text: 'Гэрээний нөхцөл', checksum: 'abc', created_at: '2026-08-17T00:00:00Z', author_account_id: 1 }],
    reviews: status === 'DRAFT' ? [] : [{ id: 1, round_number: 1, reviewer_account_id: 1, reviewer_employee_id: 1, reviewer_name: 'Test Author', decision: status === 'PENDING_REVIEW' ? 'pending' : 'approved', remark: null, acted_at: null }], comments: [],
    files: finalUploaded ? [{ id: 4, purpose: 'signed_final', filename: 'signed.pdf', content_type: 'application/pdf', size: 10, checksum: 'def', scan_status: 'disabled', confirmed_at: status === 'SIGNED_AND_STAMPED' ? '2026-08-17T02:00:00Z' : null, created_at: '2026-08-17T01:30:00Z' }] : [], timeline: [],
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'browser-test', expires_in: 900 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, email: 'author@example.test', employee_id: 1, locale: 'mn', roles: ['member'], name: 'Test Author' } })
    if (path.endsWith('/workers')) return route.fulfill({ json: [] })
    if (path.endsWith('/notifications')) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path.endsWith('/erp/meta')) return route.fulfill({ json: { modules: {} } })
    if (path === '/api/v1/contracts/reviewer-candidates') return route.fulfill({ json: [{ account_id: 1, employee_id: 1, name: 'Test Author', job_title: 'Reviewer' }] })
    if (path === '/api/v1/contracts' && request.method() === 'GET') return route.fulfill({ json: { items: [detail()], counts: { all: 1, drafts: status === 'DRAFT' ? 1 : 0, pending_my_approval: status === 'PENDING_REVIEW' ? 1 : 0, submitted_by_me: status === 'PENDING_REVIEW' ? 1 : 0, approved: status === 'APPROVED' ? 1 : 0, signed: status === 'SIGNED_AND_STAMPED' ? 1 : 0, returned: 0 } } })
    if (path === '/api/v1/contracts' && request.method() === 'POST') return route.fulfill({ status: 201, json: { ...detail(), public_id: '11111111-1111-4111-8111-111111111111' } })
    if (path.endsWith('/submit')) { status = 'PENDING_REVIEW'; return route.fulfill({ json: { status } }) }
    if (path.endsWith('/approve')) { status = 'APPROVED'; return route.fulfill({ json: { status, final_approval: true } }) }
    if (path.endsWith('/mark-printed')) return route.fulfill({ json: { printed_at: '2026-08-17T01:20:00Z' } })
    if (path.endsWith('/files') && request.method() === 'POST') { finalUploaded = true; return route.fulfill({ status: 201, json: { id: 4, purpose: 'signed_final', filename: 'signed.pdf', scan_status: 'disabled' } }) }
    if (path.endsWith('/confirm-final')) { status = 'SIGNED_AND_STAMPED'; return route.fulfill({ json: { status } }) }
    if (path.includes('/contracts/') && request.method() === 'GET') return route.fulfill({ json: detail() })
    return route.fulfill({ json: {} })
  })

  await page.goto('/contracts')
  await expect(page.getByRole('heading', { name: 'Гэрээ', level: 2 })).toBeVisible()
  await page.getByRole('button', { name: /Шинэ баримт бичиг/ }).click()
  await page.getByLabel('Гарчиг / сэдэв').fill('Туршилтын үйлчилгээний гэрээ')
  await page.locator('.contract-editor .ProseMirror').fill('Гэрээний нөхцөл')
  await page.locator('.reviewer-dropdown summary').click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: /Ноорог хадгалах/ }).click()
  await expect(page.getByRole('heading', { name: 'Туршилтын үйлчилгээний гэрээ' })).toBeVisible()
  await page.getByRole('button', { name: /Хянагчдад илгээх/ }).click()
  await expect(page.getByText('Хянагдаж байна')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Зөвшөөрөх' }).click()
  await expect(page.getByText('Гэрээ батлагдлаа.')).toBeVisible()
  await page.getByRole('button', { name: /Хэвлэх \/ PDF татах/ }).first().click()
  await page.locator('input[type="file"]').setInputFiles({ name: 'signed.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-test') })
  await expect(page.getByText('Эцсийн хувийг баталгаажуулах')).toBeVisible()
  await page.getByRole('button', { name: 'Эцсийн хувийг баталгаажуулах' }).click()
  await expect(page.getByText('Гарын үсэг зурсан')).toBeVisible()
})
