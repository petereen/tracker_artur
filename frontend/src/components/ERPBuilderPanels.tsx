import { useEffect, useMemo, useState } from 'react'
import { Plus, Save, Workflow, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { type ERPFieldType, type ERPFormField, type ERPWorkflow, useERPCatalog, useERPForm, usePublishERPForm, useSaveERPFormDraft } from '../api/enterprise'

const DEFAULT_WORKFLOW: ERPWorkflow = {
  initial_state: 'draft',
  states: [{ key: 'draft', label: 'Draft' }, { key: 'submitted', label: 'Submitted' }, { key: 'approved', label: 'Approved', terminal: true }, { key: 'rejected', label: 'Rejected', terminal: true }, { key: 'cancelled', label: 'Cancelled', terminal: true }],
  transitions: [{ from: 'draft', to: 'submitted', label: 'Submit', role_ids: [], requester_allowed: true }, { from: 'submitted', to: 'approved', label: 'Approve', role_ids: [], requester_allowed: false }, { from: 'submitted', to: 'rejected', label: 'Reject', role_ids: [], requester_allowed: false }, { from: 'draft', to: 'cancelled', label: 'Cancel', role_ids: [], requester_allowed: true }],
}

const emptyField = (section: ERPFormField['section']): ERPFormField => ({ key: '', label: '', field_type: 'text', section, required: false, options: {}, validation: {}, position: 0 })

function FieldRow({ field, fieldTypes, sections, onChange, onRemove }: { field: ERPFormField; fieldTypes: ERPFieldType[]; sections: string[]; onChange: (field: ERPFormField) => void; onRemove: () => void }) {
  return <div className="erp-form-field-row"><input aria-label="Field key" value={field.key} placeholder="field_key" onChange={(event) => onChange({ ...field, key: event.target.value })} /><input aria-label="Field label" value={field.label} placeholder="Label" onChange={(event) => onChange({ ...field, label: event.target.value })} /><select aria-label="Field type" value={field.field_type} onChange={(event) => onChange({ ...field, field_type: event.target.value as ERPFieldType, options: {} })}>{fieldTypes.map((type) => <option key={type}>{type}</option>)}</select><select aria-label="Field section" value={field.section} onChange={(event) => onChange({ ...field, section: event.target.value as ERPFormField['section'] })}>{sections.map((section) => <option key={section}>{section}</option>)}</select><label className="erp-field-required"><input type="checkbox" checked={field.required} onChange={(event) => onChange({ ...field, required: event.target.checked })} />Required</label><button aria-label={`Remove ${field.label || 'field'}`} onClick={onRemove}><X size={15} /></button></div>
}

function FormEditor({ operation, operationInfo }: { operation: string; operationInfo: { sections: Array<'header' | 'line'>; label: string } }) {
  const catalog = useERPCatalog(); const definition = useERPForm(operation, true, true); const save = useSaveERPFormDraft(operation); const publish = usePublishERPForm(operation)
  const [fields, setFields] = useState<ERPFormField[]>([]); const [workflow, setWorkflow] = useState<ERPWorkflow>(DEFAULT_WORKFLOW); const [dirty, setDirty] = useState(false)
  useEffect(() => { if (!definition.data || dirty) return; setFields(definition.data.fields); setWorkflow(definition.data.workflow || DEFAULT_WORKFLOW) }, [definition.data, dirty])
  useEffect(() => { setDirty(false) }, [operation])
  const edit = (index: number, next: ERPFormField) => { setFields((all) => all.map((field, current) => current === index ? { ...next, position: current } : field)); setDirty(true) }
  const add = () => { setFields((all) => [...all, { ...emptyField(operationInfo.sections[0]), position: all.length }]); setDirty(true) }
  const saveDraft = async () => { try { await save.mutateAsync({ fields, workflow }); setDirty(false); toast.success('Builder draft saved') } catch (error: any) { toast.error(error.response?.data?.detail?.code || 'Form draft could not be saved') } }
  const publishDraft = async () => { try { await publish.mutateAsync(); setDirty(false); toast.success('Published form version') } catch (error: any) { toast.error(error.response?.data?.detail?.code || 'Form could not be published') } }
  if (definition.isLoading || !catalog.data) return <section className="panel"><p>Loading operation builder…</p></section>
  return <section className="panel erp-builder-panel"><div className="panel-heading"><div><span className="eyebrow">FORM + WORKFLOW</span><h3>{operationInfo.label}</h3><p>Version {definition.data?.version || 1} · {definition.data?.status || 'draft'}{dirty ? ' · unsaved changes' : ''}</p></div><Workflow /></div><div className="erp-form-field-list">{fields.map((field, index) => <FieldRow key={`${field.key}-${index}`} field={field} fieldTypes={catalog.data.field_types} sections={operationInfo.sections} onChange={(next) => edit(index, next)} onRemove={() => { setFields((all) => all.filter((_, current) => current !== index)); setDirty(true) }} />)}</div><button className="secondary-action compact mt-3" onClick={add}><Plus size={14} />Add field</button><details className="erp-workflow-editor"><summary>Workflow states and transitions</summary><label>Workflow JSON<textarea value={JSON.stringify(workflow, null, 2)} onChange={(event) => { try { setWorkflow(JSON.parse(event.target.value)); setDirty(true) } catch { /* preserve editable invalid text until valid JSON */ } }} rows={11} /></label><p>States and transitions are validated when saved; transition role IDs are selected from the access-role list.</p></details><div className="flex gap-2 mt-4"><button className="primary-action compact" onClick={saveDraft} disabled={save.isPending}><Save size={14} />Save draft</button><button className="secondary-action compact" onClick={publishDraft} disabled={publish.isPending || dirty}>Publish version</button></div></section>
}

export function ERPBuilderPanels() {
  const catalog = useERPCatalog(); const [operation, setOperation] = useState('')
  const operations = catalog.data?.operations || {}
  const operationKeys = useMemo(() => Object.keys(operations), [operations])
  useEffect(() => { if (!operation && operationKeys.length) setOperation(operationKeys[0]) }, [operation, operationKeys])
  if (catalog.isLoading) return <section className="panel"><p>Loading ERP builders…</p></section>
  if (catalog.isError || !catalog.data) return <section className="panel"><p>ERP builder access is required.</p></section>
  // Roles and permissions live in RoleBuilder; this is the form/workflow builder.
  return <div className="flex flex-col gap-4"><section className="panel erp-builder-panel"><div className="view-toolbar"><div><span className="eyebrow">OPERATION BUILDER</span><h3>Versioned forms</h3></div><select aria-label="ERP operation" value={operation} onChange={(event) => setOperation(event.target.value)}>{operationKeys.map((key) => <option value={key} key={key}>{operations[key].label}</option>)}</select></div>{operation && <FormEditor operation={operation} operationInfo={operations[operation]} />}</section></div>
}
