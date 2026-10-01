import { useTranslation } from 'react-i18next'
import { Badge, Modal } from './ui'
import { intlLocale } from '../utils/locale'
import { useWorkReport } from '../api/hooks'

const TYPE_KEYS = ['daily', 'monthly', 'next_month_plan']
const STATUS_KEYS = ['approved', 'awaiting', 'draft', 'editing', 'superseded', 'deleted']

export function ReportDetailModal({ reportId, onClose }: { reportId: number; onClose: () => void }) {
  const { t } = useTranslation()
  const report = useWorkReport(reportId)
  return <Modal title={t('reports.detail.title')} onClose={onClose} className="max-w-3xl max-h-[85vh] overflow-y-auto">
    {report.isLoading && <div className="py-10 text-center text-muted">{t('reports.detail.loading')}</div>}
    {report.isError && <div className="py-10 text-center text-red">{t('reports.detail.loadError')}</div>}
    {report.data && <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div><div className="font-semibold">{TYPE_KEYS.includes(report.data.report_type) ? t(`reports.detail.type.${report.data.report_type}`) : report.data.report_type}</div><div className="text-xs text-muted mt-1">{report.data.employee_name} · {report.data.period_date}</div></div>
        <Badge color={report.data.status === 'approved' ? 'green' : 'yellow'}>{STATUS_KEYS.includes(report.data.status) ? t(`reports.detail.status.${report.data.status}`) : report.data.status}</Badge>
      </div>
      <div className="bg-surface2 border border-border rounded-xl p-4 whitespace-pre-wrap text-sm leading-6">{report.data.text || t('reports.detail.noText')}</div>
      <div>
        <div className="font-medium mb-2">{t('reports.detail.history')}</div>
        <div className="border border-border rounded-lg overflow-hidden">
          {report.data.revisions.map((revision, index) => <div key={revision.id} className={`p-3 ${index ? 'border-t border-border2' : ''}`}>
            <div className="flex justify-between gap-3 text-xs mb-1"><Badge color={revision.status === 'approved' ? 'green' : revision.status === 'deleted' ? 'red' : 'muted'}>{STATUS_KEYS.includes(revision.status) ? t(`reports.detail.status.${revision.status}`) : revision.status}</Badge><span className="text-muted">{new Date(revision.updated_at).toLocaleString(intlLocale())}</span></div>
            <div className="text-sm whitespace-pre-wrap text-muted">{revision.text}</div>
          </div>)}
          {!report.data.revisions.length && <div className="p-4 text-sm text-muted">{t('reports.detail.noHistory')}</div>}
        </div>
      </div>
    </div>}
  </Modal>
}
