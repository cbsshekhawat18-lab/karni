import {
  AuthProvider,
  KarniProvider,
  createKarniClient,
  createMemoryTokenStorage,
} from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { API_BASE, state } from "../tests/msw/server";
import { ImpersonationBanner } from "./ImpersonationBanner";

function renderBanner(props: { onStopped?: () => void } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const client = createKarniClient({ baseUrl: API_BASE });
  const storage = createMemoryTokenStorage();
  storage.set("target-refresh");
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={storage}>
        <ImpersonationBanner poll={false} {...props} />
      </AuthProvider>
    </KarniProvider>,
  );
}

describe("ImpersonationBanner", () => {
  it("names both identities and the time left", async () => {
    renderBanner();
    const banner = await screen.findByTestId("impersonation-banner");
    expect(banner).toHaveTextContent("You are acting as customer@example.com");
    expect(banner).toHaveTextContent("signed in as support@example.com");
    expect(banner).toHaveTextContent(/2[45] minutes left/);
  });

  it("stops with one click and disappears", async () => {
    const onStopped = vi.fn();
    renderBanner({ onStopped });
    await screen.findByTestId("impersonation-banner");
    fireEvent.click(screen.getByRole("button", { name: "Stop impersonating" }));
    await waitFor(() => expect(onStopped).toHaveBeenCalledTimes(1));
    expect(state.stops).toBe(1);
    await waitFor(() => expect(screen.queryByTestId("impersonation-banner")).toBeNull());
  });

  it("renders nothing outside an impersonated session", async () => {
    state.current = null;
    const { container } = renderBanner();
    await waitFor(() =>
      expect(container.querySelector("[data-testid=impersonation-banner]")).toBeNull(),
    );
  });
});
