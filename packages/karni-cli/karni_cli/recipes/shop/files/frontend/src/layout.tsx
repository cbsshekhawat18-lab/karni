// The app shell of the shop. A storefront page (staticData area "store" in routes.tsx, and
// the home page) shows in the shop's own header and footer, to visitors too when it is
// public. Every other page is the back office: @karni/ui's Layout with the menu from the
// server (navigation in karni.yaml), for staff only. A signed-in customer who opens one is
// told it is not for them.
import {
  AuthGuard,
  Button,
  Layout,
  PermissionDenied,
  TermsGate,
  ThemeToggle,
  useAuth,
} from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { StoreLayout, SHOP_NAME } from "./store/StoreLayout";
import { usePerson } from "./store/staff";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** "store": the page shows in the storefront's header and footer. */
    area?: string;
  }
}

function BackOffice() {
  const router = useRouter();
  const { status, logout } = useAuth();
  const person = usePerson();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [pathname]);
  return (
    <Layout
      navSource="server"
      pathname={pathname}
      navItems={[{ label: "Storefront", href: "/" }]}
      mobileNavOpen={navOpen}
      onMobileNavOpenChange={setNavOpen}
      sidebarHeader={
        <span className="flex items-center gap-2 px-3 text-lg font-semibold">
          <span aria-hidden="true" className="h-6 w-6 rounded-md bg-primary" />
          {SHOP_NAME}
        </span>
      }
      sidebarFooter={
        <div className="space-y-1">
          {status === "authenticated" ? (
            <Button
              variant="ghost"
              className="w-full justify-start"
              onClick={() => void logout()}
            >
              Sign out
            </Button>
          ) : null}
          <ThemeToggle className="mx-3" />
        </div>
      }
      renderNavItem={(item, { defaultNode }) => (
        <span
          className="contents"
          onClickCapture={(event) => {
            event.preventDefault();
            router.history.push(item.href);
          }}
        >
          {defaultNode}
        </span>
      )}
    >
      <AuthGuard explain>
        {person === "staff" ? (
          <TermsGate page={false}>
            <Outlet />
          </TermsGate>
        ) : person === "loading" ? null : (
          <PermissionDenied description="The back office is for the shop's staff." />
        )}
      </AuthGuard>
    </Layout>
  );
}

export default function AppLayout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const route = useRouterState({
    select: (state) => state.matches.at(-1)?.staticData,
  });
  const store = pathname === "/" || route?.area === "store";
  if (!store) return <BackOffice />;
  return (
    <StoreLayout>
      {route?.public === true || pathname === "/" ? (
        <Outlet />
      ) : (
        <AuthGuard explain>
          <Outlet />
        </AuthGuard>
      )}
    </StoreLayout>
  );
}
