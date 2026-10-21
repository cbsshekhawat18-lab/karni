import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import { delay, http, HttpResponse, type RequestHandler } from "msw";
import * as React from "react";
import { fireEvent, screen, userEvent, waitFor, within } from "storybook/test";
import { handlers as backendHandlers, openApiFixture } from "../../../../tests/msw/handlers";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { ResourceForm } from "./ResourceForm";

/**
 * One story per state, every one against msw handlers that simulate a Karni
 * backend (the OpenAPI document the test suite uses, events CRUD, and the
 * venues, tags and users the relation pickers query). Interaction states
 * (errors after a submit, a slow submit) get there through a play function.
 */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <div className="mx-auto max-w-xl">{props.children}</div>
    </KarniProvider>
  );
}

/** The story's overrides first (the first matching handler answers), then the backend. */
function backend(...overrides: RequestHandler[]): { msw: { handlers: RequestHandler[] } } {
  return { msw: { handlers: [...overrides, ...backendHandlers] } };
}

const hang = async (): Promise<Response> => {
  await delay("infinite");
  return HttpResponse.json({});
};

const meta = {
  title: "Resource/ResourceForm",
  component: ResourceForm,
  args: { resource: "events" },
  parameters: backend(),
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof ResourceForm>;

export default meta;
type Story = StoryObj<typeof meta>;

async function titleField(): Promise<HTMLElement> {
  return screen.findByRole("textbox", { name: "Title" }, { timeout: 5000 });
}

/** Fills the two required fields and a description, then presses Create. */
async function fillAndSubmit(): Promise<void> {
  const user = userEvent.setup();
  await user.type(await titleField(), "Spring gala");
  fireEvent.change(screen.getByLabelText(/Starts at/), { target: { value: "2026-05-01T18:30" } });
  await user.type(screen.getByRole("textbox", { name: "Description" }), "Bring snacks.");
  await user.click(screen.getByRole("button", { name: "Create" }));
}

/** Every field kind: text, long text, date-time, number, choices, switch, relations, file, JSON. */
export const Create: Story = {};

export const Edit: Story = { args: { id: 1 } };

/** Before the schema arrives: a generic skeleton with the submit row where the real one sits. */
export const LoadingSchema: Story = {
  parameters: backend(http.get("*/api/schema/", hang)),
};

/** Edit mode while the row loads: the schema is known, so the skeleton has the form's rows. */
export const LoadingRow: Story = {
  args: { id: 1 },
  parameters: backend(http.get("*/api/events/:id/", hang)),
};

export const LoadError: Story = {
  parameters: backend(
    http.get("*/api/schema/", () => HttpResponse.json({ detail: "Down." }, { status: 503 })),
  ),
};

export const RowNotFound: Story = { args: { id: 999 } };

/** A 403 on load: the role cannot edit this row. */
export const Forbidden: Story = {
  args: { id: 1 },
  parameters: backend(
    http.get("*/api/events/:id/", () =>
      HttpResponse.json(
        { detail: "You do not have permission to perform this action." },
        { status: 403 },
      ),
    ),
  ),
};

function perRoleSchema(): Record<string, unknown> {
  const schema = structuredClone(openApiFixture) as unknown as {
    components: { schemas: Record<string, { properties: Record<string, unknown> }> };
  };
  const { Event, EventRequest, PatchedEventRequest } = schema.components.schemas;
  for (const component of [Event, EventRequest, PatchedEventRequest]) {
    for (const name of ["capacity", "internal_note", "metadata"])
      delete component?.properties[name];
  }
  for (const component of [EventRequest, PatchedEventRequest])
    delete component?.properties["venue"];
  return schema as unknown as Record<string, unknown>;
}

/**
 * What a role that may not see capacity, notes or metadata, and may not
 * change the venue, gets: those fields are simply not there.
 */
export const PartialPermission: Story = {
  args: { id: 1 },
  parameters: backend(http.get("*/api/schema/", () => HttpResponse.json(perRoleSchema()))),
};

/** A field is checked when it loses focus, and shows the problem under it. */
export const FieldError: Story = {
  play: async () => {
    const user = userEvent.setup();
    await titleField();
    await user.type(screen.getByRole("textbox", { name: "Contact email" }), "ada@");
    await user.tab();
  },
};

/** Submitting with two required fields empty: a summary, focused, each entry a way to the field. */
export const ValidationSummary: Story = {
  play: async () => {
    const user = userEvent.setup();
    await titleField();
    await user.click(screen.getByRole("button", { name: "Create" }));
  },
};

/** DRF's answer, every shape: field lists, nested objects, unknown keys and non_field_errors. */
export const ServerErrors: Story = {
  parameters: backend(
    http.post("*/api/events/", () =>
      HttpResponse.json(
        {
          title: ["An event with this title already exists."],
          venue: ['Invalid pk "99" - object does not exist.'],
          metadata: { theme: ["Unknown theme."] },
          non_field_errors: ["The venue is closed on that day."],
        },
        { status: 400 },
      ),
    ),
  ),
  play: fillAndSubmit,
};

/** The connection dropped: a banner with Try again, and everything typed is still there. */
export const SubmitOffline: Story = {
  parameters: backend(http.post("*/api/events/", () => HttpResponse.error())),
  play: fillAndSubmit,
};

export const SubmitForbidden: Story = {
  parameters: backend(
    http.post("*/api/events/", () =>
      HttpResponse.json(
        { detail: "You do not have permission to perform this action." },
        { status: 403 },
      ),
    ),
  ),
  play: fillAndSubmit,
};

export const SubmitServerError: Story = {
  parameters: backend(
    http.post("*/api/events/", () => HttpResponse.json({ detail: "Boom." }, { status: 500 })),
  ),
  play: fillAndSubmit,
};

/** Edit mode, someone else saved first: the latest version loads without losing what was typed. */
export const SubmitConflict: Story = {
  args: { id: 1 },
  parameters: backend(
    http.patch("*/api/events/:id/", () =>
      HttpResponse.json({ detail: "The event was edited by Asha at 10:42." }, { status: 409 }),
    ),
  ),
  play: async () => {
    const user = userEvent.setup();
    await user.type(await titleField(), " (moved)");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
  },
};

/** A slow save: fields and button disabled, progress after 500ms, the button keeps its width. */
export const SlowSubmit: Story = {
  parameters: backend(http.post("*/api/events/", hang)),
  play: async () => {
    await fillAndSubmit();
    await waitFor(
      () => {
        const button = screen.getByRole("button", { name: "Create" });
        if (within(button).queryByText("Create")?.className.includes("text-transparent") !== true) {
          throw new Error("not slow yet");
        }
      },
      { timeout: 2000 },
    );
  },
};
