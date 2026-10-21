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

export interface LayoutProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Items of the derived sidebar nav. */
  navItems?: readonly LayoutNavItem[];
  /**
   * Escape hatch for router integration: wraps/replaces the default anchor of
   * one item. `defaultNode` is the styled <a> the layout would render — return
   * it, or your own node (e.g. a TanStack Router <Link> with
   * `className={defaultClassName}`).
   */
  renderNavItem?: (
    item: LayoutNavItem,
    defaults: { defaultNode: React.ReactNode; defaultClassName: string },
  ) => React.ReactNode;
  /** Escape hatch: replaces the entire derived nav inside the sidebar. */
  sidebar?: React.ReactNode;
  /**
   * Brand/logo slot pinned to the top of the sidebar. Defaults to the Karni
   * mark (`<KarniMark />`); pass your own brand, or `null` for no header.
   */
  sidebarHeader?: React.ReactNode;
  /** Slot pinned to the bottom of the sidebar (user menu, logout, …). */
  sidebarFooter?: React.ReactNode;
  /** Header slot, rendered in the top bar next to the mobile menu button. */
  header?: React.ReactNode;
  /** Accessible name of the sidebar navigation (default "Main"). */
  navLabel?: string;
  sidebarClassName?: string;
  headerClassName?: string;
  contentClassName?: string;
  children?: React.ReactNode;
}

const NAV_ITEM_CLASS =
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground [&_svg]:h-4 [&_svg]:w-4";
const NAV_ITEM_ACTIVE_CLASS = "bg-accent text-accent-foreground";

const SIDEBAR_ID = "karni-layout-sidebar";

/**
 * App shell: sidebar navigation + header slot + content area.
 *
 * Responsive: under the `md` breakpoint the sidebar collapses behind a menu
 * button and opens as an overlay drawer (Escape or backdrop click closes it).
 *
 * Escape hatches: `renderNavItem` wraps each derived link (router
 * integration), `sidebar` replaces the derived nav wholesale, and
 * `sidebarHeader`/`sidebarFooter`/`header` are free slots.
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
      sidebarClassName,
      headerClassName,
      contentClassName,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const [mobileOpen, setMobileOpen] = React.useState(false);

    const closeMobile = React.useCallback(() => {
      setMobileOpen(false);
    }, []);

    React.useEffect(() => {
      if (!mobileOpen) {
        return;
      }
      const onKeyDown = (event: KeyboardEvent): void => {
        if (event.key === "Escape") {
          setMobileOpen(false);
        }
      };
      document.addEventListener("keydown", onKeyDown);
      return () => {
        document.removeEventListener("keydown", onKeyDown);
      };
    }, [mobileOpen]);

    const navContent = sidebar ?? (
      <nav aria-label={navLabel} className="grid gap-1">
        {navItems.map((item) => {
          const defaultClassName = cn(
            NAV_ITEM_CLASS,
            item.active === true && NAV_ITEM_ACTIVE_CLASS,
          );
          const defaultNode = (
            <a
              href={item.href}
              aria-current={item.active === true ? "page" : undefined}
              className={defaultClassName}
              onClick={closeMobile}
            >
              {item.icon != null && <span aria-hidden="true">{item.icon}</span>}
              {item.label}
            </a>
          );
          return (
            <React.Fragment key={item.key ?? item.href}>
              {renderNavItem ? renderNavItem(item, { defaultNode, defaultClassName }) : defaultNode}
            </React.Fragment>
          );
        })}
      </nav>
    );

    const sidebarInner = (
      <>
        {sidebarHeader != null && <div className="mb-4">{sidebarHeader}</div>}
        <div className="flex-1 overflow-y-auto">{navContent}</div>
        {sidebarFooter != null && <div className="mt-4">{sidebarFooter}</div>}
      </>
    );

    return (
      <div
        ref={ref}
        className={cn("flex min-h-screen w-full bg-background text-foreground", className)}
        {...props}
      >
        {/* Static sidebar (md and up). */}
        <aside
          className={cn(
            "hidden w-64 shrink-0 flex-col border-r border-border bg-card p-4 md:flex",
            sidebarClassName,
          )}
        >
          {sidebarInner}
        </aside>

        {/* Overlay drawer (below md). */}
        {mobileOpen && (
          <div className="fixed inset-0 z-drawer md:hidden">
            <div
              data-testid="karni-layout-backdrop"
              aria-hidden="true"
              className="absolute inset-0 bg-overlay"
              onClick={closeMobile}
            />
            <aside
              id={SIDEBAR_ID}
              className={cn(
                "absolute inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-card p-4 shadow-lg",
                sidebarClassName,
              )}
            >
              <div className="mb-2 flex justify-end">
                <button
                  type="button"
                  onClick={closeMobile}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <CloseIcon className="h-4 w-4" />
                  <span className="sr-only">Close navigation</span>
                </button>
              </div>
              {sidebarInner}
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header
            className={cn(
              "flex h-14 shrink-0 items-center gap-3 border-b border-border px-4",
              headerClassName,
            )}
          >
            <button
              type="button"
              aria-expanded={mobileOpen}
              aria-controls={SIDEBAR_ID}
              onClick={() => {
                setMobileOpen((open) => !open);
              }}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
            >
              <MenuIcon className="h-5 w-5" />
              <span className="sr-only">Open navigation</span>
            </button>
            {header != null && (
              <div className="flex min-w-0 flex-1 items-center gap-3">{header}</div>
            )}
          </header>
          <main className={cn("flex-1 p-6", contentClassName)}>{children}</main>
        </div>
      </div>
    );
  },
);
Layout.displayName = "Layout";
