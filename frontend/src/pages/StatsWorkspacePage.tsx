import { useMemo, useState, useTransition } from "react";
import {
  AnalyticsMetric,
  useDailyAnalytics,
  useEnterpriseSummary,
  useWorkerDirectory,
} from "../api/enterprise";
import { KpiDrilldownCard } from "../components/KpiDrilldownCard";
import { TimePeriodFilter } from "../components/TimePeriodFilter";
import { EMPTY_ROLES, useAuthStore } from "../store/auth";
import { HeatmapCalendar } from "../components/HeatmapCalendar";
import { QueryRegion, Skeleton } from "../components/Loading";
import { DropdownSelect } from "../components/DropdownSelect";
import { WorkHourHierarchyChart } from "../components/WorkHourHierarchyChart";

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
      <div className="workspace-toolbar analytics-toolbar">
        <div className="toolbar-cluster">
          {canReview && (
            <DropdownSelect
              ariaLabel="Ажилтан сонгох"
              value={employeeId ? String(employeeId) : ""}
              onChange={(value) =>
                startTransition(() =>
                  setEmployeeId(
                    value ? Number(value) : undefined,
                  ),
                )
              }
              options={[
                { value: "", label: "Байгууллагын нийлбэр" },
                ...(workers.data?.map((worker) => ({ value: String(worker.id), label: worker.name })) ?? []),
              ]}
            />
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
              <span>Өдөрт дуусгасан даалгаврын дундаж</span>
              <strong>
                {Math.round((completed / Math.max(workingDays, 1)) * 10) / 10}
              </strong>
            </article>
          </section>
          <WorkHourHierarchyChart period={period} employeeId={employeeId} />
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
          <KpiDrilldownCard
            metric={metric}
            onMetricChange={setMetric}
            period={period}
            employeeId={employeeId}
            canSeeFinancials={canSeeFinancials}
          />
        </>
      </QueryRegion>
    </div>
  );
}
