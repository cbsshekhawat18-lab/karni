import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi, type Mock } from "vitest";
import {
  useImportActions,
  useImportDescribe,
  useImportJob,
  type ImportActions,
  type ImportDescription,
  type ImportJob,
} from "../../../hooks/useResourceImport";
import { ResourceImport } from "./ResourceImport";

vi.mock("../../../hooks/useResourceImport", async () => {
  const actual = await vi.importActual<typeof import("../../../hooks/useResourceImport")>(
    "../../../hooks/useResourceImport",
  );
  return {
    ...actual,
    useImportDescribe: vi.fn(),
    useImportJob: vi.fn(),
    useImportActions: vi.fn(),
    downloadImportTemplate: vi.fn(() => Promise.resolve("t.xlsx")),
  };
});
vi.mock("../../../schema/provider", () => ({
  useKarniClient: () => ({ baseUrl: "", schemaUrl: "/api/schema/" }),
}));

const mockDescribe = useImportDescribe as unknown as Mock;
const mockJob = useImportJob as unknown as Mock;
const mockActions = useImportActions as unknown as Mock;

const description: ImportDescription = {
  fields: [
    {
      name: "title",
      label: "Title",
      kind: "text",
      required: true,
      readable: true,
      writable: true,
      choices: [],
      target: null,
      lookup: null,
      help: "",
      key: false,
    },
    {
      name: "venue",
      label: "Venue",
      kind: "relation",
      required: false,
      readable: true,
      writable: true,
      choices: [],
      target: "events.venue",
      lookup: "name",
      help: "",
      key: false,
    },
  ],
  mapping: {},
  inline_rows: 500,
  max_rows: 100000,
  key: null,
};

function job(partial: Partial<ImportJob>): ImportJob {
  return {
    id: "job-1",
    model: "events.event",
    status: "uploaded",
    file_name: "events.csv",
    format: "csv",
    columns: ["Title", "Where"],
    mapping: { Title: "title", Where: "" },
    rows_total: 2,
    rows_done: 0,
    async: false,
    result: null,
    problems: [],
    error: null,
    batch: null,
    created_at: null,
    ...partial,
  };
}

function query<T>(partial: Partial<UseQueryResult<T>>): UseQueryResult<T> {
  return { isPending: false, error: null, data: undefined, ...partial } as UseQueryResult<T>;
}

function mutation<TData, TVars>(): UseMutationResult<TData, unknown, TVars> & { mutate: Mock } {
  return { mutate: vi.fn(), isPending: false, error: null } as unknown as UseMutationResult<
    TData,
    unknown,
    TVars
  > & { mutate: Mock };
}

function actions(): ImportActions & {
  upload: { mutate: Mock };
  preview: { mutate: Mock };
  commit: { mutate: Mock };
} {
  return { upload: mutation(), preview: mutation(), commit: mutation() };
}

describe("ResourceImport", () => {
  it("starts with the upload form and the template links", () => {
    mockDescribe.mockReturnValue(query({ data: description }));
    mockJob.mockReturnValue(query({ data: undefined }));
    const api = actions();
    mockActions.mockReturnValue(api);
    render(<ResourceImport resource="events" />);
    expect(screen.getByLabelText("File to import")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download template (XLSX)" })).toBeInTheDocument();
    fireEvent.submit(
      screen.getByRole("button", { name: "Upload" }).closest("form") as HTMLFormElement,
    );
    expect(api.upload.mutate).not.toHaveBeenCalled(); // no file chosen
  });

  it("maps columns to fields and previews with the mapping", () => {
    mockDescribe.mockReturnValue(query({ data: description }));
    mockJob.mockReturnValue(query({ data: job({ status: "uploaded" }) }));
    const api = actions();
    mockActions.mockReturnValue(api);
    render(<ResourceImport resource="events" />);
    const table = screen.getByRole("table", { name: "Column mapping" });
    expect(within(table).getByText("Title")).toBeInTheDocument();
    expect(within(table).getByText("Where")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(api.preview.mutate).toHaveBeenCalledWith({
      jobId: "job-1",
      mapping: { Title: "title", Where: "" },
    });
  });

  it("shows the preview's counts and problems, then commits", () => {
    mockDescribe.mockReturnValue(query({ data: description }));
    mockJob.mockReturnValue(
      query({
        data: job({
          status: "previewed",
          result: { rows_total: 2, created: 1, updated: 0, unchanged: 0, errors: 1, skipped: 1 },
          problems: [{ row: 3, field: "venue", message: "no venue with name 'Nowhere'" }],
        }),
      }),
    );
    const api = actions();
    mockActions.mockReturnValue(api);
    render(<ResourceImport resource="events" />);
    expect(screen.getByTestId("import-stats")).toHaveTextContent("Created1");
    const problems = screen.getByRole("table", { name: "Rows with errors" });
    expect(within(problems).getByText("no venue with name 'Nowhere'")).toBeInTheDocument();
    expect(within(problems).getByText("3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Commit" }));
    expect(api.commit.mutate).toHaveBeenCalledWith("job-1");
  });

  it("shows progress while the backend works and calls onDone at the end", () => {
    mockDescribe.mockReturnValue(query({ data: description }));
    mockJob.mockReturnValue(
      query({ data: job({ status: "committing", rows_total: 1000, rows_done: 250, async: true }) }),
    );
    mockActions.mockReturnValue(actions());
    const { unmount } = render(<ResourceImport resource="events" />);
    expect(screen.getByRole("status")).toHaveTextContent("Committing… 250 / 1000 rows");
    unmount();
    const onDone = vi.fn();
    mockJob.mockReturnValue(
      query({
        data: job({
          status: "done",
          result: { rows_total: 2, created: 2, updated: 0, unchanged: 0, errors: 0, skipped: 0 },
        }),
      }),
    );
    render(<ResourceImport resource="events" onDone={onDone} />);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Import another file" })).toBeInTheDocument();
  });
});
