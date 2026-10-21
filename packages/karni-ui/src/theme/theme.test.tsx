import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, ThemeToggle, THEME_STORAGE_KEY } from "./theme";

function mockSystem(dark: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: dark,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});
afterEach(() => vi.unstubAllGlobals());

describe("ThemeProvider", () => {
  it("follows the system until the user chooses", () => {
    mockSystem(true);
    render(<ThemeProvider />);
    expect(document.documentElement).toHaveClass("dark");
  });

  it("cycles Light → Dark → System and keeps the choice", async () => {
    mockSystem(false);
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const toggle = screen.getByRole("button", { name: "Theme: Light. Switch to Dark" });
    expect(document.documentElement).not.toHaveClass("dark");
    await userEvent.click(toggle);
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Theme: Dark. Switch to System" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(
      screen.getByRole("button", { name: "Theme: System. Switch to Light" }),
    ).toBeInTheDocument();
  });
});
