import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnterpriseDashboardPage } from "./EnterpriseDashboardPage";

const mocks = vi.hoisted(() => ({
  clock: { data: undefined as any, refetch: vi.fn() },
  action: { mutate: vi.fn(), isPending: false },
  agenda: { data: { tasks: [] as any[], entries: [] as any[] } },
  privateCalendar: { tasks: [] as any[], entries: [] as any[], time_blocks: [] as any[] },
  companyCalendar: { tasks: [] as any[], entries: [] as any[], time_blocks: [] as any[] },
}));

vi.mock("../api/enterprise", () => ({
  useClock: () => mocks.clock,
  useClockAction: () => mocks.action,
  useCalendarEvents: (scope: string) => ({ data: scope === "private" ? mocks.privateCalendar : mocks.companyCalendar }),
  useEnterpriseSummary: () => ({ data: { active_projects: 1, completed_tasks: 2, completion_rate: 80, worked_minutes: 60 } }),
  useTodayCheckin: () => ({ data: {} }),
  useStartCheckin: () => ({ mutateAsync: vi.fn() }),
  useSubmitCheckin: () => ({ mutateAsync: vi.fn() }),
  useTodayAgenda: () => mocks.agenda,
  useEnterpriseTasks: () => ({ data: [] }),
  useWorkerDirectory: () => ({ data: [] }),
  useUpdateEnterpriseTask: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
  useDeleteEnterpriseTask: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
}));

vi.mock("../store/auth", () => ({
  EMPTY_ROLES: [],
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ actor: { employee_id: 1, roles: [] } }),
}));

function setVisibilityState(value: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value,
  });
}

function renderDashboard() {
  return render(<EnterpriseDashboardPage />);
}

describe("Today work-hour timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-11T10:00:00.000Z"));
    setVisibilityState("visible");
    mocks.clock.refetch.mockReset();
    mocks.action.mutate.mockReset();
    mocks.agenda.data = { tasks: [], entries: [] };
    mocks.privateCalendar = { tasks: [], entries: [], time_blocks: [] };
    mocks.companyCalendar = { tasks: [], entries: [], time_blocks: [] };
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

  it("holds the timer and companion behind the clock loading gate", () => {
    mocks.clock.data = undefined;
    const { container, rerender } = renderDashboard();

    expect(container.querySelector(".clock-time")).not.toBeInTheDocument();
    expect(container.querySelector(".today-companion img")).not.toBeInTheDocument();
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
    rerender(<EnterpriseDashboardPage />);

    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:05");
    expect(container.querySelector(".today-companion img")).toHaveAttribute("src", "/oyuns-working.gif");
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
    const { container, rerender } = renderDashboard();
    act(() => vi.advanceTimersByTime(1_000));

    const endedAt = new Date(Date.now()).toISOString();
    mocks.clock.data = {
      ...mocks.clock.data,
      active: null,
      today_entries: [{ ...mocks.clock.data.today_entries[0], ended_at: endedAt }],
      server_time: endedAt,
    };
    rerender(<EnterpriseDashboardPage />);
    act(() => vi.advanceTimersByTime(3_000));

    expect(container.querySelector(".clock-time")).toHaveTextContent("00:00:06");
  });

  it("maps start, pause, resume, and stop controls to clock actions", () => {
    const { rerender } = renderDashboard();
    fireEvent.click(document.querySelector("button.clock-button.break") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "break" });
    fireEvent.click(document.querySelector("button.clock-button.stop") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "stop" });

    mocks.clock.data = {
      ...mocks.clock.data,
      active: { ...mocks.clock.data.active, entry_type: "break", mode: null },
    };
    rerender(<EnterpriseDashboardPage />);
    fireEvent.click(document.querySelector("button.clock-button.office") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "resume" });

    mocks.clock.data = { ...mocks.clock.data, active: null };
    rerender(<EnterpriseDashboardPage />);
    fireEvent.click(document.querySelector("button.clock-button.office") as HTMLButtonElement);
    expect(mocks.action.mutate).toHaveBeenLastCalledWith({ action: "start", mode: "in_person" });
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
    const bars = [...container.querySelectorAll<HTMLElement>(".mini-range-bar")];
    expect(bars).toHaveLength(2);
    expect(bars.some((bar) => bar.classList.contains("range-start") && bar.classList.contains("range-end"))).toBe(true);
    expect(bars.some((bar) => !bar.classList.contains("range-start") && bar.classList.contains("range-end"))).toBe(true);
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
      entries: [{ id: 203, kind: "reminder", starts_at: "2026-08-14", remind_at: "2026-08-14" }],
      time_blocks: [],
    };

    const { container } = renderDashboard();
    expect(container.querySelector(".mini-day-marker.task")).toBeInTheDocument();
    expect(container.querySelector(".mini-day-marker.event")).toBeInTheDocument();
    expect(container.querySelector(".mini-day-marker.reminder")).toBeInTheDocument();
  });
});
