import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnterpriseDashboardPage } from "./EnterpriseDashboardPage";

const mocks = vi.hoisted(() => ({
  clock: { data: undefined as any, refetch: vi.fn() },
  clockListeners: new Set<() => void>(),
  action: { mutate: vi.fn(), isPending: false },
  navigate: vi.fn(),
  geolocation: { getCurrentPosition: vi.fn() },
  agenda: { data: { tasks: [] as any[], entries: [] as any[] } },
  privateCalendar: { tasks: [] as any[], entries: [] as any[], time_blocks: [] as any[] },
  companyCalendar: { tasks: [] as any[], entries: [] as any[], time_blocks: [] as any[] },
  worldClock: { data: { clocks: ["Asia/Ulaanbaatar"], display_mode: "digital", hour_format: "24" }, isLoading: false, isError: false, refetch: vi.fn() },
  worldClockUpdate: { mutateAsync: vi.fn(), isPending: false },
  layout: { data: { widgets: null, updated_at: null } as any, isLoading: false },
  saveLayout: vi.fn(),
  news: { data: [] as any[], isLoading: false, isError: false, refetch: vi.fn() },
  summaryCalls: [] as any[],
}));

vi.mock("../api/enterprise", async () => {
  const React = await import("react");
  return {
  // Subscribes like react-query does, so updates reach the (memoized) widget.
  useClock: () => {
    const [, rerender] = React.useReducer((value: number) => value + 1, 0);
    React.useEffect(() => { mocks.clockListeners.add(rerender); return () => { mocks.clockListeners.delete(rerender); }; }, []);
    return mocks.clock;
  },
  useClockAction: () => mocks.action,
  useWorktimeMethods: () => ({ data: { qr_enabled: true, location_enabled: true } }),
  useCalendarEvents: (scope: string) => ({ data: scope === "private" ? mocks.privateCalendar : mocks.companyCalendar }),
  useEnterpriseSummary: (period: any) => { mocks.summaryCalls.push(period); return { data: { active_projects: 1, completed_tasks: 2, completion_rate: 80, worked_minutes: 60 } }; },
  useDailyAnalytics: () => ({ data: { days: [{ date: "2026-08-10", worked_minutes: 60, completed_tasks: 1 }, { date: "2026-08-11", worked_minutes: 120, completed_tasks: 2 }] } }),
  useERPMetadata: () => ({ data: undefined }),
  useTodayCheckin: () => ({ data: {} }),
  useStartCheckin: () => ({ mutateAsync: vi.fn() }),
  useSubmitCheckin: () => ({ mutateAsync: vi.fn() }),
  useTodayAgenda: () => mocks.agenda,
  useEnterpriseTasks: () => ({ data: [] }),
  useWorkerDirectory: () => ({ data: [] }),
  useUpdateEnterpriseTask: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
  useDeleteEnterpriseTask: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
  useWorldClockPreferences: () => mocks.worldClock,
  useUpdateWorldClockPreferences: () => mocks.worldClockUpdate,
  };
});

/** Pushes the edited `mocks.clock.data` to subscribed components. */
function publishClock() {
  act(() => mocks.clockListeners.forEach((listener) => listener()));
}

vi.mock("../api/today", () => ({
  todayLayoutQueryKey: ["v1", "auth", "preferences", "today-layout"],
  useTodayLayoutPreferences: () => mocks.layout,
  useSaveTodayLayoutPreferences: () => ({ mutate: mocks.saveLayout }),
  useAnnouncements: () => mocks.news,
}));

vi.mock("../api/tenancy", () => ({
  useTenantContext: () => ({ data: undefined }),
  isFeatureEnabled: () => true,
}));
vi.mock("../api/crm", () => ({ useCRMCapabilities: () => ({ data: undefined }) }));
vi.mock("../api/budget", () => ({ useBudgetCapabilities: () => ({ data: undefined }) }));

vi.mock("../store/auth", () => ({
  EMPTY_ROLES: [],
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ actor: { id: 7, employee_id: 1, roles: [] } }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => mocks.navigate,
}));

function setVisibilityState(value: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value,
  });
}

function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderDashboard() {
  return render(<EnterpriseDashboardPage />, { wrapper: Providers });
}

describe("Today work-hour timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-11T10:00:00.000Z"));
    setVisibilityState("visible");
    mocks.clock.refetch.mockReset();
    mocks.action.mutate.mockReset();
    mocks.navigate.mockReset();
    mocks.geolocation.getCurrentPosition.mockReset();
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: mocks.geolocation });
    mocks.agenda.data = { tasks: [], entries: [] };
    mocks.privateCalendar = { tasks: [], entries: [], time_blocks: [] };
    mocks.companyCalendar = { tasks: [], entries: [], time_blocks: [] };
    mocks.layout.data = { widgets: null, updated_at: null };
    mocks.saveLayout.mockReset();
    mocks.news.data = [];
    mocks.summaryCalls = [];
    localStorage.clear();
    // jsdom has no modal <dialog> support; Astryx Dialog calls these.
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }));
    const startedAt = new Date(Date.now() - 5_000).toISOString();
    mocks.clock.data = {
      active: {
        id: 10,
        employee_id: 1,
        local_work_date: "2026-08-11",
        project_id: null,
        task_id: null,
        entry_type: "work",
        mode: "in_person",
        started_at: startedAt,
        ended_at: null,
      },
      today_entries: [
        {
          id: 10,
          employee_id: 1,
          local_work_date: "2026-08-11",
          project_id: null,
          task_id: null,
          entry_type: "work",
          mode: "in_person",
          started_at: startedAt,
          ended_at: null,
        },
      ],
      timezone: "Asia/Ulaanbaatar",
      server_time: new Date(Date.now()).toISOString(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("holds the timer behind the clock loading gate", () => {
    mocks.clock.data = undefined;
    const { container } = renderDashboard();

    expect(container.querySelector(".clock-time")).not.toBeInTheDocument();
    expect(container.querySelector(".clock-summary-skeleton")).toBeInTheDocument();

    const active = {
        id: 10,
        employee_id: 1,
        local_work_date: "2026-08-11",
        project_id: null,
        task_id: null,
        entry_type: "work",
        mode: "in_person",
        started_at: new Date(Date.now() - 5_000).toISOString(),
        ended_at: null,
      };
    mocks.clock.data = {
      active,
      today_entries: [active],
      timezone: "Asia/Ulaanbaatar",
      server_time: new Date(Date.now()).toISOString(),
    };
    publishClock();

    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:05");
    expect(container.querySelector(".today-companion")).not.toBeInTheDocument();
  });

  it("increments from a stable server sync every second", () => {
    const { container } = renderDashboard();
    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:05");

    act(() => vi.advanceTimersByTime(2_000));

    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:07");
  });

  it("pauses background ticks and resynchronizes on visibilitychange", () => {
    const { container } = renderDashboard();

    act(() => {
      setVisibilityState("hidden");
      document.dispatchEvent(new Event("visibilitychange"));
      vi.advanceTimersByTime(3_000);
    });
    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:05");

    act(() => {
      setVisibilityState("visible");
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mocks.clock.refetch).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:08");
  });

  it("stops ticking when the active entry is cleared", () => {
    const { container } = renderDashboard();
    act(() => vi.advanceTimersByTime(1_000));

    const endedAt = new Date(Date.now()).toISOString();
    mocks.clock.data = {
      ...mocks.clock.data,
      active: null,
      today_entries: [{ ...mocks.clock.data.today_entries[0], ended_at: endedAt }],
      server_time: endedAt,
    };
    publishClock();
    act(() => vi.advanceTimersByTime(3_000));

    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:06");
  });

  it("maps start, pause, resume, and stop controls to clock actions", () => {
    renderDashboard();
    fireEvent.click(document.querySelector("button.clock-button.break") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "break" });
    fireEvent.click(document.querySelector("button.clock-button.stop") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "stop" });

    mocks.clock.data = {
      ...mocks.clock.data,
      active: { ...mocks.clock.data.active, entry_type: "break", mode: null },
    };
    publishClock();
    fireEvent.click(document.querySelector("button.clock-button.office") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "resume" });

    mocks.clock.data = { ...mocks.clock.data, active: null };
    publishClock();
    fireEvent.click(document.querySelector("button.clock-button.office") as HTMLButtonElement);
    expect(mocks.geolocation.getCurrentPosition).toHaveBeenCalledTimes(1);
    const onSuccess = mocks.geolocation.getCurrentPosition.mock.calls[0][0] as (position: { coords: { latitude: number; longitude: number } }) => void;
    onSuccess({ coords: { latitude: 47.9184, longitude: 106.9177 } });
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "start", mode: "in_person", latitude: 47.9184, longitude: 106.9177 });
  });

  it("renders date-range tasks as split bars with rounded visible ends", () => {
    mocks.agenda.data = {
      tasks: [
        { id: 101, title: "Visible range", start_at: "2026-08-03", deadline_at: "2026-08-06" },
        { id: 102, title: "Clipped range", start_at: "2026-07-20", deadline_at: "2026-08-02" },
      ],
      entries: [],
    };

    const { container } = renderDashboard();
    const visibleRange = [...container.querySelectorAll<HTMLElement>('.mini-range-fragment[title="Visible range"]')];
    const clippedRange = [...container.querySelectorAll<HTMLElement>('.mini-range-fragment[title="Clipped range"]')];
    expect(visibleRange).toHaveLength(4);
    expect(visibleRange.filter((bar) => bar.classList.contains("range-start"))).toHaveLength(1);
    expect(visibleRange.filter((bar) => bar.classList.contains("range-end"))).toHaveLength(1);
    expect(clippedRange.some((bar) => bar.classList.contains("range-start"))).toBe(false);
    expect(clippedRange.filter((bar) => bar.classList.contains("range-end"))).toHaveLength(1);
    expect(container.querySelector(".mini-day-marker.task")).not.toBeInTheDocument();
  });

  it("renders visible markers for monthly tasks, events, and reminders", () => {
    mocks.privateCalendar = {
      tasks: [{ id: 201, title: "Monthly task", start_at: "2026-08-12", deadline_at: null }],
      entries: [{ id: 202, kind: "event", starts_at: "2026-08-13" }],
      time_blocks: [],
    };
    mocks.companyCalendar = {
      tasks: [],
      entries: [],
      time_blocks: [],
    };

    const { container } = renderDashboard();
    expect(container.querySelector(".mini-day-marker.task")).toBeInTheDocument();
    expect(container.querySelector(".mini-day-marker.event")).toBeInTheDocument();
    expect(container.querySelector(".mini-day-marker.reminder")).not.toBeInTheDocument();
  });

  it("renders the default widget canvas without the removed headers, period filter, or check-in", () => {
    const { container } = renderDashboard();
    for (const selector of [".world-clock-strip", ".today-worktime", ".today-kpi", ".today-quick-actions", ".today-task-column .today-task-tabs", ".today-news", ".today-mini-calendar"]) {
      expect(container.querySelector(selector), selector).toBeInTheDocument();
    }
    expect(container.querySelector(".daily-focus")).not.toBeInTheDocument();
    expect(container.querySelector(".dashboard-period")).not.toBeInTheDocument();
    expect(container.querySelector(".period-filter")).not.toBeInTheDocument();
    expect(container.querySelector(".world-clock-panel")).not.toBeInTheDocument();
    expect(screen.queryByText("Байгууллагын тойм")).not.toBeInTheDocument();
    expect(screen.queryByText("Нийт гүйцэтгэлийн үзүүлэлт")).not.toBeInTheDocument();
    expect(screen.queryByText("WORLD CLOCK")).not.toBeInTheDocument();
    expect(container.querySelector(".world-clock-chip")).toHaveTextContent("Ulaanbaatar");
  });

  it("enters edit mode with jiggle controls and removes a widget, persisting the layout", () => {
    const { container } = renderDashboard();
    expect(container.querySelector(".today-widget-remove")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Засварлах" }));
    expect(container.querySelector(".today-canvas.is-editing")).toBeInTheDocument();
    expect(container.querySelectorAll(".today-widget-remove").length).toBe(7);

    fireEvent.click(screen.getByRole("button", { name: "Мэдээ, мэдэгдэл хасах" }));
    expect(container.querySelector(".today-news")).not.toBeInTheDocument();
    const cached = JSON.parse(localStorage.getItem("oyuns.today-layout:7") || "{}");
    expect(cached.widgets.map((widget: any) => widget.type)).not.toContain("news");

    act(() => vi.advanceTimersByTime(1_000));
    expect(mocks.saveLayout).toHaveBeenCalledWith(expect.objectContaining({ widgets: expect.not.arrayContaining([expect.objectContaining({ type: "news" })]) }), expect.anything());

    fireEvent.click(screen.getByRole("button", { name: "Болсон" }));
    expect(container.querySelector(".today-canvas.is-editing")).not.toBeInTheDocument();
  });

  it("adds the hidden check-in widget from the searchable library", async () => {
    vi.useRealTimers(); // the library is lazy-loaded
    const { container } = renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: "Засварлах" }));
    fireEvent.click(screen.getByRole("button", { name: "Виджет нэмэх" }));
    const library = await screen.findByRole("complementary", { name: "Виджетийн сан" });
    fireEvent.change(within(library).getByRole("textbox"), { target: { value: "check-in" } });
    expect(within(library).queryByText("Цаг хэмжигч")).not.toBeInTheDocument();
    fireEvent.click(within(library).getByRole("button", { name: "Өдрийн check-in нэмэх" }));
    expect(container.querySelector(".daily-focus")).toBeInTheDocument();
    expect(within(library).getByRole("button", { name: "Өдрийн check-in нэмэгдсэн" })).toBeDisabled();
  });

  it("restores a saved layout with widget settings, including the previous-week period", () => {
    mocks.layout.data = {
      updated_at: 1,
      widgets: [{ id: "kpi-1", type: "kpi", x: 0, y: 0, w: 6, h: 6, settings: { period: "previous_week", metrics: ["worked_minutes"] } }],
    };
    const { container } = renderDashboard();
    expect(container.querySelectorAll(".today-widget-slot")).toHaveLength(1);
    expect(container.querySelector(".today-kpi .today-period-toggle [aria-checked=true]")).toHaveTextContent("Өмнөх 7 хоног");
    expect(container.querySelectorAll(".today-kpi-tile")).toHaveLength(1);
    // Previous week (Mon 3 – Sun 9 Aug 2026) compared with the week before.
    expect(mocks.summaryCalls).toContainEqual({ date_from: "2026-08-03", date_to: "2026-08-09" });
    expect(mocks.summaryCalls).toContainEqual({ date_from: "2026-07-27", date_to: "2026-08-02" });
  });

  it("lists announcements compactly and opens the full article", async () => {
    vi.useRealTimers(); // the article dialog is lazy-loaded
    mocks.news.data = [
      { id: 1, title: "Шинэ журам батлагдлаа", body: "Дэлгэрэнгүй **агуулга**", published_at: "2026-08-10T02:00:00Z", author_name: "HR" },
      { id: 2, title: "Онцгой мэдэгдэл", body: "Онцолсон", is_pinned: true, published_at: "2026-08-01T02:00:00Z" },
    ];
    const { container } = renderDashboard();
    const rows = container.querySelectorAll(".today-news-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Онцгой мэдэгдэл");
    expect(container.querySelector(".today-news .today-widget-meta")).toHaveTextContent("2 шинэ");
    fireEvent.click(screen.getByRole("button", { name: /Шинэ журам батлагдлаа/ }));
    expect(await screen.findByText("агуулга")).toBeInTheDocument();
    expect(container.querySelector(".today-news .today-widget-meta")).toHaveTextContent("1 шинэ");
  });
});
