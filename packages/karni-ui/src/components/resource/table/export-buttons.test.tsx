import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, type Mock } from "vitest";
import { downloadResourceExport } from "../../../hooks/useResourceImport";
import { ExportButtons } from "./ExportButtons";

vi.mock("../../../hooks/useResourceImport", () => ({ downloadResourceExport: vi.fn() }));
const fakeClient = { baseUrl: "", schemaUrl: "/api/schema/" };
vi.mock("../../../schema/provider", () => ({ useKarniClient: () => fakeClient }));

const mockDownload = downloadResourceExport as unknown as Mock;

describe("ExportButtons", () => {
  it("downloads the table's current query in the chosen format", async () => {
    mockDownload.mockResolvedValue("events.csv");
    const params = { search: "gig", ordering: "-starts_at", filters: { status: "published" } };
    render(<ExportButtons resource="events" params={params} formats={["csv", "xlsx"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Export as XLSX" }));
    expect(mockDownload).toHaveBeenCalledWith(fakeClient, "events", params, "xlsx");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Export as XLSX" })).toBeEnabled(),
    );
  });

  it("shows the backend's refusal", async () => {
    const error = Object.assign(new Error("too big"), {
      data: { detail: "E803: narrow the filters" },
    });
    mockDownload.mockRejectedValue(error);
    render(<ExportButtons resource="events" params={{}} formats={["csv"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Export as CSV" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("E803: narrow the filters"),
    );
  });
});
