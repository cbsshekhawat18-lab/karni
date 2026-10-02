import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KARNI_SELECT_EMPTY, Select, type SelectOption } from "./select";

const options: readonly SelectOption[] = [
  { value: "draft", label: "Draft" },
  { value: "published", label: "Published" },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Select (contract D8)", () => {
  it("shows the placeholder when empty and not clearable", () => {
    render(
      <Select value={null} options={options} placeholder="Pick a status" aria-label="Status" />,
    );
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("Pick a status");
  });

  it("emits the option value through onValueChange", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Select value={null} onValueChange={onValueChange} options={options} aria-label="Status" />,
    );

    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "Published" }));

    expect(onValueChange).toHaveBeenCalledWith("published");
  });

  it("renders a clear item when clearable, and choosing it emits null", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Select
        value="draft"
        onValueChange={onValueChange}
        options={options}
        clearable
        clearLabel="All statuses"
        aria-label="Status"
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "All statuses" }));

    // The "__karni_empty__" sentinel never leaks: consumers receive null.
    expect(onValueChange).toHaveBeenCalledWith(null);
  });

  it("shows the clear label on the trigger when clearable and empty", () => {
    render(
      <Select value={null} options={options} clearable clearLabel="All" aria-label="Status" />,
    );
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("All");
  });

  it("drops reserved option values and warns", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(
      <Select
        value={null}
        options={[
          ...options,
          { value: "", label: "Bad empty" },
          { value: KARNI_SELECT_EMPTY, label: "Bad sentinel" },
        ]}
        aria-label="Status"
      />,
    );

    expect(warn).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await screen.findByRole("option", { name: "Draft" });
    expect(screen.queryByRole("option", { name: "Bad empty" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Bad sentinel" })).not.toBeInTheDocument();
  });

  it("forwards its ref to the trigger button", () => {
    const ref = React.createRef<HTMLButtonElement>();
    render(<Select ref={ref} value={null} options={options} aria-label="Status" />);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });
});
