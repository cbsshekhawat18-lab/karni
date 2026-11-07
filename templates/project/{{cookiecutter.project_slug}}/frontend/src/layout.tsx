// The app shell: @karni/ui's <Layout> around every route, with one nav entry
// per static route in routes.tsx (routeNavItems: detail and "new" routes are
// reached from their list page, and a sign-in page is listed only while
// nobody is signed in). Pages from `karni make page` show up on their own.
// Every page but a sign-in page sits behind <AuthGuard explain>: a visitor
// who is not signed in gets the sign-in prompt in place, never a page of
// errors, and the page appears once they sign in.
// A menu from data (KARNI_NAVIGATION in config/settings.py, or `navigation:` in
// karni.yaml): pass navSource="server" and pathname={pathname} to <Layout>,
// and it shows each user the entries their grants open (docs/navigation.md).
import {
    AuthGuard,
    Button,
    Layout,
    ThemeToggle,
    isSignInRoute,
    routeNavItems,
    useAuth,
} from "@karni/ui";
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
            // Your brand goes here: swap the placeholder square for your mark
            // (an <img src="/favicon.svg">, an inline SVG, or a component).
            sidebarHeader={
                <span className="flex items-center gap-2 px-3 text-lg font-semibold">
                    <span aria-hidden="true" className="h-6 w-6 rounded-md bg-primary" />
                    {{ cookiecutter.project_name }}
                </span>
            }
            sidebarFooter={
                <div className="space-y-1">
                    {status === "authenticated" ? (
                        <Button
                            variant="ghost"
                            className="w-full justify-start"
                            onClick={() => {
                                setNavOpen(false);
                                void logout();
                            }}
                        >
                            Sign out
                        </Button>
                    ) : null}
                    <ThemeToggle className="mx-3" />
                </div>
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
            {isSignInRoute(pathname) ? (
                <Outlet />
            ) : (
                <AuthGuard explain>
                    <Outlet />
                </AuthGuard>
            )}
        </Layout>
    );
}
