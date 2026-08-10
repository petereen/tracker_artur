import { useMemo, useState, useTransition } from "react";
import {
  AnalyticsMetric,
  useAnalyticsDrilldown,
  useDailyAnalytics,
  useEnterpriseSummary,
  useWorkerDirectory,
} from "../api/enterprise";
import { TimePeriodFilter } from "../components/TimePeriodFilter";
import { EMPTY_ROLES, useAuthStore } from "../store/auth";
import { HeatmapCalendar } from "../components/HeatmapCalendar";
import { QueryRegion, Skeleton } from "../components/Loading";

function localDate(value: Date) {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

export function StatsWorkspacePage() {
  const end = useMemo(() => new Date(), []);
  const start = useMemo(() => {
    const value = new Date(end);
    value.setDate(value.getDate() - 364);
    return value;
  }, [end]);
  const [period, setPeriod] = useState({
    date_from: localDate(start),
    date_to: localDate(end),
  });
  const [preset, setPreset] = useState<
    "custom" | "today" | "week" | "month" | "quarter"
  >("custom");
  const [employeeId, setEmployeeId] = useState<number>();
  const [metric, setMetric] = useState<AnalyticsMetric>("utilization");
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES);
  const canReview = roles.some((role) =>
    ["admin", "manager", "team_lead"].includes(role),
  );
  const canSeeFinancials = roles.some((role) => ["admin", "manager"].includes(role));
  const workers = useWorkerDirectory();
  const summary = useEnterpriseSummary(period, employeeId);
  const daily = useDailyAnalytics(period, employeeId);
  const drilldown = useAnalyticsDrilldown(metric, period, employeeId);
  const days = daily.data?.days ?? [];
  const workingDays = days.filter((day: any) => {
    const weekday = new Date(`${day.date}T12:00:00`).getDay();
    return weekday > 0 && weekday < 6;
  }).length;
  const totalMinutes = days.reduce(
    (sum: number, day: any) => sum + day.worked_minutes,
    0,
  );
  const completed = days.reduce(
    (sum: number, day: any) => sum + day.completed_tasks,
    0,
  );
  const [focusedDay, setFocusedDay] = useState<any>();
  const [, startTransition] = useTransition();
  return (
    <div className="stats-workspace">
      <div className="view-toolbar">
        <div>
          <h2>Гүйцэтгэлийн үзүүлэлт</h2>
          <p>Ажлын цаг болон даалгаврын түүхэн зураглал.</p>
        </div>
        <div className="toolbar-cluster">
          {canReview && (
            <select
              value={employeeId || ""}
              onChange={(event) =>
                startTransition(() =>
                  setEmployeeId(
                    event.target.value ? Number(event.target.value) : undefined,
                  ),
                )
              }
            >
              <option value="">Байгууллагын нийлбэр</option>
              {workers.data?.map((worker) => (
                <option key={worker.id} value={worker.id}>
                  {worker.name}
                </option>
              ))}
            </select>
          )}
          <TimePeriodFilter
            preset={preset}
            period={period}
            onChange={(next, value) =>
              startTransition(() => {
                setPreset(next);
                setPeriod(value);
              })
            }
          />
          <select aria-label="KPI дэлгэрэнгүй" value={metric} onChange={(event) => setMetric(event.target.value as AnalyticsMetric)}>
            <option value="utilization">Ашиглалт</option><option value="billable_ratio">Billable харьцаа</option><option value="task_completion">Даалгаврын гүйцэтгэл</option><option value="deadline_health">Хугацааны эрүүл мэнд</option><option value="report_compliance">Тайлангийн сахилга</option>{canSeeFinancials && <option value="budget_burn">Төсвийн зарцуулалт</option>}
          </select>
        </div>
      </div>
      <QueryRegion
        pending={
          summary.isLoading ||
          summary.isFetching ||
          daily.isLoading ||
          daily.isFetching
        }
        skeleton={
          <>
            <div className="metrics-grid">
              <Skeleton variant="card" count={4} />
            </div>
            <section className="panel heatmap-panel">
              <Skeleton variant="chart" />
            </section>
          </>
        }
      >
        <>
          <section className="metrics-grid">
            <article className="metric-card blue">
              <span>Нийт ажилласан</span>
              <strong>{Math.round((totalMinutes / 60) * 10) / 10}ц</strong>
            </article>
            <article className="metric-card green">
              <span>Өдрийн дундаж</span>
              <strong>
                {Math.round(
                  (totalMinutes / Math.max(workingDays, 1) / 60) * 10,
                ) / 10}
                ц
              </strong>
            </article>
            <article className="metric-card purple">
              <span>Даалгаврын гүйцэтгэл</span>
              <strong>{summary.data?.completion_rate ?? 0}%</strong>
            </article>
            <article className="metric-card amber">
              <span>Өдөрт дуусгасан дундаж</span>
              <strong>
                {Math.round((completed / Math.max(workingDays, 1)) * 10) / 10}
              </strong>
            </article>
          </section>
          <section className="panel heatmap-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Worktime heatmap</span>
                <h2>Өдрүүдээр ажилласан цаг</h2>
              </div>
              {focusedDay && (
                <small className="heatmap-detail">
                  {new Date(`${focusedDay.date}T12:00:00`).toLocaleDateString(
                    "mn-MN",
                    { month: "long", day: "numeric", weekday: "long" },
                  )}
                  : {Math.round((focusedDay.worked_minutes / 60) * 10) / 10}ц ·{" "}
                  {focusedDay.completed_tasks} даалгавар
                </small>
              )}
            </div>
            <HeatmapCalendar
              data={days.map((day: any) => ({
                date: day.date,
                value: day.worked_minutes,
                meta: day,
              }))}
              endDate={new Date(`${period.date_to}T12:00:00`)}
              rangeDays={Math.max(
                1,
                Math.round(
                  (new Date(`${period.date_to}T12:00:00`).getTime() -
                    new Date(`${period.date_from}T12:00:00`).getTime()) /
                    86_400_000,
                ) + 1,
              )}
              onCellClick={(cell) => setFocusedDay(cell.meta)}
              renderTooltip={(cell) =>
                `${cell.label}: ${Math.round((cell.value / 60) * 10) / 10} цаг, ${(cell.meta as any)?.completed_tasks || 0} даалгавар`
              }
            />
          </section>
          <section className="panel analytics-drilldown" aria-live="polite"><div className="panel-heading"><div><span className="eyebrow">KPI drill-down</span><h2>{metric.replaceAll("_", " ")}</h2></div><strong>{drilldown.data?.totals.average_value ?? "—"}%</strong></div>{drilldown.isLoading || drilldown.isFetching ? <Skeleton variant="table-row" count={4} /> : drilldown.isError ? <p role="alert">Энэ үзүүлэлтийн дэлгэрэнгүйг харах эрхгүй эсвэл өгөгдөл ачаалсангүй.</p> : drilldown.data?.items.length ? <div className="analytics-table"><header><span>Нэр</span><span>Үзүүлэлт</span><span>Тооцооллын эх өгөгдөл</span></header>{drilldown.data.items.map((item, index) => <article key={item.employee_id ?? item.project_id ?? index}><strong>{item.employee_name ?? item.project_name}</strong><span>{item.value == null ? "—" : `${item.value}%`}</span><small>{metric === "budget_burn" ? `${item.burned_amount} / ${item.budget_amount ?? "—"} ${item.currency}${item.unpriced_minutes ? ` · ${item.unpriced_minutes} минут үнэлгээгүй` : ""}` : `${item.worked_minutes ?? 0} минут · ${item.completed_tasks ?? 0}/${item.task_total ?? 0} даалгавар`}</small></article>)}</div> : <p>Сонгосон хугацаанд өгөгдөл алга.</p>}</section>
        </>
      </QueryRegion>
    </div>
  );
}
