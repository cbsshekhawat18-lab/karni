import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { API_BASE, decisionCalls, server } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { ApprovalsQueue } from "./ApprovalsQueue";

describe("ApprovalsQueue", () => {
  it("lists pending changes with their diff, maker and progress", async () => {
    renderWithKarni(<ApprovalsQueue />);
    const list = await screen.findByRole("list", { name: "Pending changes" });
    const items = within(list)
      .getAllByRole("listitem")
      .filter((item) => item.dataset["action"]);
    expect(items).toHaveLength(2);
    const [first, second] = items;
    if (first === undefined || second === undefined) throw new Error("two items expected");
    expect(within(first).getByText("Invoice INV-1")).toBeInTheDocument();
    expect(within(first).getByText("maker@example.com", { exact: false })).toBeInTheDocument();
    expect(within(first).getByText("20.00")).toBeInTheDocument();
    expect(within(second).getByText("1/2 approvals", { exact: false })).toBeInTheDocument();
    expect(within(second).getByText("Approved by first@example.com: fine")).toBeInTheDocument();
  });

  it("decides with a reason and reports the backend's refusal", async () => {
    const onDecided = vi.fn();
    renderWithKarni(<ApprovalsQueue onDecided={onDecided} />);
    await screen.findByRole("list", { name: "Pending changes" });
    fireEvent.change(screen.getByLabelText("Reason for Invoice INV-1"), {
      target: { value: "looks right" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0] as HTMLElement);
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
    expect(decisionCalls).toEqual([
      { id: "pc-1", verdict: "approve", body: { reason: "looks right" } },
    ]);
    expect(onDecided.mock.calls[0]?.[0]).toMatchObject({ id: "pc-1", status: "approved" });

    server.use(
      http.post(`${API_BASE}/pending-changes/:id/reject/`, () =>
        HttpResponse.json({ detail: "APR002: the maker cannot be the checker." }, { status: 403 }),
      ),
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[1] as HTMLElement);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "APR002: the maker cannot be the checker.",
      ),
    );
  });

  it("shows the empty state when nothing is pending", async () => {
    server.use(
      http.get(`${API_BASE}/pending-changes/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithKarni(<ApprovalsQueue empty="All clear" />);
    expect(await screen.findByText("All clear")).toBeInTheDocument();
  });
});
