// The app shell of the shop. A storefront page (staticData area "store" in routes.tsx)
// shows in the shop's own header and footer, to visitors too when it is public. The
// home page is the staff's dashboard for staff and the storefront for everyone else.
// Every other page is the back office: @karni/ui's Layout with the menu from the server
// (navigation in karni.yaml), for staff only. The terms of sale are a customer's: only
// checkout asks for them. The cart, checkout and order pages are
// karni-commerce's (@karni/commerce-ui), told here how to navigate.
import { CommerceProvider } from "@karni/commerce-ui";
import {
  AuthGuard,
  Button,
  Layout,
  PermissionDenied,
  ThemeToggle,
  useAuth,
} from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { registerShop } from "./shop/register";
import { StoreLayout, SHOP_NAME } from "./shop/StoreLayout";
import { usePerson } from "./shop/staff";

registerShop();

const PATHS = { browse: "/shop/products" };

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
          <Button
            variant="ghost"
            className="w-full justify-start"
            onClick={() => router.history.push("/shop")}
          >
            Storefront
          </Button>
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
          <Outlet />
        ) : person === "loading" ? null : (
          <PermissionDenied description="The back office is for the shop's staff." />
        )}
      </AuthGuard>
    </Layout>
  );
}

export default function AppLayout() {
  const router = useRouter();
  const person = usePerson();
  const navigate = useCallback(
    (to: string) => router.history.push(to),
    [router],
  );
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const route = useRouterState({
    select: (state) => state.matches.at(-1)?.staticData,
  });
  const home = pathname === "/";
  const store = route?.area === "store" || (home && person !== "staff");
  return (
    <CommerceProvider navigate={navigate} paths={PATHS}>
      {!store ? (
        <BackOffice />
      ) : (
        <StoreLayout>
          {route?.public === true || home ? (
            <Outlet />
          ) : (
            <AuthGuard explain>
              <Outlet />
            </AuthGuard>
          )}
        </StoreLayout>
      )}
    </CommerceProvider>
  );
}
