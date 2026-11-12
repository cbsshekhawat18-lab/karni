// Sign in: with a code sent by email (no password to remember), or with a password. A person
// who signs in for the first time with a code gets an account and the customer role.
import {
  LoginForm,
  OtpLoginForm,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useAuth,
  usePageMeta,
} from "@karni/ui";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";
import { useSearchValues } from "./search";
import { SHOP_NAME } from "./StoreLayout";

export function SignIn() {
  const router = useRouter();
  const { status } = useAuth();
  const next = useSearchValues().next ?? "/account";
  const safe =
    next.startsWith("/") && !next.startsWith("//") ? next : "/account";
  usePageMeta({ title: "Sign in", siteName: SHOP_NAME });
  useEffect(() => {
    if (status === "authenticated") router.history.push(safe);
  }, [status, router, safe]);
  return (
    <div className="mx-auto max-w-md space-y-4">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <Tabs defaultValue="code">
        <TabsList>
          <TabsTrigger value="code">Email me a code</TabsTrigger>
          <TabsTrigger value="password">Password</TabsTrigger>
        </TabsList>
        <TabsContent value="code">
          <OtpLoginForm title={null} />
        </TabsContent>
        <TabsContent value="password">
          <LoginForm title={null} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
