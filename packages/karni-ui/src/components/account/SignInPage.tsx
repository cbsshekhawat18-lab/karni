/**
 * `/signin`: sign in with a code sent by email (which also
 * opens an account for a new address, when the project lets people sign up
 * that way: `KARNI_EMAIL_OTP_SIGNUP = "open"`), with a password, or open an
 * account with a password (`signUp`, `POST <authBasePath>/register/`).
 *
 * Once signed in, the page goes to `next` (a path of this app: anything else
 * goes to `fallback`). `notice` is a slot above the forms, for example the
 * demo logins.
 */
import { useEffect, type ReactNode } from "react";
import { LoginForm } from "../../auth/LoginForm";
import { OtpLoginForm } from "../../auth/OtpLoginForm";
import { useAuth } from "../../auth/provider";
import { usePageMeta } from "../../hooks/usePageMeta";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";
import { SignUpForm } from "./SignUpForm";

export interface SignInPageProps {
  title?: string;
  siteName?: string;
  /** Where to go once signed in: a path of this app. */
  next?: string | null;
  /** Where to go when `next` is missing or not a path of this app. Default "/". */
  fallback?: string;
  /** How to go there (the router's push). Default: a page load. */
  navigate?: (to: string) => void;
  /** Shown above the forms (the demo logins, a word about privacy). */
  notice?: ReactNode;
  /** Which way first: "code" (default), "password" or "signup". */
  method?: "code" | "password" | "signup";
  /** Offer the code sign-in (needs KARNI_EMAIL_OTP). Default true. */
  code?: boolean;
  /** Offer to open an account with a password (needs KARNI_ACCOUNTS_REGISTRATION). Default true. */
  signUp?: boolean;
  /** Where the auth endpoints are, as `AuthProvider`'s `authBasePath`. Default "/auth". */
  authBasePath?: string;
}

/** `next` when it is a path of this app, else `fallback` (never another site). */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

export function SignInPage({
  title = "Sign in",
  siteName,
  next,
  fallback = "/",
  navigate,
  notice,
  method = "code",
  code = true,
  signUp = true,
  authBasePath = "/auth",
}: SignInPageProps) {
  const { status } = useAuth();
  const target = safeNext(next, fallback);
  usePageMeta({ title, siteName });
  useEffect(() => {
    if (status !== "authenticated") return;
    if (navigate) navigate(target);
    else window.location.assign(target);
  }, [status, navigate, target]);
  return (
    <div className="mx-auto max-w-128 space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {notice}
      {code || signUp ? (
        <Tabs defaultValue={method === "code" && !code ? "password" : method}>
          <TabsList className="flex-wrap">
            {code ? <TabsTrigger value="code">Email me a code</TabsTrigger> : null}
            <TabsTrigger value="password">Password</TabsTrigger>
            {signUp ? <TabsTrigger value="signup">New account</TabsTrigger> : null}
          </TabsList>
          {code ? (
            <TabsContent value="code" className="space-y-2">
              <p className="text-sm text-muted-foreground">
                New here? The code opens your account too. No password to remember.
              </p>
              <OtpLoginForm title={null} />
            </TabsContent>
          ) : null}
          <TabsContent value="password">
            <LoginForm title={null} />
          </TabsContent>
          {signUp ? (
            <TabsContent value="signup">
              <SignUpForm authBasePath={authBasePath} />
            </TabsContent>
          ) : null}
        </Tabs>
      ) : (
        <LoginForm title={null} />
      )}
    </div>
  );
}
