import type { UseQueryResult } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { useFormContext } from "react-hook-form";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { z } from "zod";
import type { ZodObject, ZodRawShape } from "zod";
import type { ResourceItemParams } from "../../../hooks/types";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import type { ResourceMutations } from "../../../hooks/useResourceMutations";
import type { ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import type { UseSchemaResult } from "../../../schema/useSchema";
import { zodFor } from "../../../schema/zod";
import { ResourceSelect } from "../select/ResourceSelect";
import type { ResourceSelectProps } from "../select/ResourceSelect";
import { eventRecord, eventSchema } from "./fixtures";
import { toDatetimeLocal, toIsoWithOffset } from "./prepare";
import { ResourceForm } from "./ResourceForm";
import type { KarniFieldProps } from "./ResourceForm";

vi.mock("../../../schema/useSchema", () => ({ useSchema: vi.fn() }));
vi.mock("../../../schema/zod", () => ({ zodFor: vi.fn() }));
vi.mock("../../../hooks/useResourceItem", () => ({ useResourceItem: vi.fn() }));
vi.mock("../../../hooks/useResourceMutations", () => ({ useResourceMutations: vi.fn() }));
// ResourceSelect forwards its ref (form focus wiring), so the double does too.
vi.mock("../select/ResourceSelect", async () => {
  const ReactModule = await import("react");
  const render = vi.fn();
  const ResourceSelect = Object.assign(
    ReactModule.forwardRef<HTMLInputElement, ResourceSelectProps>((props, ref) => {
      void ref;
      return render(props);
    }),
    { mock: render },
  );
  return { ResourceSelect };
});

const mockUseSchema = useSchema as unknown as Mock<(resource: string) => UseSchemaResult>;
const mockZodFor = zodFor as unknown as Mock<
  (schema: ResourceSchema, mode: "create" | "update") => ZodObject<ZodRawShape>
>;
const mockUseResourceItem = useResourceItem as unknown as Mock<
  (
    resource: string,
    id: string | number,
    params?: ResourceItemParams,
    options?: { enabled?: boolean },
  ) => UseQueryResult<Record<string, unknown>>
>;
const mockUseResourceMutations = useResourceMutations as unknown as Mock<
  (resource: string) => ResourceMutations<Record<string, unknown>>
>;
const mockResourceSelect = (ResourceSelect as unknown as { mock: Mock }).mock as Mock<
  (props: ResourceSelectProps) => React.ReactElement
>;

function queryResult<T>(
  data: T | undefined,
  overrides: { isLoading?: boolean; error?: unknown } = {},
): UseQueryResult<T> {
  return {
    data,
    isLoading: overrides.isLoading ?? false,
    error: overrides.error ?? null,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<T>;
}

interface MutationMock {
  mutateAsync: Mock;
  isPending: boolean;
}

function setupMutations(): { create: MutationMock; update: MutationMock; remove: MutationMock } {
  const create: MutationMock = {
    mutateAsync: vi.fn((values: Record<string, unknown>) =>
      Promise.resolve({ id: 101, ...values }),
    ),
    isPending: false,
  };
  const update: MutationMock = {
    mutateAsync: vi.fn((input: { id: string | number; values: Record<string, unknown> }) =>
      Promise.resolve({ ...eventRecord, ...input.values }),
    ),
    isPending: false,
  };
  const remove: MutationMock = { mutateAsync: vi.fn(), isPending: false };
  mockUseResourceMutations.mockReturnValue({
    create,
    update,
    remove,
  } as unknown as ResourceMutations<Record<string, unknown>>);
  return { create, update, remove };
}

beforeEach(() => {
  mockUseSchema.mockReturnValue({ data: eventSchema, isLoading: false, error: undefined });
  mockZodFor.mockReturnValue(z.object({}).passthrough() as unknown as ZodObject<ZodRawShape>);
  mockUseResourceItem.mockImplementation((_resource, _id, _params, options) =>
    options?.enabled === false
      ? queryResult<Record<string, unknown>>(undefined)
      : queryResult<Record<string, unknown>>(eventRecord),
  );
  mockResourceSelect.mockImplementation((props: ResourceSelectProps) => (
    <div data-testid={`resource-select-${props.resource}`}>
      <span data-testid={`resource-select-${props.resource}-value`}>
        {JSON.stringify(props.value ?? null)}
      </span>
      <button type="button" onClick={() => props.onChange(props.multiple === true ? [1, 2] : 7)}>
        pick-{props.resource}
      </button>
      <button type="button" onClick={() => props.onChange(null)}>
        clear-{props.resource}
      </button>
    </div>
  ));
  setupMutations();
});

describe("ResourceForm rendering", () => {
  it("renders the contract's input per field kind and skips readOnly/unknown fields", () => {
    render(<ResourceForm resource="events" />);

    expect(screen.getByRole("textbox", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Description" }).tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText(/Starts at/)).toHaveAttribute("type", "datetime-local");
    expect(screen.getByRole("spinbutton", { name: "Capacity" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Is public" })).toBeInTheDocument();
    expect(screen.getByTestId("resource-select-venues")).toBeInTheDocument();
    expect(screen.getByTestId("resource-select-tags")).toBeInTheDocument();
    // FileUpload's dropzone is a button whose accessible name comes from the
    // field's <Label htmlFor>, which overrides its visible drag-drop content.
    const dropzone = screen.getByRole("button", { name: "Image" });
    expect(dropzone).toHaveTextContent(/click to browse/);
    expect(screen.getByRole("textbox", { name: "Metadata" })).toBeInTheDocument();
    // writeOnly fields are editable; readOnly and unknown fields never render.
    expect(screen.getByRole("textbox", { name: "Internal note" })).toBeInTheDocument();
    expect(screen.queryByText("Created at")).not.toBeInTheDocument();
    expect(screen.queryByText("Mystery")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
  });

  it("shows a loading skeleton while the schema loads and an alert on schema errors", () => {
    mockUseSchema.mockReturnValue({ data: undefined, isLoading: true, error: undefined });
    const { unmount } = render(<ResourceForm resource="events" />);
    expect(screen.getByRole("status", { name: "Loading form" })).toBeInTheDocument();
    unmount();

    // Errors are worded through describeError: plain words and a retry,
    // never the raw exception text.
    const refetch = vi.fn();
    mockUseSchema.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Schema unavailable"),
      refetch,
      isFetching: false,
    });
    render(<ResourceForm resource="events" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load this form");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Schema unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("ResourceForm create mode", () => {
  it("submits coerced values per kind (D3 coercions) and reports success", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    const { create } = setupMutations();
    render(<ResourceForm resource="events" onSuccess={onSuccess} />);

    await user.type(screen.getByRole("textbox", { name: "Title" }), "Spring gala");
    fireEvent.change(screen.getByLabelText(/Starts at/), {
      target: { value: "2026-05-01T18:30" },
    });
    await user.type(screen.getByRole("spinbutton", { name: "Capacity" }), "40");
    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(await screen.findByRole("option", { name: "Published" }));
    await user.click(screen.getByRole("switch", { name: "Is public" }));
    await user.click(screen.getByRole("button", { name: "pick-venues" }));
    await user.click(screen.getByRole("button", { name: "pick-tags" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Metadata" }), {
      target: { value: '{"theme": "neon"}' },
    });
    await user.type(screen.getByRole("textbox", { name: "Internal note" }), "secret");

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(create.mutateAsync).toHaveBeenCalledTimes(1));
    expect(create.mutateAsync.mock.calls[0]?.[0]).toEqual({
      title: "Spring gala",
      description: "",
      starts_at: toIsoWithOffset("2026-05-01T18:30"),
      capacity: 40,
      status: "published",
      is_public: true,
      venue: 7,
      tags: [1, 2],
      image: null,
      metadata: { theme: "neon" },
      internal_note: "secret",
    });
    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ id: 101 })),
    );
  });

  it("surfaces zod validation errors through the resolver and never mutates", async () => {
    const user = userEvent.setup();
    mockZodFor.mockReturnValue(
      z
        .object({ title: z.string().min(1, "Title is required") })
        .passthrough() as unknown as ZodObject<ZodRawShape>,
    );
    const { create } = setupMutations();
    render(<ResourceForm resource="events" />);

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Title is required")).toBeInTheDocument();
    expect(create.mutateAsync).not.toHaveBeenCalled();
  });

  it("blocks the submit on invalid JSON with a field error", async () => {
    const user = userEvent.setup();
    const { create } = setupMutations();
    render(<ResourceForm resource="events" />);

    fireEvent.change(screen.getByRole("textbox", { name: "Metadata" }), {
      target: { value: "{oops" },
    });
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Enter valid JSON.")).toBeInTheDocument();
    expect(create.mutateAsync).not.toHaveBeenCalled();
  });

  it("maps DRF 400 field errors via setError and non_field_errors to the root alert", async () => {
    const user = userEvent.setup();
    const onError = vi.fn();
    const { create } = setupMutations();
    create.mutateAsync.mockRejectedValue({
      status: 400,
      data: { title: ["Already exists."], non_field_errors: ["Nope."] },
    });
    render(<ResourceForm resource="events" onError={onError} />);

    await user.type(screen.getByRole("textbox", { name: "Title" }), "Duplicate");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Already exists.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Nope.");
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ status: 400 }));
    const title = screen.getByRole("textbox", { name: "Title" });
    expect(title).toHaveAttribute("aria-invalid", "true");
  });
});

describe("ResourceForm create mode: cleared optional fields", () => {
  it("validates a cleared optional, non-nullable enum as absent and omits it", async () => {
    mockZodFor.mockReturnValue(
      z
        .object({ title: z.string().min(1), status: z.enum(["draft", "published"]).optional() })
        .passthrough() as unknown as ZodObject<ZodRawShape>,
    );
    const { create } = setupMutations();
    const onSuccess = vi.fn();
    render(<ResourceForm resource="events" onSuccess={onSuccess} />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Title" }), "Launch");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const sent = create.mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(sent["title"]).toBe("Launch");
    expect("status" in sent).toBe(false);
  });
});

describe("ResourceForm edit mode (D3/D10)", () => {
  it("loads the unexpanded item and PATCHes only dirty fields", async () => {
    const user = userEvent.setup();
    const { update } = setupMutations();
    render(<ResourceForm resource="events" id={1} />);

    const title = screen.getByRole("textbox", { name: "Title" });
    expect(title).toHaveValue("Launch party");
    expect(screen.getByLabelText(/Starts at/)).toHaveValue(
      toDatetimeLocal(String(eventRecord["starts_at"])),
    );
    // Relation values arrive as raw pks (unexpanded detail, D10).
    expect(screen.getByTestId("resource-select-venues-value")).toHaveTextContent("7");

    await user.clear(title);
    await user.type(title, "Updated title");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(update.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        values: { title: "Updated title" },
      }),
    );
  });

  it("sends null for emptied nullable fields and [] for cleared many relations", async () => {
    const user = userEvent.setup();
    const { update } = setupMutations();
    render(<ResourceForm resource="events" id={1} />);

    await user.clear(screen.getByRole("spinbutton", { name: "Capacity" }));
    await user.click(screen.getByRole("button", { name: "clear-venues" }));
    await user.click(screen.getByRole("button", { name: "clear-tags" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(update.mutateAsync).toHaveBeenCalledWith({
        id: 1,
        values: { capacity: null, venue: null, tags: [] },
      }),
    );
  });

  it("does not mark a required file as required when the row already has one", async () => {
    const user = userEvent.setup();
    const { update } = setupMutations();
    const requiredImage: ResourceSchema = {
      ...eventSchema,
      fields: eventSchema.fields.map((field) =>
        field.name === "image" ? { ...field, required: true, nullable: false } : field,
      ),
    };
    mockUseSchema.mockReturnValue({ data: requiredImage, isLoading: false, error: undefined });

    const { unmount } = render(<ResourceForm resource="events" />);
    expect(screen.getByRole("button", { name: "Image (required)" })).toBeInTheDocument();
    unmount();

    render(<ResourceForm resource="events" id={1} />);
    // The stored file is listed by name, and the dropzone is not required.
    expect(screen.getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(screen.queryByText("(required)", { exact: false })).toBeNull();
    expect(screen.getByRole("link", { name: "launch.png" })).toHaveAttribute(
      "href",
      String(eventRecord["image"]),
    );

    const title = screen.getByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(update.mutateAsync).toHaveBeenCalledWith({ id: 1, values: { title: "Renamed" } }),
    );
  });

  it("keeps a required file required on edit when the row has none", () => {
    const requiredImage: ResourceSchema = {
      ...eventSchema,
      fields: eventSchema.fields.map((field) =>
        field.name === "image" ? { ...field, required: true, nullable: false } : field,
      ),
    };
    mockUseSchema.mockReturnValue({ data: requiredImage, isLoading: false, error: undefined });
    mockUseResourceItem.mockImplementation(() =>
      queryResult<Record<string, unknown>>({ ...eventRecord, image: null }),
    );
    render(<ResourceForm resource="events" id={1} />);
    expect(screen.getByRole("button", { name: "Image (required)" })).toBeInTheDocument();
  });

  it("shows the skeleton while the item loads", () => {
    mockUseResourceItem.mockImplementation(() =>
      queryResult<Record<string, unknown>>(undefined, { isLoading: true }),
    );
    render(<ResourceForm resource="events" id={1} />);
    expect(screen.getByRole("status", { name: "Loading form" })).toBeInTheDocument();
  });
});

describe("ResourceForm escape hatches", () => {
  it("fields: hidden hides, label renames, component replaces the whole row", () => {
    function CustomCapacity(props: KarniFieldProps): React.ReactElement {
      return (
        <div data-testid="custom-capacity">
          {props.name}:{String(props.required)}:{props.props?.["flavor"] as string}
        </div>
      );
    }
    render(
      <ResourceForm
        resource="events"
        fields={{
          description: { hidden: true },
          title: { label: "Headline" },
          capacity: { component: CustomCapacity, props: { flavor: "custom" } },
        }}
      />,
    );

    expect(screen.queryByRole("textbox", { name: "Description" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Headline" })).toBeInTheDocument();
    expect(screen.getByTestId("custom-capacity")).toHaveTextContent("capacity:false:custom");
    expect(screen.queryByRole("spinbutton", { name: "Capacity" })).not.toBeInTheDocument();
  });

  it("extraFields register through FormProvider, transformSubmit shapes the payload, actions replaces the submit row", async () => {
    const user = userEvent.setup();
    const { create } = setupMutations();
    function SlugField(): React.ReactElement {
      const { register } = useFormContext();
      return <input aria-label="Slug" {...register("slug")} />;
    }
    render(
      <ResourceForm
        resource="events"
        extraFields={<SlugField />}
        transformSubmit={(values) => ({ ...values, transformed: true })}
        actions={<button type="submit">Ship it</button>}
      />,
    );

    expect(screen.queryByRole("button", { name: "Create" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Slug" }), "my-slug");
    await user.click(screen.getByRole("button", { name: "Ship it" }));

    await waitFor(() => expect(create.mutateAsync).toHaveBeenCalledTimes(1));
    const payload = create.mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload["slug"]).toBe("my-slug");
    expect(payload["transformed"]).toBe(true);
  });
});
