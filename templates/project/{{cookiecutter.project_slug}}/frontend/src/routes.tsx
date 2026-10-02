// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below — keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import HomePage from "./pages/home";
// karni:page-imports

const root = createRootRoute();

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    // karni:routes
];

export const router = createRouter({ routeTree: root.addChildren(routes) });

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}
