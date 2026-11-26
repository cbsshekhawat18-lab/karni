/**
 * `<FamilyLayout>`: the one app shell of a project of parts.
 *
 * A project that holds a shop, a CRM and a booking app has one layout, not
 * one per part. Each page shows in one of two frames:
 *
 * - **The storefront** (`<Storefront>`): the site's header and footer, for
 *   visitors too. Its links are the `public` menu (`GET /navigation/?menu=public`)
 *   and, once signed in, the `account` menu. A route with
 *   `staticData: { area: "store" }` shows in it.
 * - **The back office**: `<Layout>` with the `app` menu in the sidebar (the
 *   entries each person's grants open), the search box, the inbox bell and
 *   the account menu in the top bar.
 *
 * The home (`/`) and a route with `area: "family"` (`/orders`, where a
 * customer reads their own orders and staff read every order) show in the
 * back office to staff and in the storefront to everyone else, when the
 * project has a storefront (a part registered a public home). Every page but
 * a public one sits behind `<AuthGuard explain>`.
 *
 * It takes the router through props (`pathname`, `navigate`, the route's
 * `area` and `isPublic`), so the build's glue file stays a few lines.
 *
 * Escape hatch: `slots` replaces the Storefront or the BackOffice frame,
 * `audience` fixes who is looking, and a project writes its own layout.tsx
 * (the build then leaves it alone).
 */
import * as React from "react";
import { AuthGuard, type AuthGuardSlots } from "../../auth/AuthGuard";
import { useAuth } from "../../auth/provider";
import { TermsGate } from "../../auth/TermsGate";
import { useNavigation, type NavigationItem } from "../../hooks/useNavigation";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { ThemeToggle } from "../../theme/theme";
import { GlobalSearch } from "../global-search/global-search";
import { Layout, type LayoutNavLinkProps } from "../layout/layout";
import { Button } from "../primitives/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../primitives/dropdown-menu";
import { setRecordNavigate } from "../resource/record-links";
import { useAudience, useBusiness, useSiteName, type Audience } from "./audience";
import { InboxBell } from "./inbox";
import { publicHome } from "./registry";
import { searchHitHref } from "./search";

registerComponentRole("family-layout", "FamilyLayout");

/** What both frames receive. */
export interface FamilyFrameProps {
  pathname: string;
  navigate: (to: string) => void;
  siteName: string;
  audience: Audience;
  /** Show the inbox bell (karni.notify is installed). */
  inbox: boolean;
  /** Show the search box. */
  search: boolean;
  /** The app's route paths, for where a search hit opens. */
  routes: readonly string[];
  /** The project has a storefront: the back office links to it. */
  storefront: boolean;
  /** More controls in the storefront's header (a mini cart). */
  storeActions?: React.ReactNode;
  /** The terms page, linked in the storefront's footer. */
  termsHref?: string;
  /** The page. */
  children: React.ReactNode;
}

/** The frames a project can replace. */
export interface FamilyLayoutSlots {
  Storefront: React.ComponentType<FamilyFrameProps>;
  BackOffice: React.ComponentType<FamilyFrameProps>;
}

export interface FamilyLayoutProps {
  /** The current route's path (the router's location). */
  pathname: string;
  /** The router's push. */
  navigate: (to: string) => void;
  /** The route's `staticData.area`: "store", "family", or none (the back office). */
  area?: string;
  /** The route shows without signing in (`staticData.public`). */
  isPublic?: boolean;
  /** The business's name (default: Settings, Details, else the page title the app started with). */
  siteName?: string;
  /** The project has a storefront (default: a part registered a public home). */
  storefront?: boolean;
  /** Show the inbox bell. Default false: the build turns it on with karni.notify. */
  inbox?: boolean;
  /** Show the search box. Default true. */
  search?: boolean;
  /** The app's route paths (`Object.keys(router.routesByPath)`), for search links. */
  routes?: readonly string[];
  /** More controls in the storefront's header (the mini cart, with commerce). */
  storeActions?: React.ReactNode;
  /** The terms page, linked in the storefront's footer. */
  termsHref?: string;
  /** Ask for the current terms before any back-office page (KARNI_TERMS without paths). */
  terms?: boolean;
  /** The sign-in guard's slots (`{ Anonymous: DemoSignInPrompt }` in a demo). */
  guardSlots?: Partial<AuthGuardSlots>;
  /** Who is looking (default: from the signed-in person's roles, `useAudience`). */
  audience?: Audience;
  slots?: Partial<FamilyLayoutSlots>;
  children?: React.ReactNode;
}

/** The entries of a named menu the signed-in person sees (empty while loading). */
export function useMenu(menu: string): NavigationItem[] {
  const query = useNavigation({ menu });
  return query.data?.items ?? [];
}

function links(items: readonly NavigationItem[]): NavigationItem[] {
  // A group of a header menu shows its entries in line.
  return items.flatMap((item) => (item.route === null ? links(item.children) : [item]));
}

function AppLink({
  to,
  navigate,
  className,
  children,
  current,
}: {
  to: string;
  navigate: (to: string) => void;
  className?: string;
  children: React.ReactNode;
  current?: boolean;
}): React.ReactElement {
  return (
    <a
      href={to}
      aria-current={current ? "page" : undefined}
      className={cn(
        "rounded-sm underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        current && "underline",
        className,
      )}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

function Brand({ siteName }: { siteName: string }): React.ReactElement {
  const logo = useBusiness().data?.logo;
  return (
    <span className="flex items-center gap-2 text-lg font-semibold">
      {logo ? (
        <img src={logo} alt="" className="h-6 w-auto max-w-24" />
      ) : (
        <span aria-hidden="true" className="h-6 w-6 rounded-md bg-primary" />
      )}
      {siteName}
    </span>
  );
}

function AccountLinks({
  navigate,
  pathname,
  audience,
}: {
  navigate: (to: string) => void;
  pathname: string;
  audience: Audience;
}): React.ReactElement | null {
  const { logout } = useAuth();
  const account = links(useMenu("account"));
  if (audience === "loading") return null;
  if (audience === "visitor") {
    return (
      <AppLink
        to={`/signin?next=${encodeURIComponent(pathname)}`}
        navigate={navigate}
        className="text-sm font-medium"
      >
        Sign in
      </AppLink>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-3 text-sm font-medium">
      {audience === "staff" ? (
        <AppLink to="/" navigate={navigate}>
          Back office
        </AppLink>
      ) : null}
      {account.map((item) => (
        <AppLink
          key={item.route ?? item.label}
          to={item.route ?? "/"}
          navigate={navigate}
          current={item.route === pathname}
        >
          {item.label}
        </AppLink>
      ))}
      {account.some((item) => item.route === "/account") ? null : (
        <AppLink to="/account" navigate={navigate} current={pathname === "/account"}>
          Account
        </AppLink>
      )}
      <Button variant="ghost" size="sm" onClick={() => void logout()}>
        Sign out
      </Button>
    </span>
  );
}

/** The storefront's frame: the site's header (public and account menus) and footer. */
export function Storefront({
  pathname,
  navigate,
  siteName,
  audience,
  inbox,
  storeActions,
  termsHref,
  children,
}: FamilyFrameProps): React.ReactElement {
  const business = useBusiness().data;
  const header = links(useMenu("public"));
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:p-2">
        Skip to content
      </a>
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-[var(--karni-storefront-width)] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <AppLink to="/" navigate={navigate} className="hover:no-underline">
            <Brand siteName={siteName} />
          </AppLink>
          {header.length > 0 ? (
            <nav aria-label="Site" className="flex flex-wrap gap-4 text-sm font-medium">
              {header.map((item) => (
                <AppLink
                  key={item.route ?? item.label}
                  to={item.route ?? "/"}
                  navigate={navigate}
                  current={item.route === pathname}
                >
                  {item.label}
                </AppLink>
              ))}
            </nav>
          ) : null}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <AccountLinks navigate={navigate} pathname={pathname} audience={audience} />
            {inbox && audience !== "visitor" ? <InboxBell navigate={navigate} /> : null}
            {storeActions}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main
        id="main"
        className="mx-auto w-full max-w-[var(--karni-storefront-width)] flex-1 px-4 py-6"
      >
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[var(--karni-storefront-width)] flex-wrap gap-4 px-4 py-6 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{siteName}</span>
          {business?.address ? (
            <span className="whitespace-pre-line">{business.address}</span>
          ) : null}
          {business?.phone ? <span>{business.phone}</span> : null}
          {business?.email ? (
            <a href={`mailto:${business.email}`} className="hover:underline">
              {business.email}
            </a>
          ) : null}
          {termsHref ? (
            <AppLink to={termsHref} navigate={navigate}>
              Terms
            </AppLink>
          ) : null}
        </div>
      </footer>
    </div>
  );
}

function AccountMenu({ navigate }: { navigate: (to: string) => void }): React.ReactElement | null {
  const { status, user, logout } = useAuth();
  const account = links(useMenu("account"));
  if (status !== "authenticated") return null;
  const who = String(user?.email ?? "Account");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Account: ${who}`}>
          {/* A phone's top bar has no room for an address: it says Account. */}
          <span className="hidden max-w-40 truncate sm:inline">{who}</span>
          <span className="sm:hidden">Account</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {account.map((item) => (
          <DropdownMenuItem
            key={item.route ?? item.label}
            onSelect={() => navigate(item.route ?? "/")}
          >
            {item.label}
          </DropdownMenuItem>
        ))}
        {account.some((item) => item.route === "/account") ? null : (
          <DropdownMenuItem onSelect={() => navigate("/account")}>Your account</DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The back office's frame: the app menu, search, the inbox bell and the account menu. */
export function BackOffice({
  pathname,
  navigate,
  siteName,
  inbox,
  search,
  routes,
  storefront,
  children,
}: FamilyFrameProps): React.ReactElement {
  const { status, logout } = useAuth();
  const [navOpen, setNavOpen] = React.useState(false);
  React.useEffect(() => setNavOpen(false), [pathname]);
  const NavLink = React.useCallback(
    ({
      href,
      onClick,
      children: content,
      className,
      "aria-current": current,
    }: LayoutNavLinkProps) => (
      <a
        href={href}
        className={className}
        aria-current={current}
        onClick={(event) => {
          event.preventDefault();
          onClick();
          navigate(href);
        }}
      >
        {content}
      </a>
    ),
    [navigate],
  );
  return (
    <Layout
      navSource="server"
      pathname={pathname}
      mobileNavOpen={navOpen}
      onMobileNavOpenChange={setNavOpen}
      slots={{ NavLink }}
      sidebarHeader={
        <span className="px-3">
          <Brand siteName={siteName} />
        </span>
      }
      sidebarFooter={
        <div className="space-y-1">
          {storefront ? (
            <Button
              variant="ghost"
              className="w-full justify-start"
              onClick={() => navigate(publicHomePath())}
            >
              Storefront
            </Button>
          ) : null}
          {status === "authenticated" ? (
            <Button variant="ghost" className="w-full justify-start" onClick={() => void logout()}>
              Sign out
            </Button>
          ) : null}
          <ThemeToggle className="mx-3" />
        </div>
      }
      header={
        <div className="flex w-full min-w-0 items-center gap-2">
          {search && status === "authenticated" ? (
            <GlobalSearch
              hrefFor={(hit) => searchHitHref(hit, routes)}
              onSelect={(hit) => navigate(searchHitHref(hit, routes))}
              allResultsHref={(query) => `/search?q=${encodeURIComponent(query)}`}
              navigate={navigate}
            />
          ) : null}
          <span className="flex-1" />
          {inbox && status === "authenticated" ? <InboxBell navigate={navigate} /> : null}
          <AccountMenu navigate={navigate} />
        </div>
      }
    >
      {children}
    </Layout>
  );
}

function publicHomePath(): string {
  return publicHome()?.path ?? "/";
}

const SIGN_IN = new Set(["/signin", "/login", "/sign-in"]);

/** Experimental. The app shell of a project of parts: the storefront or the back office per page. */
export function FamilyLayout({
  pathname,
  navigate,
  area,
  isPublic = false,
  siteName,
  storefront,
  inbox = false,
  search = true,
  routes = [],
  storeActions,
  termsHref,
  terms = false,
  guardSlots,
  audience: fixed,
  slots,
  children,
}: FamilyLayoutProps): React.ReactElement {
  const found = useAudience();
  const audience = fixed ?? found;
  const name = useSiteName(siteName);
  React.useEffect(() => setRecordNavigate(navigate), [navigate]);
  const hasStore = storefront ?? publicHome() !== undefined;
  const home = pathname === "/";
  const shared = home || area === "family";
  const store = area === "store" || (shared && hasStore && audience !== "staff");
  const open = isPublic || home || SIGN_IN.has(pathname);
  const Store = slots?.Storefront ?? Storefront;
  const Back = slots?.BackOffice ?? BackOffice;
  const frame: Omit<FamilyFrameProps, "children"> = {
    pathname,
    navigate,
    siteName: name,
    audience,
    inbox,
    search,
    routes,
    storefront: hasStore,
    ...(storeActions !== undefined ? { storeActions } : {}),
    ...(termsHref !== undefined ? { termsHref } : {}),
  };
  const guarded = (page: React.ReactNode, gate: boolean): React.ReactNode =>
    open ? (
      page
    ) : (
      <AuthGuard explain {...(guardSlots !== undefined ? { slots: guardSlots } : {})}>
        {gate ? <TermsGate page={false}>{page}</TermsGate> : page}
      </AuthGuard>
    );
  if (store) return <Store {...frame}>{guarded(children, false)}</Store>;
  return <Back {...frame}>{guarded(children, terms)}</Back>;
}
