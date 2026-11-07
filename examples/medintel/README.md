# Medintel: the Karni large-app reference

A medical-intelligence portal on synthetic data: clinical trials, the
companies and people behind them, brands and deals, tagged to a condition
tree and an intervention tree. Customers see only the rows under the nodes
granted to them. Every name, company, trial, person and number is invented.

It lives in the Karni repository and runs in CI, so a framework change that
breaks a large, data-heavy app breaks the build. It was built from
[`karni.yaml`](karni.yaml) with `karni build`, and the project wrote only what
the spec cannot say. What that took, and what was missing, is in the
[friction log](../../docs/friction/medintel.md).

**Project code: 486 lines** (spec 144, models 28, seeds 143, pages 171),
measured with `python scripts/loc.py --pristine <karni new output>`. That
counts the non-blank, non-comment lines of what Medintel wrote by hand.
`karni build` wrote the rest: the models, API, admin, seeders, migration,
generated pages and tests in `intel/karni/`, `intel/tests/karni/` and
`frontend/src/pages/karni/`, and the settings block. The spec is counted
because it is the input an agent writes.

## What it shows

| Feature | Where |
|---|---|
| Trees: Condition and Intervention | `tree: true` in `karni.yaml`, seeded as 90 and 35 nodes in `intel/seeds.py` |
| Taxonomies: a Trial's conditions and interventions, a Company's, Brand's and Deal's interventions | `taxonomies:` in `karni.yaml` |
| The tree scope and per-user grants | `KARNI_USER_GRANTS`, the grants of the demo customers in `intel/seeds.py`, `tests/test_grants.py` |
| Aggregations and saved charts | `aggregate:` on Trial, Company and Deal, two `Chart` rows in `intel/seeds.py`, `SavedChart` in `frontend/src/pages/deals-chart.tsx` |
| Cross-model search | `global_search:` on every model, `frontend/src/pages/search.tsx` and the palette in `layout.tsx` |
| Markdown fields, field groups, column sets | `markdown?` fields, `groups:` and `column_sets:` on Trial and Company |
| Navigation from data | `navigation:` in `karni.yaml`, `navSource="server"` in `layout.tsx` |
| Page blocks | `DashboardGrid`, `ChartCard`, `DataTable` and `TreeView` in `insights.tsx` and `players.tsx`, related tabs and markdown sections on the generated company page |
| Sign in with a code and with a Google ID token, in JWT mode | `features:` in `karni.yaml`, `frontend/src/pages/login.tsx`, `tests/test_sign_in.py` |
| The terms gate | `terms:` in `karni.yaml`, `TermsGate` in `App.tsx` |
| Response caching that never mixes scopes | `api_cache:` in `karni.yaml`, `test_the_cache_never_mixes_two_users_scopes` |
| Import and export, and the admin | every model, `tests/test_transfer.py`, `tests/test_admin.py` |

The models are `Condition` and `Intervention` (trees), `Company`, `Person`,
`Trial` (phase, status, start year, enrollment, four markdown sections in
four groups), `Brand` and `Deal` (value, year, two companies).

## The pages

- **Trials dashboard** (`/insights`): trials by phase, by status, per year by
  phase and the enrollment per year, each an aggregate under the user's grants.
- **Players** (`/players`): pick an intervention category in a `TreeView` that
  greys what you may not open. A `DataTable` lists the companies under it
  and a chart shows the deal value of the five biggest buyers.
- **Deals** (`/deals-chart`): the two charts saved in the admin, narrowed to a
  category.
- **Company detail** (`/companies/$id`): markdown sections in two groups and
  tabs for the company's trials and brands.
- **Search** (`/search`, and Ctrl or Cmd+K anywhere): one query over seven
  models, each under its own access.

## Who sees what

A customer has no role grants. Each login in the demo has user grants on tree
nodes, and the grants of one user are a union.

| Login | Granted | Sees |
|---|---|---|
| `analyst@example.com` | the condition Oncology and the intervention category Biologics | trials under either, and the companies, brands, deals and people under Biologics |
| `oncology@example.com` | the condition Oncology | trials under Oncology only. Companies, deals, brands and people answer 403 |
| `vaccines@example.com` | the intervention category Vaccines | the trials, companies, brands, deals and people under Vaccines |
| `demo@example.com` | staff | everything |

The two trees themselves are readable by every signed-in user. See the
friction log for why.

## Run it

```sh
cd examples/medintel
python3.12 -m venv .venv
.venv/bin/pip install -e ../../packages/karni -e ../../packages/karni-cli -e ../../modules/karni-charts \
    'psycopg[binary]' pytest pytest-django
cp .env.example .env            # DATABASE_URL and REDIS_URL point at your PostgreSQL and Redis
(cd ../../packages/karni-ui && npm ci && npm run build)
(cd ../../modules/karni-charts/ui && npm ci && npm run build)
karni migrate && karni seed --reset --seed 42
karni serve --local             # Django on :8000
cd frontend && npm install && npm run dev   # http://localhost:5173
```

`karni seed` prints the demo login (`demo@example.com`, password
`karni-password`) and the three customers from `KARNI_SEED_LOGINS`. The seed
is 90 conditions, 35 interventions, 40 companies, 80 people, 300 trials, 60
brands and 120 deals, the same rows on every machine. Sign-in by email
needs outgoing mail, or read the code from the console backend. Google sign-in
needs a real web client id in `KARNI_SOCIAL_GOOGLE_CLIENT_IDS` and
`VITE_GOOGLE_CLIENT_ID`. A new address or Google account waits for staff to
tick Active (`KARNI_EMAIL_OTP_SIGNUP=approval`).

To change the app, edit `karni.yaml` and run `karni build`: it rewrites what
it owns and leaves `intel/models.py`, `intel/seeds.py` and the pages in
`frontend/src/pages/` alone.

## Tests

```sh
python -m pytest -q                              # 51 tests on the seeded database
python -m pytest -q --pyargs karni.testing.architecture
karni check && karni rules sync --check
```

The grant tests compare each API list with the same rows read from the
database by the tree walk, for the list, search, facets, aggregates, saved
charts, export and the menu. The sign-in tests use a fake key set, so no
network is needed. CI runs the same in the `medintel` job.
