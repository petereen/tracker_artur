import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorldClockWidget } from "./WorldClockWidget";

const mocks = vi.hoisted(() => ({
  preferences: { data: { clocks: ["Asia/Ulaanbaatar"], display_mode: "digital", hour_format: "24" }, isLoading: false, isError: false, refetch: vi.fn() },
  update: { mutateAsync: vi.fn().mockResolvedValue({ clocks: ["Asia/Ulaanbaatar"], display_mode: "digital", hour_format: "24" }), isPending: false },
}));

vi.mock("../api/enterprise", () => ({
  useWorldClockPreferences: () => mocks.preferences,
  useUpdateWorldClockPreferences: () => mocks.update,
}));

describe("WorldClockWidget", () => {
  beforeEach(() => {
    mocks.preferences.data = { clocks: ["Asia/Ulaanbaatar"], display_mode: "digital", hour_format: "24" };
  });
  afterEach(() => vi.clearAllMocks());

  it("renders the default Ulaanbaatar digital clock and opens settings", () => {
    render(<WorldClockWidget />);
    expect(screen.getByText("Ulaanbaatar")).toBeInTheDocument();
    expect(screen.getByText(/HRS/)).toBeInTheDocument();
    expect(document.querySelector(".world-clock-list.digital.count-1")).toBeInTheDocument();
    expect(document.querySelector(".world-clock-tile")).toHaveClass("world-clock-tile");

    fireEvent.click(screen.getByRole("button", { name: "Цагийн тохиргоо" }));
    expect(screen.getByRole("dialog", { name: "Цагийн тохиргоо" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analog" })).toBeInTheDocument();
  });

  it("stages a timezone addition and persists it when saved", async () => {
    render(<WorldClockWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Цагийн тохиргоо" }));
    fireEvent.click(screen.getByRole("button", { name: /Цаг нэмэх/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Цагийн бүс хайх" }), { target: { value: "Tokyo" } });
    fireEvent.click(screen.getByRole("option", { name: /Tokyo/ }));
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    expect(mocks.update.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ clocks: expect.arrayContaining(["Asia/Tokyo"]) }));
  });

  it("shows the empty state when the saved clock list is empty", () => {
    mocks.preferences.data = { clocks: [], display_mode: "analog", hour_format: "12" };
    render(<WorldClockWidget />);
    expect(screen.getByText("Цаг нэмээгүй байна")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Цаг нэмэх/ })).toBeInTheDocument();
  });

  it("uses a two-column square-tile grid for six clocks", () => {
    mocks.preferences.data = {
      clocks: ["Asia/Ulaanbaatar", "Asia/Tokyo", "Europe/London", "America/New_York", "Australia/Sydney", "Asia/Dubai"],
      display_mode: "digital",
      hour_format: "12",
    };
    render(<WorldClockWidget />);
    expect(document.querySelector(".world-clock-list.digital.count-6")).toBeInTheDocument();
    expect(document.querySelectorAll(".world-clock-tile")).toHaveLength(6);
    expect(document.querySelectorAll(".world-clock-period").length).toBeGreaterThan(0);
  });
});
