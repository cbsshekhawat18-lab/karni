// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below. Keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
// Every route renders inside the app shell (./layout.tsx), whose navigation
// lists the static routes registered here. A route with
// `staticData: { public: true }` shows to visitors who are not signed in.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import AppLayout from "./layout";
import HomePage from "./pages/home";
import BookFormPage from "./pages/book-form";
import BookDetailPage from "./pages/book-detail";
import BooksPage from "./pages/books";
import PlayPage from "./pages/play";
import LeaderboardPage from "./pages/leaderboard";
// karni:page-imports

const root = createRootRoute({ component: AppLayout });

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    createRoute({ getParentRoute: () => root, path: "/books/new", component: BookFormPage }),
    createRoute({ getParentRoute: () => root, path: "/books/$id/edit", component: BookFormPage }),
    createRoute({ getParentRoute: () => root, path: "/books/$id", component: BookDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/books", component: BooksPage }),
    createRoute({ getParentRoute: () => root, path: "/play", component: PlayPage }),
    createRoute({ getParentRoute: () => root, path: "/leaderboard", component: LeaderboardPage }),
    // karni:routes
];

// basepath is the Vite base: / in development, and in production the path the
// build is served under (KARNI_APP_PATH, /app/ by default, docs/deploy.md).
export const router = createRouter({
    routeTree: root.addChildren(routes),
    basepath: import.meta.env.BASE_URL,
});

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
    interface StaticDataRouteOption {
        /** The page shows without signing in: layout.tsx leaves out the sign-in guard. */
        public?: boolean;
    }
}
