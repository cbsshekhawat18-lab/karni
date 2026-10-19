import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { API_BASE, server } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { ApprovalsBadge } from "./ApprovalsBadge";

describe("ApprovalsBadge", () => {
  it("shows the count the backend answers", async () => {
    renderWithKarni(<ApprovalsBadge />);
    const badge = await screen.findByTestId("approvals-badge");
    expect(badge).toHaveTextContent("2");
    expect(badge).toHaveAttribute("aria-label", "Pending approvals: 2");
  });

  it("renders nothing at zero unless asked", async () => {
    server.use(
      http.get(`${API_BASE}/pending-changes/count/`, () => HttpResponse.json({ pending: 0 })),
    );
    const { unmount, queryClient } = renderWithKarni(<ApprovalsBadge />);
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.queryByTestId("approvals-badge")).toBeNull();
    unmount();
    renderWithKarni(<ApprovalsBadge showZero />);
    expect(await screen.findByTestId("approvals-badge")).toHaveTextContent("0");
  });
});
