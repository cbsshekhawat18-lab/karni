import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { REPORT_BASE, calls, ready, reportState } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { ReportButton } from "./ReportButton";

describe("<ReportButton>", () => {
  it("requests, says it is preparing, then downloads once the file is ready", async () => {
    const save = vi.fn();
    const onReady = vi.fn();
    renderWithKarni(
      <ReportButton
        report="product-sheet"
        objectId={7}
        pollInterval={10}
        save={save}
        onReady={onReady}
      />,
    );
    const button = screen.getByRole("button", { name: "Download PDF" });
    expect(button).toHaveAttribute("data-karni-role", "report-button");
    await userEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0]?.[1]).toBe("product-sheet-7.pdf");
    expect(onReady).toHaveBeenCalledWith(expect.objectContaining({ status: "ready" }));
    expect(calls.downloads).toBe(1);
    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Download PDF"));
    expect(screen.getByRole("button")).not.toBeDisabled();
  });

  it("is busy and disabled while the file renders", async () => {
    server.use(
      http.get(`${REPORT_BASE}status/`, () =>
        HttpResponse.json(reportState({ status: "rendering" })),
      ),
    );
    renderWithKarni(<ReportButton report="product-sheet" objectId={7} pollInterval={10} />);
    await userEvent.click(screen.getByRole("button"));
    const busy = await screen.findByRole("button", { name: "Preparing PDF..." });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
  });

  it("downloads a cached file again on every click", async () => {
    server.use(http.post(REPORT_BASE, () => HttpResponse.json(ready)));
    const save = vi.fn();
    renderWithKarni(<ReportButton report="product-sheet" objectId={7} save={save} />);
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(calls.statuses).toBe(0);
  });

  it("shows the failed label and calls onError when the render fails", async () => {
    server.use(
      http.get(`${REPORT_BASE}status/`, () =>
        HttpResponse.json(reportState({ status: "failed", error: "REPORT007: could not render." })),
      ),
    );
    const onError = vi.fn();
    const save = vi.fn();
    renderWithKarni(
      <ReportButton
        report="product-sheet"
        objectId={7}
        pollInterval={10}
        onError={onError}
        save={save}
        labels={{ failed: "Could not make the PDF" }}
      />,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("button", { name: "Could not make the PDF" })).toBeEnabled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(save).not.toHaveBeenCalled();
  });

  it("calls onError for a refused request (another user's row)", async () => {
    server.use(
      http.post(REPORT_BASE, () => HttpResponse.json({ detail: "Not found." }, { status: 404 })),
    );
    const onError = vi.fn();
    renderWithKarni(<ReportButton report="product-sheet" objectId={7} onError={onError} />);
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button")).toHaveTextContent("Try again");
  });

  it("autoDownload={false} stops once the file is ready", async () => {
    const save = vi.fn();
    const onReady = vi.fn();
    renderWithKarni(
      <ReportButton
        report="product-sheet"
        objectId={7}
        pollInterval={10}
        autoDownload={false}
        save={save}
        onReady={onReady}
      />,
    );
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
    expect(save).not.toHaveBeenCalled();
  });
});
