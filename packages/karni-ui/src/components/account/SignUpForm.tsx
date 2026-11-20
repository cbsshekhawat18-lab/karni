/**
 * Experimental. `<SignUpForm>`: open an account with an email and a
 * password (`POST <authBasePath>/register/`, karni.accounts).
 *
 * The server sends the verification email. When it signs the new account in
 * at once (`KARNI_ACCOUNTS_AUTO_LOGIN`), the form adopts the tokens (JWT
 * mode) or re-reads the session, and `onSignedUp` runs. Otherwise it says
 * to open the email. A project that closed sign-up
 * (`KARNI_ACCOUNTS_REGISTRATION = False`) answers 404: the form says so and
 * offers the code sign-in instead, which can still open an account when
 * `KARNI_EMAIL_OTP_SIGNUP` lets it.
 */
import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { useAuth } from "../../auth/provider";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { PendingButton } from "../../states/PendingButton";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";

export interface SignUpFormProps {
  /** Where the auth endpoints are (default "/auth", as `AuthProvider`'s `authBasePath`). */
  authBasePath?: string;
  /** Runs once the new account is signed in. */
  onSignedUp?: () => void;
}

interface Registered {
  access?: string;
  refresh?: string;
}

function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof KarniApiError) || typeof error.data !== "object" || error.data === null) {
    return {};
  }
  const found: Record<string, string> = {};
  for (const [name, value] of Object.entries(error.data as Record<string, unknown>)) {
    found[name] = Array.isArray(value) ? value.map(String).join(" ") : String(value);
  }
  return found;
}

/** Experimental. An account opened with an email and a password. */
export function SignUpForm({
  authBasePath = "/auth",
  onSignedUp,
}: SignUpFormProps): React.ReactElement {
  const client = useKarniClient();
  const { adoptTokens, refresh } = useAuth();
  const ids = { email: React.useId(), password: React.useId(), name: React.useId() };
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [done, setDone] = React.useState(false);
  const register = useMutation({
    mutationFn: () => {
      const [first = "", ...rest] = name.trim().split(/\s+/);
      return client.request<Registered>(`${authBasePath.replace(/\/+$/, "")}/register/`, {
        method: "POST",
        body: { email, password, first_name: first, last_name: rest.join(" ") },
      });
    },
    onSuccess: async (data) => {
      if (data.access && data.refresh) {
        await adoptTokens(data.access, data.refresh);
        onSignedUp?.();
        return;
      }
      await refresh();
      setDone(true);
    },
  });
  const errors = fieldErrors(register.error);
  const closed = register.error instanceof KarniApiError && register.error.status === 404;
  if (done) {
    return (
      <p role="status" className="text-sm">
        Your account is open. We sent a link to {email}: open it to verify your email, then sign in.
      </p>
    );
  }
  if (closed) {
    return (
      <p role="alert" className="text-sm">
        This project does not open accounts with a password. Use “Email me a code”: the code opens
        an account when sign-up by code is on.
      </p>
    );
  }
  const general =
    register.isError && Object.keys(errors).length === 0
      ? "Your account was not opened. Try again."
      : (errors["non_field_errors"] ?? errors["detail"]);
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        register.mutate();
      }}
    >
      <div className="space-y-1">
        <Label htmlFor={ids.name}>Your name</Label>
        <Input
          id={ids.name}
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={ids.email}>Email</Label>
        <Input
          id={ids.email}
          type="email"
          autoComplete="email"
          required
          value={email}
          aria-invalid={errors["email"] !== undefined || undefined}
          aria-describedby={errors["email"] !== undefined ? `${ids.email}-error` : undefined}
          onChange={(event) => setEmail(event.target.value)}
        />
        {errors["email"] !== undefined ? (
          <p id={`${ids.email}-error`} role="alert" className="text-sm text-destructive">
            {errors["email"]}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <Label htmlFor={ids.password}>Password</Label>
        <Input
          id={ids.password}
          type="password"
          autoComplete="new-password"
          required
          value={password}
          aria-invalid={errors["password"] !== undefined || undefined}
          aria-describedby={errors["password"] !== undefined ? `${ids.password}-error` : undefined}
          onChange={(event) => setPassword(event.target.value)}
        />
        {errors["password"] !== undefined ? (
          <p id={`${ids.password}-error`} role="alert" className="text-sm text-destructive">
            {errors["password"]}
          </p>
        ) : null}
      </div>
      {general !== undefined ? (
        <p role="alert" className="text-sm text-destructive">
          {general}
        </p>
      ) : null}
      <PendingButton type="submit" pending={register.isPending} pendingLabel="Opening…">
        Open an account
      </PendingButton>
    </form>
  );
}
