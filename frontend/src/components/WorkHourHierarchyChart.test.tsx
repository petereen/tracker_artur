import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { WorkHourHierarchyChart } from "./WorkHourHierarchyChart";

const mockedUseWorkHoursAnalytics = vi.hoisted(() => vi.fn());

vi.mock("../api/enterprise", () => ({
  useWorkHoursAnalytics: mockedUseWorkHoursAnalytics,
}));

const period = { date_from: "2026-08-03", date_to: "2026-08-09" };
const current = {
  ...period,
  employee_id: null,
  remote_minutes: 120,
  office_minutes: 120,
  total_minutes: 240,
  scope: "organization" as const,
};
const previous = {
  date_from: "2026-07-27",
  date_to: "2026-08-02",
  employee_id: null,
  remote_minutes: 60,
  office_minutes: 180,
  total_minutes: 240,
  scope: "organization" as const,
};

function setAnalytics(overrides: Record<string, unknown> = {}) {
  mockedUseWorkHoursAnalytics.mockReturnValue({
    data: current,
    previousData: previous,
    isLoading: false,
    isFetching: false,
    trendPending: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  });
}

describe("WorkHourHierarchyChart", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    mockedUseWorkHoursAnalytics.mockReset();
    setAnalytics();
  });

  it("shows the visible total and localized category legend by default", () => {
    render(<WorkHourHierarchyChart period={period} />);

    expect(screen.getByText("4.0 hrs")).toBeInTheDocument();
    expect(screen.getByText("Total Logged")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Remote/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Office/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("syncs legend hover with the center content and trend", async () => {
    const { container } = render(<WorkHourHierarchyChart period={period} />);
    const remote = screen.getByRole("button", { name: /Remote/ });

    fireEvent.mouseEnter(remote, { clientX: 160, clientY: 120 });

    await waitFor(() => expect(container.querySelector(".work-hour-center")).toHaveTextContent("50.0%"));
    expect(container.querySelector(".work-hour-center")).toHaveTextContent("Remote");
    expect(screen.getAllByText(/25.0pp/).length).toBeGreaterThan(0);
  });

  it("recalculates the center and remaining share when a category is hidden", () => {
    render(<WorkHourHierarchyChart period={period} />);
    fireEvent.click(screen.getByRole("button", { name: /Remote/ }));

    expect(screen.getByText("2.0 hrs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Remote/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /Office/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText(/100\.0%/).length).toBeGreaterThan(0);
  });

  it("renders the empty state for a period without work hours", () => {
    setAnalytics({
      data: { ...current, remote_minutes: 0, office_minutes: 0, total_minutes: 0 },
      previousData: { ...previous, remote_minutes: 0, office_minutes: 0, total_minutes: 0 },
    });
    render(<WorkHourHierarchyChart period={period} />);

    expect(screen.getByText("No work hours recorded for this period")).toBeInTheDocument();
  });

  it("renders loading and retryable error states", () => {
    setAnalytics({ data: undefined, previousData: undefined, isLoading: true });
    const { unmount, container } = render(<WorkHourHierarchyChart period={period} />);
    expect(container.querySelector(".work-hour-loading")).toBeInTheDocument();
    unmount();

    const refetch = vi.fn();
    setAnalytics({ data: undefined, previousData: undefined, isError: true, refetch });
    render(<WorkHourHierarchyChart period={period} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
