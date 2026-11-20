/** DemoNotice and DemoSignInPrompt: the demo accounts from GET /demo/, and nothing otherwise. */
import { QueryClient } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../tests/msw/server";
import { AuthGuard } from "../auth/AuthGuard";
import { AuthContext, type AuthContextValue } from "../auth/provider";
import { karniKeys } from "../hooks/keys";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { DemoNotice, DemoSignInPrompt } from "./DemoNotice";
import { useDemo, type DemoInfo } from "./useDemo";

const BASE = "http://karni.test/api";
const DEMO: DemoInfo = {
  enabled: true,
  accounts: [
    {
      login: "demo@example.com",
      password: "karni-password",
      label: "Staff",
      can: "Manage products and orders.",
      roles: ["staff"],
    },
    {
      login: "customer@example.com",
      password: "karni-password",
      label: "Customer",
      can: "",
      roles: ["customer"],
    },
  ],
  reset_hours: 24,
  next_reset: null,
  admin_url: "/admin/",
};

function setup(status: AuthContextValue["status"] = "anonymous") {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = {
    status,
    user: null,
    roles: [],
    login: () => Promise.resolve({ ok: false }),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
  } as unknown as AuthContextValue;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
    </KarniProvider>
  );
  return { queryClient, wrapper };
}

function serve(body: DemoInfo | null, calls?: { count: number }) {
  server.use(
    http.get(`${BASE}/demo/`, () => {
      if (calls) calls.count += 1;
      return body === null
        ? HttpResponse.json({ code: "E954", detail: "off" }, { status: 404 })
        : HttpResponse.json(body);
    }),
  );
}

describe("useDemo", () => {
  it("reads GET /demo/ and caches it under karniKeys.demo()", async () => {
    const calls = { count: 0 };
    serve(DEMO, calls);
    const { wrapper, queryClient } = setup();
    const { result } = renderHook(() => useDemo(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(DEMO));
    expect(queryClient.getQueryData(karniKeys.demo())).toEqual(DEMO);
    expect(calls.count).toBe(1);
  });

  it("does not retry a 404: a server that is not a demo has no data", async () => {
    const calls = { count: 0 };
    serve(null, calls);
    const { wrapper } = setup();
    const { result } = renderHook(() => useDemo(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(calls.count).toBe(1);
  });
});

describe("DemoNotice", () => {
  it("lists every account with its password and what it can do", async () => {
    serve(DEMO);
    const { wrapper } = setup();
    render(<DemoNotice />, { wrapper });

    expect(await screen.findByText("This is a demo")).toBeInTheDocument();
    expect(screen.getByText("Staff")).toBeInTheDocument();
    expect(screen.getByText("demo@example.com")).toBeInTheDocument();
    expect(screen.getByText("Manage products and orders.")).toBeInTheDocument();
    expect(screen.getByText("customer@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("karni-password")).toHaveLength(2);
    expect(screen.getByText(/every 24 hours/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "admin" })).toHaveAttribute("href", "/admin/");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders nothing for a server that is not a demo", async () => {
    serve(null);
    const { wrapper, queryClient } = setup();
    const { container } = render(<DemoNotice />, { wrapper });
    await waitFor(() => expect(queryClient.getQueryState(karniKeys.demo())?.status).toBe("error"));
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onPick with the chosen account", async () => {
    serve(DEMO);
    const onPick = vi.fn();
    const { wrapper } = setup();
    render(<DemoNotice onPick={onPick} />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Use the Customer account" }));
    expect(onPick).toHaveBeenCalledWith(DEMO.accounts[1]);
  });

  it("takes another body in its Notice prop", async () => {
    serve(DEMO);
    const { wrapper } = setup();
    render(<DemoNotice Notice={({ demo }) => <p>{demo.accounts.length} logins</p>} />, { wrapper });
    expect(await screen.findByText("2 logins")).toBeInTheDocument();
  });
});

describe("DemoSignInPrompt", () => {
  it("puts the notice above Karni's sign-in prompt inside AuthGuard", async () => {
    serve(DEMO);
    const { wrapper } = setup("anonymous");
    render(
      <AuthGuard explain slots={{ Anonymous: DemoSignInPrompt }}>
        <p>secret</p>
      </AuthGuard>,
      { wrapper },
    );

    expect(await screen.findByText("This is a demo")).toBeInTheDocument();
    expect(screen.getByText("Sign in to continue")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("is Karni's prompt alone when the server is not a demo", async () => {
    serve(null);
    const { wrapper, queryClient } = setup("anonymous");
    render(
      <AuthGuard explain slots={{ Anonymous: DemoSignInPrompt }}>
        <p>secret</p>
      </AuthGuard>,
      { wrapper },
    );
    await waitFor(() => expect(queryClient.getQueryState(karniKeys.demo())?.status).toBe("error"));
    expect(screen.getByText("Sign in to continue")).toBeInTheDocument();
    expect(screen.queryByText("This is a demo")).not.toBeInTheDocument();
  });
});
