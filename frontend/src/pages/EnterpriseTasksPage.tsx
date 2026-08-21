import { useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AnimatePresence, motion } from "motion/react";
import {
  CalendarDays,
  ArrowUp,
  Check,
  CheckSquare2,
  Download,
  FileText,
  Filter,
  GripVertical,
  History,
  LayoutGrid,
  List,
  ListChecks,
  MapPin,
  MessageSquare,
  MoreVertical,
  Paperclip,
  Plus,
  Rows3,
  Save,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import {
  downloadAttachment,
  EnterpriseTask,
  TaskFilters,
  useAddTaskCheckItem,
  useAddTaskComment,
  useAttachments,
  useCreateEnterpriseTask,
  useDeleteEnterpriseTask,
  useDeadlines,
  useDeleteAttachment,
  useDeleteTaskCheckItem,
  useDeleteTaskComment,
  useEnterpriseTasks,
  useEnterpriseTask,
  useProjects,
  useResolveTaskComment,
  useTaskActivity,
  useTaskCheckItems,
  useTaskComments,
  useUpdateEnterpriseTask,
  useUpdateTaskCheckItem,
  useUploadAttachment,
  useWorkerDirectory,
  WorkflowStatus,
} from "../api/enterprise";
import { periodFromPreset } from "../components/TimePeriodFilter";
import { EMPTY_ROLES, useAuthStore } from "../store/auth";
import {
  KanbanSkeleton,
  QueryRegion,
  TableSkeleton,
} from "../components/Loading";
import { UserTagPicker } from "../components/UserTagPicker";
import { resolvePublicAssetUrl } from "../platform/runtime";

const COLUMNS: { key: WorkflowStatus; label: string }[] = [
  { key: "backlog", label: "Backlog" },
  { key: "to_do", label: "Хийх" },
  { key: "in_progress", label: "Хийгдэж буй" },
  { key: "review", label: "Хянах" },
  { key: "done", label: "Дууссан" },
];
const EMPTY = {
  title: "",
  description: "",
  project_id: "",
  parent_task_id: "",
  primary_owner_id: "",
  assignee_ids: [] as number[],
  reviewer_ids: [] as number[],
  workflow_status: "to_do" as WorkflowStatus,
  priority: "2",
  start_at: "",
  deadline_at: "",
  estimate_minutes: "",
  work_location_type: "",
  work_location: "",
};
const taskPlace = (task: EnterpriseTask) =>
  task.work_location ||
  (task.work_location_type === "office"
    ? "Оффис"
    : task.work_location_type === "remote"
      ? "Remote"
      : "Байршилгүй");

const taskCreatorName = (task: EnterpriseTask) => task.creator_name || "Тодорхойгүй";

const formatTaskCreatedAt = (createdAt: string) =>
  new Date(createdAt).toLocaleString("mn-MN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

function TaskCreatorAvatar({ task, large = false }: { task: EnterpriseTask; large?: boolean }) {
  const name = taskCreatorName(task);
  return (
    <span className={`task-creator-avatar ${large ? "large" : ""}`} aria-hidden="true">
      {task.creator_avatar_url ? <img src={resolvePublicAssetUrl(task.creator_avatar_url) || undefined} alt="" /> : name.slice(0, 1).toUpperCase()}
    </span>
  );
}

const statusLabel = (status: WorkflowStatus) =>
  COLUMNS.find((column) => column.key === status)?.label || status;

function TaskCard({
  task,
  onOpen,
  draggable = false,
  subtasks = [],
  onToggleSubtask,
  subtaskUpdating = false,
}: {
  task: EnterpriseTask;
  onOpen: (task?: EnterpriseTask) => void;
  draggable?: boolean;
  subtasks?: EnterpriseTask[];
  onToggleSubtask?: (subtask: EnterpriseTask) => void;
  subtaskUpdating?: boolean;
}) {
  const sortable = useSortable({
    id: task.id,
    data: { status: task.workflow_status },
    disabled: !draggable,
  });
  return (
    <div
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      }}
      className={`kanban-card task-card-clear ${task.parent_task_id ? "subtask-card" : ""} ${sortable.isDragging ? "dragging" : ""}`}
    >
      <button className="task-card-body" onClick={() => onOpen()}>
        <div className="task-priority" data-priority={task.priority} />
        {task.parent_task_id && (
          <span className="subtask-tag">Дэд даалгавар</span>
        )}
        <h3>{task.title}</h3>
        <div className="task-facts">
          <span>
            <UserRound size={13} />
            {task.primary_owner_name || "Хариуцагчгүй"}
          </span>
          <span>
            <CalendarDays size={13} />
            {task.deadline_at
              ? new Date(task.deadline_at).toLocaleString("mn-MN")
              : "Хугацаагүй"}
          </span>
          <span>
            <MapPin size={13} />
            {taskPlace(task)}
          </span>
          <span>{task.project_name || "Төсөл сонгоогүй"}</span>
          <span className="task-creator-fact" title={`Үүсгэсэн: ${taskCreatorName(task)}`}>
            <TaskCreatorAvatar task={task} />
            Үүсгэсэн: {taskCreatorName(task)}
          </span>
        </div>
      </button>
      {subtasks.length > 0 && (
        <div className="nested-subtasks" aria-label={`${task.title} дэд даалгавар`}>
          <div className="nested-subtasks-heading">
            <span>Дэд даалгавар</span>
            <b>{subtasks.length}</b>
          </div>
          {subtasks.map((subtask) => (
            <article className="nested-subtask" key={subtask.id}>
              <input
                type="checkbox"
                checked={subtask.workflow_status === "done"}
                disabled={!onToggleSubtask || subtaskUpdating}
                aria-label={`${subtask.title} ${subtask.workflow_status === "done" ? "буцаах" : "дуусгах"}`}
                onChange={() => onToggleSubtask?.(subtask)}
              />
              <button type="button" className="nested-subtask-title" onClick={() => onOpen(subtask)}>
                <strong>{subtask.title}</strong>
                <small>
                  {subtask.primary_owner_name || "Хариуцагчгүй"}
                  {subtask.deadline_at && ` · ${new Date(subtask.deadline_at).toLocaleDateString("mn-MN")}`}
                </small>
              </button>
              <span className={`nested-subtask-status ${subtask.workflow_status}`}>
                {statusLabel(subtask.workflow_status)}
              </span>
            </article>
          ))}
        </div>
      )}
      {draggable && (
        <button
          className="drag-handle"
          aria-label={`${task.title} зөөх`}
          {...sortable.attributes}
          {...sortable.listeners}
        >
          <GripVertical size={15} />
        </button>
      )}
    </div>
  );
}
function Column({
  status,
  children,
}: {
  status: WorkflowStatus;
  children: React.ReactNode;
}) {
  const drop = useDroppable({ id: `column:${status}` });
  return (
    <div
      ref={drop.setNodeRef}
      className={`kanban-dropzone ${drop.isOver ? "over" : ""}`}
    >
      {children}
    </div>
  );
}

type CollaborationTab = "subtasks" | "checklist" | "comments" | "files" | "activity";

export const taskCollaborationLabels: Record<CollaborationTab, string> = {
  subtasks: "Дэд ажил",
  checklist: "Checklist",
  comments: "Сэтгэгдэл",
  files: "Файл",
  activity: "Түүх",
};

export function taskActivitySummary(item: { entity_type: string; action: string; after: Record<string, unknown>; before: Record<string, unknown> }) {
  const detail = item.after.text || item.before.text || item.after.filename || item.before.filename;
  const verb = item.action === "created" ? "нэмэгдлээ" : item.action === "deleted" ? "устгагдлаа" : item.action === "updated" ? "шинэчлэгдлээ" : item.action;
  const subject = item.entity_type === "task_check_item" ? "Checklist" : item.entity_type === "task_comment" ? "Сэтгэгдэл" : item.entity_type === "task_dependency" ? "Холбоос" : item.entity_type === "attachment" ? "Файл" : item.entity_type === "task" ? "Даалгавар" : item.entity_type;
  return detail ? `${subject}: “${detail}” ${verb}` : `${subject} ${verb}`;
}

export function commentMentionQuery(value: string, caret: number): string | null {
  const beforeCaret = value.slice(0, caret);
  const match = beforeCaret.match(/(?:^|\s)@([^\s@]*)$/u);
  return match ? match[1] : null;
}

function TaskCollaboration({
  task,
  tasks,
  canManage,
  conflict,
  resolveConflict,
  onCreateSubtask,
  onOpenSubtask,
  onDeleteSubtask,
  workers,
}: {
  task: EnterpriseTask;
  tasks: EnterpriseTask[];
  canManage: boolean;
  conflict: EnterpriseTask | null;
  resolveConflict: (reapply: boolean) => void;
  onCreateSubtask: () => void;
  onOpenSubtask: (task: EnterpriseTask) => void;
  onDeleteSubtask: (task: EnterpriseTask) => void;
  workers: { id: number; name: string }[];
}) {
  const [tab, setTab] = useState<CollaborationTab>("subtasks");
  const [text, setText] = useState("");
  const [progress, setProgress] = useState(0);
  const [commentMentionIds, setCommentMentionIds] = useState<number[]>([]);
  const commentInput = useRef<HTMLTextAreaElement>(null);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const checks = useTaskCheckItems(task.id);
  const addCheck = useAddTaskCheckItem();
  const updateCheck = useUpdateTaskCheckItem();
  const deleteCheck = useDeleteTaskCheckItem();
  const comments = useTaskComments(task.id);
  const addComment = useAddTaskComment();
  const resolveComment = useResolveTaskComment();
  const deleteComment = useDeleteTaskComment();
  const files = useAttachments("task", task.id);
  const upload = useUploadAttachment();
  const deleteFile = useDeleteAttachment();
  const activity = useTaskActivity(task.id);
  const subtasks = tasks.filter((item) => item.parent_task_id === task.id);
  const completedChecks = checks.data?.filter((item) => item.is_completed).length ?? 0;
  const totalChecks = checks.data?.length ?? 0;
  const checklistPercent = totalChecks ? Math.round((completedChecks / totalChecks) * 100) : 0;
  const tabs: { id: CollaborationTab; Icon: typeof ListChecks; count?: number }[] = [
    { id: "subtasks", Icon: CheckSquare2, count: subtasks.length },
    { id: "checklist", Icon: ListChecks, count: totalChecks },
    { id: "comments", Icon: MessageSquare, count: comments.data?.filter((item) => !item.is_resolved).length },
    { id: "files", Icon: FileText, count: files.data?.length },
    { id: "activity", Icon: History, count: activity.data?.length },
  ];
  const submitText = async () => {
    if (!text.trim()) return;
    try {
      if (tab === "checklist")
        await addCheck.mutateAsync({ taskId: task.id, text: text.trim() });
      if (tab === "comments")
        await addComment.mutateAsync({ taskId: task.id, text: text.trim(), mentions: commentMentionIds });
      setText("");
      setCommentMentionIds([]);
    } catch {
      // The mutation keeps the user's draft and shows the server error.
    }
  };
  return (
    <section className="task-collaboration" aria-label="Даалгаврын collaboration">
      {conflict && (
        <div className="conflict-banner" role="alert">
          <strong>Даалгавар өөр төхөөрөмж дээр шинэчлэгдсэн.</strong>
          <button type="button" onClick={() => resolveConflict(false)}>
            Сүүлийн хувилбар
          </button>
          <button type="button" onClick={() => resolveConflict(true)}>
            Дахин хэрэглэх
          </button>
        </div>
      )}
      <div className="collaboration-heading">
        <div>
          <span className="eyebrow">Collaboration</span>
          <h3>{taskCollaborationLabels[tab]}</h3>
        </div>
        {tab === "checklist" && totalChecks > 0 && <span className="collaboration-summary">{completedChecks}/{totalChecks} дууссан</span>}
      </div>
      <nav className="collaboration-tabs" role="tablist" aria-label="Даалгаврын дэлгэрэнгүй">
        {tabs.map(({ id, Icon, count }) => (
          <button
            type="button"
            className={tab === id ? "active" : ""}
            key={id}
            role="tab"
            aria-selected={tab === id}
            aria-controls={`task-collaboration-${id}`}
            onClick={() => setTab(id)}
          >
            <Icon size={15} />
            <span>{taskCollaborationLabels[id]}</span>
            {typeof count === "number" && <b>{count}</b>}
          </button>
        ))}
      </nav>
      <div className="collaboration-panel" id={`task-collaboration-${tab}`} role="tabpanel">
        {tab === "subtasks" && (
          <>
            <div className="collaboration-panel-copy">
              <p>Том ажлыг жижиг, хянахад хялбар алхмуудад хуваана.</p>
              {canManage && <button type="button" className="collaboration-icon-button collaboration-add-button" aria-label="Дэд ажил нэмэх" title="Дэд ажил нэмэх" onClick={onCreateSubtask}><Plus size={17} /></button>}
            </div>
            {subtasks.length ? <div className="collaboration-list subtask-list">
              {subtasks.map((item) => <article key={item.id}>
                <div>
                  <button type="button" className="subtask-title-button" onClick={() => onOpenSubtask(item)}><strong>{item.title}</strong></button>
                  <small>{item.primary_owner_name || "Хариуцагч сонгоогүй"} · {item.deadline_at ? new Date(item.deadline_at).toLocaleDateString("mn-MN") : "Хугацаагүй"}</small>
                </div>
                <div className="subtask-list-actions"><span className="collaboration-status">{item.workflow_status}</span>{canManage && <><button type="button" aria-label="Дэд ажлыг засах" title="Засах" onClick={() => onOpenSubtask(item)}><Save size={14} /></button><button type="button" aria-label="Дэд ажлыг устгах" title="Устгах" onClick={() => onDeleteSubtask(item)}><Trash2 size={14} /></button></>}</div>
              </article>)}
            </div> : <div className="collaboration-empty"><CheckSquare2 size={20} /><p>Одоогоор дэд ажил алга.</p></div>}
          </>
        )}
        {tab === "checklist" && (
          <>
            <div className="collaboration-panel-copy">
              <p>Гүйцэтгэлийг жижиг алхмуудаар тэмдэглэж, явцыг шууд хянаарай.</p>
              <span className="collaboration-summary">{checklistPercent}%</span>
            </div>
            <div className="checklist-progress" aria-label={`Checklist ${checklistPercent}%`}><i style={{ width: `${checklistPercent}%` }} /></div>
            {checks.isLoading ? <p className="collaboration-state">Checklist ачаалж байна…</p> : checks.isError ? <p className="collaboration-state error">Checklist ачаалж чадсангүй.</p> : totalChecks ? <div className="collaboration-list checklist-list">
              {checks.data?.map((item) => <article key={item.id}>
                <label>
                  <input type="checkbox" checked={item.is_completed} disabled={updateCheck.isPending} onChange={() => updateCheck.mutate({ taskId: task.id, id: item.id, is_completed: !item.is_completed })} />
                  <span>{item.text}</span>
                </label>
                <button type="button" aria-label="Checklist устгах" disabled={deleteCheck.isPending} onClick={() => deleteCheck.mutate({ taskId: task.id, id: item.id })}><Trash2 size={14} /></button>
              </article>)}
            </div> : <div className="collaboration-empty"><ListChecks size={20} /><p>Checklist хоосон байна.</p></div>}
            <div className="collaboration-composer collaboration-pill-composer">
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Checklist-д ажил нэмэх" onKeyDown={(event) => { if (event.key === "Enter") submitText(); }} />
              <button type="button" className="composer-submit" aria-label="Checklist нэмэх" title="Checklist нэмэх" onClick={submitText} disabled={!text.trim() || addCheck.isPending}><ArrowUp size={17} /></button>
            </div>
          </>
        )}
        {tab === "comments" && (
          <>
            <div className="collaboration-panel-copy"><p>Шийдвэр, асуултаа нэг газар үлдээгээд холбогдох хүнээ дурдана.</p></div>
            {comments.isLoading ? <p className="collaboration-state">Сэтгэгдэл ачаалж байна…</p> : comments.isError ? <p className="collaboration-state error">Сэтгэгдэл ачаалж чадсангүй.</p> : comments.data?.length ? <div className="collaboration-list comment-list">
              {comments.data.map((item) => <article className={item.is_resolved ? "resolved" : ""} key={item.id}>
                <div><span className="comment-avatar">{item.author_avatar_url ? <img src={resolvePublicAssetUrl(item.author_avatar_url) || undefined} alt="" /> : (item.author_name || "?").slice(0, 1)}</span><div><strong>{item.author_name || "Тодорхойгүй хэрэглэгч"}</strong><span>{item.text}</span><small>{new Date(item.created_at).toLocaleString("mn-MN")}</small></div></div>
                <div className="comment-actions"><button type="button" className={`comment-status-toggle ${item.is_resolved ? "is-resolved" : ""}`} aria-label={item.is_resolved ? "Сэтгэгдлийг дахин нээх" : "Сэтгэгдлийг шийдсэн гэж тэмдэглэх"} title={item.is_resolved ? "Нээх" : "Шийдсэн"} disabled={resolveComment.isPending} onClick={() => resolveComment.mutate({ taskId: task.id, id: item.id, is_resolved: !item.is_resolved })}><Check size={15} /></button><button type="button" className="icon-danger" aria-label="Сэтгэгдэл устгах" title="Устгах" disabled={deleteComment.isPending} onClick={() => { if (window.confirm("Энэ сэтгэгдлийг устгах уу?")) deleteComment.mutate({ taskId: task.id, id: item.id }); }}><Trash2 size={15} /></button></div>
              </article>)}
            </div> : <div className="collaboration-empty"><MessageSquare size={20} /><p>Сэтгэгдэл алга байна.</p></div>}
            <div className="comment-composer">
              <div className="comment-input-wrap">
                <textarea ref={commentInput} rows={1} value={text} onChange={(e) => { setText(e.target.value); setMentionQuery(commentMentionQuery(e.target.value, e.target.selectionStart)); }} onClick={(e) => setMentionQuery(commentMentionQuery(e.currentTarget.value, e.currentTarget.selectionStart))} onKeyUp={(e) => setMentionQuery(commentMentionQuery(e.currentTarget.value, e.currentTarget.selectionStart))} placeholder="Сэтгэгдэл бичих…" />
                <button type="button" className="composer-submit" aria-label="Сэтгэгдэл илгээх" title="Сэтгэгдэл илгээх" onClick={submitText} disabled={!text.trim() || addComment.isPending}><ArrowUp size={17} /></button>
                {mentionQuery !== null && workers.filter((worker) => worker.name.toLocaleLowerCase().includes(mentionQuery.toLocaleLowerCase())).slice(0, 6).length > 0 && (
                  <div className="mention-suggestions" role="listbox" aria-label="Дурдах ажилтан">
                    {workers.filter((worker) => worker.name.toLocaleLowerCase().includes(mentionQuery.toLocaleLowerCase())).slice(0, 6).map((worker) => (
                      <button type="button" role="option" key={worker.id} onMouseDown={(event) => event.preventDefault()} onClick={() => {
                        const input = commentInput.current;
                        if (!input) return;
                        const start = input.selectionStart;
                        const before = text.slice(0, start).replace(/@[^\s@]*$/u, `@${worker.name} `);
                        const next = before + text.slice(start);
                        setText(next);
                        setCommentMentionIds((ids) => ids.includes(worker.id) ? ids : [...ids, worker.id]);
                        setMentionQuery(null);
                        requestAnimationFrame(() => { input.focus(); const position = before.length; input.setSelectionRange(position, position); });
                      }}><span className="worker-avatar">{worker.name[0]}</span><span>{worker.name}</span></button>
                    ))}
                  </div>
                )}
              </div>
              <UserTagPicker label="Дурдсан хүмүүс" value={commentMentionIds} users={workers} onChange={setCommentMentionIds} />
              <div><span>Дурдсан хүмүүс web мэдэгдэл авна.</span></div>
            </div>
          </>
        )}
        {tab === "files" && (
          <>
            <div className="collaboration-panel-copy"><p>Холбогдох баримт, эх файлаа аюулгүйгээр хавсаргана.</p><label className={`collaboration-icon-button collaboration-attach-button ${upload.isPending ? "uploading" : ""}`} aria-label="Файл хавсаргах" title={upload.isPending ? "Файл байршуулж байна…" : "Файл хавсаргах"}>
              <Paperclip size={18} />
              <input type="file" disabled={upload.isPending} onChange={async (e) => { const file = e.target.files?.[0]; if (!file) return; try { await upload.mutateAsync({ objectType: "task", objectId: task.id, file, onProgress: setProgress }); e.currentTarget.value = ""; setProgress(0); } catch { /* the hook displays the error */ } }} />
            </label></div>
            {upload.isPending && <div className="upload-progress"><i style={{ width: `${progress}%` }} /></div>}
            {files.isLoading ? <p className="collaboration-state">Файл ачаалж байна…</p> : files.isError ? <p className="collaboration-state error">Файл ачаалж чадсангүй.</p> : files.data?.length ? <div className="collaboration-list file-list">
              {files.data.map((file) => <article key={file.id}><div><FileText size={17} /><div><strong>{file.filename}</strong><small>{Math.ceil(file.size / 1024)} KB</small></div></div><div><span className={`file-scan ${file.scan_status}`}>{file.scan_status}</span><button type="button" aria-label="Татах" onClick={() => downloadAttachment(file.id, file.filename)}><Download size={14} /></button><button type="button" aria-label="Файл устгах" disabled={deleteFile.isPending} onClick={() => deleteFile.mutate({ id: file.id, objectType: "task", objectId: task.id })}><Trash2 size={14} /></button></div></article>)}
            </div> : <div className="collaboration-empty"><FileText size={20} /><p>Хавсаргасан файл алга.</p></div>}
          </>
        )}
        {tab === "activity" && (
          <>
            <div className="collaboration-panel-copy"><p>Энэ даалгаварт хийсэн өөрчлөлт бүр энд дарааллаар хадгалагдана.</p></div>
            {activity.isLoading ? <p className="collaboration-state">Түүх ачаалж байна…</p> : activity.isError ? <p className="collaboration-state error">Түүх ачаалж чадсангүй.</p> : activity.data?.length ? <div className="activity-list">
              {activity.data.map((item) => <article key={item.id}><span className="activity-icon">{item.action === "created" ? <Plus size={14} /> : item.action === "updated" ? <Check size={14} /> : <History size={14} />}</span><div><strong>{taskActivitySummary(item)}</strong><time>{new Date(item.created_at).toLocaleString("mn-MN")}</time></div></article>)}
            </div> : <div className="collaboration-empty"><History size={20} /><p>Түүхийн бичлэг алга байна.</p></div>}
          </>
        )}
      </div>
    </section>
  );
}

export function EnterpriseTasksPage() {
  const params = new URLSearchParams(location.search);
  const projectId = params.get("project")
    ? Number(params.get("project"))
    : undefined;
  const [filterProjectId, setFilterProjectId] = useState<number | undefined>(
    projectId,
  );
  const [section, setSection] = useState<"tasks" | "deadlines">("tasks");
  const period = useMemo(() => periodFromPreset("month"), []);
  const [view, setView] = useState<"board" | "list" | "timeline" | "calendar">(
    "board",
  );
  const [selected, setSelected] = useState<EnterpriseTask | null>(null);
  const [deadlineTaskId, setDeadlineTaskId] = useState<number | undefined>();
  const [creating, setCreating] = useState(false);
  const [returnToTask, setReturnToTask] = useState<EnterpriseTask | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [form, setForm] = useState({
    ...EMPTY,
    project_id: projectId ? String(projectId) : "",
  });
  const [filters, setFilters] = useState<TaskFilters>({
    kind: "all",
    scope: "mine",
  });
  const [dateFilters, setDateFilters] = useState<{
    date_from?: string;
    date_to?: string;
  }>({});
  const [conflict, setConflict] = useState<EnterpriseTask | null>(null);
  const [lastMove, setLastMove] = useState<{
    task: EnterpriseTask;
    newVersion: number;
  } | null>(null);
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES);
  const employeeId = useAuthStore((state) => state.actor?.employee_id);
  const canReview = roles.some((role) =>
    ["admin", "manager", "team_lead"].includes(role),
  );
  const tasks = useEnterpriseTasks(
    filterProjectId,
    Object.keys(dateFilters).length ? dateFilters : undefined,
    filters,
  );
  const deepLinkedTask = useEnterpriseTask(params.get("task") ? Number(params.get("task")) : undefined);
  const deadlineTask = useEnterpriseTask(deadlineTaskId);
  const projects = useProjects();
  const workers = useWorkerDirectory();
  const createTask = useCreateEnterpriseTask();
  const updateTask = useUpdateEnterpriseTask();
  const deleteTask = useDeleteEnterpriseTask();
  const grouped = useMemo(
    () =>
      Object.fromEntries(
        COLUMNS.map((column) => [
          column.key,
          (tasks.data ?? []).filter(
            (task) => !task.parent_task_id && task.workflow_status === column.key,
          ),
        ]),
      ) as Record<WorkflowStatus, EnterpriseTask[]>,
    [tasks.data],
  );
  const days = useMemo(() => {
    const result: Date[] = [];
    const cursor = new Date(`${period.date_from}T12:00:00`);
    const end = new Date(`${period.date_to}T12:00:00`);
    while (cursor <= end && result.length < 93) {
      result.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    return result;
  }, [period]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const payload = () => ({
    title: form.title,
    description: form.description || null,
    project_id: form.project_id ? Number(form.project_id) : null,
    parent_task_id: form.parent_task_id ? Number(form.parent_task_id) : null,
    primary_owner_id: form.primary_owner_id
      ? Number(form.primary_owner_id)
      : null,
    assignee_ids: form.assignee_ids,
    reviewer_ids: form.reviewer_ids,
    workflow_status: form.workflow_status,
    priority: Number(form.priority),
    start_at: form.start_at ? new Date(form.start_at).toISOString() : null,
    deadline_at: form.deadline_at
      ? new Date(form.deadline_at).toISOString()
      : null,
    estimate_minutes: form.estimate_minutes
      ? Number(form.estimate_minutes)
      : null,
    work_location_type: (form.work_location_type ||
      null) as EnterpriseTask["work_location_type"],
    work_location: form.work_location || null,
  });
  const openCreate = (workflow_status: WorkflowStatus = "to_do") => {
    setForm({
      ...EMPTY,
      project_id: projectId ? String(projectId) : "",
      workflow_status,
    });
    setReturnToTask(null);
    setCreating(true);
  };
  const openSubtaskCreate = (parent: EnterpriseTask) => {
    setForm({
      ...EMPTY,
      project_id: parent.project_id ? String(parent.project_id) : "",
      parent_task_id: String(parent.id),
      workflow_status: "to_do",
    });
    setReturnToTask(parent);
    setSelected(null);
    setCreating(true);
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const created = await createTask.mutateAsync(payload()) as EnterpriseTask;
      setCreating(false);
      setSelected(returnToTask || created);
      setReturnToTask(null);
      setForm({ ...EMPTY, project_id: projectId ? String(projectId) : "" });
    } catch {
      /* hook reports */
    }
  };
  const openTask = (task: EnterpriseTask) => {
    setSelected(task);
    setForm({
      title: task.title,
      description: task.description || "",
      project_id: task.project_id ? String(task.project_id) : "",
      parent_task_id: task.parent_task_id ? String(task.parent_task_id) : "",
      primary_owner_id: task.primary_owner_id
        ? String(task.primary_owner_id)
        : "",
      assignee_ids: task.assignee_ids || [],
      reviewer_ids: task.reviewer_ids || (task.reviewer_id ? [task.reviewer_id] : []),
      workflow_status: task.workflow_status,
      priority: String(task.priority),
      start_at: task.start_at?.slice(0, 16) || "",
      deadline_at: task.deadline_at?.slice(0, 16) || "",
      estimate_minutes: task.estimate_minutes
        ? String(task.estimate_minutes)
        : "",
      work_location_type: task.work_location_type || "",
      work_location: task.work_location || "",
    });
  };
  useEffect(() => {
    if (deepLinkedTask.data && !selected) openTask(deepLinkedTask.data);
  }, [deepLinkedTask.data]);
  useEffect(() => {
    if (deadlineTaskId && deadlineTask.data) {
      openTask(deadlineTask.data);
      setDeadlineTaskId(undefined);
    }
  }, [deadlineTask.data, deadlineTaskId]);
  useEffect(() => {
    if (params.get("create") === "1") openCreate();
  }, []);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    try {
      await updateTask.mutateAsync({
        id: selected.id,
        version: selected.version,
        ...payload(),
      });
      setConflict(null);
      setSelected(null);
    } catch (error: any) {
      const latest = error.response?.data?.detail?.latest;
      if (error.response?.status === 409 && latest)
        setConflict({ ...selected, ...latest });
    }
  };
  const remove = async () => {
    if (!selected || !window.confirm("Энэ даалгаврыг устгах уу?")) return;
    try {
      await deleteTask.mutateAsync(selected.id);
      setConflict(null);
      setSelected(null);
    } catch {
      /* hook reports */
    }
  };
  const onDragEnd = (event: DragEndEvent) => {
    const task = tasks.data?.find(
      (item) => item.id === Number(event.active.id),
    );
    if (!task || !event.over) return;
    const overId = String(event.over.id);
    const overTask = tasks.data?.find(
      (item) => item.id === Number(event.over?.id),
    );
    const status = (
      overId.startsWith("column:") ? overId.slice(7) : overTask?.workflow_status
    ) as WorkflowStatus | undefined;
    if (!status || status === task.workflow_status) return;
    const target = grouped[status];
    const targetIndex = overTask
      ? target.findIndex((item) => item.id === overTask.id)
      : target.length;
    updateTask
      .mutateAsync({
        id: task.id,
        version: task.version,
        workflow_status: status,
        sort_position: targetIndex + 1,
      })
      .then((updated) => {
        setLastMove({ task, newVersion: updated.version });
        window.setTimeout(
          () =>
            setLastMove((value) => (value?.task.id === task.id ? null : value)),
          8000,
        );
      })
      .catch(() => undefined);
  };
  const toggleSubtask = (subtask: EnterpriseTask) => {
    updateTask.mutate({
      id: subtask.id,
      version: subtask.version,
      workflow_status: subtask.workflow_status === "done" ? "to_do" : "done",
    });
  };
  const undoMove = () => {
    if (!lastMove) return;
    updateTask.mutate({
      id: lastMove.task.id,
      version: lastMove.newVersion,
      workflow_status: lastMove.task.workflow_status,
      sort_position: lastMove.task.sort_position,
    });
    setLastMove(null);
  };
  const resolveConflict = async (reapply: boolean) => {
    if (!conflict) return;
    if (reapply) {
      const updated = await updateTask.mutateAsync({
        id: conflict.id,
        version: conflict.version,
        ...payload(),
      });
      setSelected(updated);
    } else openTask(conflict);
    setConflict(null);
  };
  const toggleAssignee = (id: number) =>
    setForm({
      ...form,
      assignee_ids: form.assignee_ids.includes(id)
        ? form.assignee_ids.filter((value) => value !== id)
        : [...form.assignee_ids, id],
    });
  const assignAll = () =>
    setForm({
      ...form,
      assignee_ids: workers.data?.map((worker) => worker.id) ?? [],
    });
  const possibleParents = (tasks.data || []).filter(
    (task) =>
      !task.parent_task_id &&
      task.id !== selected?.id &&
      (!form.project_id || String(task.project_id || "") === form.project_id),
  );
  const formFields = (
    <>
      <label>
        Юу хийх вэ?
        <input
          required
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
        />
      </label>
      <label>
        Тайлбар
        <textarea
          rows={4}
          value={form.description}
          onChange={(event) =>
            setForm({ ...form, description: event.target.value })
          }
        />
      </label>
      <div className="form-row">
        <label>
          Төсөл
          <select
            value={form.project_id}
            onChange={(event) =>
              setForm({
                ...form,
                project_id: event.target.value,
                parent_task_id: "",
              })
            }
          >
            <option value="">Төсөл сонгоогүй</option>
            {projects.data?.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Харьяалагдах даалгавар
          <select
            value={form.parent_task_id}
            onChange={(event) =>
              setForm({ ...form, parent_task_id: event.target.value })
            }
          >
            <option value="">Үндсэн даалгавар</option>
            {possibleParents.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Хэн хариуцах вэ?
        <select
          value={form.primary_owner_id}
          onChange={(event) =>
            setForm({ ...form, primary_owner_id: event.target.value })
          }
        >
          <option value="">Хариуцагчгүй</option>
          {workers.data?.map((worker) => (
            <option key={worker.id} value={worker.id}>
              {worker.name}
            </option>
          ))}
        </select>
      </label>
      <UserTagPicker label="Оролцогчид" value={form.assignee_ids} users={workers.data || []} allLabel="Бүгдийг сонгох" onChange={(assignee_ids) => setForm({ ...form, assignee_ids })} />
      <div className="form-row">
        <label>
          Эхлэх
          <input
            type="datetime-local"
            value={form.start_at}
            onChange={(event) =>
              setForm({ ...form, start_at: event.target.value })
            }
          />
        </label>
        <label>
          Дуусах
          <input
            type="datetime-local"
            value={form.deadline_at}
            onChange={(event) =>
              setForm({ ...form, deadline_at: event.target.value })
            }
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Хаана?
          <select
            value={form.work_location_type}
            onChange={(event) =>
              setForm({ ...form, work_location_type: event.target.value })
            }
          >
            <option value="">Байршилгүй</option>
            <option value="office">Оффис</option>
            <option value="remote">Remote</option>
            <option value="custom">Тодорхой байршил</option>
          </select>
        </label>
        <label>
          Байршлын дэлгэрэнгүй
          <input
            value={form.work_location}
            onChange={(event) =>
              setForm({ ...form, work_location: event.target.value })
            }
            placeholder="Жишээ: УБ оффис, 3-р давхар"
            disabled={form.work_location_type !== "custom"}
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Төлөв
          <select
            value={form.workflow_status}
            onChange={(event) =>
              setForm({
                ...form,
                workflow_status: event.target.value as WorkflowStatus,
              })
            }
          >
            {COLUMNS.map((column) => (
              <option key={column.key} value={column.key}>
                {column.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Тэргүүлэх зэрэг
          <select
            value={form.priority}
            onChange={(event) =>
              setForm({ ...form, priority: event.target.value })
            }
          >
            <option value="1">1 — Нэн яаралтай</option>
            <option value="2">2 — Дундаж</option>
            <option value="3">3 — Яаралтай бус</option>
          </select>
        </label>
      </div>
      <label>
        Тооцоолсон минут
        <input
          type="number"
          min="0"
          value={form.estimate_minutes}
          onChange={(event) =>
            setForm({ ...form, estimate_minutes: event.target.value })
          }
        />
      </label>
    </>
  );
  const simplifiedFormFields = (
    <>
      <label>Нэр<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
      <label>Тайлбар<textarea rows={4} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
      <div className="form-row"><label>Эхлэх огноо<input type="datetime-local" value={form.start_at} onChange={(event) => setForm({ ...form, start_at: event.target.value })} /></label><label>Дуусах огноо<input type="datetime-local" value={form.deadline_at} onChange={(event) => setForm({ ...form, deadline_at: event.target.value })} /></label></div>
      <label>Тэргүүлэх зэрэг<select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option value="1">1 — Нэн яаралтай</option><option value="2">2 — Дундаж</option><option value="3">3 — Яаралтай бус</option></select></label>
      <label>Хэн хариуцах вэ?<select value={form.primary_owner_id} onChange={(event) => setForm({ ...form, primary_owner_id: event.target.value })}><option value="">Хариуцагчгүй</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>
      <UserTagPicker label="Оролцогчид" value={form.assignee_ids} users={workers.data || []} onChange={(assignee_ids) => setForm({ ...form, assignee_ids })} />
    </>
  );
  if (section === "deadlines")
    return <Deadlines onBack={() => setSection("tasks")} onEditTask={(id) => setDeadlineTaskId(id)} />;
  const resetFilters = () => {
    setFilters({ kind: "all", scope: "mine" });
    setFilterProjectId(projectId);
    setDateFilters({});
  };
  return (
    <div className="task-workspace">
      <div className="workspace-toolbar task-toolbar">
        <div className="task-viewmodes toolbar-start">
          <div className="segmented-control">
            <button
              className={view === "board" ? "active" : ""}
              onClick={() => setView("board")}
            >
              <LayoutGrid size={15} />
              Самбар
            </button>
            <button
              className={view === "list" ? "active" : ""}
              onClick={() => setView("list")}
            >
              <List size={15} />
              Жагсаалт
            </button>
            <button
              className={view === "timeline" ? "active" : ""}
              onClick={() => setView("timeline")}
            >
              <Rows3 size={15} />
              Timeline
            </button>
            <button
              className={view === "calendar" ? "active" : ""}
              onClick={() => setView("calendar")}
            >
              <CalendarDays size={15} />
              Календарь
            </button>
          </div>
        </div>
        <div className="toolbar-cluster">
          <div className="task-filter-control">
            <button
              className="secondary-action compact"
              onClick={() => setFiltersOpen(!filtersOpen)}
              aria-expanded={filtersOpen}
            >
              <Filter size={15} />
              Шүүлтүүр
            </button>
            {filtersOpen && (
            <div className="task-filter-panel">
              <div className="form-row">
                <label>
                  Эхлэх огноо
                  <input
                    type="date"
                    value={dateFilters.date_from || ""}
                    onChange={(event) =>
                      setDateFilters({
                        ...dateFilters,
                        date_from: event.target.value || undefined,
                      })
                    }
                  />
                </label>
                <label>
                  Дуусах огноо
                  <input
                    type="date"
                    value={dateFilters.date_to || ""}
                    onChange={(event) =>
                      setDateFilters({
                        ...dateFilters,
                        date_to: event.target.value || undefined,
                      })
                    }
                  />
                </label>
              </div>
              <select
                value={filters.kind}
                onChange={(event) =>
                  setFilters({
                    ...filters,
                    kind: event.target.value as TaskFilters["kind"],
                  })
                }
              >
                <option value="all">Бүх төрөл</option>
                <option value="standalone">Бие даасан</option>
                <option value="project">Төслийн</option>
                <option value="subtask">Дэд даалгавар</option>
              </select>
              <select
                value={filterProjectId || ""}
                onChange={(event) =>
                  setFilterProjectId(
                    event.target.value ? Number(event.target.value) : undefined,
                  )
                }
              >
                <option value="">Бүх төсөл</option>
                {projects.data?.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <select
                value={filters.workflow_status || ""}
                onChange={(event) =>
                  setFilters({
                    ...filters,
                    workflow_status: event.target.value || undefined,
                  })
                }
              >
                <option value="">Бүх төлөв</option>
                {COLUMNS.map((column) => (
                  <option key={column.key} value={column.key}>
                    {column.label}
                  </option>
                ))}
              </select>
              <select
                value={filters.priority || ""}
                onChange={(event) =>
                  setFilters({
                    ...filters,
                    priority: event.target.value
                      ? (Number(event.target.value) as 1 | 2 | 3)
                      : undefined,
                  })
                }
              >
                <option value="">Бүх priority</option>
                <option value="1">1 — Нэн яаралтай</option>
                <option value="2">2 — Дундаж</option>
                <option value="3">3 — Яаралтай бус</option>
              </select>
              <label>
                <input
                  type="checkbox"
                  checked={filters.overdue || false}
                  onChange={(event) =>
                    setFilters({ ...filters, overdue: event.target.checked })
                  }
                />
                Хугацаа хэтэрсэн
              </label>
              <button className="text-action" onClick={resetFilters}>
                Цэвэрлэх
              </button>
            </div>
          )}
          </div>
          {canReview && (
            <button
              className="secondary-action compact"
              onClick={() => setSection("deadlines")}
            >
              Нийт даалгаврууд
            </button>
          )}
          <button
            className="primary-action compact"
            onClick={() => openCreate()}
          >
            <Plus size={16} />
            Даалгавар
            </button>
        </div>
      </div>
      {lastMove && (
        <div className="undo-banner" role="status">
          Даалгавар зөөгдлөө.<button onClick={undoMove}>Буцаах</button>
        </div>
      )}
      <QueryRegion
        pending={tasks.isLoading || tasks.isFetching}
        skeleton={
          view === "board" ? <KanbanSkeleton /> : <TableSkeleton rows={6} />
        }
      >
        {view === "board" && (
          <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <div className="kanban-board">
              {COLUMNS.map((column) => {
                const isAssignedReviewer = (task: EnterpriseTask) =>
                  employeeId != null &&
                  (task.reviewer_ids || [task.reviewer_id]).some((id) => id != null && Number(id) === Number(employeeId));
                const reviewQueue =
                  column.key === "review"
                    ? grouped.review.filter(isAssignedReviewer)
                    : [];
                const otherTasks =
                  column.key === "review"
                    ? grouped.review.filter((task) => !isAssignedReviewer(task))
                    : grouped[column.key];
                return (
                  <section className="kanban-column" key={column.key}>
                    <header>
                      <span>{column.label}</span>
                      <button
                        className="column-add"
                        onClick={() => openCreate(column.key)}
                        aria-label={`${column.label} төлөвт даалгавар нэмэх`}
                      >
                        <Plus size={14} />
                      </button>
                      <b>{grouped[column.key].length}</b>
                    </header>
                    <Column status={column.key}>
                      {otherTasks.map((task) => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          subtasks={(tasks.data ?? []).filter((item) => item.parent_task_id === task.id)}
                          onToggleSubtask={toggleSubtask}
                          subtaskUpdating={updateTask.isPending}
                          draggable
                          onOpen={() => openTask(task)}
                        />
                      ))}
                    </Column>
                    {column.key === "review" && (
                      <section className="review-queue">
                        <header>
                          <strong>Хянах шаардлагатай</strong>
                          <b>{reviewQueue.length}</b>
                        </header>
                        {reviewQueue.length ? (
                          reviewQueue.map((task) => (
                            <TaskCard
                              key={task.id}
                              task={task}
                              subtasks={(tasks.data ?? []).filter((item) => item.parent_task_id === task.id)}
                              onToggleSubtask={toggleSubtask}
                              subtaskUpdating={updateTask.isPending}
                              draggable
                              onOpen={() => openTask(task)}
                            />
                          ))
                        ) : (
                          <p>Танд хянах шаардлагатай даалгавар байхгүй байна.</p>
                        )}
                      </section>
                    )}
                  </section>
                );
              })}
            </div>
          </DndContext>
        )}
        {view === "list" && (
          <div className="task-list panel">
            {tasks.data?.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onOpen={() => openTask(task)}
              />
            ))}
          </div>
        )}
        {view === "timeline" && (
          <Timeline
            tasks={tasks.data ?? []}
            period={period}
            onOpen={openTask}
          />
        )}
        {view === "calendar" && (
          <div className="task-calendar panel">
            {days.map((day) => {
              const key = day.toISOString().slice(0, 10);
              const dayTasks = (tasks.data ?? []).filter(
                (task) =>
                  (task.start_at || task.deadline_at)?.slice(0, 10) === key,
              );
              return (
                <section key={key}>
                  <header>
                    <strong>{day.getDate()}</strong>
                    <span>
                      {day.toLocaleDateString("mn-MN", { weekday: "short" })}
                    </span>
                  </header>
                  {dayTasks.map((task) => (
                    <button
                      className={task.parent_task_id ? "subtask-event" : ""}
                      key={task.id}
                      onClick={() => openTask(task)}
                    >
                      {task.title}
                    </button>
                  ))}
                </section>
              );
            })}
          </div>
        )}
      </QueryRegion>
      <AnimatePresence>
        {(selected || creating) && (
          <motion.div
            className="sheet-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onMouseDown={() => {
              setSelected(null);
              setCreating(false);
              setReturnToTask(null);
            }}
          >
            <motion.aside
              className="detail-sheet"
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", bounce: 0, duration: 0.4 }}
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="sheet-header">
                <div>
                  <span className="eyebrow">
                    {selected ? `Task #${selected.id}` : "Quick create"}
                  </span>
                  <h2>{selected ? selected.title : "Шинэ даалгавар"}</h2>
                </div>
                <button
                  onClick={() => {
                    setSelected(null);
                    setCreating(false);
                    setReturnToTask(null);
                  }}
                >
                  <X />
                </button>
              </div>
              {selected && (
                <section className="task-creator-meta" aria-label="Даалгавар үүсгэсэн мэдээлэл">
                  <TaskCreatorAvatar task={selected} large />
                  <div>
                    <span className="eyebrow">Даалгавар үүсгэгч</span>
                    <strong>
                      Үүсгэсэн: {taskCreatorName(selected)} <span aria-hidden="true">•</span>{" "}
                      <time dateTime={selected.created_at}>{formatTaskCreatedAt(selected.created_at)}</time>
                    </strong>
                  </div>
                </section>
              )}
              <form className="sheet-form" onSubmit={selected ? save : submit}>
                {selected?.parent_task_id ? simplifiedFormFields : formFields}
                <UserTagPicker label="Хянагч" value={form.reviewer_ids} users={workers.data || []} onChange={(reviewer_ids) => setForm({ ...form, reviewer_ids })} />
                {selected ? (
                  <div className="task-settings-actions">
                    <button
                      type="button"
                      className="danger-action task-delete-action"
                      aria-label="Даалгавар устгах"
                      title="Даалгавар устгах"
                      onClick={remove}
                      disabled={deleteTask.isPending || updateTask.isPending}
                    >
                      <Trash2 size={16} />
                    </button>
                    <button
                      className="primary-action task-save-action"
                      disabled={deleteTask.isPending || updateTask.isPending}
                    >
                      <Save size={16} />
                      Хадгалах
                    </button>
                  </div>
                ) : (
                  <button
                    className="primary-action"
                    disabled={createTask.isPending}
                  >
                    Үүсгэх
                  </button>
                )}
              </form>
              {selected && !selected.parent_task_id && (
                <TaskCollaboration
                  task={selected}
                  tasks={tasks.data ?? []}
                  canManage={Boolean(selected.can_manage_collaboration)}
                  conflict={conflict}
                  resolveConflict={resolveConflict}
                  onCreateSubtask={() => openSubtaskCreate(selected)}
                  onOpenSubtask={openTask}
                  onDeleteSubtask={(subtask) => { if (window.confirm("Энэ дэд ажлыг устгах уу?")) deleteTask.mutate(subtask.id); }}
                  workers={workers.data ?? []}
                />
              )}
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Timeline({
  tasks,
  period,
  onOpen,
}: {
  tasks: EnterpriseTask[];
  period: { date_from: string; date_to: string };
  onOpen: (task: EnterpriseTask) => void;
}) {
  const start = new Date(`${period.date_from}T00:00:00`).getTime();
  const end = new Date(`${period.date_to}T23:59:59`).getTime();
  const duration = Math.max(end - start, 86_400_000);
  const labels = [0, 0.25, 0.5, 0.75, 1].map((part) =>
    new Date(start + duration * part).toLocaleDateString("mn-MN", {
      month: "short",
      day: "numeric",
    }),
  );
  const scheduled = tasks.filter((task) => task.start_at || task.deadline_at);
  return (
    <section
      className="task-timeline panel"
      aria-label="Даалгаврын хугацааны зураглал"
    >
      <header className="timeline-axis">
        <span>Даалгавар</span>
        <div>
          {labels.map((label) => (
            <b key={label}>{label}</b>
          ))}
        </div>
      </header>
      {scheduled.length ? (
        scheduled.map((task) => {
          const taskStart = new Date(
            task.start_at || task.deadline_at!,
          ).getTime();
          const taskEnd = new Date(
            task.deadline_at || task.start_at!,
          ).getTime();
          const left = Math.max(
            0,
            Math.min(100, ((taskStart - start) / duration) * 100),
          );
          const width = Math.max(
            2.5,
            Math.min(
              100 - left,
              ((Math.max(taskEnd, taskStart + 86_400_000) - taskStart) /
                duration) *
                100,
            ),
          );
          return (
            <button
              key={task.id}
              className={task.parent_task_id ? "subtask-timeline-row" : ""}
              onClick={() => onOpen(task)}
            >
              <strong>{task.title}</strong>
              <span className="timeline-track">
                <i
                  className={task.is_overdue ? "overdue" : ""}
                  style={{ left: `${left}%`, width: `${width}%` }}
                >
                  <em>{task.primary_owner_name || "Томилоогүй"}</em>
                </i>
              </span>
            </button>
          );
        })
      ) : (
        <p className="timeline-empty">
          Энэ хугацаанд товлосон даалгавар байхгүй байна. Даалгаварт эхлэх эсвэл дуусах
          огноо оруулж Timeline дээр харна.
        </p>
      )}
    </section>
  );
}

function Deadlines({ onBack, onEditTask }: { onBack: () => void; onEditTask: (id: number) => void }) {
  const deadlines = useDeadlines();
  const updateTask = useUpdateEnterpriseTask();
  const deleteTask = useDeleteEnterpriseTask();
  const [type, setType] = useState("all");
  const [project, setProject] = useState("all");
  const [status, setStatus] = useState("all");
  const [owner, setOwner] = useState("all");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const all = deadlines.data || [];
  const projects = Array.from(
    new Set(all.map((item) => item.project_name).filter(Boolean)),
  ) as string[];
  const statuses = Array.from(
    new Set(all.map((item) => item.status).filter(Boolean)),
  ) as string[];
  const owners = Array.from(
    new Set(all.map((item) => item.owner).filter(Boolean)),
  ) as string[];
  const visible = all.filter(
    (item) =>
      (type === "all" || item.type === type) &&
      (project === "all" || item.project_name === project) &&
      (status === "all" || item.status === status) &&
      (owner === "all" || item.owner === owner),
  );
  const visibleTasks = visible.filter((item) => item.type === "task" || item.type === "subtask");
  const selectedTasks = visibleTasks.filter((item) => selectedIds.includes(item.entity_id));
  const allVisibleSelected = visibleTasks.length > 0 && visibleTasks.every((item) => selectedIds.includes(item.entity_id));
  const toggleSelected = (id: number) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const changeStatus = async (item: (typeof all)[number], workflow_status: WorkflowStatus) => {
    if (item.version == null) return;
    await updateTask.mutateAsync({ id: item.entity_id, version: item.version, workflow_status });
    setOpenMenu(null);
  };
  const batchStatus = async (workflow_status: WorkflowStatus) => {
    for (const item of selectedTasks) {
      if (item.version != null) await updateTask.mutateAsync({ id: item.entity_id, version: item.version, workflow_status });
    }
    setSelectedIds([]);
  };
  const batchDelete = async () => {
    if (!selectedTasks.length || !window.confirm(`${selectedTasks.length} даалгаврыг устгах уу?`)) return;
    for (const item of selectedTasks) await deleteTask.mutateAsync(item.entity_id);
    setSelectedIds([]);
  };
  const buckets = [
    { id: "overdue", label: "Хугацаа хэтэрсэн" },
    { id: "soon", label: "7 хоногт" },
    { id: "later", label: "Дараа" },
    { id: "none", label: "Хугацаагүй" },
  ];
  return (
    <div className="deadline-workspace">
      <div className="view-toolbar">
        <div>
          <button className="text-action" onClick={onBack}>
            ← Миний даалгавар
          </button>
          <h2>Байгууллагын нийт даалгаврууд</h2>
        </div>
        <div className="deadline-filters">
          {visibleTasks.length > 0 && <label className="deadline-select-all"><input type="checkbox" checked={allVisibleSelected} onChange={() => setSelectedIds(allVisibleSelected ? [] : visibleTasks.map((item) => item.entity_id))} />Бүгдийг сонгох</label>}
          {selectedTasks.length > 0 && <div className="deadline-batch-actions" aria-label="Сонгосон даалгаврын багц үйлдэл">
            <span>{selectedTasks.length} сонгосон</span>
            <select aria-label="Сонгосон даалгаврын төлөв" defaultValue="" onChange={(event) => { if (event.target.value) void batchStatus(event.target.value as WorkflowStatus); }} disabled={updateTask.isPending}>
              <option value="">Төлөв өөрчлөх</option>
              {COLUMNS.map((column) => <option key={column.key} value={column.key}>{column.label}</option>)}
            </select>
            <button type="button" className="danger-action compact" onClick={() => void batchDelete()} disabled={deleteTask.isPending}><Trash2 size={14} />Устгах</button>
          </div>}
          <select
            value={type}
            onChange={(event) => setType(event.target.value)}
          >
            <option value="all">Бүх төрөл</option>
            <option value="project">Төсөл</option>
            <option value="plan">Төлөвлөгөө</option>
            <option value="task">Даалгавар</option>
            <option value="subtask">Дэд даалгавар</option>
          </select>
          <select
            value={project}
            onChange={(event) => setProject(event.target.value)}
          >
            <option value="all">Бүх төсөл</option>
            {projects.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          <select
            value={owner}
            onChange={(event) => setOwner(event.target.value)}
          >
            <option value="all">Бүх хариуцагч</option>
            {owners.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="all">Бүх төлөв</option>
            {statuses.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="deadline-groups">
        {buckets.map((bucket) => (
          <section className="panel" key={bucket.id}>
            <header>
              <strong>{bucket.label}</strong>
              <span>
                {visible.filter((item) => item.bucket === bucket.id).length}
              </span>
            </header>
            {visible
              .filter((item) => item.bucket === bucket.id)
              .map((item) => (
                <article key={item.id} className={item.type === "task" || item.type === "subtask" ? "deadline-task-row" : ""}>
                  {(item.type === "task" || item.type === "subtask") && <input type="checkbox" aria-label={`${item.title} сонгох`} checked={selectedIds.includes(item.entity_id)} onChange={() => toggleSelected(item.entity_id)} />}
                  <span className={`deadline-type ${item.type}`}>
                    {item.type}
                  </span>
                  <div>
                    <strong>{item.title}</strong>
                    <small>
                      {item.project_name || item.owner || "Байгууллага"}
                    </small>
                  </div>
                  <time>
                    {item.due_date
                      ? new Date(item.due_date).toLocaleDateString("mn-MN")
                      : "—"}
                  </time>
                  <span className={`status-pill ${item.status}`}>{statusLabel(item.status as WorkflowStatus)}</span>
                  {(item.type === "task" || item.type === "subtask") && <div className="deadline-row-menu">
                    <button type="button" className="icon-button" aria-label={`${item.title} үйлдлүүд`} aria-expanded={openMenu === item.id} onClick={() => setOpenMenu(openMenu === item.id ? null : item.id)}><MoreVertical size={18} /></button>
                    {openMenu === item.id && <div className="deadline-action-menu">
                      <button type="button" onClick={() => onEditTask(item.entity_id)}>Засах</button>
                      <label>Төлөв<select value={item.status} onChange={(event) => void changeStatus(item, event.target.value as WorkflowStatus)} disabled={updateTask.isPending}>{COLUMNS.map((column) => <option key={column.key} value={column.key}>{column.label}</option>)}</select></label>
                      <button type="button" className="danger" onClick={() => { if (window.confirm(`“${item.title}” даалгаврыг устгах уу?`)) void deleteTask.mutateAsync(item.entity_id).then(() => setOpenMenu(null)); }}>Устгах</button>
                    </div>}
                  </div>}
                </article>
              ))}
          </section>
        ))}
      </div>
    </div>
  );
}
