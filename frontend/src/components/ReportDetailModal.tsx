import { Badge, Modal } from './ui'
import { useWorkReport } from '../api/hooks'

const TYPE_LABELS: Record<string, string> = { daily: 'Өдрийн тайлан', monthly: 'Сарын тайлан', next_month_plan: 'Дараа сарын төлөвлөгөө' }
const STATUS_LABELS: Record<string, string> = { approved: 'Батлагдсан', awaiting: 'Хүлээгдэж буй', draft: 'Ноорог', editing: 'Засаж байна', superseded: 'Солигдсон', deleted: 'Устгасан' }

export function ReportDetailModal({ reportId, onClose }: { reportId: number; onClose: () => void }) {
  const report = useWorkReport(reportId)
  return <Modal title="Тайлангийн дэлгэрэнгүй" onClose={onClose} className="max-w-3xl max-h-[85vh] overflow-y-auto">
    {report.isLoading && <div className="py-10 text-center text-muted">Тайлан ачаалж байна…</div>}
    {report.isError && <div className="py-10 text-center text-red">Тайлан ачаалахад алдаа гарлаа</div>}
    {report.data && <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div><div className="font-semibold">{TYPE_LABELS[report.data.report_type] || report.data.report_type}</div><div className="text-xs text-muted mt-1">{report.data.employee_name} · {report.data.period_date}</div></div>
        <Badge color={report.data.status === 'approved' ? 'green' : 'yellow'}>{STATUS_LABELS[report.data.status]}</Badge>
      </div>
      <div className="bg-surface2 border border-border rounded-xl p-4 whitespace-pre-wrap text-sm leading-6">{report.data.text || 'Тайлангийн текст байхгүй'}</div>
      <div>
        <div className="font-medium mb-2">Өөрчлөлтийн түүх</div>
        <div className="border border-border rounded-lg overflow-hidden">
          {report.data.revisions.map((revision, index) => <div key={revision.id} className={`p-3 ${index ? 'border-t border-border2' : ''}`}>
            <div className="flex justify-between gap-3 text-xs mb-1"><Badge color={revision.status === 'approved' ? 'green' : revision.status === 'deleted' ? 'red' : 'muted'}>{STATUS_LABELS[revision.status] || revision.status}</Badge><span className="text-muted">{new Date(revision.updated_at).toLocaleString('mn-MN')}</span></div>
            <div className="text-sm whitespace-pre-wrap text-muted">{revision.text}</div>
          </div>)}
          {!report.data.revisions.length && <div className="p-4 text-sm text-muted">Өөрчлөлтийн түүх байхгүй</div>}
        </div>
      </div>
    </div>}
  </Modal>
}
