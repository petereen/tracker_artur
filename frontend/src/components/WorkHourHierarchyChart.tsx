import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Building2,
  Clock3,
  Laptop,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Sector,
} from "recharts";
import { useTranslation } from "react-i18next";
import {
  DateRange,
  WorkHoursAnalytics,
  useWorkHoursAnalytics,
} from "../api/enterprise";

type CategoryKey = "remote" | "office";

type Category = {
  key: CategoryKey;
  minutes: number;
  label: string;
  color: string;
  Icon: LucideIcon;
};

type Trend =
  | { kind: "up" | "down" | "flat"; delta: number }
  | { kind: "new" }
  | null;

type TooltipState = {
  key: CategoryKey;
  left: number;
  top: number;
};

const CATEGORY_COLORS: Record<CategoryKey, string> = {
  remote: "#0f9f9a",
  office: "#f59e0b",
};

const CATEGORY_ICONS: Record<CategoryKey, LucideIcon> = {
  remote: Laptop,
  office: Building2,
};

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

function formatClock(minutes: number) {
  const rounded = Math.max(0, Math.round(minutes));
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return `${hours.toString().padStart(2, "0")}:${rest.toString().padStart(2, "0")}`;
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function formatDecimalHours(minutes: number, unit: string) {
  return `${(Math.max(0, minutes) / 60).toFixed(1)} ${unit}`;
}

function dateRangeLabel(period: DateRange, language: string) {
  const from = new Date(`${period.date_from}T12:00:00`);
  const to = new Date(`${period.date_to}T12:00:00`);
  const formatter = new Intl.DateTimeFormat(language, {
    month: "short",
    day: "numeric",
  });
  return `${formatter.format(from)} – ${formatter.format(to)}`;
}

function categoryMinutes(data: WorkHoursAnalytics | undefined, key: CategoryKey) {
  if (!data) return 0;
  return key === "remote" ? data.remote_minutes : data.office_minutes;
}

function trendFor(
  key: CategoryKey,
  current: WorkHoursAnalytics | undefined,
  previous: WorkHoursAnalytics | undefined,
  previousPending: boolean,
): Trend {
  if (previousPending || !current || !previous) return null;
  if (!previous.total_minutes) {
    return categoryMinutes(current, key) > 0 ? { kind: "new" } : null;
  }
  const currentShare = current.total_minutes
    ? (categoryMinutes(current, key) / current.total_minutes) * 100
    : 0;
  const previousShare =
    (categoryMinutes(previous, key) / previous.total_minutes) * 100;
  const delta = currentShare - previousShare;
  return {
    kind: delta > 0.05 ? "up" : delta < -0.05 ? "down" : "flat",
    delta,
  };
}

function trendText(trend: Trend, labels: { newLabel: string; points: string }) {
  if (!trend) return "—";
  if (trend.kind === "new") return labels.newLabel;
  const arrow = trend.kind === "up" ? "↑" : trend.kind === "down" ? "↓" : "→";
  return `${arrow} ${Math.abs(trend.delta).toFixed(1)}${labels.points}`;
}

function renderActiveShape(props: any) {
  const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill, ...rest } = props;
  return (
    <Sector
      {...rest}
      cx={cx}
      cy={cy}
      innerRadius={innerRadius}
      outerRadius={outerRadius + 8}
      startAngle={startAngle}
      endAngle={endAngle}
      fill={fill}
    />
  );
}

function trendClass(trend: Trend) {
  if (!trend || trend.kind === "flat") return "is-flat";
  return trend.kind === "up" ? "is-up" : trend.kind === "down" ? "is-down" : "is-new";
}

export function WorkHourHierarchyChart({
  period,
  employeeId,
}: {
  period: DateRange;
  employeeId?: number;
}) {
  const { t, i18n } = useTranslation();
  const reducedMotion = useReducedMotion();
  const analytics = useWorkHoursAnalytics(period, employeeId);
  const cardRef = useRef<HTMLElement>(null);
  const [activeKey, setActiveKey] = useState<CategoryKey | null>(null);
  const [hiddenKeys, setHiddenKeys] = useState<Set<CategoryKey>>(new Set());
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  useEffect(() => {
    setHiddenKeys(new Set());
    setActiveKey(null);
    setTooltip(null);
  }, [period.date_from, period.date_to, employeeId]);

  const categories = useMemo<Category[]>(
    () =>
      (["remote", "office"] as CategoryKey[]).map((key) => ({
        key,
        minutes: categoryMinutes(analytics.data, key),
        label: t(`analytics.workHours.categories.${key}`),
        color: CATEGORY_COLORS[key],
        Icon: CATEGORY_ICONS[key],
      })),
    [analytics.data, t],
  );
  const visibleCategories = categories.filter((category) => !hiddenKeys.has(category.key));
  const visibleTotal = visibleCategories.reduce((sum, category) => sum + category.minutes, 0);
  const hasWork = (analytics.data?.total_minutes ?? 0) > 0;
  const hovered = activeKey
    ? visibleCategories.find((category) => category.key === activeKey) ?? null
    : null;
  const activeIndex = hovered
    ? visibleCategories.findIndex((category) => category.key === hovered.key)
    : -1;
  const selectedTotal = hovered ? hovered.minutes : visibleTotal;
  const selectedShare = visibleTotal ? (selectedTotal / visibleTotal) * 100 : 0;
  const centerKey = !hasWork
    ? "empty"
    : !visibleCategories.length
      ? "hidden"
      : hovered?.key ?? "total";

  const trends = useMemo(
    () =>
      Object.fromEntries(
        categories.map((category) => [
          category.key,
          trendFor(
            category.key,
            analytics.data,
            analytics.previousData,
            analytics.trendPending,
          ),
        ]),
      ) as Record<CategoryKey, Trend>,
    [
      analytics.data,
      analytics.previousData,
      analytics.trendPending,
      categories,
    ],
  );

  const tooltipPosition = (event?: { clientX?: number; clientY?: number }) => {
    if (event?.clientX == null || event.clientY == null) {
      return { left: 16, top: 16 };
    }
    const width = 238;
    const height = 142;
    const gap = 16;
    const left = Math.min(
      Math.max(12, event.clientX + gap),
      Math.max(12, window.innerWidth - width - 12),
    );
    const top = Math.min(
      Math.max(12, event.clientY - 26),
      Math.max(12, window.innerHeight - height - 12),
    );
    return { left, top };
  };

  const showHover = (category: Category, event?: { clientX?: number; clientY?: number }) => {
    setActiveKey(category.key);
    setTooltip({ key: category.key, ...tooltipPosition(event) });
  };

  const clearHover = () => {
    setActiveKey(null);
    setTooltip(null);
  };

  const toggleCategory = (key: CategoryKey) => {
    setHiddenKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const cardHeader = (
    <header className="work-hour-card-header">
      <div>
        <span className="eyebrow">{t("analytics.workHours.eyebrow")}</span>
        <h2>{t("analytics.workHours.title")}</h2>
        <p>{t("analytics.workHours.subtitle")}</p>
      </div>
      <span className="work-hour-period">{dateRangeLabel(period, i18n.language)}</span>
    </header>
  );

  if (analytics.isLoading && !analytics.data) {
    return (
      <section className="panel work-hour-card" ref={cardRef} aria-busy="true">
        {cardHeader}
        <div className="work-hour-layout work-hour-loading">
          <div className="work-hour-chart-placeholder" aria-hidden="true">
            <span className="work-hour-loading-ring" />
            <span className="work-hour-loading-core" />
          </div>
          <div className="work-hour-legend-skeleton" aria-hidden="true">
            <span />
            <span />
          </div>
        </div>
      </section>
    );
  }

  if (analytics.isError) {
    return (
      <section className="panel work-hour-card" ref={cardRef}>
        {cardHeader}
        <div className="work-hour-state" role="alert">
          <TriangleAlert aria-hidden="true" />
          <strong>{t("analytics.workHours.errorTitle")}</strong>
          <p>{t("analytics.workHours.errorDescription")}</p>
          <button type="button" className="secondary-action" onClick={() => analytics.refetch()}>
            <RefreshCw size={15} aria-hidden="true" />
            {t("analytics.workHours.retry")}
          </button>
        </div>
      </section>
    );
  }

  const tooltipCategory = tooltip
    ? categories.find((category) => category.key === tooltip.key) ?? null
    : null;
  const tooltipTrend = tooltipCategory ? trends[tooltipCategory.key] : null;
  const TooltipIcon = tooltipCategory?.Icon;

  return (
    <section className="panel work-hour-card" ref={cardRef} aria-live="polite">
      {cardHeader}
      {!hasWork ? (
        <div className="work-hour-state work-hour-empty">
          <div className="work-hour-empty-ring" aria-hidden="true">
            <Clock3 size={24} />
          </div>
          <strong>{t("analytics.workHours.emptyTitle")}</strong>
          <p>{t("analytics.workHours.emptyDescription")}</p>
        </div>
      ) : (
        <div className="work-hour-layout">
          <div
            className={`work-hour-chart${analytics.isFetching ? " is-fetching" : ""}`}
            role="img"
            aria-label={t("analytics.workHours.chartLabel", {
              total: formatDecimalHours(visibleTotal, t("analytics.workHours.hoursUnit")),
            })}
            onMouseLeave={clearHover}
          >
            {visibleCategories.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    key={visibleCategories.map((category) => `${category.key}:${category.minutes}`).join("|")}
                    data={visibleCategories}
                    dataKey="minutes"
                    nameKey="label"
                    cx="50%"
                    cy="50%"
                    innerRadius="61%"
                    outerRadius="81%"
                    startAngle={90}
                    endAngle={-270}
                    paddingAngle={3}
                    stroke="var(--color-surface)"
                    strokeWidth={3}
                    activeIndex={activeIndex >= 0 ? activeIndex : undefined}
                    activeShape={renderActiveShape}
                    isAnimationActive={!reducedMotion}
                    animationDuration={750}
                    onMouseEnter={(entry: any, index: number, event: any) => showHover(visibleCategories[index], event)}
                    onMouseMove={(entry: any, index: number, event: any) => showHover(visibleCategories[index], event)}
                    onMouseLeave={clearHover}
                  >
                    {visibleCategories.map((category) => (
                      <Cell
                        key={category.key}
                        fill={category.color}
                        fillOpacity={activeKey && activeKey !== category.key ? 0.4 : 1}
                        className="work-hour-slice"
                      />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="work-hour-hidden-ring" aria-hidden="true" />
            )}
            <div className="work-hour-center">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={centerKey}
                  initial={{ opacity: 0, filter: reducedMotion ? "none" : "blur(2px)", y: reducedMotion ? 0 : 3 }}
                  animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
                  exit={{ opacity: 0, filter: reducedMotion ? "none" : "blur(2px)", y: reducedMotion ? 0 : -3 }}
                  transition={{ duration: reducedMotion ? 0.08 : 0.16, ease: EASE_OUT }}
                >
                  {!visibleCategories.length ? (
                    <>
                      <strong>—</strong>
                      <span>{t("analytics.workHours.noCategories")}</span>
                      <button type="button" onClick={() => setHiddenKeys(new Set())}>
                        {t("analytics.workHours.showAll")}
                      </button>
                    </>
                  ) : hovered ? (
                    <>
                      <strong>{formatPercent(selectedShare)}</strong>
                      <span>{formatDecimalHours(selectedTotal, t("analytics.workHours.hoursUnit"))}</span>
                      <small>{hovered.label}</small>
                    </>
                  ) : (
                    <>
                      <strong>{formatDecimalHours(visibleTotal, t("analytics.workHours.hoursUnit"))}</strong>
                      <span>{t("analytics.workHours.totalLogged")}</span>
                    </>
                  )}
                </motion.div>
              </AnimatePresence>
            </div>
            {analytics.isFetching && <span className="work-hour-fetching-ring" aria-label={t("analytics.workHours.loading")} />}
          </div>
          <div className="work-hour-legend" aria-label={t("analytics.workHours.legendLabel")}>
            {categories.map((category) => {
              const hidden = hiddenKeys.has(category.key);
              const share = visibleTotal ? (category.minutes / visibleTotal) * 100 : 0;
              const trend = trends[category.key];
              const Icon = category.Icon;
              return (
                <button
                  type="button"
                  key={category.key}
                  className={`work-hour-legend-item${hidden ? " is-hidden" : ""}${activeKey === category.key ? " is-active" : ""}`}
                  aria-pressed={!hidden}
                  onClick={() => toggleCategory(category.key)}
                  onMouseEnter={(event) => showHover(category, event)}
                  onMouseMove={(event) => showHover(category, event)}
                  onMouseLeave={clearHover}
                  onFocus={() => setActiveKey(category.key)}
                  onBlur={clearHover}
                >
                  <span className="work-hour-legend-icon" style={{ "--work-hour-color": category.color } as React.CSSProperties}>
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <span className="work-hour-legend-copy">
                    <strong>{category.label}</strong>
                    <small>
                      {formatClock(category.minutes)} · {hidden ? "0.0%" : formatPercent(share)}
                    </small>
                  </span>
                  <span className={`work-hour-trend ${trendClass(trend)}`}>
                    {trendText(trend, {
                      newLabel: t("analytics.workHours.newTrend"),
                      points: t("analytics.workHours.pointsUnit"),
                    })}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
      {tooltipCategory && (
        <motion.div
          className="work-hour-tooltip"
          style={{ left: tooltip?.left, top: tooltip?.top }}
          initial={{ opacity: 0, scale: 0.97, filter: "blur(2px)" }}
          animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.16, ease: EASE_OUT }}
          aria-hidden="true"
        >
          <div className="work-hour-tooltip-heading">
            <span className="work-hour-tooltip-pill" style={{ background: tooltipCategory.color }} />
            {TooltipIcon && <TooltipIcon className="work-hour-tooltip-icon" size={15} aria-hidden="true" />}
            <strong>{tooltipCategory.label}</strong>
          </div>
          <div className="work-hour-tooltip-metric">
            <span>{formatClock(tooltipCategory.minutes)}</span>
            <small>{formatDecimalHours(tooltipCategory.minutes, t("analytics.workHours.hoursUnit"))}</small>
          </div>
          <div className="work-hour-tooltip-footer">
            <span>{formatPercent(visibleTotal ? (tooltipCategory.minutes / visibleTotal) * 100 : 0)} {t("analytics.workHours.ofTotal")}</span>
            <span className={`work-hour-trend ${trendClass(tooltipTrend)}`}>
              {trendText(tooltipTrend, {
                newLabel: t("analytics.workHours.newTrend"),
                points: t("analytics.workHours.pointsUnit"),
              })}
            </span>
          </div>
        </motion.div>
      )}
    </section>
  );
}
