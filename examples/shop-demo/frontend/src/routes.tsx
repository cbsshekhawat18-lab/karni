// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below. Keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
// Every route renders inside the app shell (./layout.tsx), whose navigation
// lists the static routes registered here.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import AppLayout from "./layout";
import HomePage from "./pages/home";
// karni:spec imports start
import ProductsPage from "./pages/karni/products";
import ProductDetailPage from "./pages/karni/product-detail";
import ProductFormPage from "./pages/karni/product-form";
import CategoriesPage from "./pages/karni/categories";
import CategoryFormPage from "./pages/karni/category-form";
import OrdersPage from "./pages/karni/orders";
import OrderDetailPage from "./pages/karni/order-detail";
import CartDetailPage from "./pages/karni/cart-detail";
// karni:spec imports end
// karni:page-imports

const root = createRootRoute({ component: AppLayout });

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    // karni:spec routes start
    createRoute({ getParentRoute: () => root, path: "/products", component: ProductsPage }),
    createRoute({ getParentRoute: () => root, path: "/products/$id", component: ProductDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/products/new", component: ProductFormPage }),
    createRoute({ getParentRoute: () => root, path: "/products/$id/edit", component: ProductFormPage }),
    createRoute({ getParentRoute: () => root, path: "/categories", component: CategoriesPage }),
    createRoute({ getParentRoute: () => root, path: "/categories/new", component: CategoryFormPage }),
    createRoute({ getParentRoute: () => root, path: "/categories/$id/edit", component: CategoryFormPage }),
    createRoute({ getParentRoute: () => root, path: "/orders", component: OrdersPage }),
    createRoute({ getParentRoute: () => root, path: "/orders/$id", component: OrderDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/carts/$id", component: CartDetailPage }),
    // karni:spec routes end
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
}
