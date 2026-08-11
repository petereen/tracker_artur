import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown } from "lucide-react";
import {
  AnalyticsMetric,
  useAnalyticsDrilldown,
} from "../api/enterprise";
import { Skeleton } from "./Loading";

type KpiDrilldownCardProps = {
  metric: AnalyticsMetric;
  onMetricChange: (metric: AnalyticsMetric) => void;
  period: { date_from: string; date_to: string };
  employeeId?: number;
  canSeeFinancials: boolean;
};

const metricLabels: Record<AnalyticsMetric, string> = {
  utilization: "Ашиглалт",
  billable_ratio: "Billable ratio",
  task_completion: "Даалгаврын гүйцэтгэл",
  deadline_health: "Deadline Health",
  report_compliance: "Тайлангийн биелэлт",
  budget_burn: "Төсвийн зарцуулалт",
};

function DrilldownContent({
  metric,
  drilldown,
}: {
  metric: AnalyticsMetric;
  drilldown: ReturnType<typeof useAnalyticsDrilldown>;
}) {
  if (drilldown.isLoading || drilldown.isFetching) {
    return <Skeleton variant="table-row" count={4} />;
  }

  if (drilldown.isError) {
    return (
      <p role="alert">
        Энэ үзүүлэлтийн дэлгэрэнгүйг харах эрхгүй эсвэл өгөгдөл ачаалсангүй.
      </p>
    );
  }

  if (!drilldown.data?.items.length) {
    return <p>Сонгосон хугацаанд өгөгдөл алга.</p>;
  }

  return (
    <div className="analytics-table">
      <header>
        <span>Нэр</span>
        <span>Үзүүлэлт</span>
        <span>Тооцооллын эх өгөгдөл</span>
      </header>
      {drilldown.data.items.map((item, index) => (
        <article key={item.employee_id ?? item.project_id ?? index}>
          <strong>{item.employee_name ?? item.project_name}</strong>
          <span>{item.value == null ? "—" : `${item.value}%`}</span>
          <small>
            {metric === "budget_burn"
              ? `${item.burned_amount} / ${item.budget_amount ?? "—"} ${item.currency}${item.unpriced_minutes ? ` · ${item.unpriced_minutes} минут үнэлгээгүй` : ""}`
              : `${item.worked_minutes ?? 0} минут · ${item.completed_tasks ?? 0}/${item.task_total ?? 0} даалгавар`}
          </small>
        </article>
      ))}
    </div>
  );
}

export function KpiDrilldownCard({
  metric,
  onMetricChange,
  period,
  employeeId,
  canSeeFinancials,
}: KpiDrilldownCardProps) {
  const drilldown = useAnalyticsDrilldown(metric, period, employeeId);
  const averageValue = drilldown.data?.totals.average_value ?? "—";
  const [isMetricMenuOpen, setIsMetricMenuOpen] = useState(false);
  const metricMenuRef = useRef<HTMLDivElement>(null);
  const metricTriggerRef = useRef<HTMLButtonElement>(null);
  const metricOptions = [
    ["utilization", "Ашиглалт"],
    ["billable_ratio", "Billable ratio"],
    ["task_completion", "Даалгаврын гүйцэтгэл"],
    ["deadline_health", "Deadline Health"],
    ["report_compliance", "Тайлангийн биелэлт"],
    ...(canSeeFinancials ? [["budget_burn", "Төсвийн зарцуулалт"]] : []),
  ] as Array<[AnalyticsMetric, string]>;

  useEffect(() => {
    if (!isMetricMenuOpen) return;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!metricMenuRef.current?.contains(event.target as Node)) {
        setIsMetricMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMetricMenuOpen(false);
        metricTriggerRef.current?.focus();
      }
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isMetricMenuOpen]);

  const selectMetric = (nextMetric: AnalyticsMetric) => {
    onMetricChange(nextMetric);
    setIsMetricMenuOpen(false);
    metricTriggerRef.current?.focus();
  };

  return (
    <section className="panel analytics-drilldown" aria-live="polite">
      <div className="analytics-drilldown-heading">
        <div>
          <span className="eyebrow">KPI drill-down</span>
          <h2>{metricLabels[metric]}</h2>
        </div>
        <div className="analytics-drilldown-controls">
          <div className="analytics-metric-picker" ref={metricMenuRef}>
            <span className="analytics-metric-picker-label">Drilldown Type</span>
            <button
              ref={metricTriggerRef}
              type="button"
              className="analytics-metric-trigger"
              aria-label="KPI дэлгэрэнгүй"
              aria-haspopup="listbox"
              aria-expanded={isMetricMenuOpen}
              onClick={() => setIsMetricMenuOpen((open) => !open)}
            >
              <span>{metricLabels[metric]}</span>
              <ChevronDown
                aria-hidden="true"
                size={16}
                strokeWidth={2.25}
                className={`analytics-metric-chevron${isMetricMenuOpen ? " is-open" : ""}`}
              />
            </button>
            <AnimatePresence>
              {isMetricMenuOpen && (
                <motion.div
                  className="analytics-metric-menu bg-white shadow-xl rounded-xl p-1.5 mt-2"
                  role="listbox"
                  aria-label="KPI дэлгэрэнгүй сонгох"
                  initial={{ opacity: 0, scale: 0.96, y: -4 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.96, y: -4 }}
                  transition={{ duration: 0.16, ease: [0.23, 1, 0.32, 1] }}
                >
                  {metricOptions.map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={`analytics-metric-option${metric === value ? " is-selected" : ""}`}
                      role="option"
                      aria-selected={metric === value}
                      onClick={() => selectMetric(value)}
                    >
                      <span>{label}</span>
                      {metric === value && <Check aria-hidden="true" size={15} strokeWidth={2.5} />}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <strong className="analytics-drilldown-average">{averageValue}%</strong>
        </div>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={`${metric}-${period.date_from}-${period.date_to}-${employeeId ?? "all"}`}
          className="analytics-drilldown-content"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
        >
          <DrilldownContent metric={metric} drilldown={drilldown} />
        </motion.div>
      </AnimatePresence>
    </section>
  );
}
