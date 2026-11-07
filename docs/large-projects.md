---
description: "Karni's tooling for projects with 100 models or more (experimental): karni context one area at a time, a karni check that skips unchanged files, karni seed --volume for realistic row counts, configurable scaling budgets, karni queries --explain on PostgreSQL and a CI benchmark."
---

# Large projects

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    `karni context --summary`, `--app`, `--model` and `--max-tokens`,
    `manage.py karni_context`'s flags of the same names, the check cache
    (`karni check --changed` and `--no-cache`, `manage.py karni_check
    --changed` and `--no-cache`, `.karni/local/check-cache.json`,
    `karni.testing.checkcache`), `karni seed --volume` and `--batch-size`,
    `karni.bulk_seeding`, the seed ledger (`.karni/local/seeded.json`),
    `karni.performance.Scaling` and `query_scaling`, `karni queries
    --explain`'s analysis (`karni.api.explain`), the settings
    `KARNI_CHECK_CACHE`, `KARNI_SCALING_ROWS`, `KARNI_SEED_BULK_THRESHOLD`,
    `KARNI_SEED_BATCH_SIZE`, `KARNI_SEED_LEDGER` and
    `KARNI_EXPLAIN_SEQ_SCAN_ROWS`, and `scripts/benchmark/large_project.py`.
    They may change in a minor release, with a CHANGELOG entry. The error
    codes keep their meaning.

A project with a hundred models or more strains the tools an agent runs again
and again. The inventory no longer fits in one read, `karni check` reads
every file each time, the demo seed makes ten rows per table when the slow
query only shows at a hundred thousand, and nothing finds the missing index
before production does. This page covers what Karni does about each.

## Context, one area at a time

`karni context` prints the whole inventory, and on a large project it caps
the models it lists. Read one area at a time instead:

```sh
karni context --summary                  # one line per app: models, viewsets, pages
karni context --app catalog              # one app in full
karni context --model catalog.Product    # one model in depth (repeatable)
karni context --app catalog --max-tokens 1500
```

`--summary` prints one `APP` line per app with its models (the first 20
named), its viewsets and its pages, with their counts:

```text
KIND: app (an API and a React app for signed-in users ...)
APPS: catalog(catalog/) orders(orders/) regions(regions/)
SUMMARY: 3 apps, 31 models, 29 viewsets. One app: karni context --app <label>. One model: karni context --model <name>.
APP catalog: 12 models (Category Product Supplier ...), 11 viewsets, 6 pages
APP orders: 14 models (Order OrderLine Payment ...), 13 viewsets, 4 pages
APP regions: 5 models (Region Country City Office Zone), 5 viewsets, 0 pages
```

`--app LABEL` prints that app in full: every model with up to twelve fields,
the key types, the relations out of the app and `in:` the relations from
other apps into it, the active scopes, each viewset with its route and
access, the roles and actions that reach the models, the field visibility,
the declared performance exceptions and the pages named after the models.
`--model NAME` (a name or `app_label.Name`) prints one model in depth: where
the class is, its key and table, every field in the spec's words (`str:200`,
`fk:Category?`, `decimal:10,2`, `choices(draft,live)`), the relations that
point at it, its viewsets with their search fields, and its pages. An unknown
name is `E470` with the names that come close, and a bare name two apps share
is `E471`.

`--max-tokens N` cuts the output at whole sections (a line with the indented
lines under it) to about N tokens, four characters each, and ends it with a
line that says what was left out and the command that prints it:

```text
LEFT OUT: VIEWSETS ROLES PERF PAGES BASES (~640 tokens). karni context --app catalog prints them.
```

Without these flags `karni context` prints what it always printed.

## The check cache

`karni check` keeps the results of the checks that read files one by one in
`.karni/local/check-cache.json`, under each file's content hash. On the next
run an unchanged file is not read again. These checks use the cache: the
architecture rules that parse the source (`raw-sql`, `http-client`,
`access-override`, `unpaginated-action`, `audited-bulk-write`) and the
duplication check's fingerprints, of the project and of Karni's own source.
ESLint keeps its own cache in `.karni/local/eslintcache`. The checks that
read the whole project always run: Django's system checks (the models, the
migrations, the URL routing), the external tables, the rules that inspect
classes, jscpd and every `karni.checks` hook of a module.

```sh
karni check                    # an unchanged file comes from the cache
karni check --changed          # only the files git reports as changed
karni check --changed main     # the files changed since main
karni check --no-cache         # read every file again
```

The backend prints how much it reused: `check cache: 1459 of 1459 file
results reused`. The cache is ignored whole when another Karni, Django or
Python version wrote it, or other settings (every `KARNI_*` setting,
`INSTALLED_APPS` and the installed check hooks are part of its fingerprint).
A check whose other inputs changed (the audited models of
`audited-bulk-write`) drops its own entries.

`--changed` asks git for the files changed in the working tree and the index
against `HEAD` (against `REF` with `--changed REF`), plus the untracked files
git does not ignore. The file checks and ESLint read only those, and every
check reports only their findings. The whole-project checks still run in
full. Outside a git repository, or with a ref git does not know, it stops
with `C581`.

`KARNI_CHECK_CACHE = False` turns the cache off for a project, and a path
moves the file. On the 100-model benchmark project a cached `manage.py
karni_check` takes 1.5 s against 2.5 s without the cache, and the whole
`karni check` 4.4 s against 8.1 s cold. The rest of the run is Django's
start and its system checks, which read the whole project.

## Volume seeding

The demo seed (`karni seed`, see [seeding](seeding.md)) makes ten connected
rows per table. A query that slows down at a hundred thousand rows needs a
hundred thousand rows:

```sh
karni seed --volume 100000                        # 100,000 rows per model
karni seed --volume 100000 --model shop.Order     # only these models, and what they need
karni seed --volume 20000 --batch-size 5000
```

The models are seeded in the demo seed's order, the targets of a relation
before the model that points at them. Each model's rows are built with the
same factories, so the inferred values and every override in `<app>/seeds.py`
apply, then written with `bulk_create` in batches (`--batch-size`,
`KARNI_SEED_BATCH_SIZE`, default 2000). A foreign key is drawn from the
target's existing rows, a one-to-one target is used once, a relation to the
model itself points at rows of earlier batches (so a tree gets depth), and a
many-to-many gets zero to three targets per row. Free text repeats from a
pool of a thousand values per field, because text is the costly value to
make. The user model gets one user per hundred rows, the demo way, with the
demo login. The report has the rows, the time and the rate per model:

```text
Seeded 3 model(s) with seed 0 (volume 100000) in 74.6s:
  testapp.Tag    100000  (bulk, 16.4s, 6,102 rows/s)
  testapp.Venue  100000  (bulk, 15.5s, 6,451 rows/s)
  testapp.Event  100000  (bulk, 38.7s, 2,584 rows/s)
```

That run is on PostgreSQL on a laptop. `Event` has two foreign keys and a
many-to-many, so its 100,000 rows bring about 200,000 links.

Bulk rows skip `save()`: no `post_save` is sent and no change history is
written for them. A seeder that overrides `Seeder.seed()` keeps full
control, and its model is seeded row by row through that method.

Volume rows never mix with real content. Every seed run records, per
database, how many rows each table holds when it is done, in
`.karni/local/seeded.json`. `karni seed --volume` refuses (`E473`) when a
table holds another number of rows than the ledger recorded, because someone
else wrote to it. `--reset` wipes the project's tables first, and `--force`
adds rows anyway. So a demo seed followed by a volume seed, or two volume
runs in a row, go through, while a table with real rows stops the run.
`KARNI_SEED_LEDGER = False` turns the ledger off, and a volume run then needs
empty tables, as the demo seed does.

A model whose seed count reaches `KARNI_SEED_BULK_THRESHOLD` (default 1000)
takes the bulk path in a plain `karni seed` too. That is how a large `seed`
count in [`karni.yaml`](app-spec.md#seed) reaches it: `karni plan` shows the
volume and how long it takes, and `karni build` seeds it in bulk.

## The scaling check

The scaling check in the architecture suite measures every routed
viewset's `list` with 2 and with 12 rows, and `retrieve` with 2 and with 12
related rows, and fails when the query count grows (see
[testing](testing.md#3-the-scaling-check)). Both numbers can move:

```python
# config/settings.py
KARNI_SCALING_ROWS = [2, 50]
```

```python
# catalog/viewsets.py
from karni.api import Scaling


class ProductViewSet(karni.ProductViewSet):
    query_scaling = Scaling(rows=(5, 500), seconds=0.3)
```

`rows` overrides the setting for one viewset. `seconds` is a time budget:
the request at the large row count (the faster of two runs) must take no
longer. A failed budget is `E476` and names the endpoint, the rows, the time
and the queries, with the statements:

```text
ProductViewSet.list (GET /api/products/): 500 rows took 0.412s against a time budget of 0.3s, in 4 queries.
```

A declaration that is not two row counts (small then large) or a positive
number of seconds is `E477`. `karni context` lists every `query_scaling` on
its `PERF` line.

## Query plans: `karni queries --explain`

`karni queries ENDPOINT --explain` (see [find an N+1](debugging/queries.md))
adds the plan of every query. On PostgreSQL it runs `EXPLAIN (ANALYZE, FORMAT
JSON)` of each distinct `SELECT` the endpoint ran, each in a savepoint inside
the request's transaction, which is rolled back: `ANALYZE` runs the query and
nothing it does stays. Each plan prints with the actual rows, loops and time
of every node, and each sequential scan on a table of
`KARNI_EXPLAIN_SEQ_SCAN_ROWS` rows or more (default 1000) is a `W611` finding
that names the index that would serve its filter or its sort:

```text
EXPLAIN SELECT … FROM "catalog_product" WHERE ("catalog_product"."deleted_at" IS NULL AND UPPER("catalog_pro…
  Limit (actual rows=50 loops=1 time=1.500ms)
    Sort (actual rows=50 loops=1 time=1.497ms)
      Sort Key: created_at DESC
      Seq Scan on catalog_product (actual rows=111 loops=1 time=1.477ms)
        Filter: ((deleted_at IS NULL) AND (upper((name)::text) ~~ '%LAMP%'::text))
        Rows Removed by Filter: 4889
  Execution Time: 1.512ms

Sequential scans on large tables (1):
  W611 Seq Scan on catalog_product (5,000 rows, 5,000 read, 111 kept) for ((deleted_at IS NULL) AND (upper((name)::text) ~~ '%LAMP%'::text)): add GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="product_name_trgm_idx", condition=Q(deleted_at__isnull=True)) to Product.Meta.indexes (GinIndex and OpClass come from django.contrib.postgres, Upper from django.db.models.functions, and the index needs the pg_trgm extension)
```

The suggestion puts the equality columns first, then one range column, and
with neither a `LIKE` (a search, `icontains`) asks for a trigram index and a
sort asks for an index on its keys. The soft-delete filter becomes the
index's `condition`. When the filter keeps most of the rows read, the finding
says an index would not help, and when an index on the column exists and the
planner read the table anyway, it says to run `ANALYZE` on the table. The
`--json` output has the findings under `seq_scans`.

Only PostgreSQL has a plan Karni reads. On another database `--explain` keeps
its plain `EXPLAIN` of the three slowest statements and says so (`W610`).
Run it against PostgreSQL with data at volume (`karni seed --volume`) to see
where an index is missing.

## The benchmark

`scripts/benchmark/large_project.py` makes a large project the way a user
does and times the tooling on it. It runs `karni new` (and removes
`frontend/`, so it needs no npm), writes a `karni.yaml` of N entities spread
over apps (seven fields each, a relation to the entity before it in its app,
and every third one a relation into the app before), runs `karni build`,
then times `karni check` (cold, cached, after one edit, and `--changed` after
one edit in a git repository), `karni context` (whole, `--summary` and
`--app`) and the project's tests. The project runs on SQLite in its own
folder with an in-process cache.

```sh
python scripts/benchmark/large_project.py                       # 100 models, against the baseline
python scripts/benchmark/large_project.py --models 5 --apps 1   # a quick run
python scripts/benchmark/large_project.py --out times.json --keep ../bench
python scripts/benchmark/large_project.py --record              # write the baseline
```

The times go to stdout and `--out` as JSON. Machines differ, so each run
first times a fixed piece of pure Python work (the calibration) and scales
the baseline's times by it. A step fails the run when it takes more than
`baseline x scale x threshold + slack` (`--threshold`, default 1.5, and
`--slack`, default 1 s, which keeps a step under a second from failing on
noise). The CI job `Benchmark (100 models)` runs it on every push and keeps
the times as an artifact. The baseline in `scripts/benchmark/baseline.json`
was recorded on a laptop (Apple silicon, macOS, Python 3.12): after a change
that makes a step slower on purpose, record a new one with `--record` and
commit it.

The calibration is pure Python, and the project's tests are not: relative to
it, they ran 1.4 to 1.7 times slower on GitHub's Linux runners than on that
laptop, in three runs of the same code. So the CI job compares with
`scripts/benchmark/baseline-ci.json`, the times of one CI run (the middle of
those three), and the laptop's baseline stays for runs on a laptop. A change
that slows a step on purpose records both: `--record` on the laptop, and the
CI job's `benchmark` artifact copied to `baseline-ci.json`.

| Step | Baseline |
|---|---|
| `karni check`, cold | 8.05 s |
| `karni check`, cached | 4.35 s |
| `karni check`, after one edit | 4.12 s |
| `karni check --changed`, after one edit | 3.20 s |
| `karni context` | 2.51 s |
| `karni context --summary` | 2.57 s |
| `karni context --app` | 2.54 s |
| the project's tests (102) | 83.8 s |
