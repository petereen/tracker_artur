import { Check, FileCheck2, MessageSquareWarning, Send } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { useEnterpriseReports, useReportReview } from '../api/enterprise'

export function EnterpriseReportsPage() {
  const reports = useEnterpriseReports()
  const review = useReportReview()
  const roles = useAuthStore((state) => state.actor?.roles ?? [])
  const canReview = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  return <div><div className="view-toolbar"><div><h2>Нэгдсэн тайлан</h2><p>Өдөр, сар болон дараа сарын төлөвлөгөө.</p></div><div className="report-summary"><span><strong>{reports.data?.filter((report) => report.status === 'submitted').length ?? 0}</strong> хүлээгдэж буй</span><span><strong>{reports.data?.filter((report) => report.status === 'approved').length ?? 0}</strong> батлагдсан</span></div></div><section className="report-table panel"><header><span>Ажилтан / Тайлан</span><span>Хугацаа</span><span>Төлөв</span><span>Үйлдэл</span></header>{reports.data?.map((report) => <article key={report.id}><div><div className="report-icon"><FileCheck2 /></div><div><strong>{report.employee_name}</strong><span>{report.report_type.replaceAll('_', ' ')}</span></div></div><time>{report.period_date}</time><span className={`status-pill ${report.status}`}>{report.status}</span><div className="row-actions">{report.status !== 'submitted' && !canReview && <button onClick={() => review.mutate({ id: report.id, action: 'submit' })}><Send />Илгээх</button>}{canReview && report.status === 'submitted' && <><button onClick={() => review.mutate({ id: report.id, action: 'request-revision' })}><MessageSquareWarning />Засвар</button><button className="approve" onClick={() => review.mutate({ id: report.id, action: 'approve' })}><Check />Батлах</button></>}</div></article>)}</section></div>
}
