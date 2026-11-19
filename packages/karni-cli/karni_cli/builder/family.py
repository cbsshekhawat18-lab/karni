"""Experimental. The family's frontend that ``karni build`` writes for a project of parts.

A project that holds parts (``app.recipes``) gets, in ``frontend/src/karni/``
(Karni-owned, rewritten on every build like ``parts.ts``):

* ``layout.tsx``: the one layout of the project, ``FamilyLayout`` of @karni/ui
  with the router's glue, the commerce provider and mini cart when commerce
  is installed, the inbox bell with notify, the terms link and gate.
* ``home.tsx``: ``FamilyHome``, the one home: each role's tiles, the public
  home a part registers, and what to do when nothing is installed.
* ``pages/<name>.tsx``: the family pages whose provider the project holds
  (:data:`karni_cli.spec.navigation.FAMILY_PROVIDERS`): sign-in, account and
  search always, the inbox with notify, settings with preferences, people
  with the people contract, and the cart, checkout and orders with commerce.
  Each is registered in ``routes.tsx``'s Karni block. A path the project
  routes itself keeps the project's page.
* ``router.ts``: the few hooks the pages share (the router's push, a query
  value, a route parameter).

The scaffold's ``frontend/src/layout.tsx`` and ``frontend/src/pages/home.tsx``
become one-line re-exports of the family's, while they are still what
``karni new`` wrote (the digest ``karni new`` recorded, or the template's
text). A project that changed one keeps it, and the build says how to use
the family's.

So a part ships none of these pages: a shop, a CRM and a booking app share
one layout, one home, one cart and one account page.

Override / escape hatch: route a family path yourself in ``routes.tsx``
(outside the Karni block) and the build leaves it to you; adopt a file with
``karni build --adopt``; or keep your own ``layout.tsx``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli.spec import navigation as nav
from karni_cli.spec import schema

__all__ = [
    "FAMILY_DIR",
    "HOME_FILE",
    "LAYOUT_FILE",
    "ROUTER_FILE",
    "SCAFFOLD_HOME",
    "SCAFFOLD_LAYOUT",
    "FamilyPage",
    "family_pages",
    "home_text",
    "layout_text",
    "parts_lines",
    "reexport_text",
    "router_text",
    "scaffold_text",
]

#: Where the family's files go: Karni's, next to ``parts.ts``.
FAMILY_DIR: Final = "frontend/src/karni"
LAYOUT_FILE: Final = f"{FAMILY_DIR}/layout.tsx"
HOME_FILE: Final = f"{FAMILY_DIR}/home.tsx"
ROUTER_FILE: Final = f"{FAMILY_DIR}/router.ts"
#: The files ``karni new`` writes that become re-exports of the family's.
SCAFFOLD_LAYOUT: Final = "frontend/src/layout.tsx"
SCAFFOLD_HOME: Final = "frontend/src/pages/home.tsx"

_HEADER: Final = "Written by karni build from karni.yaml. Do not edit it: karni build rewrites it."


@dataclass(frozen=True)
class FamilyPage:
    """Experimental. One family page: its file, its component, its routes and their data."""

    #: The family page it belongs to (a key of ``FAMILY_PAGES``: ``orders``).
    family: str
    #: The file's name under ``frontend/src/karni/pages/`` (``order-invoice``).
    name: str
    component: str
    paths: tuple[str, ...]
    text: str
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def file(self) -> str:
        return f"{FAMILY_DIR}/pages/{self.name}.tsx"

    def route_line(self, path: str) -> str:
        """The ``createRoute(...)`` entry of ``path``, as the Karni block holds it."""
        pairs = ", ".join(
            f"{key}: {'true' if value is True else json.dumps(value)}"
            for key, value in self.data.items()
        )
        data = f", staticData: {{ {pairs} }}" if pairs else ""
        return (
            f'createRoute({{ getParentRoute: () => root, path: "{path}", '
            f"component: {self.component}{data} }}),"
        )


def _page(
    family: str,
    name: str,
    component: str,
    paths: tuple[str, ...],
    imports: list[str],
    body: list[str],
    *,
    public: bool = False,
    area: str | None = None,
) -> FamilyPage:
    # The scaffold's indent: 4 spaces (the bodies here are written with 2).
    wide = [" " * (2 * (len(line) - len(line.lstrip(" ")))) + line.lstrip(" ") for line in body]
    lines = [f"// {_HEADER}", *imports, "", f"export default function {component}() {{", *wide]
    lines.append("}")
    data: dict[str, Any] = {}
    if public:
        data["public"] = True
    if area is not None:
        data["area"] = area
    return FamilyPage(family, name, component, paths, "\n".join(lines) + "\n", data)


_SITE = 'import { useSiteName } from "@karni/ui";'


def family_pages(spec: schema.Spec) -> list[FamilyPage]:
    """Experimental. The family pages of ``spec``: those whose provider the project holds."""
    have = {name for name, provider in nav.FAMILY_PROVIDERS.items() if nav.provided(spec, provider)}
    found: list[FamilyPage] = []
    if "signin" in have:
        found.append(
            _page(
                "signin",
                "signin",
                "KarniSignInPage",
                ("/signin",),
                [
                    'import { SignInPage, useSiteName } from "@karni/ui";',
                    'import { useGo, useQueryValue } from "../router";',
                ],
                [
                    '  const next = useQueryValue("next");',
                    "  return (",
                    (
                        "    <SignInPage siteName={useSiteName()} next={next || null} "
                        "navigate={useGo()} />"
                    ),
                    "  );",
                ],
                public=True,
                area="store",
            )
        )
    if "account" in have:
        found.append(
            _page(
                "account",
                "account",
                "KarniAccountPage",
                ("/account",),
                ['import { AccountPage, useSiteName } from "@karni/ui";'],
                ["  return <AccountPage siteName={useSiteName()} />;"],
                area="family",
            )
        )
    if "search" in have:
        found.append(
            _page(
                "search",
                "search",
                "KarniSearchPage",
                ("/search",),
                [
                    'import { SearchPage, useSiteName } from "@karni/ui";',
                    'import { useRouter } from "@tanstack/react-router";',
                    'import { useGo, useQueryValue } from "../router";',
                ],
                [
                    "  const router = useRouter();",
                    "  return (",
                    "    <SearchPage",
                    '      query={useQueryValue("q")}',
                    "      onQueryChange={(q) =>",
                    "        router.history.replace(`/search?q=${encodeURIComponent(q)}`)",
                    "      }",
                    "      navigate={useGo()}",
                    "      routes={Object.keys(router.routesByPath)}",
                    "      siteName={useSiteName()}",
                    "    />",
                    "  );",
                ],
                area="family",
            )
        )
    if "inbox" in have:
        found.append(
            _page(
                "inbox",
                "inbox",
                "KarniInboxPage",
                ("/inbox",),
                [
                    'import { InboxPage, useSiteName } from "@karni/ui";',
                    'import { useGo } from "../router";',
                ],
                ["  return <InboxPage navigate={useGo()} siteName={useSiteName()} />;"],
                area="family",
            )
        )
    if "settings" in have:
        found.append(
            _page(
                "settings",
                "settings",
                "KarniSettingsPage",
                ("/settings",),
                ['import { SettingsPage, useSiteName } from "@karni/ui";'],
                ["  return <SettingsPage siteName={useSiteName()} />;"],
            )
        )
    if "people" in have:
        found += _people_pages(spec)
    if "orders" in have:
        found += _commerce_pages()
    return found


def _people_pages(spec: schema.Spec) -> list[FamilyPage]:
    label = nav.people_label(spec)
    # A shop alone: its people are its customers, the people who bought.
    filters = ' filters={{ orders__gte: "1" }}' if nav.sells_alone(spec) else ""
    return [
        _page(
            "people",
            "people",
            "KarniPeoplePage",
            ("/people",),
            [
                'import { PeoplePage, useSiteName } from "@karni/ui";',
                'import { useGo } from "../router";',
            ],
            [
                "  return (",
                (
                    f'    <PeoplePage label="{label}"{filters} navigate={{useGo()}} '
                    "siteName={useSiteName()} />"
                ),
                "  );",
            ],
        ),
        _page(
            "people",
            "person",
            "KarniPersonPage",
            ("/people/$id",),
            [
                'import { PersonPage, routeHref, useSiteName } from "@karni/ui";',
                'import { useRouter } from "@tanstack/react-router";',
                'import { useGo, useParam } from "../router";',
            ],
            [
                "  const router = useRouter();",
                "  const routes = Object.keys(router.routesByPath);",
                "  return (",
                "    <PersonPage",
                '      id={useParam("id")}',
                "      navigate={useGo()}",
                f'      listLabel="{label}"',
                "      hrefFor={(resource, id) => routeHref(resource, id, routes)}",
                "      siteName={useSiteName()}",
                "    />",
                "  );",
            ],
        ),
    ]


def _commerce_pages() -> list[FamilyPage]:
    ui = "@karni/commerce-ui"
    site = "siteName={useSiteName()}"
    return [
        _page(
            "cart",
            "cart",
            "KarniCartPage",
            ("/cart",),
            [f'import {{ CartPage }} from "{ui}";', _SITE],
            [f"  return <CartPage {site} />;"],
            public=True,
            area="store",
        ),
        _page(
            "checkout",
            "checkout",
            "KarniCheckoutPage",
            ("/checkout",),
            [f'import {{ CheckoutPage }} from "{ui}";', _SITE],
            [f"  return <CheckoutPage {site} />;"],
            public=True,
            area="store",
        ),
        _page(
            "orders",
            "orders",
            "KarniOrdersPage",
            ("/orders",),
            [f'import {{ FamilyOrdersPage }} from "{ui}";', _SITE],
            [f"  return <FamilyOrdersPage {site} />;"],
            area="family",
        ),
        _page(
            "orders",
            "order-new",
            "KarniNewOrderPage",
            ("/orders/new",),
            [f'import {{ NewOrderPage }} from "{ui}";', _SITE],
            [f"  return <NewOrderPage {site} />;"],
        ),
        _page(
            "orders",
            "order",
            "KarniOrderPage",
            ("/orders/$number",),
            [
                f'import {{ FamilyOrderPage }} from "{ui}";',
                _SITE,
                'import { useParam, useQueryValue } from "../router";',
            ],
            [
                "  return (",
                "    <FamilyOrderPage",
                '      number={useParam("number")}',
                '      orderKey={useQueryValue("key")}',
                '      justPaid={useQueryValue("paid") === "1"}',
                f"      {site}",
                "    />",
                "  );",
            ],
            public=True,
            area="family",
        ),
        _page(
            "orders",
            "order-invoice",
            "KarniInvoicePage",
            ("/orders/$number/invoice",),
            [
                f'import {{ OrderDocumentPage }} from "{ui}";',
                'import { useParam, useQueryValue } from "../router";',
            ],
            [
                "  return (",
                "    <OrderDocumentPage",
                '      number={useParam("number")}',
                '      orderKey={useQueryValue("key")}',
                '      kind="invoice"',
                "    />",
                "  );",
            ],
            public=True,
            area="family",
        ),
        _page(
            "orders",
            "order-packing-slip",
            "KarniPackingSlipPage",
            ("/orders/$number/packing-slip",),
            [
                f'import {{ OrderDocumentPage }} from "{ui}";',
                'import { useParam } from "../router";',
            ],
            ['  return <OrderDocumentPage number={useParam("number")} kind="packing_slip" />;'],
        ),
    ]


def router_text() -> str:
    """Experimental. ``frontend/src/karni/router.ts``: the hooks the family pages share."""
    return f"""// {_HEADER}
// The router's glue the family pages share (TanStack Router).
import {{ useRouter, useRouterState }} from "@tanstack/react-router";
import {{ useCallback }} from "react";

/** The router's push, for the family components' `navigate`. */
export function useGo(): (to: string) => void {{
    const router = useRouter();
    return useCallback((to: string) => router.history.push(to), [router]);
}}

/** One value of the address's query (`?key=`, `?next=`), or "". */
export function useQueryValue(name: string): string {{
    return useRouterState({{
        select: (state) => {{
            const value = (state.location.search as Record<string, unknown>)[name];
            return value === undefined || value === null ? "" : String(value);
        }},
    }});
}}

/** One parameter of the current route (`$id`, `$number`), or "". */
export function useParam(name: string): string {{
    return useRouterState({{
        select: (state) => {{
            const params = state.matches.at(-1)?.params as Record<string, unknown> | undefined;
            const value = params?.[name];
            return value === undefined || value === null ? "" : String(value);
        }},
    }});
}}
"""


def layout_text(spec: schema.Spec) -> str:
    """Experimental. ``frontend/src/karni/layout.tsx``: the project's one layout."""
    commerce = "commerce" in spec.modules
    notify = nav.provided(spec, "features.notify")
    terms = spec.features.terms
    terms_url = terms.url if terms is not None and terms.required else None
    gate = terms is not None and terms.required and not terms.paths
    imports = []
    if commerce:
        imports.append(
            'import { CommerceProvider, MiniCart, useMergeOnSignIn } from "@karni/commerce-ui";'
        )
    imports += [
        'import { FamilyLayout } from "@karni/ui";',
        'import { Outlet, useRouter, useRouterState } from "@tanstack/react-router";',
        'import { useCallback, type ReactNode } from "react";'
        if commerce
        else 'import { useCallback } from "react";',
    ]
    props = [
        "pathname={pathname}",
        "navigate={navigate}",
        "area={route?.area}",
        "isPublic={route?.public === true}",
        "routes={routes}",
    ]
    if notify:
        props.append("inbox")
    if commerce:
        props.append("storeActions={<MiniCart />}")
    if terms_url is not None:
        props.append(f"termsHref={json.dumps(terms_url)}")
    if gate:
        props.append("terms")
    shell: list[str] = []
    if commerce:
        shell = [
            "// The cart, checkout and order pages navigate with the router.",
            "function Providers({",
            "    children,",
            "    navigate,",
            "}: {",
            "    children: ReactNode;",
            "    navigate: (to: string) => void;",
            "}) {",
            "    return (",
            "        <CommerceProvider navigate={navigate}>",
            "            <CartSession />",
            "            {children}",
            "        </CommerceProvider>",
            "    );",
            "}",
            "",
            "// A visitor's cart joins the person's cart when they sign in.",
            "function CartSession() {",
            "    useMergeOnSignIn();",
            "    return null;",
            "}",
            "",
        ]
    lines = [
        f"// {_HEADER}",
        "// The one layout of this project of parts (@karni/ui's FamilyLayout): the storefront's",
        '// frame for a route with staticData area "store", the back office for the rest, and the',
        '// home and area "family" routes in the frame of who is looking. frontend/src/layout.tsx',
        "// re-exports it: write your own there to change it.",
        *imports,
        "",
        'declare module "@tanstack/react-router" {',
        "    interface StaticDataRouteOption {",
        '        /** "store": the storefront\'s frame. "family": the storefront to customers, the',
        "         *  back office to staff. None: the back office. */",
        "        area?: string;",
        "    }",
        "}",
        "",
        *shell,
        "export default function KarniLayout() {",
        "    const router = useRouter();",
        "    const navigate = useCallback((to: string) => router.history.push(to), [router]);",
        "    const pathname = useRouterState({ select: (state) => state.location.pathname });",
        "    const route = useRouterState({ select: (state) => state.matches.at(-1)?.staticData });",
        "    const routes = Object.keys(router.routesByPath);",
    ]
    family = [
        "<FamilyLayout",
        *(f"    {prop}" for prop in props),
        ">",
        "    <Outlet />",
        "</FamilyLayout>",
    ]
    if commerce:
        body = [
            "<Providers navigate={navigate}>",
            *(f"    {line}" for line in family),
            "</Providers>",
        ]
    else:
        body = family
    lines += ["    return (", *(f"        {line}" for line in body), "    );", "}"]
    return "\n".join(lines) + "\n"


def home_text() -> str:
    """Experimental. ``frontend/src/karni/home.tsx``: the project's one home."""
    return f"""// {_HEADER}
// The home (@karni/ui's FamilyHome): each staff role's tiles from every part, the public
// home a part registers for visitors and customers, and what to do when nothing is in.
import {{ FamilyHome }} from "@karni/ui";
import {{ PARTS }} from "./parts";
import {{ useGo }} from "./router";

export default function KarniHome() {{
    return <FamilyHome navigate={{useGo()}} parts={{PARTS}} />;
}}
"""


def parts_lines(spec: schema.Spec) -> tuple[list[str], list[str]]:
    """Experimental. What ``parts.ts`` adds for the family: its imports, and its calls (before
    each part's own ``register()``, so a part may replace what the family registered)."""
    imports = ['import { registerFamily } from "@karni/ui";']
    people = nav.provided(spec, "features.people")
    notify = nav.provided(spec, "features.notify")
    calls = [
        (
            f"registerFamily({{ people: {'true' if people else 'false'}, "
            f"notify: {'true' if notify else 'false'} }});"
        )
    ]
    if "commerce" in spec.modules:
        imports.append('import { register as registerCommerce } from "@karni/commerce-ui";')
        calls.append("registerCommerce();")
    return imports, calls


def reexport_text(rel: str) -> str:
    """Experimental. The scaffold file ``rel`` as a re-export of the family's."""
    if rel == SCAFFOLD_LAYOUT:
        return (
            "// The app shell is the family's (frontend/src/karni/layout.tsx), which karni build\n"
            "// writes for this project of parts. Write your own layout here to replace it.\n"
            'export { default } from "./karni/layout";\n'
        )
    return (
        "// The home page is the family's (frontend/src/karni/home.tsx), which karni build\n"
        "// writes for this project of parts. Write your own page here to replace it.\n"
        'export { default } from "../karni/home";\n'
    )


def scaffold_text(rel: str, project_name: str) -> str | None:
    """Experimental. What ``karni new`` wrote at ``rel`` for a project named ``project_name``,
    from the project template (``None`` when the template is not found)."""
    from karni_cli.project import CliError
    from karni_cli.scaffold import resolve_template

    try:
        template = resolve_template()
    except CliError:
        return None
    path = template / "{{cookiecutter.project_slug}}" / Path(rel)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return text.replace("{{ cookiecutter.project_name }}", project_name)


def digest(text: str) -> str:
    """Experimental. The sha256 the record keeps for a file."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
