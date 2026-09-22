import { lazy, Suspense, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { Download } from "lucide-react";
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
import { useWorkspaceMode } from "../components/WorkspaceModeProvider";
import { QueryRegion, Skeleton, combineQueryRegionStates, toQueryRegionState } from "../components/Loading";
import { DropdownSelect } from "../components/DropdownSelect";
import { WorktimeExportModal } from "../components/WorktimeExportModal";

const LazyWorkHourHierarchyChart = lazy(() => import('../components/WorkHourHierarchyChart').then((module) => ({ default: module.WorkHourHierarchyChart })))

function DeferredWorkHourChart({ period, employeeId }: { period: { date_from: string; date_to: string }; employeeId?: number }) {
  const [visible, setVisible] = useState(false)
  const region = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (visible || !region.current || typeof IntersectionObserver === 'undefined') { if (typeof IntersectionObserver === 'undefined') setVisible(true); return }
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect() } }, { rootMargin: '240px' })
    observer.observe(region.current)
    return () => observer.disconnect()
  }, [visible])
  return <div ref={region} className="deferred-chart-region">{visible ? <Suspense fallback={<section className="panel work-hour-card"><Skeleton variant="chart" /></section>}><LazyWorkHourHierarchyChart period={period} employeeId={employeeId} /></Suspense> : <section className="panel work-hour-card" aria-label="Ажлын цагийн график"><Skeleton variant="chart" /></section>}</div>
}

function localDate(value: Date) {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

export function StatsWorkspacePage() {
  const end = useMemo(() => new Date(), []);
  const start = useMemo(() => {
    const value = new Date(end);
    value.setDate(value.getDate() - 29);
    return value;
  }, [end]);
  const [period, setPeriod] = useState({
    date_from: localDate(start),
    date_to: localDate(end),
  });
  const [preset, setPreset] = useState<
    "custom" | "today" | "week" | "month" | "quarter"
  >("month");
  const [metric, setMetric] = useState<AnalyticsMetric>("utilization");
  const actor = useAuthStore((state) => state.actor);
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES);
  const canReview = roles.some((role) =>
    ["admin", "manager", "team_lead", "hr"].includes(role),
  );
  const canExportWorktime = roles.some((role) =>
    ["admin", "manager", "team_lead", "hr"].includes(role),
  );
  const isAdmin = roles.includes("admin");
  const { isManagerMode, isEligible } = useWorkspaceMode();
  const [employeeId, setEmployeeId] = useState<number | undefined>(() =>
    isManagerMode || isAdmin ? undefined : actor?.employee_id ?? undefined,
  );
  useEffect(() => {
    if (isEligible) {
      setEmployeeId(isManagerMode ? undefined : actor?.employee_id ?? undefined);
    } else if (!isAdmin && actor?.employee_id != null) {
      setEmployeeId((current) => current ?? actor.employee_id ?? undefined);
    }
  }, [actor?.employee_id, isAdmin, isEligible, isManagerMode]);
  const [exportOpen, setExportOpen] = useState(false);
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
          {canReview && (!isEligible || isManagerMode) && (
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
          {canExportWorktime && (
            <button
              type="button"
              className="secondary-action stats-worktime-export-trigger"
              aria-label="Export Worktime"
              onClick={() => setExportOpen(true)}
            >
              <Download aria-hidden="true" size={16} strokeWidth={2.25} />
              <span className="stats-worktime-export-label">Export</span>
            </button>
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
        state={combineQueryRegionStates([toQueryRegionState(summary), toQueryRegionState(daily)])}
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
          <DeferredWorkHourChart period={period} employeeId={employeeId} />
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
      {exportOpen && <WorktimeExportModal onClose={() => setExportOpen(false)} />}
    </div>
  );
}
