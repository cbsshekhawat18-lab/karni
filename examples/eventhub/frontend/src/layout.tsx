// The app shell: @karni/ui's <Layout>, with one nav entry per static route in
// routes.tsx, in registration order. Pages from `karni make page` show up
// here on their own.
// Detail/edit routes ($id) and "new" forms are reached from their list page,
// and the sign-in page is listed only while nobody is signed in.
import { Button, Layout, ThemeToggle, useAuth, type LayoutNavItem } from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

function label(path: string): string {
    const name = path.split("/").filter(Boolean).at(-1) ?? "home";
    return name.replace(/[-_]+/g, " ").replace(/^./, (first) => first.toUpperCase());
}

// Whether a route gets a nav entry. A signed-in user has no use for the
// sign-in page, and it stays listed while the session is still loading.
function inNav(path: string, signedOut: boolean): boolean {
    if (path.includes("$") || path.endsWith("/new")) return false;
    return signedOut || !path.endsWith("/login");
}

export default function AppLayout() {
    const router = useRouter();
    const { status, logout } = useAuth();
    const pathname = useRouterState({ select: (state) => state.location.pathname });
    // The drawer closes on every route change, so an action in its footer
    // (Sign out) does not leave it open, focus trapped, over the next page.
    const [navOpen, setNavOpen] = useState(false);
    useEffect(() => setNavOpen(false), [pathname]);
    const navItems: LayoutNavItem[] = Object.keys(router.routesByPath)
        .filter((path) => inNav(path, status !== "authenticated"))
        .map((href) => ({
            href,
            label: label(href),
            active: href === pathname || (href !== "/" && pathname.startsWith(`${href}/`)),
        }));
    return (
        <Layout
            navItems={navItems}
            mobileNavOpen={navOpen}
            onMobileNavOpenChange={setNavOpen}
            sidebarHeader={<span className="px-3 text-lg font-semibold">EventHub</span>}
            header={<ThemeToggle className="ml-auto" />}
            sidebarFooter={
                status === "authenticated" ? (
                    <Button
                        variant="ghost"
                        className="w-full justify-start"
                        onClick={() => {
                            setNavOpen(false); // before the login page mounts and autofocuses
                            void logout().then(() => router.history.push("/login"));
                        }}
                    >
                        Sign out
                    </Button>
                ) : null
            }
            // Client-side navigation: intercept the default link's click (it
            // still closes the mobile drawer); `contents` keeps the nav grid.
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
            <Outlet />
        </Layout>
    );
}
