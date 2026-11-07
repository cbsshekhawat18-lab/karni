// The app shell: @karni/ui's <Layout>, with one nav entry per static route in
// routes.tsx, in registration order (routeNavItems: detail and "new" routes
// are reached from their list page, and the sign-in page is listed only while
// nobody is signed in). Pages from `karni make page` show up here on their own.
import { Button, Layout, ThemeToggle, routeNavItems, useAuth } from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

export default function AppLayout() {
    const router = useRouter();
    const { status, logout } = useAuth();
    const pathname = useRouterState({ select: (state) => state.location.pathname });
    // The drawer closes on every route change, so an action in its footer
    // (Sign out) does not leave it open, focus trapped, over the next page.
    const [navOpen, setNavOpen] = useState(false);
    useEffect(() => setNavOpen(false), [pathname]);
    const navItems = routeNavItems(Object.keys(router.routesByPath), {
        pathname,
        signedIn: status === "authenticated",
    });
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
