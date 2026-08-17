import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { motion } from "motion/react";
import {
  Archive,
  ArrowUpRight,
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  Coffee,
  House,
  Laptop2,
  MoreHorizontal,
  Pause,
  Play,
  Save,
  Trash2,
  X,
} from "lucide-react";
import {
  EnterpriseTask,
  useClock,
  useClockAction,
  useCalendarEvents,
  useDeleteEnterpriseTask,
  useEnterpriseSummary,
  useEnterpriseTasks,
  useStartCheckin,
  useSubmitCheckin,
  useTodayAgenda,
  useTodayCheckin,
  useUpdateEnterpriseTask,
  useWorkerDirectory,
  WorkflowStatus,
} from "../api/enterprise";
import {
  PeriodPreset,
  periodFromPreset,
  TimePeriodFilter,
} from "../components/TimePeriodFilter";
import { EMPTY_ROLES, useAuthStore } from "../store/auth";
import { UserTagPicker } from "../components/UserTagPicker";

function formatDuration(seconds: number) {
  seconds = Math.max(0, Math.floor(seconds));
  return [
    Math.floor(seconds / 3600),
    Math.floor((seconds % 3600) / 60),
    seconds % 60,
  ]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function formatLocalTime(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
}

const toInputDateTime = (value: string | null) =>
  value ? new Date(value).toISOString().slice(0, 16) : "";

type MiniCalendarRange = {
  id: string;
  title: string;
  week: number;
  start: number;
  end: number;
  lane: number;
  laneCount: number;
  isStart: boolean;
  isEnd: boolean;
};

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function calendarDayKey(value: string | null | undefined) {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : localDateKey(parsed);
}

function DelegatedTaskSheet({
  task,
  workers,
  onClose,
}: {
  task: EnterpriseTask;
  workers: ReturnType<typeof useWorkerDirectory>["data"];
  onClose: () => void;
}) {
  const update = useUpdateEnterpriseTask();
  const remove = useDeleteEnterpriseTask();
  const [form, setForm] = useState({
    title: task.title,
    description: task.description || "",
    workflow_status: task.workflow_status,
    priority: String(task.priority),
    primary_owner_id: task.primary_owner_id
      ? String(task.primary_owner_id)
      : "",
    assignee_ids: task.assignee_ids,
    start_at: toInputDateTime(task.start_at),
    deadline_at: toInputDateTime(task.deadline_at),
    work_location: task.work_location || "",
  });
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    await update.mutateAsync({
      id: task.id,
      version: task.version,
      title: form.title,
      description: form.description || null,
      workflow_status: form.workflow_status,
      priority: Number(form.priority),
      primary_owner_id: form.primary_owner_id
        ? Number(form.primary_owner_id)
        : null,
      assignee_ids: form.assignee_ids,
      start_at: form.start_at ? new Date(form.start_at).toISOString() : null,
      deadline_at: form.deadline_at
        ? new Date(form.deadline_at).toISOString()
        : null,
      work_location: form.work_location || null,
    });
    onClose();
  };
  const archive = async () => {
    await update.mutateAsync({
      id: task.id,
      version: task.version,
      is_archived: true,
    });
    onClose();
  };
  const deleteTask = async () => {
    if (window.confirm(`“${task.title}” даалгаврыг бүрмөсөн устгах уу?`)) {
      await remove.mutateAsync(task.id);
      onClose();
    }
  };
  return (
    <div
      className="sheet-backdrop delegated-task-backdrop"
      onMouseDown={onClose}
    >
      <aside
        className="detail-sheet delegated-task-sheet"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sheet-header">
          <div>
            <span className="eyebrow">Миний өгсөн даалгавар</span>
            <h2>{task.title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Хаах">
            <X />
          </button>
        </div>
        <form className="sheet-form" onSubmit={save}>
          <label>
            Гарчиг
            <input
              required
              value={form.title}
              onChange={(event) =>
                setForm({ ...form, title: event.target.value })
              }
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
                {[
                  ["backlog", "Backlog"],
                  ["to_do", "Хийх"],
                  ["in_progress", "Хийгдэж буй"],
                  ["review", "Хянах"],
                  ["done", "Дууссан"],
                  ["cancelled", "Цуцлагдсан"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Эрэмбэ
              <select
                value={form.priority}
                onChange={(event) =>
                  setForm({ ...form, priority: event.target.value })
                }
              >
                <option value="1">Яаралтай</option>
                <option value="2">Энгийн</option>
                <option value="3">Бага</option>
                <option value="4">Маш бага</option>
              </select>
            </label>
          </div>
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
              Хугацаа
              <input
                type="datetime-local"
                value={form.deadline_at}
                onChange={(event) =>
                  setForm({ ...form, deadline_at: event.target.value })
                }
              />
            </label>
          </div>
          <label>
            Үндсэн хариуцагч
            <select
              value={form.primary_owner_id}
              onChange={(event) =>
                setForm({ ...form, primary_owner_id: event.target.value })
              }
            >
              <option value="">Сонгоогүй</option>
              {workers?.map((worker) => (
                <option key={worker.id} value={worker.id}>
                  {worker.name}
                </option>
              ))}
            </select>
          </label>
          <UserTagPicker label="Хариуцагчид" value={form.assignee_ids} users={workers || []} allLabel="Бүгдийг сонгох" onChange={(assignee_ids) => setForm({ ...form, assignee_ids })} />
          <label>
            Байршил
            <input
              value={form.work_location}
              onChange={(event) =>
                setForm({ ...form, work_location: event.target.value })
              }
              placeholder="Оффис, remote эсвэл тодорхой газар"
            />
          </label>
          <div className="delegated-task-actions">
            <button
              className="primary-action"
              disabled={update.isPending || remove.isPending}
            >
              <Save size={16} />
              Хадгалах
            </button>
            <button
              type="button"
              className="secondary-action"
              onClick={archive}
              disabled={update.isPending || remove.isPending}
            >
              <Archive size={16} />
              Архивлах
            </button>
            <button
              type="button"
              className="danger-action"
              onClick={deleteTask}
              disabled={update.isPending || remove.isPending}
            >
              <Trash2 size={16} />
              Устгах
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}

export function EnterpriseDashboardPage() {
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset | "custom">(
    "week",
  );
  const [period, setPeriod] = useState(() => periodFromPreset("week"));
  const summary = useEnterpriseSummary(period);
  const employeeId = useAuthStore((state) => state.actor?.employee_id);
  const clock = useClock(employeeId != null);
  const action = useClockAction();
  const todayCheckin = useTodayCheckin();
  const startCheckin = useStartCheckin();
  const submitCheckin = useSubmitCheckin();
  const [checkinOpen, setCheckinOpen] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>(() => {
    try { return JSON.parse(localStorage.getItem("oyuns-checkin-draft") || "{}"); } catch { return {}; }
  });
  const today = new Date().toISOString().slice(0, 10);
  const todayTasks = useEnterpriseTasks(undefined, {
    date_from: today,
    date_to: today,
  });
  const delegatedTasks = useEnterpriseTasks(undefined, undefined, {
    scope: "delegated",
  });
  const workers = useWorkerDirectory();
  const updateTask = useUpdateEnterpriseTask();
  const deleteTask = useDeleteEnterpriseTask();
  const [taskTab, setTaskTab] = useState<"today" | "delegated">("today");
  const [selectedDelegatedTask, setSelectedDelegatedTask] =
    useState<EnterpriseTask | null>(null);
  const agenda = useTodayAgenda();
  const monthDays = useMemo(() => {
    const now = new Date();
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
    return Array.from({ length: 42 }, (_, index) => {
      const day = new Date(first);
      day.setDate(day.getDate() + index);
      return day;
    });
  }, []);
  const miniCalendarTasks = useEnterpriseTasks(undefined, {
    date_from: localDateKey(monthDays[0]),
    date_to: localDateKey(monthDays[monthDays.length - 1]),
  });
  const miniCalendarEvents = useCalendarEvents("private", monthDays[20]);
  const miniCalendarVisibleTasks = useMemo(() => {
    const tasks = new Map<number, EnterpriseTask>();
    [...(miniCalendarEvents.data?.tasks ?? []), ...(miniCalendarTasks.data ?? []), ...(todayTasks.data ?? []), ...(agenda.data?.tasks ?? [])].forEach((task: EnterpriseTask) => tasks.set(task.id, task));
    return [...tasks.values()];
  }, [agenda.data?.tasks, miniCalendarEvents.data?.tasks, miniCalendarTasks.data, todayTasks.data]);
  const miniCalendarMarkerDates = useMemo(() => {
    const dates = new Set<string>();
    const add = (value: string | null | undefined) => {
      const key = calendarDayKey(value);
      if (key) dates.add(key);
    };
    miniCalendarVisibleTasks.forEach((task) => {
      if (!task.start_at || !task.deadline_at) add(task.start_at || task.deadline_at);
    });
    [...(miniCalendarEvents.data?.entries ?? []), ...(miniCalendarEvents.data?.time_blocks ?? []), ...(agenda.data?.entries ?? [])].forEach((item: any) => add(item.remind_at || item.starts_at || item.start_at));
    return dates;
  }, [agenda.data?.entries, miniCalendarEvents.data?.entries, miniCalendarEvents.data?.time_blocks, miniCalendarVisibleTasks]);
  const miniCalendarRanges = useMemo(() => {
    const visibleStart = localDateKey(monthDays[0]);
    const visibleEnd = localDateKey(monthDays[monthDays.length - 1]);
    const dayIndex = new Map(monthDays.map((day, index) => [localDateKey(day), index]));
    const segments: MiniCalendarRange[] = [];

    miniCalendarVisibleTasks.forEach((task) => {
      if (!task.start_at || !task.deadline_at) return;
      let taskStart = calendarDayKey(task.start_at)!;
      let taskEnd = calendarDayKey(task.deadline_at)!;
      if (taskEnd < taskStart) [taskStart, taskEnd] = [taskEnd, taskStart];
      if (taskEnd < visibleStart || taskStart > visibleEnd) return;
      const start = Math.max(0, dayIndex.get(taskStart) ?? (taskStart < visibleStart ? 0 : -1));
      const end = Math.min(monthDays.length - 1, dayIndex.get(taskEnd) ?? (taskEnd > visibleEnd ? monthDays.length - 1 : -1));
      if (start < 0 || end < start) return;
      for (let week = Math.floor(start / 7); week <= Math.floor(end / 7); week += 1) {
        const segmentStart = Math.max(start, week * 7);
        const segmentEnd = Math.min(end, week * 7 + 6);
        const overlapping = segments.filter((segment) => segment.week === week && segment.start <= segmentEnd && segment.end >= segmentStart);
        let lane = 0;
        while (overlapping.some((segment) => segment.lane === lane)) lane += 1;
        segments.push({
          id: `${task.id}-${week}`,
          title: task.title,
          week,
          start: segmentStart % 7,
          end: segmentEnd % 7,
          lane,
          laneCount: 0,
          isStart: segmentStart === start && taskStart >= visibleStart,
          isEnd: segmentEnd === end && taskEnd <= visibleEnd,
        });
      }
    });

    for (let week = 0; week < 6; week += 1) {
      const weekSegments = segments.filter((segment) => segment.week === week);
      const laneCount = Math.max(1, ...weekSegments.map((segment) => segment.lane + 1));
      weekSegments.forEach((segment) => { segment.laneCount = laneCount; });
    }
    return segments;
  }, [miniCalendarVisibleTasks, monthDays]);
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES);
  const isSupervisor = roles.some((role) =>
    ["admin", "manager", "team_lead"].includes(role),
  );
  const active = clock.data?.active;
  const clockReady = Boolean(clock.data);
  const [clientNow, setClientNow] = useState(() => Date.now());
  const serverClockRef = useRef<{ serverTimeMs: number; clientTimeMs: number } | null>(null);
  const clockRefetchRef = useRef(clock.refetch);
  clockRefetchRef.current = clock.refetch;
  const serverTime = clock.data?.server_time;
  useEffect(() => {
    if (!serverTime) return;
    const serverTimeMs = new Date(serverTime).getTime();
    if (Number.isFinite(serverTimeMs)) {
      serverClockRef.current = { serverTimeMs, clientTimeMs: Date.now() };
    }
  }, [serverTime]);
  useEffect(() => {
    if (!clockReady) return;
    // Prime both states so a later clock action can switch companions without
    // introducing a network request during the visible state transition.
    ["/oyuns-working.gif", "/oyuns-sleeping.gif"].forEach((src) => {
      const image = new Image();
      image.src = src;
    });
  }, [clockReady]);
  const activeTimerKey = active
    ? `${active.id}:${active.entry_type}:${active.started_at}`
    : null;
  useEffect(() => {
    let timer: number | undefined;
    const syncNow = () => setClientNow(Date.now());
    const clearTimer = () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
        timer = undefined;
      }
    };
    const startTimer = () => {
      if (
        activeTimerKey &&
        document.visibilityState === "visible" &&
        timer === undefined
      ) {
        timer = window.setInterval(syncNow, 1000);
      }
    };
    const handleVisibilityChange = () => {
      syncNow();
      if (document.visibilityState === "visible") {
        void clockRefetchRef.current();
        startTimer();
      } else {
        clearTimer();
      }
    };

    syncNow();
    startTimer();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [activeTimerKey]);
  const serverClock = serverClockRef.current;
  const initialServerTime = serverTime ? new Date(serverTime).getTime() : NaN;
  const clockNow = serverClock
    ? serverClock.serverTimeMs + (clientNow - serverClock.clientTimeMs)
    : Number.isFinite(initialServerTime)
      ? initialServerTime
      : clientNow;
  const recoveredClock = Boolean(active && (active.local_work_date !== today || clockNow - new Date(active.started_at).getTime() > 16 * 60 * 60 * 1000));
  const working = active?.entry_type === "work";
  const onBreak = active?.entry_type === "break";
  const companionSrc = clockReady
    ? working
      ? "/oyuns-working.gif"
      : "/oyuns-sleeping.gif"
    : null;
  const todayEntries = clock.data?.today_entries ?? [];
  const todayWorkSeconds = todayEntries.reduce((total, entry) => {
    if (entry.entry_type !== "work") return total;
    return (
      total +
      Math.max(
        0,
        ((entry.ended_at ? new Date(entry.ended_at).getTime() : clockNow) -
          new Date(entry.started_at).getTime()) /
          1000,
      )
    );
  }, 0);
  const activeTasks = (todayTasks.data ?? []).filter((task) =>
    task.assignee_ids.includes(employeeId ?? -1),
  );
  const delegated = delegatedTasks.data ?? [];
  const completeDelegatedTask = (task: EnterpriseTask) =>
    updateTask.mutate({
      id: task.id,
      version: task.version,
      workflow_status: "done",
    });
  const deleteDelegatedTask = (task: EnterpriseTask) => {
    if (window.confirm(`“${task.title}” даалгаврыг бүрмөсөн устгах уу?`))
      deleteTask.mutate(task.id);
  };

  const cards = [
    {
      label: "Идэвхтэй төсөл",
      value: summary.data?.active_projects ?? "—",
      icon: BriefcaseBusiness,
      tone: "blue",
    },
    {
      label: "Дууссан даалгавар",
      value: summary.data?.completed_tasks ?? "—",
      icon: CheckCircle2,
      tone: "green",
    },
    {
      label: "Гүйцэтгэл",
      value: summary.data ? `${summary.data.completion_rate}%` : "—",
      icon: ArrowUpRight,
      tone: "purple",
    },
    {
      label: "Ажилласан цаг",
      value: summary.data
        ? `${Math.round((summary.data.worked_minutes / 60) * 10) / 10}ц`
        : "—",
      icon: Coffee,
      tone: "amber",
    },
  ];

  const openCheckin = async () => {
    if (todayCheckin.data?.checkin?.status === "submitted") return;
    if (!todayCheckin.data?.checkin && todayCheckin.data?.template?.id)
      await startCheckin.mutateAsync(todayCheckin.data.template.id);
    setCheckinOpen(true);
  };
  const saveCheckin = async (event: React.FormEvent) => {
    event.preventDefault();
    const current =
      todayCheckin.data?.checkin ||
      (await startCheckin.mutateAsync(todayCheckin.data.template.id));
    const questions = todayCheckin.data?.template?.questions ?? [];
    await submitCheckin.mutateAsync({
      id: current.id,
      answers: questions.map((question: any) =>
        question.answer_type === "integer" || question.answer_type === "decimal"
          ? {
              question_id: question.id,
              value_numeric: Number(answers[question.id]),
            }
          : { question_id: question.id, value_text: answers[question.id] },
      ),
    });
    localStorage.removeItem("oyuns-checkin-draft");
    setAnswers({});
    setCheckinOpen(false);
  };

  useEffect(() => {
    if (Object.keys(answers).length) localStorage.setItem("oyuns-checkin-draft", JSON.stringify(answers));
  }, [answers]);

  return (
    <div className="dashboard-grid">
      <div className="dashboard-period">
        <div>
          <span className="eyebrow">
            {isSupervisor ? "Байгууллагын тойм" : "Хувийн тойм"}
          </span>
          <h2>
            {isSupervisor
              ? "Нийт гүйцэтгэлийн үзүүлэлт"
              : "Таны гүйцэтгэлийн үзүүлэлт"}
          </h2>
        </div>
        <TimePeriodFilter
          preset={periodPreset}
          period={period}
          onChange={(nextPreset, nextPeriod) => {
            setPeriodPreset(nextPreset);
            setPeriod(nextPeriod);
          }}
        />
      </div>
      <section className="clock-panel panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ЦАГИЙН БҮРТГЭЛ</span>
            <h2>Өнөөдрийн ажлын цаг</h2>
          </div>
          <span className={`live-indicator ${active ? "online" : ""}`}>
            {active ? "АЖИЛЛАЖ БАЙНА" : "АМАРЧ БАЙНА"}
          </span>
        </div>
        {clockReady ? (
          <div className="clock-summary">
            <div className="clock-time" aria-live="polite">
              {formatDuration(todayWorkSeconds)}
            </div>
            <p>
              {working
                ? `${active?.mode === "remote" ? "Remote" : "Оффис"} горимоор ажиллаж байна.`
                : onBreak
                  ? "Завсарлагын хугацаа ажилласан цагт орохгүй."
                  : "Telegram болон вэбийн цагийн төлөв үргэлж ижил байна."}
            </p>
            <div
              className="clock-details"
              aria-label="Өнөөдрийн цагийн дэлгэрэнгүй"
            >
              {todayEntries.map((entry) => {
                const seconds = Math.max(
                  0,
                  ((entry.ended_at
                    ? new Date(entry.ended_at).getTime()
                    : clockNow) -
                    new Date(entry.started_at).getTime()) /
                    1000,
                );
                return (
                  <div key={entry.id}>
                    {entry.entry_type === "break"
                      ? "Завсарлага"
                      : entry.mode === "remote"
                        ? "Remote"
                        : "Оффис"}
                    :{" "}
                    {formatLocalTime(
                      entry.started_at,
                      clock.data?.timezone ?? "Asia/Ulaanbaatar",
                    )}
                    –
                    {entry.ended_at
                      ? formatLocalTime(
                          entry.ended_at,
                          clock.data?.timezone ?? "Asia/Ulaanbaatar",
                        )
                      : "одоо"}{" "}
                    ({formatDuration(seconds)})
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="clock-summary clock-summary-skeleton" aria-label="Цагийн төлөв ачаалж байна">
            <span className="skeleton clock-time-skeleton" />
            <span className="skeleton clock-copy-skeleton" />
          </div>
        )}
        {recoveredClock && <div className="clock-recovery" role="alert"><strong>Өмнөх сесс сэргээгдлээ.</strong><span>Энэ цагийн бүртгэл удаан нээлттэй эсвэл өөр өдрөөс үргэлжилж байна. Одоогийн төлөвөө шалгаад үргэлжлүүлэх эсвэл дуусгана уу.</span></div>}
        <div className="clock-actions">
          {!active && (
            <>
              <button
                className="clock-button office"
                onClick={() =>
                  action.mutate({ action: "start", mode: "in_person" })
                }
              >
                <House />
                Оффис эхлэх
              </button>
              <button
                className="clock-button remote"
                onClick={() =>
                  action.mutate({ action: "start", mode: "remote" })
                }
              >
                <Laptop2 />
                Remote эхлэх
              </button>
            </>
          )}
          {working && (
            <>
              <button
                className="clock-button break"
                onClick={() => action.mutate({ action: "break" })}
              >
                <Coffee />
                Завсарлага
              </button>
              <button
                className="clock-button stop"
                onClick={() => action.mutate({ action: "stop" })}
              >
                <Pause />
                Өдөр дуусгах
              </button>
            </>
          )}
          {onBreak && (
            <>
              <button
                className="clock-button office"
                onClick={() => action.mutate({ action: "resume" })}
              >
                <Play />
                Үргэлжлүүлэх
              </button>
              <button
                className="clock-button stop"
                onClick={() => action.mutate({ action: "stop" })}
              >
                <Pause />
                Өдөр дуусгах
              </button>
            </>
          )}
        </div>
        {companionSrc && (
          <div
            className={`today-companion ${working ? "working" : "sleeping"}`}
            aria-hidden="true"
          >
            <img src={companionSrc} alt="" />
          </div>
        )}
      </section>
      <section className="daily-focus panel">
        <span className="eyebrow">Өнөөдрийн төвлөрөл</span>
        <h2>Хамгийн чухал ажлаа тодорхой болго.</h2>
        {todayCheckin.data?.template?.questions
          ?.slice(0, 2)
          .map((question: any, index: number) => (
            <div className="focus-question" key={question.id}>
              <span>{index + 1}</span>
              <div>
                <strong>{question.prompt?.mn || question.prompt?.en}</strong>
                <p>{question.is_required ? "Заавал хариулна" : "Сонголттой"}</p>
              </div>
            </div>
          ))}
        {!todayCheckin.data?.template && (
          <p>Check-in асуулт тохируулаагүй байна.</p>
        )}
        <button
          className="secondary-action"
          onClick={openCheckin}
          disabled={
            !todayCheckin.data?.template ||
            todayCheckin.data?.checkin?.status === "submitted"
          }
        >
          {todayCheckin.data?.checkin?.status === "submitted"
            ? "Өнөөдрийн check-in бөглөгдсөн"
            : "Өдрийн check-in бөглөх"}
        </button>
        {checkinOpen && (
          <form className="checkin-form" onSubmit={saveCheckin}>
            {todayCheckin.data.template.questions.map((question: any) => (
              <label key={question.id}>
                <strong>{question.prompt?.mn || question.prompt?.en}</strong>
                {question.choices?.length ? (
                  <select
                    required={question.is_required}
                    value={answers[question.id] || ""}
                    onChange={(event) =>
                      setAnswers({
                        ...answers,
                        [question.id]: event.target.value,
                      })
                    }
                  >
                    <option value="">Сонгох</option>
                    {question.choices.map((choice: any) => (
                      <option key={String(choice)}>{String(choice)}</option>
                    ))}
                  </select>
                ) : ["integer", "decimal", "number"].includes(question.answer_type) ? (
                  <input
                    type="number"
                    step={question.answer_type === "integer" ? "1" : "any"}
                    required={question.is_required}
                    value={answers[question.id] || ""}
                    onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}
                  />
                ) : question.answer_type === "boolean" ? (
                  <select required={question.is_required} value={answers[question.id] || ""} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}>
                    <option value="">Сонгох</option><option value="true">Тийм</option><option value="false">Үгүй</option>
                  </select>
                ) : (
                  <textarea
                    required={question.is_required}
                    value={answers[question.id] || ""}
                    onChange={(event) =>
                      setAnswers({
                        ...answers,
                        [question.id]: event.target.value,
                      })
                    }
                  />
                )}
              </label>
            ))}
            <div>
              <button
                type="button"
                className="secondary-action compact"
                onClick={() => setCheckinOpen(false)}
              >
                Цуцлах
              </button>
              <button
                className="primary-action compact"
                disabled={submitCheckin.isPending}
              >
                Хадгалах
              </button>
            </div>
          </form>
        )}
      </section>
      <section className="metrics-grid" aria-label="Гүйцэтгэлийн үзүүлэлт">
        {cards.map(({ label, value, icon: Icon, tone }, index) => (
          <motion.article
            className={`metric-card ${tone}`}
            key={label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: index * 0.04,
              type: "spring",
              bounce: 0,
              duration: 0.35,
            }}
          >
            <Icon />
            <span>{label}</span>
            <strong>{value}</strong>
          </motion.article>
        ))}
      </section>
      <section className="panel productivity-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Өнөөдрийн ажил</span>
            <h2>Хийх даалгаврууд</h2>
          </div>
          <div
            className="today-task-tabs"
            role="tablist"
            aria-label="Даалгаврын жагсаалт"
          >
            <button
              className={taskTab === "today" ? "active" : ""}
              onClick={() => setTaskTab("today")}
              role="tab"
              aria-selected={taskTab === "today"}
            >
              Надад өгсөн
            </button>
            <button
              className={taskTab === "delegated" ? "active" : ""}
              onClick={() => setTaskTab("delegated")}
              role="tab"
              aria-selected={taskTab === "delegated"}
            >
              Миний өгсөн даалгаврууд
            </button>
          </div>
        </div>
        <div className="today-task-list">
          {taskTab === "today" ? (
            activeTasks.length ? (
              activeTasks.map((task) => (
                <article className="today-task-row" key={task.id}>
                  <div>
                    <strong>{task.title}</strong>
                    <span>{task.primary_owner_name || "Хариуцагчгүй"}</span>
                  </div>
                  <time>
                    {task.deadline_at
                      ? new Date(task.deadline_at).toLocaleTimeString("mn-MN", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "Хугацаагүй"}
                  </time>
                </article>
              ))
            ) : (
              <p>Өнөөдөр төлөвлөсөн даалгавар байхгүй байна.</p>
            )
          ) : delegated.length ? (
            delegated.map((task) => (
              <article
                className="today-task-row delegated-task-row"
                key={task.id}
              >
                <div>
                  <strong>{task.title}</strong>
                  <span>
                    {task.assignee_names.length
                      ? task.assignee_names.join(", ")
                      : "Хариуцагчгүй"}{" "}
                    ·{" "}
                    {task.workflow_status === "done"
                      ? "Дууссан"
                      : "Явагдаж байна"}
                  </span>
                </div>
                <div className="today-task-controls">
                  <button
                    onClick={() => completeDelegatedTask(task)}
                    disabled={
                      task.workflow_status === "done" || updateTask.isPending
                    }
                    aria-label={`${task.title} дууссан гэж тэмдэглэх`}
                    title="Дууссан"
                  >
                    <Check size={16} />
                  </button>
                  <button
                    onClick={() => deleteDelegatedTask(task)}
                    disabled={deleteTask.isPending}
                    aria-label={`${task.title} устгах`}
                    title="Устгах"
                  >
                    <Trash2 size={15} />
                  </button>
                  <button
                    onClick={() => setSelectedDelegatedTask(task)}
                    aria-label={`${task.title} дэлгэрэнгүй`}
                    title="Дэлгэрэнгүй"
                  >
                    <MoreHorizontal size={17} />
                  </button>
                </div>
              </article>
            ))
          ) : (
            <p>Таны өгсөн идэвхтэй даалгавар алга.</p>
          )}
        </div>
        <aside className="today-mini-calendar">
          <strong>
            {new Date().toLocaleDateString("mn-MN", {
              month: "long",
              year: "numeric",
            })}
          </strong>
          <div className="mini-weekdays">
            {["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"].map((day) => (
              <b key={day}>{day}</b>
            ))}
          </div>
          <div className="mini-month-grid">
            {monthDays.map((day) => {
              const local = new Date(
                day.getTime() - day.getTimezoneOffset() * 60_000,
              )
                .toISOString()
                .slice(0, 10);
              const todayKey = new Date(
                Date.now() - new Date().getTimezoneOffset() * 60_000,
              )
                .toISOString()
                .slice(0, 10);
              const count =
                miniCalendarMarkerDates.has(local) ? 1 : 0;
              return (
                <span
                  key={local}
                  className={`${local === todayKey ? "today" : ""} ${day.getMonth() !== new Date().getMonth() ? "outside" : ""}`}
                >
                  <i>{day.getDate()}</i>
                  {count > 0 && <em />}
                </span>
              );
            })}
            <div className="mini-range-layer" aria-label="Олон өдрийн даалгаврууд">
              {miniCalendarRanges.map((range) => (
                <span
                  className={`mini-range-bar${range.isStart ? " range-start" : ""}${range.isEnd ? " range-end" : ""}`}
                  key={range.id}
                  title={range.title}
                  aria-label={range.title}
                  style={{
                    "--mini-lane": range.lane,
                    "--mini-lane-count": range.laneCount,
                    gridColumn: `${range.start + 1} / ${range.end + 2}`,
                    gridRow: range.week + 1,
                  } as CSSProperties}
                />
              ))}
            </div>
          </div>
        </aside>
      </section>
      {selectedDelegatedTask && (
        <DelegatedTaskSheet
          task={selectedDelegatedTask}
          workers={workers.data}
          onClose={() => setSelectedDelegatedTask(null)}
        />
      )}
    </div>
  );
}
