import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { Button, type ButtonProps } from "../components/primitives/button";
import { Input } from "../components/primitives/input";
import { Select } from "../components/primitives/select";
import {
  KarniPrimitivesProvider,
  useKarniPrimitives,
  type KarniPrimitiveOverrides,
  type KarniSelectParts,
} from "./registry";

/** A design system's own button, as a project would register it. */
const ProjectButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant, size, ...props }, ref) => (
    <button
      ref={ref}
      data-design-system="project"
      data-variant={variant ?? "default"}
      data-size={size ?? "default"}
      {...props}
    />
  ),
);
ProjectButton.displayName = "ProjectButton";

describe("the primitive registry", () => {
  it("renders Karni's primitive when the role is not registered", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).not.toHaveAttribute("data-design-system");
  });

  it("renders the project's component, with Karni's props and the ref", async () => {
    const onClick = vi.fn();
    const ref = React.createRef<HTMLButtonElement>();
    render(
      <KarniPrimitivesProvider value={{ button: ProjectButton }}>
        <Button ref={ref} variant="destructive" onClick={onClick}>
          Delete
        </Button>
      </KarniPrimitivesProvider>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toHaveAttribute("data-design-system", "project");
    expect(button).toHaveAttribute("data-variant", "destructive");
    expect(ref.current).toBe(button);
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("lets a registered component wrap Karni's own without calling itself", () => {
    const Wrapped = React.forwardRef<HTMLButtonElement, ButtonProps>((props, ref) => (
      <Button ref={ref} data-wrapped="" {...props} />
    ));
    Wrapped.displayName = "Wrapped";
    render(
      <KarniPrimitivesProvider value={{ button: Wrapped }}>
        <Button>Go</Button>
      </KarniPrimitivesProvider>,
    );
    expect(screen.getByRole("button", { name: "Go" })).toHaveAttribute("data-wrapped");
  });

  it("merges a nested registry over the one above it", () => {
    const ProjectInput = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
      (props, ref) => <input ref={ref} data-design-system="project" {...props} />,
    );
    ProjectInput.displayName = "ProjectInput";
    let seen: KarniPrimitiveOverrides = {};
    function Probe(): null {
      seen = useKarniPrimitives();
      return null;
    }
    render(
      <KarniPrimitivesProvider value={{ button: ProjectButton }}>
        <KarniPrimitivesProvider value={{ input: ProjectInput }}>
          <Button>Ok</Button>
          <Input aria-label="Name" />
          <Probe />
        </KarniPrimitivesProvider>
      </KarniPrimitivesProvider>,
    );
    expect(Object.keys(seen).sort()).toEqual(["button", "input"]);
    expect(screen.getByRole("button", { name: "Ok" })).toHaveAttribute("data-design-system");
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("data-design-system");
  });

  it("renders Karni's composed Select from a registered select family", () => {
    const parts: Record<string, string[]> = {};
    const record =
      (part: string) =>
      ({ children, ...props }: { children?: React.ReactNode } & Record<string, unknown>) => {
        (parts[part] ??= []).push(String(props["value"] ?? ""));
        return <div data-part={part}>{children}</div>;
      };
    const family = {
      Root: record("Root"),
      Trigger: record("Trigger"),
      Value: record("Value"),
      Content: record("Content"),
      Item: record("Item"),
      Group: record("Group"),
      Label: record("Label"),
      Separator: record("Separator"),
    } as unknown as KarniSelectParts;
    render(
      <KarniPrimitivesProvider value={{ select: family }}>
        <Select
          value="b"
          options={[
            { value: "a", label: "A" },
            { value: "b", label: "B" },
          ]}
        />
      </KarniPrimitivesProvider>,
    );
    expect(parts["Root"]).toEqual(["b"]);
    expect(parts["Item"]).toEqual(["a", "b"]);
    expect(Object.keys(parts).sort()).toEqual(["Content", "Item", "Root", "Trigger", "Value"]);
  });
});
