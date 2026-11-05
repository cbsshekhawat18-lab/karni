// Routes (TanStack Router, code-based). `karni make page` registers each new
// page through the two marker comments below. Keep them. Hand-written routes
// are fine too: import the page and add a createRoute(...) entry to `routes`.
// Every route renders inside the app shell (./layout.tsx), whose navigation
// lists the static routes registered here.
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import AppLayout from "./layout";
import HomePage from "./pages/home";
// karni:spec imports start
import TrialsPage from "./pages/karni/trials";
import TrialDetailPage from "./pages/karni/trial-detail";
import TrialFormPage from "./pages/karni/trial-form";
import CompaniesPage from "./pages/karni/companies";
import CompanyDetailPage from "./pages/karni/company-detail";
import CompanyFormPage from "./pages/karni/company-form";
import DealsPage from "./pages/karni/deals";
import DealDetailPage from "./pages/karni/deal-detail";
import DealFormPage from "./pages/karni/deal-form";
import PersonsPage from "./pages/karni/persons";
import PersonDetailPage from "./pages/karni/person-detail";
import PersonFormPage from "./pages/karni/person-form";
import BrandsPage from "./pages/karni/brands";
import BrandDetailPage from "./pages/karni/brand-detail";
import BrandFormPage from "./pages/karni/brand-form";
import ConditionsPage from "./pages/karni/conditions";
import ConditionFormPage from "./pages/karni/condition-form";
import InterventionsPage from "./pages/karni/interventions";
import InterventionFormPage from "./pages/karni/intervention-form";
// karni:spec imports end
// karni:page-imports
import DealsChartPage from "./pages/deals-chart";
import InsightsPage from "./pages/insights";
import LoginPage from "./pages/login";
import PlayersPage from "./pages/players";
import SearchPage from "./pages/search";

const root = createRootRoute({ component: AppLayout });

const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    // karni:spec routes start
    createRoute({ getParentRoute: () => root, path: "/trials", component: TrialsPage }),
    createRoute({ getParentRoute: () => root, path: "/trials/$id", component: TrialDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/trials/new", component: TrialFormPage }),
    createRoute({ getParentRoute: () => root, path: "/trials/$id/edit", component: TrialFormPage }),
    createRoute({ getParentRoute: () => root, path: "/companies", component: CompaniesPage }),
    createRoute({ getParentRoute: () => root, path: "/companies/$id", component: CompanyDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/companies/new", component: CompanyFormPage }),
    createRoute({ getParentRoute: () => root, path: "/companies/$id/edit", component: CompanyFormPage }),
    createRoute({ getParentRoute: () => root, path: "/deals", component: DealsPage }),
    createRoute({ getParentRoute: () => root, path: "/deals/$id", component: DealDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/deals/new", component: DealFormPage }),
    createRoute({ getParentRoute: () => root, path: "/deals/$id/edit", component: DealFormPage }),
    createRoute({ getParentRoute: () => root, path: "/persons", component: PersonsPage }),
    createRoute({ getParentRoute: () => root, path: "/persons/$id", component: PersonDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/persons/new", component: PersonFormPage }),
    createRoute({ getParentRoute: () => root, path: "/persons/$id/edit", component: PersonFormPage }),
    createRoute({ getParentRoute: () => root, path: "/brands", component: BrandsPage }),
    createRoute({ getParentRoute: () => root, path: "/brands/$id", component: BrandDetailPage }),
    createRoute({ getParentRoute: () => root, path: "/brands/new", component: BrandFormPage }),
    createRoute({ getParentRoute: () => root, path: "/brands/$id/edit", component: BrandFormPage }),
    createRoute({ getParentRoute: () => root, path: "/conditions", component: ConditionsPage }),
    createRoute({ getParentRoute: () => root, path: "/conditions/new", component: ConditionFormPage }),
    createRoute({ getParentRoute: () => root, path: "/conditions/$id/edit", component: ConditionFormPage }),
    createRoute({ getParentRoute: () => root, path: "/interventions", component: InterventionsPage }),
    createRoute({ getParentRoute: () => root, path: "/interventions/new", component: InterventionFormPage }),
    createRoute({ getParentRoute: () => root, path: "/interventions/$id/edit", component: InterventionFormPage }),
    // karni:spec routes end
    createRoute({ getParentRoute: () => root, path: "/login", component: LoginPage }),
    createRoute({ getParentRoute: () => root, path: "/insights", component: InsightsPage }),
    createRoute({ getParentRoute: () => root, path: "/players", component: PlayersPage }),
    createRoute({ getParentRoute: () => root, path: "/deals-chart", component: DealsChartPage }),
    createRoute({ getParentRoute: () => root, path: "/search", component: SearchPage }),
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
