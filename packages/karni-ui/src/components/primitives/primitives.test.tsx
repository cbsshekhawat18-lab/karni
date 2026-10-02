import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./button";
import { Checkbox } from "./checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { Input } from "./input";
import { Label } from "./label";
import { Skeleton } from "./skeleton";
import { Switch } from "./switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";
import { Textarea } from "./textarea";

describe("Input", () => {
  it("renders, forwards its ref, and merges className with cn()", () => {
    const ref = React.createRef<HTMLInputElement>();
    render(<Input ref={ref} placeholder="Email" className="h-12" />);
    const input = screen.getByPlaceholderText("Email");
    expect(ref.current).toBe(input);
    const classes = input.className.split(/\s+/);
    expect(classes).toContain("h-12");
    // the default h-10 loses the tailwind-merge conflict
    expect(classes).not.toContain("h-10");
  });
});

describe("Textarea", () => {
  it("renders a textbox and forwards its ref", () => {
    const ref = React.createRef<HTMLTextAreaElement>();
    render(<Textarea ref={ref} aria-label="Notes" />);
    expect(screen.getByRole("textbox", { name: "Notes" })).toBe(ref.current);
  });
});

describe("Checkbox", () => {
  it("toggles its checked state on click", async () => {
    const user = userEvent.setup();
    render(<Checkbox aria-label="Accept" />);
    const checkbox = screen.getByRole("checkbox", { name: "Accept" });
    expect(checkbox).toHaveAttribute("aria-checked", "false");
    await user.click(checkbox);
    expect(checkbox).toHaveAttribute("aria-checked", "true");
  });
});

describe("Switch", () => {
  it("toggles and reports state changes", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Switch aria-label="Notifications" onCheckedChange={onCheckedChange} />);
    const toggle = screen.getByRole("switch", { name: "Notifications" });
    await user.click(toggle);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});

describe("Label", () => {
  it("associates with its control via htmlFor", () => {
    render(
      <div>
        <Label htmlFor="name-field">Name</Label>
        <Input id="name-field" />
      </div>,
    );
    expect(screen.getByLabelText("Name")).toBeInstanceOf(HTMLInputElement);
  });
});

describe("Tabs", () => {
  it("shows the panel of the active trigger", async () => {
    const user = userEvent.setup();
    render(
      <Tabs defaultValue="one">
        <TabsList>
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one">First panel</TabsContent>
        <TabsContent value="two">Second panel</TabsContent>
      </Tabs>,
    );
    expect(screen.getByText("First panel")).toBeVisible();
    expect(screen.queryByText("Second panel")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Two" }));
    expect(screen.getByText("Second panel")).toBeVisible();
  });
});

describe("DropdownMenu", () => {
  it("opens on trigger click and fires onSelect for items", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline">Actions</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={onSelect}>Edit</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

describe("Skeleton", () => {
  it("renders the pulse placeholder and forwards its ref", () => {
    const ref = React.createRef<HTMLDivElement>();
    render(<Skeleton ref={ref} data-testid="skeleton" className="h-4 w-24" />);
    const el = screen.getByTestId("skeleton");
    expect(el).toBe(ref.current);
    expect(el.className.split(/\s+/)).toEqual(
      expect.arrayContaining(["animate-pulse", "h-4", "w-24"]),
    );
  });
});
