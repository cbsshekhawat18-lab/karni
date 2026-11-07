// The app shell: @karni/ui's <Layout>, with one nav entry per static route in
// routes.tsx, in registration order (routeNavItems: detail and "new" routes
// are reached from their list page, and the sign-in page is listed only while
// nobody is signed in). Pages from `karni make page` show up here on their own.
import { Layout, routeNavItems, useAuth } from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";

export default function AppLayout() {
    const router = useRouter();
    const { status } = useAuth();
    const pathname = useRouterState({ select: (state) => state.location.pathname });
    const navItems = routeNavItems(Object.keys(router.routesByPath), {
        pathname,
        signedIn: status === "authenticated",
    });
    return (
        <Layout
            navItems={navItems}
            // Your brand goes here: swap the placeholder square for your mark
            // (an <img src="/favicon.svg">, an inline SVG, or a component).
            sidebarHeader={
                <span className="flex items-center gap-2 px-3 text-lg font-semibold">
                    <span aria-hidden="true" className="h-6 w-6 rounded-md bg-slate-500" />
                    Social Leads
                </span>
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
