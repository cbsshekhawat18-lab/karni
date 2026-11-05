## Rules for this task

Nobody is available to answer questions. Decide yourself and build the whole app.

The app is a Django project with a JSON API under `/api/` and a React app in `frontend/`. The
database is PostgreSQL, read from the `DATABASE_URL` environment variable (already set). Your
virtualenv is active.

After you stop, a script checks the app. It runs `python manage.py migrate`, starts
`python manage.py runserver` on a free port, creates its test accounts, calls the API and
runs `npm run build` in `frontend/`. The app counts as done when every check passes and the
frontend builds.

The checks are in `acceptance/` (pytest and requests, black box). You may run them yourself
against your running server: `BENCH_BASE_URL=http://127.0.0.1:8000 pytest acceptance`. They create
their test accounts with the management command `create_account` (see "Accounts" in the
contract), so the app must provide it. Do not edit `acceptance/`: the script uses its own copy.
