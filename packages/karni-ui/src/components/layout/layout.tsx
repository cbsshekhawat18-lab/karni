import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { useNavigation } from "../../hooks/useNavigation";
import { KarniMark } from "../brand/karni-mark";
import { Skeleton } from "../primitives/skeleton";
import { navigationEntries } from "./navigation";
import { useRouteFocus, type LayoutRouteFocusOptions } from "./route-focus";

export type { LayoutRouteFocusOptions } from "./route-focus";

registerComponentRole("layout-shell", "Layout");

type IconProps = React.SVGAttributes<SVGSVGElement>;

function MenuIcon(props: IconProps): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
    </svg>
  );
}

function CloseIcon(props: IconProps): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function ChevronIcon(props: IconProps): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

export interface LayoutNavItem {
  /** Visible label of the nav entry. */
  label: React.ReactNode;
  /** Target URL (rendered as a plain <a> by default). */
  href: string;
  /** Optional icon rendered before the label. */
  icon?: React.ReactNode;
  /** Marks the current page (aria-current="page" + active styling). */
  active?: boolean;
  /** React key override when `href` is not unique. */
  key?: string;
}

/**
 * Experimental. A collapsible group of the sidebar nav: a label and the
 * entries under it (links and further groups), with no link of its own.
 */
export interface LayoutNavGroup {
  /** Visible label of the group's button. */
  label: React.ReactNode;
  /** Optional icon rendered before the label. */
  icon?: React.ReactNode;
  /** The entries inside the group, in order. */
  children: readonly LayoutNavEntry[];
  /** Open on the first render. Default: open while it holds the current page. */
  defaultOpen?: boolean;
  /** React key override (default: the index). */
  key?: string;
}

/** A sidebar nav entry: a link (`LayoutNavItem`) or, experimental, a group (`LayoutNavGroup`). */
export type LayoutNavEntry = LayoutNavItem | LayoutNavGroup;

/** Experimental. Whether a nav entry is a group (it has `children`). */
export function isNavGroup(entry: LayoutNavEntry): entry is LayoutNavGroup {
  return "children" in entry && Array.isArray(entry.children);
}

/** Experimental. What the `NavGroup` slot receives. */
export interface LayoutNavGroupProps {
  group: LayoutNavGroup;
  /** Whether the entries show. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** True while an entry inside is the current page. */
  active: boolean;
  /** The id of the element that holds the entries (the button's aria-controls). */
  id: string;
  /** The rendered entries. */
  children: React.ReactNode;
}

/** What the `NavLink` slot receives: the props of the <a> it replaces, plus the item. */
export interface LayoutNavLinkProps {
  item: LayoutNavItem;
  href: string;
  /** The styled class, focus indicator and active state included. */
  className: string;
  "aria-current"?: "page";
  /** Closes the mobile drawer. Call it when the link navigates. */
  onClick: () => void;
  /** The icon and the label. */
  children: React.ReactNode;
}

/** What the `Sidebar` slot (the static sidebar, md and up) receives. */
export interface LayoutSidebarProps {
  /** The `sidebarHeader` (the Karni mark by default), or null. */
  header: React.ReactNode;
  /** The derived nav, or the `sidebar` prop. */
  nav: React.ReactNode;
  /** The `sidebarFooter`, or null. */
  footer: React.ReactNode;
  /** `sidebarClassName`. */
  className?: string;
}

/** What the `MobileDrawer` slot (the sidebar below md) receives. */
export interface LayoutMobileDrawerProps extends LayoutSidebarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The id the menu button's aria-controls names while the drawer is open. */
  id: string;
  /** The menu button: where focus returns when the drawer closes. */
  returnFocusRef: React.RefObject<HTMLButtonElement | null>;
}

/** What the `Header` slot (the top bar) receives. */
export interface LayoutHeaderProps {
  /** The button that opens the drawer below md. Render it, or the drawer cannot open. */
  menuButton: React.ReactNode;
  /** The `header` prop's content. */
  children?: React.ReactNode;
  /** `headerClassName`. */
  className?: string;
}

/** What the `SkipLink` slot receives: the first focusable element of the page. */
export interface LayoutSkipLinkProps {
  /** `#` + the id of <main>. */
  href: string;
  /** Moves focus to <main> without changing the URL (hash routers keep their route). */
  onClick: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  children: React.ReactNode;
}

/** The parts of the shell a project can replace (`slots={{ NavLink: RouterLink }}`). */
export interface LayoutSlots {
  /** The top bar with the menu button and the `header` content. */
  Header: React.ComponentType<LayoutHeaderProps>;
  /** The static sidebar (md and up). The default hides itself below md. */
  Sidebar: React.ComponentType<LayoutSidebarProps>;
  /** Each derived nav link. Replace it with your router's link. */
  NavLink: React.ComponentType<LayoutNavLinkProps>;
  /** The sidebar below md: a modal drawer (focus trapped, Escape closes). */
  MobileDrawer: React.ComponentType<LayoutMobileDrawerProps>;
  /** "Skip to content", visible only while focused. `() => null` removes it. */
  SkipLink: React.ComponentType<LayoutSkipLinkProps>;
  /** Experimental. A collapsible group of the nav: its button and its entries. */
  NavGroup?: React.ComponentType<LayoutNavGroupProps>;
}

export interface LayoutProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Entries of the derived sidebar nav: links, and (experimental) collapsible groups. */
  navItems?: readonly LayoutNavEntry[];
  /**
   * Experimental. Where the nav comes from. `"static"` (the default) renders
   * `navItems`. `"server"` renders the menu `useNavigation()` reads from
   * `GET /navigation/` (Django's `KARNI_NAVIGATION`), filtered by the
   * user's grants, with `navItems` shown if that request fails. It needs
   * `KarniProvider`.
   */
  navSource?: "static" | "server";
  /**
   * Experimental. The current route's path: marks the current page of the
   * server menu. Default: `window.location.pathname`. Pass your router's
   * pathname so the mark follows client-side navigation.
   */
  pathname?: string;
  /** Experimental. Icons by name for the server menu, over `defaultNavIcons`. */
  icons?: Readonly<Record<string, React.ReactNode>>;
  /**
   * Wraps or replaces the default link of one item. `defaultNode` is the
   * link the layout would render. Return it, or your own node (e.g. a
   * TanStack Router <Link> with `className={defaultClassName}`).
   * Prefer the `NavLink` slot, which also closes the mobile drawer.
   */
  renderNavItem?: (
    item: LayoutNavItem,
    defaults: { defaultNode: React.ReactNode; defaultClassName: string },
  ) => React.ReactNode;
  /** Escape hatch: replaces the entire derived nav inside the sidebar. */
  sidebar?: React.ReactNode;
  /**
   * Brand/logo slot pinned to the top of the sidebar. Defaults to the Karni
   * mark (`<KarniMark />`). Pass your own brand, or `null` for no header.
   */
  sidebarHeader?: React.ReactNode;
  /** Slot pinned to the bottom of the sidebar (user menu, logout, …). */
  sidebarFooter?: React.ReactNode;
  /** Header slot, rendered in the top bar next to the mobile menu button. */
  header?: React.ReactNode;
  /** Accessible name of the sidebar navigation (default "Main"). */
  navLabel?: string;
  /** Controlled open state of the mobile drawer (pair with onMobileNavOpenChange). */
  mobileNavOpen?: boolean;
  /** Initial open state of the mobile drawer when uncontrolled. */
  defaultMobileNavOpen?: boolean;
  /** Called when the drawer opens or closes (menu button, Escape, backdrop, a link). */
  onMobileNavOpenChange?: (open: boolean) => void;
  /** Replaces internal pieces of the shell. See LayoutSlots. */
  slots?: Partial<LayoutSlots>;
  /**
   * Focus after a client-side navigation. Default `true`: once the new page
   * is in, focus moves to its `<h1>` (else `<main>`) and a polite live region
   * says the page title. Nothing moves on the first load (a redirect before
   * the user acts included), when only search params change (filters,
   * pagination, sorting), or when something took focus for the page itself
   * (an autofocused field, a control inside `<main>`, a dialog). `false`
   * turns it off. An object keeps it on and sets the route key, the target
   * or the announcement (see LayoutRouteFocusOptions).
   */
  routeFocus?: boolean | LayoutRouteFocusOptions;
  sidebarClassName?: string;
  headerClassName?: string;
  contentClassName?: string;
  children?: React.ReactNode;
}

const NAV_ITEM_CLASS =
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-4 [&_svg]:w-4";
const NAV_ITEM_ACTIVE_CLASS = "bg-accent text-accent-foreground";

const ICON_BUTTON_CLASS =
  "inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The sidebar's inner column, shared by the static sidebar and the drawer. */
function SidebarColumn({ header, nav, footer }: LayoutSidebarProps): React.ReactElement {
  return (
    <>
      {header != null && <div className="mb-4">{header}</div>}
      <div className="flex-1 overflow-y-auto">{nav}</div>
      {footer != null && <div className="mt-4">{footer}</div>}
    </>
  );
}

function DefaultHeader({ menuButton, children, className }: LayoutHeaderProps): React.ReactElement {
  return (
    <header
      className={cn("flex h-14 shrink-0 items-center gap-3 border-b border-border px-4", className)}
    >
      {menuButton}
      {children != null && <div className="flex min-w-0 flex-1 items-center gap-3">{children}</div>}
    </header>
  );
}

function DefaultSidebar(props: LayoutSidebarProps): React.ReactElement {
  return (
    <aside
      className={cn(
        "hidden w-64 shrink-0 flex-col border-r border-border bg-card p-4 md:flex",
        props.className,
      )}
    >
      <SidebarColumn {...props} />
    </aside>
  );
}

function DefaultNavLink(props: LayoutNavLinkProps): React.ReactElement {
  return (
    <a
      href={props.href}
      className={props.className}
      aria-current={props["aria-current"]}
      onClick={props.onClick}
    >
      {props.children}
    </a>
  );
}

function DefaultMobileDrawer({
  open,
  onOpenChange,
  id,
  returnFocusRef,
  className,
  ...column
}: LayoutMobileDrawerProps): React.ReactElement {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          data-testid="karni-layout-backdrop"
          className="fixed inset-0 z-drawer bg-overlay md:hidden"
        />
        <DialogPrimitive.Content
          id={id}
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            // Back to the menu button, even where a click does not focus it (Safari).
            const target = returnFocusRef.current;
            if (target !== null) {
              event.preventDefault();
              target.focus();
            }
          }}
          className={cn(
            "fixed inset-y-0 left-0 z-drawer flex w-64 flex-col border-r border-border bg-card p-4 shadow-lg focus:outline-none md:hidden",
            className,
          )}
        >
          <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
          <div className="mb-2 flex justify-end">
            <DialogPrimitive.Close className={cn(ICON_BUTTON_CLASS, "h-8 w-8")}>
              <CloseIcon className="h-4 w-4" />
              <span className="sr-only">Close navigation</span>
            </DialogPrimitive.Close>
          </div>
          <SidebarColumn {...column} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function DefaultNavGroup({
  group,
  open,
  onOpenChange,
  active,
  id,
  children,
}: LayoutNavGroupProps): React.ReactElement {
  const buttonId = `${id}-button`;
  return (
    <div className="grid gap-1">
      <button
        id={buttonId}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        data-active={active ? "true" : undefined}
        onClick={() => onOpenChange(!open)}
        className={cn(
          NAV_ITEM_CLASS,
          "w-full justify-between text-left",
          active && !open && "text-foreground",
        )}
      >
        <span className="flex min-w-0 items-center gap-3">
          {group.icon != null && <span aria-hidden="true">{group.icon}</span>}
          {group.label}
        </span>
        <ChevronIcon className={cn("shrink-0 transition-transform", open && "rotate-90")} />
      </button>
      <div
        id={id}
        role="group"
        aria-labelledby={buttonId}
        hidden={!open}
        className="ml-4 grid gap-1 border-l border-border pl-2"
      >
        {children}
      </div>
    </div>
  );
}

function holdsActive(entries: readonly LayoutNavEntry[]): boolean {
  return entries.some((entry) =>
    isNavGroup(entry) ? holdsActive(entry.children) : entry.active === true,
  );
}

function GroupEntry({
  group,
  NavGroup,
  children,
}: {
  group: LayoutNavGroup;
  NavGroup: React.ComponentType<LayoutNavGroupProps>;
  children: React.ReactNode;
}): React.ReactElement {
  const active = holdsActive(group.children);
  const [open, setOpen] = React.useState(group.defaultOpen ?? active);
  // Navigating into a closed group opens it, so the current page is in view.
  React.useEffect(() => {
    if (active) setOpen(true);
  }, [active]);
  const id = React.useId();
  return (
    <NavGroup group={group} open={open} onOpenChange={setOpen} active={active} id={id}>
      {children}
    </NavGroup>
  );
}

function currentPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname;
}

/** The server menu: its entries once loaded, placeholders while loading, `fallback` on error. */
function ServerNav({
  pathname,
  icons,
  fallback,
  render,
  navLabel,
}: {
  pathname: string | undefined;
  icons: Readonly<Record<string, React.ReactNode>> | undefined;
  fallback: readonly LayoutNavEntry[];
  render: (entries: readonly LayoutNavEntry[]) => React.ReactNode;
  navLabel: string;
}): React.ReactElement {
  const menu = useNavigation();
  if (menu.isPending) {
    return (
      <nav aria-label={navLabel} aria-busy="true" className="grid gap-2 px-3 py-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-5 w-2/3" />
      </nav>
    );
  }
  const entries =
    menu.data === undefined
      ? fallback
      : navigationEntries(menu.data.items, { pathname: pathname ?? currentPath(), icons });
  return <>{render(entries)}</>;
}

function DefaultSkipLink({ href, onClick, children }: LayoutSkipLinkProps): React.ReactElement {
  return (
    <a
      href={href}
      onClick={onClick}
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-popover focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-md focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {children}
    </a>
  );
}

/** The default pieces of the shell, which you spread to wrap one (`{ ...defaultLayoutSlots }`). */
export const defaultLayoutSlots: LayoutSlots = {
  Header: DefaultHeader,
  Sidebar: DefaultSidebar,
  NavLink: DefaultNavLink,
  MobileDrawer: DefaultMobileDrawer,
  SkipLink: DefaultSkipLink,
  NavGroup: DefaultNavGroup,
};

/**
 * App shell: sidebar navigation + header slot + content area.
 *
 * Responsive: under the `md` breakpoint the sidebar collapses behind a menu
 * button and opens as a modal drawer: focus moves into it and stays there,
 * Escape, the backdrop, the close button or a link close it, and focus
 * returns to the menu button. A "Skip to content" link is the first stop of
 * the keyboard.
 *
 * After a client-side navigation, focus moves to the new page's `<h1>` and
 * a live region says its title (`routeFocus`). Render the Layout once,
 * around your router's outlet, so it sees the route change.
 *
 * The nav is `navItems` (links and collapsible groups), or with
 * `navSource="server"` (experimental) the menu the server gives the
 * signed-in user (`useNavigation`, Django's `KARNI_NAVIGATION`): groups
 * collapse with a button (Enter or Space), icons come by name (`icons`
 * over `defaultNavIcons`) and the current page is marked from `pathname`.
 *
 * Escape hatches: `slots` replaces the Header, Sidebar, NavLink, NavGroup,
 * MobileDrawer or SkipLink. `renderNavItem` wraps each derived link.
 * `sidebar` replaces the derived nav wholesale. `sidebarHeader`,
 * `sidebarFooter` and `header` are free slots. `mobileNavOpen` controls
 * the drawer. `routeFocus={false}` turns the focus move off, and an object
 * sets its route key, target or announcement.
 */
export const Layout = React.forwardRef<HTMLDivElement, LayoutProps>(
  (
    {
      navItems = [],
      navSource = "static",
      pathname,
      icons,
      renderNavItem,
      sidebar,
      sidebarHeader = <KarniMark className="mx-3" />,
      sidebarFooter,
      header,
      navLabel = "Main",
      mobileNavOpen,
      defaultMobileNavOpen = false,
      onMobileNavOpenChange,
      slots,
      routeFocus = true,
      sidebarClassName,
      headerClassName,
      contentClassName,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const { Header, Sidebar, NavLink, MobileDrawer, SkipLink, NavGroup } = {
      ...defaultLayoutSlots,
      ...slots,
    };
    const Group = NavGroup ?? DefaultNavGroup;
    const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultMobileNavOpen);
    const open = mobileNavOpen ?? uncontrolledOpen;
    const setOpen = React.useCallback(
      (next: boolean) => {
        if (mobileNavOpen === undefined) setUncontrolledOpen(next);
        onMobileNavOpenChange?.(next);
      },
      [mobileNavOpen, onMobileNavOpenChange],
    );
    const closeMobile = React.useCallback(() => setOpen(false), [setOpen]);

    const menuButtonRef = React.useRef<HTMLButtonElement>(null);
    const drawerId = React.useId();
    const mainId = React.useId();
    const mainRef = React.useRef<HTMLElement>(null);
    const skipToMain = React.useCallback((event: React.MouseEvent<HTMLAnchorElement>) => {
      const main = mainRef.current;
      if (main === null) return;
      event.preventDefault();
      main.focus();
    }, []);
    const routeFocusOn = routeFocus !== false;
    const routeAnnouncement = useRouteFocus(mainRef, {
      ...(typeof routeFocus === "object" ? routeFocus : {}),
      enabled: routeFocusOn,
    });

    // The drawer is for narrow screens only: once the menu button is hidden
    // (the window grew past md), a still-open modal drawer would trap focus
    // in an invisible panel, so it closes.
    React.useEffect(() => {
      if (!open) return undefined;
      const closeIfWide = (): void => {
        const button = menuButtonRef.current;
        if (button !== null && window.getComputedStyle(button).display === "none") {
          setOpen(false);
        }
      };
      closeIfWide();
      window.addEventListener("resize", closeIfWide);
      return () => window.removeEventListener("resize", closeIfWide);
    }, [open, setOpen]);

    const renderEntries = (entries: readonly LayoutNavEntry[]): React.ReactNode =>
      entries.map((entry, index) => {
        if (isNavGroup(entry)) {
          return (
            <GroupEntry key={entry.key ?? `group-${index}`} group={entry} NavGroup={Group}>
              {renderEntries(entry.children)}
            </GroupEntry>
          );
        }
        const item = entry;
        const defaultClassName = cn(NAV_ITEM_CLASS, item.active === true && NAV_ITEM_ACTIVE_CLASS);
        const defaultNode = (
          <NavLink
            item={item}
            href={item.href}
            aria-current={item.active === true ? "page" : undefined}
            className={defaultClassName}
            onClick={closeMobile}
          >
            {item.icon != null && <span aria-hidden="true">{item.icon}</span>}
            {item.label}
          </NavLink>
        );
        return (
          <React.Fragment key={item.key ?? item.href}>
            {renderNavItem ? renderNavItem(item, { defaultNode, defaultClassName }) : defaultNode}
          </React.Fragment>
        );
      });
    const renderNav = (entries: readonly LayoutNavEntry[]): React.ReactNode => (
      <nav aria-label={navLabel} className="grid gap-1">
        {renderEntries(entries)}
      </nav>
    );
    const nav =
      sidebar ??
      (navSource === "server" ? (
        <ServerNav
          pathname={pathname}
          icons={icons}
          fallback={navItems}
          render={renderNav}
          navLabel={navLabel}
        />
      ) : (
        renderNav(navItems)
      ));
    const column = { header: sidebarHeader, nav, footer: sidebarFooter };

    const menuButton = (
      <button
        ref={menuButtonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        // Names the drawer only while it exists.
        aria-controls={open ? drawerId : undefined}
        onClick={() => setOpen(!open)}
        className={cn(ICON_BUTTON_CLASS, "h-9 w-9 md:hidden")}
      >
        <MenuIcon className="h-5 w-5" />
        <span className="sr-only">Open navigation</span>
      </button>
    );

    return (
      <div
        ref={ref}
        className={cn("flex min-h-screen w-full bg-background text-foreground", className)}
        {...props}
      >
        <SkipLink href={`#${mainId}`} onClick={skipToMain}>
          Skip to content
        </SkipLink>
        <Sidebar {...column} className={sidebarClassName} />
        <MobileDrawer
          {...column}
          className={sidebarClassName}
          open={open}
          onOpenChange={setOpen}
          id={drawerId}
          returnFocusRef={menuButtonRef}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header menuButton={menuButton} className={headerClassName}>
            {header}
          </Header>
          <main
            ref={mainRef}
            id={mainId}
            // Focusable from the skip link, not part of the tab order.
            tabIndex={-1}
            className={cn("flex-1 p-6 focus:outline-none", contentClassName)}
          >
            {children}
          </main>
        </div>
        {routeFocusOn && (
          <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
            {routeAnnouncement}
          </div>
        )}
      </div>
    );
  },
);
Layout.displayName = "Layout";
