---
description: "Navigation from data in Karni (experimental): each user's menu from KARNI_NAVIGATION or a NavItem tree edited in the admin, opened by the same role and per-user grants as the API, served at GET /api/navigation/ and rendered by @karni/ui's Layout."
---

# Navigation from data

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `KARNI_NAVIGATION` and `KARNI_NAVIGATION_PAGES` settings,
    `karni.navigation` (with `karni.navigation.api`, `karni.navigation.checks`
    and `karni.navigation.admin`), the `NavItem` model, `GET
    /api/navigation/`, the `navigation` key of `karni.yaml`, and `useNavigation`,
    `navigationEntries`, `defaultNavIcons`, `LayoutNavGroup`, the `NavGroup`
    slot and `Layout`'s `navSource`, `pathname` and `icons` in `@karni/ui`.
    They may change in a minor release, and each change is in the CHANGELOG.
    The error codes keep their meaning.

A large app shows each customer a different set of modules and pages, and
its admins change the menu without a deploy. Karni builds that menu from data
and opens each entry with the same grants that open the API: a user sees an
entry when their roles or their [per-user grants](accounts.md#per-user-grants)
hold the permission it names.

## Two sources, one shape

The menu lives in the settings, or in the database.

**In the settings**, `KARNI_NAVIGATION` is a list of items and groups:

```python
# config/settings.py
KARNI_NAVIGATION = [
    {"label": "Home", "route": "/", "icon": "home", "requires": "public"},
    {
        "label": "Catalog",
        "icon": "box",
        "children": [
            {"label": "Products", "route": "/products", "requires": "catalog.product:view"},
            {"label": "Categories", "route": "/categories", "requires": "catalog.category:view"},
        ],
    },
    {"label": "Regions", "route": "/regions", "icon": "map", "requires": "catalog.region:*"},
    {"label": "Account", "route": "/account"},
]
```

**In the database**, `KARNI_NAVIGATION = "db"` reads the menu from the
`NavItem` table, a [tree model](models.md#tree-models) the admin edits. The
table comes with the `karni.navigation` app, which only a project that uses
this source installs, so every other project gains no table:

```python
# config/settings.py
KARNI_NAVIGATION = "db"
INSTALLED_APPS += ["karni.navigation"]
```

Then run `karni migrate` and add the entries in the admin under *Navigation
items*. Startup refuses `"db"` without the app (`E531`).

An entry has:

| Key | Takes |
|---|---|
| `label` | the text of the entry, required |
| `route` | an app path that starts with `/`, such as `/products`. An entry without a route is a group |
| `icon` | an icon name the frontend knows (`home`, `bar-chart`), optional |
| `order` | the place among its siblings, default 0, then the list order. A `NavItem` has `position` instead |
| `requires` | `public`, `authenticated` (the default) or a permission pattern |
| `children` | a group's entries |

`requires` takes one of three:

- `public`: everyone, signed in or not.
- `authenticated`: every signed-in user.
- a permission pattern as `KARNI_ROLES` writes it: `catalog.product:view`,
  `catalog.*:view`, `catalog.region:*` or `*`. The entry opens for a user who
  holds a grant for a permission the pattern names, from a role or a per-user
  grant. An expired user grant opens nothing. A superuser holds every
  permission. This is `grants_for`, what `Granted()` and `user.can` read, so
  the menu and the API always agree.

A group is an entry without a route. It shows when its own requirement opens
and at least one entry inside it shows, so a group whose entries are all
hidden is left out. Groups nest. A group's requirement defaults to
`authenticated` like any entry, so a group that holds a `public` entry says
`"requires": "public"` too. An entry with a route has no children: startup
refuses that in the settings (`E530`), and the admin form refuses it in the
table (`E536`).

## The endpoint: `GET /api/navigation/`

While `KARNI_NAVIGATION` is set, `karni.api.urls` mounts `navigation/`
first: the menu of the requesting user, signed in or not. A catalog editor
whose role holds `catalog.product:*` and `catalog.category:view` gets:

```json
{
  "items": [
    {"label": "Home", "icon": "home", "route": "/", "children": []},
    {
      "label": "Catalog",
      "icon": "box",
      "route": null,
      "children": [
        {"label": "Products", "icon": null, "route": "/products", "children": []},
        {"label": "Categories", "icon": null, "route": "/categories", "children": []}
      ]
    },
    {"label": "Account", "icon": null, "route": "/account", "children": []}
  ]
}
```

A visitor who is not signed in gets the `public` entries. Both sources give
the same response for the same menu. The requirement is not in the response.

It is one response per user and cheap: no query for `public` and
`authenticated` entries, one query for the role grants once an entry names a
permission, one more for the user grants while `KARNI_USER_GRANTS` is on, and
one for the `NavItem` rows of the database source. At most three queries,
whatever the size of the menu, besides the ones that sign the user in.

The OpenAPI schema describes the response as the `Navigation` and
`NavigationItem` components (`operationId` `navigation`), so `karni types`
writes their types. Unset, the route does not exist and the schema leaves it
out. A URLconf built while it was set answers 404 `E535`.

## The menu in the React app

`@karni/ui`'s `Layout` renders the server's menu with one prop:

```tsx
const pathname = useRouterState({ select: (state) => state.location.pathname });

<Layout navSource="server" pathname={pathname} navItems={fallbackItems}>
  <Outlet />
</Layout>
```

- `useNavigation()` reads `GET /navigation/` through the `KarniProvider`
  client, cached per signed-in user (`karniKeys.navigation(user)`), so a
  sign-in or a sign-out reads the menu again.
- Groups collapse behind a button (`aria-expanded`, `aria-controls`) that
  Enter and Space open and close. A group opens by itself while it holds the
  current page.
- The current page is the item whose route is `pathname`, else the item with
  the longest route `pathname` is under (`/products/42` is under
  `/products`). It gets `aria-current="page"`. Without `pathname`, Layout
  reads `window.location.pathname`.
- Icons come by name: `defaultNavIcons` knows `home`, `list`, `grid`,
  `dashboard`, `folder`, `file`, `chart`, `bar-chart`, `settings`, `sliders`,
  `user`, `users`, `box`, `calendar`, `map`, `tag` and `search`. The `icons`
  prop adds names or replaces these. An unknown name shows no icon.
- While the menu loads, the nav shows placeholders. When the request fails,
  it shows `navItems`.

Static menus take groups too: `navItems` accepts `{ label, icon, children }`
next to links. `navigationEntries(items, { pathname, icons })` turns the
server's items into those entries on their own, and the `NavGroup` slot
replaces how a group renders. The scaffold's `layout.tsx` keeps its menu from
the routes until you pass `navSource="server"`.

## The admin

`NavItem` has the tree changelist of the [admin](admin.md): entries in tree
order, each label indented by its depth, with the route, the requirement and
the icon. The form takes the label, route, icon, requirement, parent and
position, and checks each one (`E530`, `E532`, `E536`). Every change is in
the [change history](change-history.md).

*Menu preview*, a button on the changelist (`preview/`), shows the menu one
user gets: pick them by email or id, or a visitor who is not signed in. It is
exactly what `GET /api/navigation/` answers that user, with each entry's
requirement next to it. Previewing someone else's menu shows what they may
do, so it needs what *Effective permissions* needs: the permission matrix's
`view`.

## `karni check`

`karni check` compares the menu with the project while `KARNI_NAVIGATION` is
set. The settings source is always compared, and the database source when its
database answers.

| Code | Problem |
|---|---|
| [E533](errors.md#e533) | an item's route is served by no page of the frontend. The message names the closest route |
| [E534](errors.md#e534) | an entry's requirement names no permission of the project, so only a superuser would see it |
| [W630](errors.md#w630) | the database menu could not be read, so it was not compared |
| [W631](errors.md#w631) | no `KARNI_NAVIGATION_PAGES` file exists, so the routes were not compared |

The frontend's pages are the `path:` entries of the files in
`KARNI_NAVIGATION_PAGES` (default `frontend/src/routes.tsx`, where `karni make
page` and `karni build` register each page). A `$param` segment takes any
value. `KARNI_NAVIGATION_PAGES = []` turns the comparison off, for a menu
whose client Karni cannot read (a mobile app). A code in
`SILENCED_SYSTEM_CHECKS` is left out.

```text
navigation: karni.E533: Navigation item 'Catalog > Products' links to /prodcts, which no page of the frontend serves. The closest route is /products.
```

## In `karni.yaml`

The spec's `navigation` key writes `KARNI_NAVIGATION` into the settings
block ([details](app-spec.md#navigation)):

```yaml
pages:
  - home: dashboard
  - Product: [list, detail, form]
  - Category: [list]
  - reports: code
navigation:
  - home
  - Catalog: {icon: box, items: [Product, Category]}
  - reports: {icon: bar-chart}
```

`navigation: true` is every page with a route in `pages` order. Each page's
requirement comes from its access.

## Escape hatches

- `menu_for(user, nodes=...)` filters any tree of `NavNode` (a project's own
  source), and `opens(requirement, user)` is the requirement check alone.
- `NavigationView` is a plain view: subclass it, override `get_menu`, and
  declare `path("api/navigation/", YourView.as_view())` before the API
  include.
- `NavItemAdmin` is an ordinary admin: unregister `NavItem` and register your
  own.
- `Layout`'s `sidebar` replaces the whole nav, and `navItems` without
  `navSource` keeps a menu of your own.

## Codes

| Code | Problem |
|---|---|
| [E530](errors.md#e530) | `KARNI_NAVIGATION` or a `NavItem` field is not valid |
| [E531](errors.md#e531) | `KARNI_NAVIGATION = "db"` without the `karni.navigation` app |
| [E532](errors.md#e532) | an entry's requirement is not valid |
| [E533](errors.md#e533) | an item's route is served by no page |
| [E534](errors.md#e534) | a requirement names no permission |
| [E535](errors.md#e535) | navigation is turned off |
| [E536](errors.md#e536) | an entry has both a route and entries |
| [W630](errors.md#w630) | the database menu could not be read |
| [W631](errors.md#w631) | no frontend pages file to compare with |
| [C640](errors.md#c640) | `navigation` names a page the spec does not have |
| [C641](errors.md#c641) | a `navigation` entry is not valid |
| [C642](errors.md#c642) | a `navigation` requirement is not valid |
