// The app shell: @karni/ui's <Layout>, with one nav entry per static route in
// routes.tsx, in registration order — pages from `karni make page` show up
// here on their own.
// Detail/edit routes ($id) and "new" forms are reached from their list page.
import { Layout, type LayoutNavItem } from "@karni/ui";
import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";

function label(path: string): string {
    const name = path.split("/").filter(Boolean).at(-1) ?? "home";
    return name.replace(/[-_]+/g, " ").replace(/^./, (first) => first.toUpperCase());
}

export default function AppLayout() {
    const router = useRouter();
    const pathname = useRouterState({ select: (state) => state.location.pathname });
    const navItems: LayoutNavItem[] = Object.keys(router.routesByPath)
        .filter((path) => !path.includes("$") && !path.endsWith("/new"))
        .map((href) => ({
            href,
            label: label(href),
            active: href === pathname || (href !== "/" && pathname.startsWith(`${href}/`)),
        }));
    return (
        <Layout
            navItems={navItems}
            // Your brand goes here: swap the placeholder square for your mark
            // (an <img src="/favicon.svg">, an inline SVG, or a component).
            sidebarHeader={
                <span className="flex items-center gap-2 px-3 text-lg font-semibold">
                    <span aria-hidden="true" className="h-6 w-6 rounded-md bg-slate-500" />
                    {{ cookiecutter.project_name }}
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
