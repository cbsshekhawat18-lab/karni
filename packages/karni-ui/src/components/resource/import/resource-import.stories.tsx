import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient } from "@tanstack/react-query";
import * as React from "react";
import { fireEvent, userEvent, waitFor, within } from "storybook/test";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { demoJob, importBackend } from "../testapp-fixtures";
import { ResourceImport } from "./ResourceImport";

/** msw serves `/api/events/import/…`; the later steps are reached by playing the upload. */
function Providers(props: { children: React.ReactNode }): React.ReactElement {
  const [context] = React.useState(() => ({
    client: createKarniClient({ baseUrl: `${window.location.origin}/api` }),
    queryClient: new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    }),
  }));
  return (
    <KarniProvider client={context.client} queryClient={context.queryClient}>
      <div className="max-w-3xl">{props.children}</div>
    </KarniProvider>
  );
}

const meta = {
  title: "Resource/ResourceImport",
  component: ResourceImport,
  tags: ["autodocs"],
  args: { resource: "events", title: "Import events" },
  parameters: { msw: { handlers: importBackend() } },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
} satisfies Meta<typeof ResourceImport>;

export default meta;
type Story = StoryObj<typeof meta>;

async function upload(canvasElement: HTMLElement): Promise<void> {
  const canvas = within(canvasElement);
  const input = (await canvas.findByLabelText("File to import")) as HTMLInputElement;
  // Set the browser's own file list (user-event's cannot be seen by the native input),
  // so the story shows the file staying chosen after a failed upload.
  const transfer = new DataTransfer();
  transfer.items.add(new File(["Title,Starts,Seats,Where\n"], "events.csv", { type: "text/csv" }));
  input.files = transfer.files;
  fireEvent.change(input);
  fireEvent.submit(input.form as HTMLFormElement);
}

async function preview(canvasElement: HTMLElement): Promise<void> {
  await upload(canvasElement);
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByRole("button", { name: "Preview" }));
}

async function openCommit(canvasElement: HTMLElement): Promise<void> {
  await preview(canvasElement);
  await userEvent.click(await within(canvasElement).findByRole("button", { name: "Commit" }));
  await within(document.body).findByRole("dialog");
}

/** The upload form, with the template links. */
export const Ready: Story = {};

/** Slow: after 500ms the placeholder draws the form's layout. */
export const Loading: Story = {
  parameters: { msw: { handlers: importBackend({ describe: "pending" }) } },
};

/** The role may not import: no form at all. */
export const Forbidden: Story = {
  parameters: { msw: { handlers: importBackend({ describe: { status: 403, body: {} } }) } },
};

export const DescribeFailed: Story = {
  parameters: { msw: { handlers: importBackend({ describe: { status: 500, body: {} } }) } },
};

export const Offline: Story = {
  parameters: { msw: { handlers: importBackend({ describe: "network" }) } },
};

/** The upload failed on the server: the file stays chosen, "Try again" re-sends it. */
export const UploadFailed: Story = {
  parameters: { msw: { handlers: importBackend({ upload: { status: 502, body: {} } }) } },
  play: async ({ canvasElement }) => {
    await upload(canvasElement);
    await within(canvasElement).findByRole("alert");
  },
};

/** The backend refused the file, and says why. */
export const UploadRefused: Story = {
  parameters: {
    msw: {
      handlers: importBackend({
        upload: {
          status: 400,
          body: { code: "E802", detail: "The file has no header row: the first row is empty." },
        },
      }),
    },
  },
  play: async ({ canvasElement }) => {
    await upload(canvasElement);
    await within(canvasElement).findByRole("alert");
  },
};

export const Uploading: Story = {
  parameters: { msw: { handlers: importBackend({ upload: "pending" }) } },
  play: async ({ canvasElement }) => {
    await upload(canvasElement);
  },
};

export const Mapping: Story = {
  play: async ({ canvasElement }) => {
    await upload(canvasElement);
    await within(canvasElement).findByRole("table", { name: "Column mapping" });
  },
};

/** A large file previews in the background: a progress bar, announced by the quarter. */
export const Progress: Story = {
  parameters: {
    msw: {
      handlers: importBackend({
        uploaded: demoJob({ rows_total: 12000 }),
        previewed: demoJob({
          status: "previewing",
          async: true,
          rows_total: 12000,
          rows_done: 4500,
        }),
        polls: Array.from({ length: 50 }, () =>
          demoJob({ status: "previewing", async: true, rows_total: 12000, rows_done: 4500 }),
        ),
      }),
    },
  },
  play: async ({ canvasElement }) => {
    await preview(canvasElement);
    await within(canvasElement).findByRole("progressbar");
  },
};

/** The dry run: counts and the rows that would fail, in a captioned table. */
export const Previewed: Story = {
  play: async ({ canvasElement }) => {
    await preview(canvasElement);
    await within(canvasElement).findByRole("table", { name: "Rows with errors" });
  },
};

/** The confirmation before a commit, with what it will do. */
export const ConfirmCommit: Story = {
  play: async ({ canvasElement }) => {
    await openCommit(canvasElement);
  },
};

export const CommitFailed: Story = {
  parameters: { msw: { handlers: importBackend({ commit: { status: 503, body: {} } }) } },
  play: async ({ canvasElement }) => {
    await openCommit(canvasElement);
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Commit import" }));
    await waitFor(() => within(dialog).getByRole("alert"));
  },
};

/** Committed: the counts, and the rows that were skipped for errors. */
export const Done: Story = {
  play: async ({ canvasElement }) => {
    await openCommit(canvasElement);
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Commit import" }));
    await within(canvasElement).findByRole("button", { name: "Import another file" });
  },
};
