import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { periodBounds, ReportInsightsPanel, shiftAnchor } from './ReportInsightsPanel'

const mocks = vi.hoisted(() => ({ download: vi.fn(), summary: vi.fn(), previewParams: [] as any[] }))

vi.mock('../api/reportInsights', () => ({
  useReportInsightScope: () => ({ data: { employees: [{ id: 3, name: 'Сараа', department_id: 1, department: 'Борлуулалт', is_active: true }], departments: [{ id: 1, name: 'Борлуулалт' }] } }),
  useReportExportPreview: (params: any, enabled: boolean) => { if (enabled) mocks.previewParams.push(params); return { data: { report_count: 4, format: 'zip', groups: [{ name: 'Борлуулалт', count: 3 }, { name: 'Санхүү', count: 1 }] }, isFetching: false } },
  useReportSummary: () => ({ mutateAsync: mocks.summary, isPending: false }),
  downloadReportExport: mocks.download,
  saveBlob: vi.fn(),
}))

describe('report insight periods', () => {
  it('aligns week, month, quarter and year to calendar bounds', () => {
    const anchor = new Date(2026, 8, 25) // Friday 25 Sep 2026
    expect(periodBounds('week', anchor)).toEqual({ date_from: '2026-09-21', date_to: '2026-09-27' })
    expect(periodBounds('month', anchor)).toEqual({ date_from: '2026-09-01', date_to: '2026-09-30' })
    expect(periodBounds('quarter', anchor)).toEqual({ date_from: '2026-07-01', date_to: '2026-09-30' })
    expect(periodBounds('year', anchor)).toEqual({ date_from: '2026-01-01', date_to: '2026-12-31' })
    expect(periodBounds('month', new Date(2024, 1, 10)).date_to).toBe('2024-02-29')
  })

  it('steps to previous periods across year boundaries', () => {
    expect(periodBounds('month', shiftAnchor('month', new Date(2026, 0, 15), -1))).toEqual({ date_from: '2025-12-01', date_to: '2025-12-31' })
    expect(periodBounds('quarter', shiftAnchor('quarter', new Date(2026, 1, 1), -1))).toEqual({ date_from: '2025-10-01', date_to: '2025-12-31' })
    expect(periodBounds('week', shiftAnchor('week', new Date(2026, 8, 25), -1)).date_from).toBe('2026-09-14')
  })
})

describe('report insights panel', () => {
  beforeEach(() => {
    mocks.download.mockReset().mockResolvedValue({ filename: 'x.zip', count: 4 })
    mocks.summary.mockReset()
    mocks.previewParams.length = 0
    Element.prototype.scrollTo = vi.fn()
  })

  it('downloads a zip grouped by the chosen folder structure', async () => {
    render(<ReportInsightsPanel onClose={vi.fn()} />)
    expect(screen.getByText('4 тайлан · ZIP')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Хэлтсээр' }))
    fireEvent.click(screen.getByRole('button', { name: 'Жил' }))
    fireEvent.click(screen.getByRole('button', { name: /ZIP татах/ }))
    await waitFor(() => expect(mocks.download).toHaveBeenCalled())
    const params = mocks.download.mock.calls[0][0]
    expect(params).toMatchObject({ group_by: 'department', employee_ids: [], department_ids: [], approved_only: false })
    expect(params.date_from.endsWith('-01-01')).toBe(true)
    expect(params.date_to.endsWith('-12-31')).toBe(true)
  })

  it('sends OYUNS chat prompts with prior turns as history', async () => {
    mocks.summary.mockResolvedValueOnce({ answer: '## Ашиг\nӨгөгдөлд байхгүй.', degraded: false, kpis: {}, report_count: 2 })
      .mockResolvedValueOnce({ answer: 'Зардал 30 сая₮.', degraded: false, kpis: {}, report_count: 2 })
    render(<ReportInsightsPanel onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('tab', { name: /OYUNS чат/ }))
    const input = screen.getByRole('textbox', { name: 'OYUNS Agent-д асуулт' })
    fireEvent.change(input, { target: { value: 'Ашиг хэд вэ?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText('Өгөгдөлд байхгүй.')).toBeInTheDocument()
    fireEvent.change(input, { target: { value: 'Зардал?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText('Зардал 30 сая₮.')).toBeInTheDocument()
    expect(mocks.summary.mock.calls[0][0]).toMatchObject({ scope: 'all', prompt: 'Ашиг хэд вэ?', history: [] })
    expect(mocks.summary.mock.calls[1][0].history).toEqual([
      { role: 'user', content: 'Ашиг хэд вэ?' },
      { role: 'assistant', content: '## Ашиг\nӨгөгдөлд байхгүй.' },
    ])
  })

  it('requires a worker before a single-worker summary can run', () => {
    render(<ReportInsightsPanel onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('tab', { name: /Хураангуй/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Хамрах хүрээ' }))
    fireEvent.click(screen.getByRole('option', { name: 'Нэг ажилтан' }))
    expect(screen.getByText('Ажилтнаа сонгоно уу.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Хураангуй гаргах/ })).toBeDisabled()
  })
})
