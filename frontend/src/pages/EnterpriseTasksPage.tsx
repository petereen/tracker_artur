import { useMemo, useState } from "react";
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
  Download,
  Filter,
  GripVertical,
  LayoutGrid,
  List,
  MapPin,
  MessageSquare,
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
  useAddTaskDependency,
  useAttachments,
  useCreateEnterpriseTask,
  useCreateSavedView,
  useDeleteEnterpriseTask,
  useDeadlines,
  useDeleteAttachment,
  useDeleteSavedView,
  useDeleteTaskCheckItem,
  useDeleteTaskDependency,
  useEnterpriseTasks,
  useProjects,
  useResolveTaskComment,
  useSavedViews,
  useTaskActivity,
  useTaskCheckItems,
  useTaskComments,
  useTaskDependencies,
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

function TaskCard({
  task,
  onOpen,
  draggable = false,
}: {
  task: EnterpriseTask;
  onOpen: () => void;
  draggable?: boolean;
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
      <button className="task-card-body" onClick={onOpen}>
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
        </div>
      </button>
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

function SavedViewControls({
  view,
  setView,
  filters,
  setFilters,
}: {
  view: "board" | "list" | "timeline" | "calendar";
  setView: (value: "board" | "list" | "timeline" | "calendar") => void;
  filters: TaskFilters;
  setFilters: (value: TaskFilters) => void;
}) {
  const saved = useSavedViews("tasks");
  const create = useCreateSavedView();
  const remove = useDeleteSavedView();
  const save = () => {
    const name = window.prompt("Харагдацын нэр");
    if (name?.trim())
      create.mutate({
        module: "tasks",
        name: name.trim(),
        view_type: view,
        filters: { ...filters },
        grouping: {},
        visible_columns: [],
        sort: [],
        is_shared: false,
      });
  };
  return (
    <div className="saved-view-controls">
      <select
        aria-label="Хадгалсан харагдац"
        defaultValue=""
        onChange={(event) => {
          const item = saved.data?.find(
            (candidate) => candidate.id === Number(event.target.value),
          );
          if (item) {
            setView(item.view_type as typeof view);
            setFilters(item.filters as TaskFilters);
          }
        }}
      >
        <option value="">Хадгалсан харагдац</option>
        {saved.data?.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <button className="text-action" onClick={save}>
        Хадгалах
      </button>
      {saved.data?.length ? (
        <button
          className="text-action"
          onClick={() => {
            const id = Number(window.prompt("Устгах харагдацын ID"));
            if (id) remove.mutate(id);
          }}
        >
          Устгах
        </button>
      ) : null}
    </div>
  );
}

function TaskCollaboration({
  task,
  tasks,
  canManage,
  conflict,
  resolveConflict,
}: {
  task: EnterpriseTask;
  tasks: EnterpriseTask[];
  canManage: boolean;
  conflict: EnterpriseTask | null;
  resolveConflict: (reapply: boolean) => void;
}) {
  const [tab, setTab] = useState<
    | "subtasks"
    | "checklist"
    | "dependencies"
    | "comments"
    | "files"
    | "activity"
  >("subtasks");
  const [text, setText] = useState("");
  const [progress, setProgress] = useState(0);
  const checks = useTaskCheckItems(task.id);
  const addCheck = useAddTaskCheckItem();
  const updateCheck = useUpdateTaskCheckItem();
  const deleteCheck = useDeleteTaskCheckItem();
  const dependencies = useTaskDependencies(task.id);
  const addDependency = useAddTaskDependency();
  const deleteDependency = useDeleteTaskDependency();
  const comments = useTaskComments(task.id);
  const addComment = useAddTaskComment();
  const resolveComment = useResolveTaskComment();
  const files = useAttachments("task", task.id);
  const upload = useUploadAttachment();
  const deleteFile = useDeleteAttachment();
  const activity = useTaskActivity(task.id);
  const subtasks = tasks.filter((item) => item.parent_task_id === task.id);
  const submitText = () => {
    if (!text.trim()) return;
    if (tab === "checklist")
      addCheck.mutate({ taskId: task.id, text: text.trim() });
    if (tab === "comments")
      addComment.mutate({ taskId: task.id, text: text.trim() });
    setText("");
  };
  return (
    <section className="task-collaboration">
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
      <nav aria-label="Даалгаврын дэлгэрэнгүй">
        {(
          [
            "subtasks",
            "checklist",
            "dependencies",
            "comments",
            "files",
            "activity",
          ] as const
        ).map((name) => (
          <button
            type="button"
            className={tab === name ? "active" : ""}
            key={name}
            onClick={() => setTab(name)}
          >
            {
              {
                subtasks: "Дэд ажил",
                checklist: "Checklist",
                dependencies: "Хамаарал",
                comments: "Сэтгэгдэл",
                files: "Файл",
                activity: "Түүх",
              }[name]
            }
          </button>
        ))}
      </nav>
      {tab === "subtasks" && (
        <div className="collaboration-list">
          {subtasks.length ? (
            subtasks.map((item) => (
              <article key={item.id}>
                <strong>{item.title}</strong>
                <span>{item.workflow_status}</span>
              </article>
            ))
          ) : (
            <p>Дэд даалгавар байхгүй байна.</p>
          )}
        </div>
      )}
      {tab === "checklist" && (
        <>
          <div className="collaboration-list">
            {checks.data?.map((item) => (
              <article key={item.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={item.is_completed}
                    onChange={() =>
                      updateCheck.mutate({
                        taskId: task.id,
                        id: item.id,
                        is_completed: !item.is_completed,
                      })
                    }
                  />
                  {item.text}
                </label>
                <button
                  type="button"
                  aria-label="Checklist устгах"
                  onClick={() =>
                    deleteCheck.mutate({ taskId: task.id, id: item.id })
                  }
                >
                  <Trash2 size={14} />
                </button>
              </article>
            ))}
          </div>
          <div className="inline-compose">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Checklist нэмэх"
            />
            <button type="button" onClick={submitText}>
              Нэмэх
            </button>
          </div>
        </>
      )}
      {tab === "dependencies" && (
        <>
          <div className="collaboration-list">
            {dependencies.data?.map((item) => (
              <article key={item.id}>
                <strong>{item.predecessor_title}</strong>
                {canManage && (
                  <button
                    type="button"
                    aria-label="Хамаарал устгах"
                    onClick={() =>
                      deleteDependency.mutate({ taskId: task.id, id: item.id })
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </article>
            ))}
          </div>
          {canManage && (
            <select
              defaultValue=""
              onChange={(e) => {
                if (e.target.value)
                  addDependency.mutate({
                    taskId: task.id,
                    predecessor_task_id: Number(e.target.value),
                  });
                e.target.value = "";
              }}
            >
              <option value="">Өмнөх даалгавар нэмэх</option>
              {tasks
                .filter((item) => item.id !== task.id)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
            </select>
          )}
        </>
      )}
      {tab === "comments" && (
        <>
          <div className="collaboration-list">
            {comments.data?.map((item) => (
              <article
                className={item.is_resolved ? "resolved" : ""}
                key={item.id}
              >
                <div>
                  <MessageSquare size={14} />
                  <span>{item.text}</span>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    resolveComment.mutate({
                      taskId: task.id,
                      id: item.id,
                      is_resolved: !item.is_resolved,
                    })
                  }
                >
                  {item.is_resolved ? "Нээх" : "Шийдсэн"}
                </button>
              </article>
            ))}
          </div>
          <div className="inline-compose">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="@mention бүхий сэтгэгдэл"
            />
            <button type="button" onClick={submitText}>
              Илгээх
            </button>
          </div>
        </>
      )}
      {tab === "files" && (
        <>
          <label className="file-upload">
            <Paperclip size={15} />
            Файл нэмэх
            <input
              type="file"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file)
                  upload.mutate({
                    objectType: "task",
                    objectId: task.id,
                    file,
                    onProgress: setProgress,
                  });
              }}
            />
          </label>
          {upload.isPending && <progress value={progress} max="100" />}
          <div className="collaboration-list">
            {files.data?.map((file) => (
              <article key={file.id}>
                <span>
                  {file.filename} · {Math.ceil(file.size / 1024)} KB ·{" "}
                  {file.scan_status}
                </span>
                <div>
                  <button
                    type="button"
                    aria-label="Татах"
                    onClick={() => downloadAttachment(file.id, file.filename)}
                  >
                    <Download size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label="Файл устгах"
                    onClick={() =>
                      deleteFile.mutate({
                        id: file.id,
                        objectType: "task",
                        objectId: task.id,
                      })
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      {tab === "activity" && (
        <div className="collaboration-list">
          {activity.data?.map((item) => (
            <article key={item.id}>
              <span>
                {item.entity_type}: {item.action}
              </span>
              <time>{new Date(item.created_at).toLocaleString("mn-MN")}</time>
            </article>
          ))}
        </div>
      )}
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
  const [creating, setCreating] = useState(false);
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
            (task) => task.workflow_status === column.key,
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
    setCreating(true);
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await createTask.mutateAsync(payload());
      setCreating(false);
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
  if (section === "deadlines")
    return <Deadlines onBack={() => setSection("tasks")} />;
  const resetFilters = () => {
    setFilters({ kind: "all", scope: "mine" });
    setFilterProjectId(projectId);
    setDateFilters({});
  };
  return (
    <div className="task-workspace">
      <div className="view-toolbar">
        <div>
          <h2>Миний даалгавар</h2>
          <p>Таны хариуцаж буй ажил, төсөл болон дэд даалгавар.</p>
        </div>
        <div className="toolbar-cluster">
          {canReview && (
            <button
              className="secondary-action compact"
              onClick={() => setSection("deadlines")}
            >
              Хугацааны хяналт
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
      <SavedViewControls
        view={view}
        setView={setView}
        filters={filters}
        setFilters={setFilters}
      />
      {lastMove && (
        <div className="undo-banner" role="status">
          Даалгавар зөөгдлөө.<button onClick={undoMove}>Буцаах</button>
        </div>
      )}
      <div className="task-filterbar">
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
                  }}
                >
                  <X />
                </button>
              </div>
              <form className="sheet-form" onSubmit={selected ? save : submit}>
                {formFields}
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
              {selected && (
                <TaskCollaboration
                  task={selected}
                  tasks={tasks.data ?? []}
                  canManage={canReview}
                  conflict={conflict}
                  resolveConflict={resolveConflict}
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

function Deadlines({ onBack }: { onBack: () => void }) {
  const deadlines = useDeadlines();
  const [type, setType] = useState("all");
  const [project, setProject] = useState("all");
  const [status, setStatus] = useState("all");
  const [owner, setOwner] = useState("all");
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
          <h2>Байгууллагын хугацааны хяналт</h2>
        </div>
        <div className="deadline-filters">
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
                <article key={item.id}>
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
                  <span>{item.status}</span>
                </article>
              ))}
          </section>
        ))}
      </div>
    </div>
  );
}
