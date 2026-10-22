/**
 * ResourceImport's states against an msw backend: the description loading,
 * failing (403: no form) and offline; a failed upload that keeps the file;
 * progress that is announced by the quarter; the problems table's
 * semantics; and the confirmation before a commit.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { server } from "../../../../tests/msw/server";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { demoImportDescription, demoJob, importBackend, previewedJob } from "../testapp-fixtures";
import {
  defaultResourceImportSlots,
  ResourceImport,
  type ResourceImportProps,
} from "./ResourceImport";

const BASE = "http://karni.test/api";

function mount(props: Partial<ResourceImportProps> = {}) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      <ResourceImport resource="events" {...props} />
    </KarniProvider>,
  );
}

function setOnline(online: boolean): void {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => online });
  window.dispatchEvent(new Event(online ? "online" : "offline"));
}

afterEach(() => {
  act(() => setOnline(true));
});

const csv = (): File =>
  new File(["Title,Starts\nA,2026-11-01\n"], "events.csv", { type: "text/csv" });

async function chooseAndUpload(
  user: ReturnType<typeof userEvent.setup>,
): Promise<HTMLInputElement> {
  const input = (await screen.findByLabelText("File to import")) as HTMLInputElement;
  await user.upload(input, csv());
  // jsdom's constraint validation does not see files set by user.upload (the
  // input is `required`), so the form is submitted directly.
  fireEvent.submit(input.form as HTMLFormElement);
  return input;
}

describe("ResourceImport before the upload", () => {
  it("holds the form's layout while loading and draws it once loading is slow", async () => {
    server.use(...importBackend({ describe: "pending" }));
    mount();
    const section = screen.getByRole("region", { name: "Import" });
    expect(section).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("resource-import-loading")).toHaveClass("invisible");
    expect(screen.queryByLabelText("File to import")).toBeNull();
    expect(screen.queryByRole("button", { name: "Download template (XLSX)" })).toBeNull();
    await waitFor(() => expect(screen.getByText("Loading the import form…")).toBeInTheDocument(), {
      timeout: 2000,
    });
    expect(screen.getByTestId("resource-import-loading")).not.toHaveClass("invisible");
  });

  it("does not show the form when the description is refused (403)", async () => {
    server.use(...importBackend({ describe: { status: 403, body: {} } }));
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You can't import events");
    expect(alert).not.toHaveTextContent("403");
    expect(screen.queryByLabelText("File to import")).toBeNull();
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Download template (XLSX)" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("retries a description that failed on the server", async () => {
    let calls = 0;
    server.use(...importBackend());
    server.use(
      http.get("*/api/events/import/", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({}, { status: 500 })
          : HttpResponse.json(demoImportDescription);
      }),
    );
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("File to import")).toBeInTheDocument();
  });

  it("says it is offline and shows the form once back online", async () => {
    server.use(...importBackend());
    act(() => setOnline(false));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("You're offline");
    act(() => setOnline(true));
    expect(await screen.findByLabelText("File to import")).toBeInTheDocument();
  });

  it("labels the file input and describes what it accepts", async () => {
    server.use(...importBackend());
    mount();
    const input = await screen.findByLabelText("File to import");
    expect(input).toHaveAccessibleDescription(
      "CSV or XLSX with a header row, up to 100,000 rows. The template lists the columns.",
    );
    expect(screen.getByRole("button", { name: "CSV template" })).toBeInTheDocument();
  });
});

describe("ResourceImport upload", () => {
  it("keeps the chosen file after a failed upload, moves focus to the error and retries it", async () => {
    const names: string[] = [];
    server.use(...importBackend());
    server.use(
      http.post("*/api/events/import/", async ({ request }) => {
        const body = await request.text();
        names.push(/filename="([^"]+)"/.exec(body)?.[1] ?? "(no file)");
        return names.length === 1
          ? HttpResponse.json({}, { status: 502 })
          : HttpResponse.json(demoJob(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    mount();
    const input = await chooseAndUpload(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await waitFor(() => expect(alert.parentElement).toHaveFocus());
    // The same input (not a fresh one) still holds the file.
    expect(screen.getByLabelText("File to import")).toBe(input);
    expect(input.isConnected).toBe(true);
    expect(input.files?.[0]?.name).toBe("events.csv");

    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table", { name: "Column mapping" })).toBeInTheDocument();
    expect(names).toEqual(["events.csv", "events.csv"]);
  });

  it("says when the server cannot be reached during the upload", async () => {
    server.use(...importBackend({ upload: "network" }));
    const user = userEvent.setup();
    mount();
    await chooseAndUpload(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't reach the server");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("says why the backend refused the file and marks the input invalid", async () => {
    server.use(
      ...importBackend({
        upload: { status: 400, body: { code: "E802", detail: "The file has no header row." } },
      }),
    );
    const user = userEvent.setup();
    mount();
    const input = await chooseAndUpload(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This file can't be imported");
    expect(alert).toHaveTextContent("The file has no header row.");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("moves focus to the mapping step after an upload, with table semantics", async () => {
    server.use(...importBackend());
    const user = userEvent.setup();
    mount();
    await chooseAndUpload(user);
    const table = await screen.findByRole("table", { name: "Column mapping" });
    for (const header of within(table).getAllByRole("columnheader")) {
      expect(header).toHaveAttribute("scope", "col");
    }
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Title", "Starts", "Seats", "Where"]);
    await waitFor(() => expect(table.closest("[data-step]")).toHaveFocus());
  });
});

describe("ResourceImport preview and commit", () => {
  it("shows a preview's problems in a captioned table with row headers", async () => {
    server.use(...importBackend());
    const user = userEvent.setup();
    mount();
    await chooseAndUpload(user);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    const problems = await screen.findByRole("table", { name: "Rows with errors" });
    expect(problems.querySelector("caption")).toHaveTextContent("Rows with errors");
    expect(
      within(problems)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Row", "Field", "Problem"]);
    for (const header of within(problems).getAllByRole("columnheader")) {
      expect(header).toHaveAttribute("scope", "col");
    }
    const rows = within(problems).getAllByRole("rowheader");
    expect(rows.map((cell) => cell.textContent)).toEqual(["14", "87"]);
    expect(rows[0]).toHaveAttribute("scope", "row");
    expect(screen.getByText(/previewed; nothing is saved yet/)).toHaveAttribute("role", "status");
  });

  it("asks before committing, with the counts, and returns focus when cancelled", async () => {
    let commits = 0;
    server.use(...importBackend());
    const count = ({ request }: { request: Request }): void => {
      if (request.method === "POST" && request.url.endsWith("/commit/")) commits += 1;
    };
    server.events.on("request:start", count);
    onTestFinished(() => server.events.removeListener("request:start", count));
    const onDone = vi.fn();
    const user = userEvent.setup();
    mount({ onDone });
    await chooseAndUpload(user);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    const commit = await screen.findByRole("button", { name: "Commit" });

    await user.click(commit);
    let dialog = screen.getByRole("dialog", { name: "Commit this import?" });
    expect(dialog).toHaveTextContent("events.csv: 114 rows will be saved to events.");
    expect(within(dialog).getByTestId("import-confirm-counts")).toHaveTextContent(
      "Created96Updated18Unchanged4Failed2",
    );
    expect(dialog).toHaveTextContent("2 rows have errors and will not be imported");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(commit).toHaveFocus());
    expect(commits).toBe(0);

    await user.click(commit);
    dialog = screen.getByRole("dialog", { name: "Commit this import?" });
    await user.click(within(dialog).getByRole("button", { name: "Commit import" }));
    expect(await screen.findByText(/120 rows, imported\./)).toBeInTheDocument();
    expect(commits).toBe(1);
    expect(onDone).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByText(/imported\./).closest("[data-step]")).toHaveFocus(),
    );
  });

  it("reports a failed commit inside the confirmation and moves focus to it", async () => {
    server.use(...importBackend({ commit: { status: 503, body: {} } }));
    const user = userEvent.setup();
    mount();
    await chooseAndUpload(user);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(await screen.findByRole("button", { name: "Commit" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Commit import" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    await waitFor(() => expect(alert.parentElement).toHaveFocus());
  });

  it("polls a background preview and shows the result", async () => {
    const running = demoJob({ status: "previewing", async: true, rows_total: 1000, rows_done: 0 });
    server.use(
      ...importBackend({
        uploaded: demoJob({ rows_total: 1000 }),
        previewed: running,
        polls: [
          { ...running, rows_done: 600 },
          { ...previewedJob, rows_total: 1000 },
        ],
      }),
    );
    const user = userEvent.setup();
    mount();
    await chooseAndUpload(user);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    const bar = await screen.findByRole("progressbar", { name: "Previewing events.csv" });
    expect(bar.getAttribute("aria-valuetext")).toMatch(/^\d+ of 1000 rows$/);
    expect(
      await screen.findByRole("table", { name: "Rows with errors" }, { timeout: 5000 }),
    ).toBeInTheDocument();
  }, 10_000);
});

describe("ResourceImport progress announcements", () => {
  const Progress = defaultResourceImportSlots.Progress;
  const at = (done: number) =>
    demoJob({ status: "committing", async: true, rows_total: 1000, rows_done: done });

  it("is a progressbar whose live text changes only by the quarter", () => {
    const { rerender } = render(<Progress job={at(100)} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Committing 1,000 rows: 0% done.");
    rerender(<Progress job={at(200)} />);
    expect(status).toHaveTextContent("Committing 1,000 rows: 0% done."); // not re-announced
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    rerender(<Progress job={at(260)} />);
    expect(status).toHaveTextContent("Committing 1,000 rows: 25% done.");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "260 of 1000 rows");
  });
});
