import { useMemo, useState } from 'react'
import { BarChart3, Boxes, BriefcaseBusiness, Calculator, CheckCircle2, ClipboardList, Factory, HeartPulse, Landmark, Plus, ShieldCheck, ShoppingCart, UsersRound, Wrench } from 'lucide-react'
import toast from 'react-hot-toast'
import { type ERPModule, useCreateERPDocument, useERPDashboard, useERPDocuments, useERPMetadata, useSubmitERPDocument, useUpdateERPModules } from '../api/enterprise'

const MODULE_ICONS: Record<ERPModule, typeof Landmark> = {
  accounting: Calculator, selling: ShoppingCart, buying: BriefcaseBusiness, stock: Boxes, crm: UsersRound,
  support: HeartPulse, payroll: Landmark, manufacturing: Factory, assets_maintenance: Wrench,
}
const MODULE_DOCUMENTS: Record<ERPModule, Array<{ type: string; label: string }>> = {
  accounting: [{ type: 'journal_entry', label: 'Journal entries' }, { type: 'payment_entry', label: 'Payments' }, { type: 'budget', label: 'Budgets' }],
  selling: [{ type: 'quotation', label: 'Quotations' }, { type: 'sales_order', label: 'Sales orders' }, { type: 'sales_invoice', label: 'Sales invoices' }],
  buying: [{ type: 'supplier_quotation', label: 'Supplier quotations' }, { type: 'purchase_order', label: 'Purchase orders' }, { type: 'purchase_invoice', label: 'Purchase invoices' }],
  stock: [{ type: 'stock_entry', label: 'Stock movements' }, { type: 'stock_reconciliation', label: 'Stock reconciliation' }],
  crm: [{ type: 'lead', label: 'Leads' }, { type: 'opportunity', label: 'Opportunities' }],
  support: [{ type: 'support_ticket', label: 'Customer tickets' }, { type: 'service_level_agreement', label: 'SLA policies' }],
  payroll: [{ type: 'salary_structure', label: 'Salary structures' }, { type: 'payroll_run', label: 'Payroll runs' }, { type: 'salary_slip', label: 'Salary slips' }],
  manufacturing: [{ type: 'bill_of_materials', label: 'Bills of materials' }, { type: 'work_order', label: 'Work orders' }, { type: 'job_card', label: 'Job cards' }],
  assets_maintenance: [{ type: 'asset', label: 'Assets' }, { type: 'maintenance_schedule', label: 'Maintenance schedules' }, { type: 'maintenance_visit', label: 'Maintenance visits' }],
}

const MONEY = (amount: string | undefined, currency = 'MNT') => new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(Number(amount || 0))

export function ERPWorkspacePage() {
  const metadata = useERPMetadata()
  const dashboard = useERPDashboard(Boolean(metadata.data && Object.values(metadata.data.modules).some(Boolean)))
  const updateModules = useUpdateERPModules()
  const enabledModules = useMemo(() => Object.entries(metadata.data?.modules ?? {}).filter(([, enabled]) => enabled).map(([module]) => module as ERPModule), [metadata.data])
  const [module, setModule] = useState<ERPModule>('accounting')
  const available = enabledModules.includes(module) ? module : enabledModules[0] || 'accounting'
  const [documentType, setDocumentType] = useState('journal_entry')
  const documents = useERPDocuments(documentType, Boolean(metadata.data?.modules[available]))
  const create = useCreateERPDocument(documentType)
  const submit = useSubmitERPDocument(documentType)

  const toggleModule = (target: ERPModule) => {
    if (!metadata.data) return
    updateModules.mutate({ ...metadata.data.modules, [target]: !metadata.data.modules[target] }, {
      onSuccess: () => toast.success('ERP module visibility updated'),
      onError: (error: any) => toast.error(error.response?.data?.detail || 'Module settings could not be updated'),
    })
  }
  const newDraft = () => create.mutate({ lines: [{ description: 'New line', quantity: 1, rate: 0, tax_rate: 0 }] }, { onSuccess: () => toast.success('Draft created'), onError: (error: any) => toast.error(error.response?.data?.detail || 'Draft could not be created') })

  if (metadata.isLoading) return <div className="panel"><p>Loading ERP workspace…</p></div>
  if (metadata.isError || !metadata.data) return <div className="panel"><h2>ERP is not available</h2><p>Your account does not yet have access to the ERP service.</p></div>

  return <div className="erp-workspace">
    <div className="view-toolbar"><div><span className="eyebrow">CONFIGURABLE ERP</span><h2>Business operations</h2><p>Enable only the workflows your organization uses. Visibility does not replace permissions.</p></div><Landmark /></div>
    <section className="erp-module-grid" aria-label="ERP modules">
      {(Object.keys(metadata.data.module_labels) as ERPModule[]).map((key) => {
        const Icon = MODULE_ICONS[key]
        const enabled = metadata.data.modules[key]
        return <article key={key} className={`panel erp-module-card ${enabled ? 'enabled' : ''}`}><Icon size={21} /><div><strong>{metadata.data.module_labels[key]}</strong><small>{enabled ? 'Visible in workspace' : 'Hidden from workspace'}</small></div><button className="erp-toggle" onClick={() => toggleModule(key)} disabled={updateModules.isPending} aria-label={`${metadata.data.module_labels[key]} ${enabled ? 'disable' : 'enable'}`}><span /></button></article>
      })}
    </section>
    <p className="erp-settings-notice"><ShieldCheck size={15} /> Module switches affect navigation and normal UI only. API, posting, audit, and integrations remain capability-controlled.</p>
    {enabledModules.length === 0 ? <section className="panel erp-empty"><Boxes size={28} /><h3>No ERP modules are visible</h3><p>An administrator can enable modules above to set up the business workspace.</p></section> : <>
      <section className="erp-kpis">
        {[
          ['Revenue', dashboard.data?.revenue], ['Expenses', dashboard.data?.expenses], ['Profit', dashboard.data?.profit], ['Inventory value', dashboard.data?.inventory_value],
          ['Open customer queries', String(dashboard.data?.open_customer_queries ?? 0)], ['Payroll', dashboard.data?.payroll_total],
        ].map(([label, value]) => <article className="panel" key={label}><small>{label}</small><strong>{label === 'Open customer queries' ? value : MONEY(value, dashboard.data?.currency)}</strong></article>)}
      </section>
      <section className="erp-document-panel panel"><div className="view-toolbar"><div><span className="eyebrow">DOCUMENT WORKBENCH</span><h3>{MODULE_DOCUMENTS[available].find((entry) => entry.type === documentType)?.label || 'Documents'}</h3></div><button className="primary-action compact" onClick={newDraft} disabled={create.isPending}><Plus size={15} />New draft</button></div>
        <div className="erp-document-tabs">{enabledModules.flatMap((enabledModule) => MODULE_DOCUMENTS[enabledModule]).map((entry) => <button key={entry.type} className={documentType === entry.type ? 'active' : ''} onClick={() => { setModule(Object.entries(MODULE_DOCUMENTS).find(([, entries]) => entries.some((item) => item.type === entry.type))?.[0] as ERPModule); setDocumentType(entry.type) }}>{entry.label}</button>)}</div>
        {documents.isLoading ? <p>Loading documents…</p> : documents.isError ? <p>Document permission is required for this workspace.</p> : <div className="erp-document-list">{documents.data?.length ? documents.data.map((document) => <article key={document.id}><div><strong>{document.number}</strong><span>{document.status} · {document.posting_date}</span></div><div><strong>{MONEY(document.grand_total, document.currency)}</strong>{document.status === 'draft' && <button className="secondary-action compact" onClick={() => submit.mutate(document.id, { onError: (error: any) => toast.error(error.response?.data?.detail || 'Document could not be submitted') })} disabled={submit.isPending}><CheckCircle2 size={14} />Submit</button>}</div></article>) : <div className="erp-empty"><ClipboardList size={24} /><p>No documents yet. Start with a draft.</p></div>}</div>}
      </section>
    </>}
  </div>
}
