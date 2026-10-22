// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below. Keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
// Every route renders inside the app shell (./layout.tsx), whose navigation
// lists the static routes registered here.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import AppLayout from "./layout";
import HomePage from "./pages/home";
import LeadFormPage from "./pages/lead-form";
import LeadDetailPage from "./pages/lead-detail";
import LeadsPage from "./pages/leads";
import LoginPage from "./pages/login";
// karni:page-imports

const root = createRootRoute({ component: AppLayout });

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    createRoute({ getParentRoute: () => root, path: "/leads/new", component: LeadFormPage }),
    createRoute({ getParentRoute: () => root, path: "/leads/$id/edit", component: LeadFormPage }),
    createRoute({ getParentRoute: () => root, path: "/leads/$id", component: LeadDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/leads", component: LeadsPage }),
    createRoute({ getParentRoute: () => root, path: "/login", component: LoginPage }),
    // karni:routes
];

export const router = createRouter({ routeTree: root.addChildren(routes) });

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}
