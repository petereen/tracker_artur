import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Archive, Check, ListChecks, MoreHorizontal, Save, Trash2, X } from 'lucide-react'
import {
  useDeleteEnterpriseTask,
  useEnterpriseTasks,
  useUpdateEnterpriseTask,
  useWorkerDirectory,
  type EnterpriseTask,
  type WorkflowStatus,
} from '../../../api/enterprise'
import { useAuthStore } from '../../../store/auth'
import { intlLocale } from '../../../utils/locale'
import { UserTagPicker } from '../../UserTagPicker'
import { useWorkspaceMode } from '../../WorkspaceModeProvider'
import { WidgetHeader } from './shared'

const toInputDateTime = (value: string | null) => (value ? new Date(value).toISOString().slice(0, 16) : '')

function DelegatedTaskSheet({ task, workers, onClose }: { task: EnterpriseTask; workers: ReturnType<typeof useWorkerDirectory>['data']; onClose: () => void }) {
  const { t } = useTranslation()
  const update = useUpdateEnterpriseTask()
  const remove = useDeleteEnterpriseTask()
  const [form, setForm] = useState({
    title: task.title,
    description: task.description || '',
    workflow_status: task.workflow_status,
    priority: String(task.priority),
    primary_owner_id: task.primary_owner_id ? String(task.primary_owner_id) : '',
    assignee_ids: task.assignee_ids,
    start_at: toInputDateTime(task.start_at),
    deadline_at: toInputDateTime(task.deadline_at),
    work_location: task.work_location || '',
  })
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    await update.mutateAsync({
      id: task.id,
      version: task.version,
      title: form.title,
      description: form.description || null,
      workflow_status: form.workflow_status,
      priority: Number(form.priority),
      primary_owner_id: form.primary_owner_id ? Number(form.primary_owner_id) : null,
      assignee_ids: form.assignee_ids,
      start_at: form.start_at ? new Date(form.start_at).toISOString() : null,
      deadline_at: form.deadline_at ? new Date(form.deadline_at).toISOString() : null,
      work_location: form.work_location || null,
    })
    onClose()
  }
  const archive = async () => {
    await update.mutateAsync({ id: task.id, version: task.version, is_archived: true })
    onClose()
  }
  const deleteTask = async () => {
    if (window.confirm(t('today.tasks.confirmDelete', { title: task.title }))) {
      await remove.mutateAsync(task.id)
      onClose()
    }
  }
  const busy = update.isPending || remove.isPending
  return createPortal(
    <div className="sheet-backdrop delegated-task-backdrop" onMouseDown={onClose}>
      <aside className="detail-sheet delegated-task-sheet" onMouseDown={(event) => event.stopPropagation()}>
        <div className="sheet-header">
          <div>
            <span className="eyebrow">{t('today.tasks.sheetEyebrow')}</span>
            <h2>{task.title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label={t('today.tasks.close')}><X /></button>
        </div>
        <form className="sheet-form" onSubmit={save}>
          <label>{t('today.tasks.fieldTitle')}<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
          <label>{t('today.tasks.fieldDescription')}<textarea rows={4} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          <div className="form-row">
            <label>
              {t('today.tasks.fieldStatus')}
              <select value={form.workflow_status} onChange={(event) => setForm({ ...form, workflow_status: event.target.value as WorkflowStatus })}>
                {['backlog', 'to_do', 'in_progress', 'review', 'done', 'cancelled'].map((value) => (
                  <option key={value} value={value}>{t(`today.tasks.status.${value}`)}</option>
                ))}
              </select>
            </label>
            <label>
              {t('today.tasks.fieldPriority')}
              <select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}>
                <option value="1">{t('today.tasks.priority.1')}</option>
                <option value="2">{t('today.tasks.priority.2')}</option>
                <option value="3">{t('today.tasks.priority.3')}</option>
                <option value="4">{t('today.tasks.priority.4')}</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>{t('today.tasks.fieldStart')}<input type="datetime-local" value={form.start_at} onChange={(event) => setForm({ ...form, start_at: event.target.value })} /></label>
            <label>{t('today.tasks.fieldDeadline')}<input type="datetime-local" value={form.deadline_at} onChange={(event) => setForm({ ...form, deadline_at: event.target.value })} /></label>
          </div>
          <label>
            {t('today.tasks.fieldOwner')}
            <select value={form.primary_owner_id} onChange={(event) => setForm({ ...form, primary_owner_id: event.target.value })}>
              <option value="">{t('today.tasks.noneSelected')}</option>
              {workers?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}
            </select>
          </label>
          <UserTagPicker label={t('today.tasks.fieldAssignees')} value={form.assignee_ids} users={workers || []} allLabel={t('today.tasks.selectAll')} onChange={(assignee_ids) => setForm({ ...form, assignee_ids })} />
          <label>{t('today.tasks.fieldLocation')}<input value={form.work_location} onChange={(event) => setForm({ ...form, work_location: event.target.value })} placeholder={t('today.tasks.locationPlaceholder')} /></label>
          <div className="delegated-task-actions">
            <button className="primary-action" disabled={busy}><Save size={16} />{t('today.tasks.save')}</button>
            <button type="button" className="secondary-action" onClick={archive} disabled={busy}><Archive size={16} />{t('today.tasks.archive')}</button>
            <button type="button" className="danger-action" onClick={deleteTask} disabled={busy}><Trash2 size={16} />{t('today.tasks.delete')}</button>
          </div>
        </form>
      </aside>
    </div>,
    document.body,
  )
}

type TaskTab = 'today' | 'delegated' | 'organization'

/** Today's tasks: assigned to me, delegated by me, and (manager mode) the organization's open work. */
export function TasksWidget() {
  const { t } = useTranslation()
  const employeeId = useAuthStore((state) => state.actor?.employee_id)
  const { isManagerMode } = useWorkspaceMode()
  const today = new Date().toISOString().slice(0, 10)
  const todayTasks = useEnterpriseTasks(undefined, { date_from: today, date_to: today }, { scope: 'mine' })
  const delegatedTasks = useEnterpriseTasks(undefined, undefined, { scope: 'delegated' })
  const oversightTasks = useEnterpriseTasks(undefined, undefined, { scope: 'oversight' }, { enabled: isManagerMode })
  const workers = useWorkerDirectory()
  const updateTask = useUpdateEnterpriseTask()
  const deleteTask = useDeleteEnterpriseTask()
  const [taskTab, setTaskTab] = useState<TaskTab>('today')
  const [selectedTask, setSelectedTask] = useState<EnterpriseTask | null>(null)
  useEffect(() => {
    if (!isManagerMode) setTaskTab('today')
  }, [isManagerMode])

  const activeTasks = (todayTasks.data ?? []).filter((task) => task.assignee_ids.includes(employeeId ?? -1))
  const delegated = delegatedTasks.data ?? []
  const organizationTasks = (oversightTasks.data ?? []).filter((task) => task.workflow_status !== 'done' && task.workflow_status !== 'cancelled')
  const completeDelegatedTask = (task: EnterpriseTask) => updateTask.mutate({ id: task.id, version: task.version, workflow_status: 'done' })
  const deleteDelegatedTask = (task: EnterpriseTask) => {
    if (window.confirm(t('today.tasks.confirmDelete', { title: task.title }))) deleteTask.mutate(task.id)
  }
  const tab = (key: TaskTab, label: string) => (
    <button className={taskTab === key ? 'active' : ''} onClick={() => setTaskTab(key)} role="tab" aria-selected={taskTab === key}>{label}</button>
  )
  const details = (task: EnterpriseTask) => (
    <button onClick={() => setSelectedTask(task)} aria-label={t('today.tasks.detailsLabel', { title: task.title })} title={t('today.tasks.details')}><MoreHorizontal size={17} /></button>
  )

  return (
    <section className="today-widget today-task-column" aria-label={t('today.widget.tasks.title')}>
      <WidgetHeader icon={ListChecks} title={t('today.widget.tasks.title')} />
      <div className="today-task-tabs" role="tablist" aria-label={t('today.tasks.list')}>
        {tab('today', t('today.tasks.tabMine'))}
        {isManagerMode && tab('delegated', t('today.tasks.tabDelegated'))}
        {isManagerMode && tab('organization', t('today.tasks.tabOrganization'))}
      </div>
      <div className="today-task-list">
        {taskTab === 'today' ? (
          activeTasks.length ? activeTasks.map((task) => (
            <article className="today-task-row" key={task.id}>
              <div><strong>{task.title}</strong><span>{task.primary_owner_name || t('today.tasks.noOwner')}</span></div>
              <time>{task.deadline_at ? new Date(task.deadline_at).toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit' }) : t('today.tasks.noDeadline')}</time>
            </article>
          )) : <p>{t('today.tasks.emptyToday')}</p>
        ) : taskTab === 'organization' ? (
          organizationTasks.length ? organizationTasks.map((task) => (
            <article className="today-task-row delegated-task-row" key={task.id}>
              <div>
                <strong>{task.title}</strong>
                <span>{task.assignee_names.length ? task.assignee_names.join(', ') : t('today.tasks.noOwner')} · {task.workflow_status === 'review' ? t('today.tasks.inReview') : t('today.tasks.inProgress')}</span>
              </div>
              <div className="today-task-controls">{details(task)}</div>
            </article>
          )) : <p>{t('today.tasks.emptyOrganization')}</p>
        ) : delegated.length ? delegated.map((task) => (
          <article className="today-task-row delegated-task-row" key={task.id}>
            <div>
              <strong>{task.title}</strong>
              <span>{task.assignee_names.length ? task.assignee_names.join(', ') : t('today.tasks.noOwner')} · {task.workflow_status === 'done' ? t('today.tasks.finished') : t('today.tasks.inProgress')}</span>
            </div>
            <div className="today-task-controls">
              <button onClick={() => completeDelegatedTask(task)} disabled={task.workflow_status === 'done' || updateTask.isPending} aria-label={t('today.tasks.markDoneLabel', { title: task.title })} title={t('today.tasks.markDone')}><Check size={16} /></button>
              <button onClick={() => deleteDelegatedTask(task)} disabled={deleteTask.isPending} aria-label={t('today.tasks.deleteLabel', { title: task.title })} title={t('today.tasks.delete')}><Trash2 size={15} /></button>
              {details(task)}
            </div>
          </article>
        )) : <p>{t('today.tasks.emptyDelegated')}</p>}
      </div>
      {selectedTask && <DelegatedTaskSheet task={selectedTask} workers={workers.data} onClose={() => setSelectedTask(null)} />}
    </section>
  )
}
