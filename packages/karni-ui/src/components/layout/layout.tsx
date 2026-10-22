import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { KarniMark } from "../brand/karni-mark";

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
}

export interface LayoutProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Items of the derived sidebar nav. */
  navItems?: readonly LayoutNavItem[];
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
 * Escape hatches: `slots` replaces the Header, Sidebar, NavLink,
 * MobileDrawer or SkipLink. `renderNavItem` wraps each derived link.
 * `sidebar` replaces the derived nav wholesale. `sidebarHeader`,
 * `sidebarFooter` and `header` are free slots. `mobileNavOpen` controls
 * the drawer.
 */
export const Layout = React.forwardRef<HTMLDivElement, LayoutProps>(
  (
    {
      navItems = [],
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
      sidebarClassName,
      headerClassName,
      contentClassName,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const { Header, Sidebar, NavLink, MobileDrawer, SkipLink } = {
      ...defaultLayoutSlots,
      ...slots,
    };
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

    const nav = sidebar ?? (
      <nav aria-label={navLabel} className="grid gap-1">
        {navItems.map((item) => {
          const defaultClassName = cn(
            NAV_ITEM_CLASS,
            item.active === true && NAV_ITEM_ACTIVE_CLASS,
          );
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
        })}
      </nav>
    );
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
      </div>
    );
  },
);
Layout.displayName = "Layout";
