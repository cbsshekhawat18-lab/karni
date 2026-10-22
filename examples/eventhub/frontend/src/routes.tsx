// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below. Keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
// Every route renders inside the app shell (./layout.tsx), whose navigation
// lists the static routes registered here.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import AppLayout from "./layout";
import HomePage from "./pages/home";
import EventFormPage from "./pages/event-form";
import EventDetailPage from "./pages/event-detail";
import EventsPage from "./pages/events";
import BookingFormPage from "./pages/booking-form";
import BookingDetailPage from "./pages/booking-detail";
import BookingsPage from "./pages/bookings";
import LoginPage from "./pages/login";
import EventDashboardPage from "./pages/event-dashboard";
// karni:page-imports

const root = createRootRoute({ component: AppLayout });

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    createRoute({ getParentRoute: () => root, path: "/events/new", component: EventFormPage }),
    createRoute({ getParentRoute: () => root, path: "/events/$id/edit", component: EventFormPage }),
    createRoute({ getParentRoute: () => root, path: "/events/$id", component: EventDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/events", component: EventsPage }),
    createRoute({ getParentRoute: () => root, path: "/bookings/new", component: BookingFormPage }),
    createRoute({ getParentRoute: () => root, path: "/bookings/$id/edit", component: BookingFormPage }),
    createRoute({ getParentRoute: () => root, path: "/bookings/$id", component: BookingDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/bookings", component: BookingsPage }),
    createRoute({ getParentRoute: () => root, path: "/login", component: LoginPage }),
    createRoute({ getParentRoute: () => root, path: "/events/$id/dashboard", component: EventDashboardPage }),
    // karni:routes
];

export const router = createRouter({ routeTree: root.addChildren(routes) });

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}
