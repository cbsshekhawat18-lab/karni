/**
 * AccountPage (registered sections, the person's details) and SignInPage
 * (code or password, then `next`), driven through the AuthContext.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthContext, type AuthContextValue } from "../../auth/provider";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { AccountPage } from "./AccountPage";
import { accountSections, registerAccountSection, unregisterAccountSection } from "./sections";
import { SignInPage, safeNext } from "./SignInPage";

function auth(over: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: { id: 1, email: "ada@example.com", first_name: "Ada", last_name: "Lovelace", roles: [] },
    roles: ["customer"],
    status: "authenticated",
    login: () =>
      Promise.resolve({ ok: true, user: { id: 1, email: "ada@example.com", roles: [] } }),
    logout: vi.fn(() => Promise.resolve()),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
    ...over,
  };
}

function mount(ui: ReactNode, value: AuthContextValue) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>
    </KarniProvider>,
  );
}

describe("AccountPage", () => {
  afterEach(() => {
    unregisterAccountSection("orders");
    unregisterAccountSection("staff-notes");
  });

  it("shows the registered sections in order, then the person's details", () => {
    registerAccountSection({
      key: "orders",
      title: "Your orders",
      order: 10,
      component: () => <p>Order 1001</p>,
    });
    registerAccountSection({
      key: "staff-notes",
      title: "Staff notes",
      roles: ["shop-staff"],
      component: () => <p>Notes</p>,
    });
    expect(accountSections().map((section) => section.key)).toEqual(["orders", "staff-notes"]);
    mount(<AccountPage />, auth());
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Your orders", "Your details"]); // not a staff role
    expect(screen.getByText("Order 1001")).toBeInTheDocument();
    expect(screen.getByLabelText("First name")).toHaveValue("Ada");
    expect(screen.getByText("Email: ada@example.com")).toBeInTheDocument();
  });

  it("signs the person out", async () => {
    const value = auth();
    mount(<AccountPage details={false} />, value);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(value.logout).toHaveBeenCalled();
    expect(screen.queryByText("Your details")).not.toBeInTheDocument();
  });
});

describe("SignInPage", () => {
  it("offers a code (which opens an account) and a password, with a notice", () => {
    mount(
      <SignInPage notice={<p>Demo: customer@example.com</p>} />,
      auth({ status: "anonymous", user: null, roles: [] }),
    );
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Demo: customer@example.com")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Email me a code" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText(/The code opens your account too/)).toBeInTheDocument();
  });

  it("goes to next once signed in, never to another site", async () => {
    const navigate = vi.fn();
    mount(<SignInPage next="/checkout" navigate={navigate} />, auth());
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/checkout"));
    expect(safeNext("//evil.example.com", "/account")).toBe("/account");
    expect(safeNext("https://evil.example.com")).toBe("/");
    expect(safeNext(null, "/account")).toBe("/account");
  });
});
