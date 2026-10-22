/**
 * <LoginForm> failures through the real AuthProvider against msw: wrong
 * credentials, throttling, a refused field, a server error and a dropped
 * connection each read differently; the message is announced and wired to
 * the fields; focus and the typed email survive.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server, TEST_USER } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { LoginForm, type LoginFormProps } from "./LoginForm";
import { AuthProvider } from "./provider";
import { createMemoryTokenStorage } from "./storage";

const BASE = "http://karni.test/api";

function mount(props: LoginFormProps = {}) {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthProvider mode="jwt" tokenStorage={createMemoryTokenStorage()}>
        <LoginForm {...props} />
      </AuthProvider>
    </KarniProvider>,
  );
}

async function signIn(email: string, password: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

function answerLogin(response: () => Response | Promise<Response>): void {
  server.use(http.post("*/api/auth/login/", response));
}

afterEach(() => {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => true });
});

describe("LoginForm failures", () => {
  it("wrong credentials: says so, marks both fields, keeps the email, clears and focuses the password", async () => {
    mount();
    await signIn("ada@example.com", "wrong-pass");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That email and password do not match");
    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    for (const field of [email, password]) {
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveClass("border-destructive");
      expect(field).toHaveAttribute("aria-describedby", alert.id);
      expect(field).toHaveAccessibleDescription(expect.stringContaining("do not match"));
    }
    expect(email).toHaveValue("ada@example.com");
    expect(password).toHaveValue("");
    await waitFor(() => expect(password).toHaveFocus());
  });

  it("announces the same failure again on the next attempt", async () => {
    mount();
    await signIn("ada@example.com", "wrong-pass");
    const first = await screen.findByRole("alert");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Password"), "still-wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBe(first));
    expect(screen.getByRole("alert")).toHaveTextContent("do not match");
  });

  it("throttled: says how long to wait, without blaming the credentials", async () => {
    answerLogin(() =>
      HttpResponse.json(
        { detail: "Request was throttled. Expected available in 42 seconds." },
        { status: 429 },
      ),
    );
    mount();
    await signIn("ada@example.com", "secret-pass");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Too many sign-in attempts");
    expect(alert).toHaveTextContent("Wait 42 seconds, then try again.");
    expect(alert).not.toHaveTextContent("do not match");
    expect(alert).not.toHaveTextContent("429");
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("Password")).toHaveValue("secret-pass");
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toHaveFocus());
  });

  it("a refused field: shows the backend's message and focuses the email", async () => {
    answerLogin(() =>
      HttpResponse.json({ email: ["Enter a valid email address."] }, { status: 400 }),
    );
    mount();
    await signIn("ada@example.com", "secret-pass");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Check your email and password");
    expect(alert).toHaveTextContent("Enter a valid email address.");
    await waitFor(() => expect(screen.getByLabelText("Email")).toHaveFocus());
  });

  it("a server error: plain words, never the status or the body", async () => {
    answerLogin(() =>
      HttpResponse.json({ detail: "Traceback (most recent call last)" }, { status: 500 }),
    );
    mount();
    await signIn("ada@example.com", "secret-pass");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).not.toHaveTextContent(/500|Traceback|do not match/);
    expect(screen.getByLabelText("Password")).toHaveValue("secret-pass");
  });

  it("a network failure: says the server could not be reached, or that the browser is offline", async () => {
    answerLogin(() => HttpResponse.error());
    mount();
    await signIn("ada@example.com", "secret-pass");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the server");

    Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => false });
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("You're offline"));
  });
});

describe("LoginForm submit and focus", () => {
  it("submits through a PendingButton and signs in", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("*/api/auth/login/", async () => {
        await gate;
        await delay(1);
        return HttpResponse.json({ access: "a1", refresh: "r1" });
      }),
      http.get("*/api/auth/me/", () =>
        HttpResponse.json({ id: TEST_USER.id, email: TEST_USER.email, roles: [] }),
      ),
    );
    const onSuccess = vi.fn();
    mount({ onSuccess });
    await signIn(TEST_USER.email, TEST_USER.password);
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Signing in…")).toBeInTheDocument();
    release();
    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ email: TEST_USER.email })),
    );
  });

  it("focuses the email when it appears, unless told not to", () => {
    mount();
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("leaves the focus alone with autoFocus={false}", () => {
    mount({ autoFocus: false });
    expect(screen.getByLabelText("Email")).not.toHaveFocus();
  });

  it("renders a project's Error slot with the worded failure and the id the fields point at", async () => {
    mount({
      slots: {
        Error: ({ id, described }) => (
          <p id={id} role="alert">
            custom: {described.title}
          </p>
        ),
      },
    });
    await signIn("ada@example.com", "wrong-pass");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("custom: That email and password do not match");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-describedby", alert.id);
  });
});
