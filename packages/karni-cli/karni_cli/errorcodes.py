"""Error codes: the CLI's own (``C``), and lookup across every registry for ``karni explain``.

Every :class:`~karni_cli.project.CliError` carries a ``C`` code (or passes
through a Karni code such as ``E704``). :func:`lookup` finds any code offline:

- ``E``/``W`` codes: Karni's registry (``karni.errorcodes``), read from the
  monorepo source or the copy bundled into this wheel (``karni_cli/_errorcodes``)
  — no Django, no project needed;
- ``C`` codes: :data:`CODES` below;
- module codes (``PAY001``): ``karni.errorcodes`` entry points installed next to
  karni-cli, else the project interpreter (``python -m karni.errorcodes``);
- ``K`` codes: the agent rules (``karni rules --explain``).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NamedTuple

__all__ = ["CODES", "CliCode", "core_module", "docs_url", "failures_module", "lookup"]

_MODULE_NAME = "karni_cli._bundled_karni_errorcodes"
_FALLBACK_BASE = "https://cbsshekhawat18-lab.github.io/karni/"


class CliCode(NamedTuple):
    code: str
    title: str
    why: str
    fix: str
    source: str
    kind: str = "cli"

    def as_dict(self) -> dict[str, str]:
        return {**self._asdict(), "url": docs_url(self.code)}


def _c(code: str, title: str, source: str, why: str, fix: str) -> CliCode:
    return CliCode(code=code, title=title, why=why, fix=fix, source=source)


CODES: Final[tuple[CliCode, ...]] = (
    # C0xx project and environment
    _c(
        "C001",
        "Not inside a Karni project",
        "karni_cli.project.require_project and every project command",
        "Project commands find the project by walking up to the directory with manage.py "
        "(and config/settings.py).",
        "cd into the project (or a directory below it), or create one: karni new <name>.",
    ),
    _c(
        "C002",
        "No way to run the project's Python",
        "karni_cli.project (runners: serve, migrate, test, shell, seed, ...)",
        "Project commands run in the project's own interpreter: its .venv, else the "
        "active virtualenv (VIRTUAL_ENV), else the running docker compose stack.",
        "Create the venv (python -m venv .venv && .venv/bin/pip install -e .), activate "
        "one that has the project's dependencies, or start the stack (docker compose up "
        "-d). The message says which one the command looked for.",
    ),
    _c(
        "C003",
        "Docker is not installed",
        "karni_cli.project",
        "Without --local, karni runs the project through docker compose.",
        "Install Docker with the compose plugin, or run on the host: karni serve --local "
        "(with a .venv).",
    ),
    _c(
        "C004",
        "These options cannot be combined",
        "karni serve, karni make model/page/schedule",
        "Some options only apply in a particular mode (for example --host needs --local).",
        "Drop one of the options as the message says, or add the option it needs.",
    ),
    _c(
        "C005",
        "This karni-cli install is incomplete",
        "karni_cli (bundled templates, agent rules, changelog, error codes)",
        "The wheel bundles the project template, agent rules, changelog, error codes and the "
        "settings reference. One is missing, so the install is broken.",
        "Reinstall karni-cli (pipx reinstall karni-cli, or pip install --force-reinstall "
        "karni-cli).",
    ),
    _c(
        "C006",
        "An optional tool is not installed",
        "karni mcp, karni types, karni ui detect",
        "Some commands need extra tools: the MCP SDK for karni mcp, Node and "
        "openapi-typescript for karni types, Node for karni ui detect to evaluate a "
        "tailwind.config.",
        "Install what the message names, e.g. pip install 'karni-cli[mcp]', or add "
        "openapi-typescript to frontend devDependencies (Node 20+).",
    ),
    _c(
        "C007",
        "A configuration value is invalid",
        "karni config, KARNI_AGENT_SOURCE, KARNI_TEMPLATES, KARNI_UI_SRC, KARNI_DEV_PORT",
        "karni reads its settings from karni config files and a few environment variables "
        "(the project's .env included).",
        "Use a value the message lists (karni config shows the known settings), or unset "
        "the environment variable.",
    ),
    _c(
        "C008",
        "A file cannot be written",
        "karni config, karni ui detect",
        "The file or its directory is not writable.",
        "Check the path's permissions. For karni config, set the value per project instead of "
        "--global. For karni ui detect, choose another place with --output.",
    ),
    _c(
        "C009",
        "A command in the project failed",
        "karni context, karni upgrade, karni rules (project interpreter)",
        "karni ran manage.py or Python in the project and it exited with an error.",
        "Read the project's error in the message (often a settings or import error), fix "
        "it, and re-run. `karni doctor` checks the environment.",
    ),
    _c(
        "C010",
        "The path is not a file inside the project",
        "karni rules --check, karni context --with-history",
        "These commands read files of the current project only.",
        "Pass an existing file path inside the project.",
    ),
    _c(
        "C011",
        "pytest is not installed in the project interpreter",
        "karni test",
        "karni test runs `python -m pytest` through the project's interpreter (its .venv, the "
        "active virtualenv, or the compose service). pytest and pytest-django are in the "
        "project's dev dependency group, not in karni.",
        "Install them there: pip install pytest pytest-django (or `uv sync` for the dev "
        "group), then run karni test again.",
    ),
    _c(
        "C012",
        "The project's database driver is not installed",
        "karni_cli.database (every command that starts Django: check, context, migrate, "
        "serve --local, test, ...)",
        "Django imports the database driver as it starts (psycopg for PostgreSQL), so "
        "without it every project command stops with a traceback. A venv made for the "
        "quickstart has none: the quickstart uses SQLite.",
        'Install the driver into the project interpreter: pip install "psycopg[binary]" (or '
        "pip install -e . for all of the project's dependencies). Or run in Docker: `karni "
        "serve -d` starts the stack, whose image has the driver, and --docker runs a project "
        "command inside it. KARNI_DB_CHECK=false skips the check.",
    ),
    _c(
        "C013",
        "The project's database cannot be reached",
        "karni_cli.database (commands that open the database: migrate, seed, sync-roles, "
        "createsuperuser, serve --local, test, beat, manage)",
        "These commands open the database at DATABASE_URL first. A server that is not "
        "running, a host that does not resolve (the compose default `db`, from the host) or "
        "rejected credentials would stop them with a traceback.",
        "Start the database (`karni serve -d` runs the compose stack with PostgreSQL), or point "
        "DATABASE_URL in .env at one that runs (cp .env.example .env first). "
        "DATABASE_URL=sqlite:///db.sqlite3 needs no server. The message names the address and the "
        "driver's error. KARNI_DB_CHECK=false skips the check.",
    ),
    # C1xx karni make
    _c(
        "C101",
        "The file karni make would write already exists",
        "karni make (every generator)",
        "Generators never overwrite your code silently.",
        "Pass --force to overwrite (or, for multi-file generators, to create only the "
        "missing files), or remove the file first.",
    ),
    _c(
        "C102",
        "Which app? (none, unknown, or several)",
        "karni make (generators that write into an app)",
        "Generators write into a local app listed in the `# karni:apps` block of "
        "config/settings.py.",
        "Create one (karni make app <name>), or choose one with --app <label>.",
    ),
    _c(
        "C103",
        "The name is not valid here",
        "karni make, karni new",
        "Names become Python modules, classes, URLs or task names, each with its own rules, "
        "and must not shadow existing modules or Django/Karni commands.",
        "Use the form the message shows (snake_case module, CamelCase model, kebab-case "
        "module or route) and a name nothing else uses.",
    ),
    _c(
        "C104",
        "A field spec is invalid",
        "karni make model (name:type[:arg][?] fields)",
        "Fields are written as name:type[:arg][?], e.g. title:str:200 or starts_at:datetime?, and "
        "relations name their target model.",
        "Fix the field the message names. `karni make model --help` lists the types.",
    ),
    _c(
        "C105",
        "Something the generator builds on does not exist yet",
        "karni make (viewset, test, serializer, listener, schedule, ...)",
        "Generators wire new code into existing code: a viewset needs its model, a test its "
        "viewset, a listener its event.",
        "Run the karni make command the message names first, then re-run this one.",
    ),
    _c(
        "C106",
        "An option value is invalid",
        "karni make, karni new, karni types, karni ui detect",
        "The option accepts specific values (the message lists them).",
        "Use one of the values shown, e.g. --access owned:organizer or --every 15m.",
    ),
    _c(
        "C107",
        "The new code would clash with existing code",
        "karni make (component, viewset, schedule, page, service)",
        "Two components claiming one role, two viewsets for one model, or two schedules "
        "or routes with one name would shadow each other.",
        "Extend or edit the existing code the message names, or choose another name.",
    ),
    _c(
        "C108",
        "A karni marker is missing from a project file",
        "karni make, karni add (settings.py and routes.tsx markers)",
        "Generators insert code at `# karni:` / `// karni:` markers that karni new writes. Older "
        "or hand-edited projects may lack them.",
        "Add the change by hand as the message shows, or restore the marker from a fresh "
        "karni new project.",
    ),
    _c(
        "C109",
        "An explicit serializer needs a reason",
        "karni make serializer",
        "BaseViewSet generates the serializer from the model (rule K106), so a hand-written one "
        "must say why it exists.",
        'Pass --reason "<why>", or tune the generated serializer with APIMeta instead.',
    ),
    _c(
        "C110",
        "A project file cannot be parsed",
        "karni make (reads your Python before editing it)",
        "karni make edits your files structurally and stops rather than guess.",
        "Fix the syntax error at the file and line in the message, then re-run.",
    ),
    _c(
        "C111",
        "The design folder has nothing to import",
        "karni import design",
        "karni import design reads a folder of static pages: every .html file in it is a page "
        "(a meta-refresh stub is a redirect), and every other file is copied as an asset.",
        "Pass the folder that holds the design's index.html and the other pages, with its "
        "css/, js/ and image folders inside it.",
    ),
    _c(
        "C112",
        "The project's kind is not one Karni knows",
        "karni context, karni rules sync, karni add site (pyproject.toml [tool.karni] kind)",
        "`karni new` records the project's kind in pyproject.toml: site, app or site+app. The "
        "agent files and `karni context` state it with its stack, so a value Karni cannot "
        "read stops them instead of guessing.",
        'Set kind = "site", "app" or "site+app" under [tool.karni] in pyproject.toml (or remove '
        "the line, and Karni infers the kind from the project), then run `karni rules sync`.",
    ),
    _c(
        "C121",
        "The content map cannot be used",
        "karni design extract --map, karni import design --map",
        "The map says which structure of the design is which model and which element is which "
        "field. Extract follows it exactly, so a model, a field, a relation's target or a "
        "selector it cannot follow stops it before anything is written.",
        "Fix each problem the message lists in the map (the field names come from the map's "
        '"fields", the selectors are CSS with an optional @attribute), or write a fresh draft '
        "with karni design analyze <design> --map <file> --force.",
    ),
    _c(
        "C122",
        "The content map has decisions left",
        "karni design extract --map",
        "karni design analyze marks what the markup cannot settle with a decide entry: a list "
        "on a detail page or a few items on the home page may be hand-picked or derived by a "
        "query. Extract will not guess either way.",
        'For each one: keep the value (remove its "decide", and add the field to the model\'s '
        "karni make model command) or delete the value from the map and query the rows in the "
        "view.",
    ),
    _c(
        "C123",
        "A content map is there already",
        "karni design analyze --map",
        "The map is a file the agent edits: names, decisions, selectors. Writing a new draft "
        "over it would lose those edits.",
        "Write the draft to another file, or pass --force to replace the map.",
    ),
    # C140-C149 karni make model --external (experimental)
    _c(
        "C140",
        "The database to read the table from cannot be used",
        "karni make model --external",
        "`karni make model <Name> --external --table <table>` writes the model from the table's "
        "columns, so it reads them from the database (manage.py karni_inspect, in the project's "
        "interpreter). The database did not answer, the alias is not in DATABASES, or the "
        "project's karni has no karni_inspect command.",
        "Start the database or fix its settings (the message names the alias and the error), "
        "pass the alias with --database, or upgrade the project's karni. Then run the command "
        "again.",
    ),
    _c(
        "C141",
        "The table or view is not in the database",
        "karni make model --external",
        "The database answered, but has no table or view of that name, or the name has a schema "
        "(schema.table) on a database other than PostgreSQL, which has none.",
        "Check the name and the alias (--database). A PostgreSQL table in another schema is "
        "written schema.table, e.g. --table reporting.sales.",
    ),
    _c(
        "C142",
        "These options do not go with --external",
        "karni make model --external",
        "An external model's fields come from the table, so it takes no field list and needs "
        "--table. --table, --database and --writable describe an external model, so they need "
        "--external. Imports never write a read-only table, so --key does not apply.",
        "Run karni make model <Name> --external --table <[schema.]table> [--database <alias>] "
        "[--writable], with no fields.",
    ),
    _c(
        "C124",
        "A content map option has a value extract does not know",
        "karni design extract --map",
        'Some options of the map take one of a few values: a relation\'s "by" (absent for a '
        'link to the row\'s page, "key" for the row\'s key, "title" for its title), a key\'s '
        '"from" (page, link, attr, field, position) and "link" ("path"). A value outside them '
        "would be read some other way without a word, so extract refuses it.",
        "Write one of the values the message lists, or leave the option out for its default. "
        "docs/design-content.md#the-content-map describes each.",
    ),
    _c(
        "C199",
        "Internal error in karni",
        "karni make, karni upgrade",
        "A generator or codemod hit a case it does not handle. Nothing was written.",
        "Report it with the command and the file it stopped on. Meanwhile, make the change "
        "by hand.",
    ),
    # C2xx upgrade, rules, types, add
    _c(
        "C201",
        "karni upgrade needs a clean git work tree",
        "karni upgrade",
        "Codemods rewrite many files. A clean tree lets you review and undo them with git.",
        "Commit or stash first, preview with --dry-run, or pass --allow-dirty to write anyway.",
    ),
    _c(
        "C202",
        "karni upgrade does not downgrade",
        "karni upgrade",
        "Codemods only move code forward.",
        "Pass a --to version newer than the project's karni, or check --from.",
    ),
    _c(
        "C203",
        "That is not a version number",
        "karni upgrade (--to / --from)",
        "Versions are MAJOR.MINOR[.PATCH].",
        "Write e.g. --to 0.2 or --to 0.2.0.",
    ),
    _c(
        "C204",
        "No such rule or procedure",
        "karni rules, karni explain",
        "Rules (K codes) and procedures are listed by karni rules.",
        "Run `karni rules` for the codes and procedures, then use one of them.",
    ),
    _c(
        "C205",
        "The agent adapter configuration is invalid",
        "karni rules sync (karni.rules.py ADAPTERS)",
        "Adapters are the generated agent guidance files. Each has an id and a line cap.",
        "Use the adapter ids the message lists, and shorten project rules feeding an adapter "
        "that exceeds its cap.",
    ),
    _c(
        "C206",
        "The OpenAPI schema cannot be turned into types",
        "karni types",
        "karni types reads the backend's schema (x-karni-resource operations) to generate "
        "typed hooks.",
        "Make sure the backend serves Karni viewsets (karni routes) and the schema uses only "
        "local $refs.",
    ),
    _c(
        "C207",
        "karni add cannot edit pyproject.toml",
        "karni add",
        "karni add manages the [project].dependencies table of the project's pyproject.toml.",
        "Add the table (or the dependency) by hand, then re-run.",
    ),
    # C21x-C24x karni spec (experimental): karni.yaml
    _c(
        "C210",
        "No spec file",
        "karni spec validate",
        "karni spec validate reads a karni.yaml: by default the project root's, else the current directory's.",
        "Write one (docs/app-spec.md), export the project's with karni spec export -o karni.yaml, or pass --spec <file>.",
    ),
    _c(
        "C211",
        "The spec is not valid YAML",
        "karni spec validate (karni_cli.spec.validate)",
        "The spec is YAML. A syntax error stops everything else, and the parser names the line.",
        "Fix the line the message names: indent with spaces, and quote a value that holds ': ' or starts with *, &, !, %, @ or a backtick.",
    ),
    _c(
        "C212",
        "Unknown key in the spec",
        "karni spec validate (karni_cli.spec.validate)",
        "Every key of the format means one thing, so a misspelt key would be ignored without a word. A key that starts with x- is kept and ignored, for notes of your own.",
        "Fix the spelling (the message lists the keys that mapping takes), remove the key, or prefix it with x-.",
    ),
    _c(
        "C213",
        "A spec value has the wrong type, or a required key is missing",
        "karni spec validate (karni_cli.spec.validate)",
        "Values are never coerced: a list where a string is expected, or a number written for a text, is an error rather than a guess. version and app.name are required.",
        "Write the value in the form docs/app-spec.md shows for the key. Quote a value YAML would read as a date, a number or true/false.",
    ),
    _c(
        "C214",
        "Unknown spec version",
        "karni spec validate (karni_cli.spec.validate)",
        "version moves only for a breaking change of the format, and this karni reads version 1.",
        "Write version: 1, or upgrade karni-cli when the spec comes from a newer release.",
    ),
    _c(
        "C215",
        "A name in the spec is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "Names become code: app labels are Python packages, entities classes, pages file names and roles the slugs HasRole checks.",
        "Use snake_case app labels (not one Django, Karni or a module takes), PascalCase entities, kebab-case page names, and role slugs of letters, digits, _, . and -.",
    ),
    _c(
        "C216",
        "A field's type is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "Fields use karni make model's own syntax and are checked by its own parser and renderer, so the spec and the generator accept exactly the same fields. The message is the generator's, with its code.",
        "Write name: type[:arg...], a trailing ? for optional (karni make model --help lists the types and their arguments).",
    ),
    _c(
        "C217",
        "An access rule is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "An entity's access maps onto Karni's Access(read=..., write=..., create=...): each slot takes public, authenticated, granted, role:<slug> or owned:<field>, or a list of them, any of which admits.",
        "Use those forms, or write access: code and declare the viewset's Access(...) by hand (Where, Can, &, a computed get_access).",
    ),
    _c(
        "C218",
        "A role grant is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "Grants map onto KARNI_ROLES: a pattern app.entity[:action] (with * for a part, or * alone) to a scope all, own, own:<owner field>, related:<scope path key>, custom:<name> or tree:<path>. A spec grants the standard actions view, add, change and delete.",
        "Fix the pattern or the scope. An entity's own actions, and a grant on a model outside the spec, go in KARNI_ROLES by hand.",
    ),
    _c(
        "C219",
        "A feature's value is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "Each feature is one setting: social_login names the built-in providers of KARNI_SOCIAL_TOKEN_PROVIDERS, and terms is KARNI_TERMS (a version of at most 100 characters, URL path prefixes that start with /).",
        "Name google, microsoft or apple (a provider class of your own goes in settings), and fix the terms value the message names.",
    ),
    _c(
        "C220",
        "A page entry is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "Each entry of pages is one key: an entity with the pages karni make page makes for it (list, detail, form, and {detail: {related: [...]}} for a detail page with related tabs), or a page name with its kind (blank, login, code, or dashboard: the scaffold's home at /, or a page of charts at /<name>).",
        "Write e.g. - Session: [list, detail, form], - about: blank, - home: dashboard or - overview: dashboard, each entity or page once.",
    ),
    _c(
        "C221",
        "A module option is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "A module's options are its settings: the option provider of payments is KARNI_PAYMENTS_PROVIDER. An option the module does not have, or a value of the wrong type, would be lost.",
        "Use an option the message lists, with the type its setting takes (the module's README has the table). Credentials stay in .env.",
    ),
    _c(
        "C222",
        "A key is written twice",
        "karni spec validate (karni_cli.spec.validate)",
        "YAML keeps the last of two equal keys in a mapping and drops the first without a word, so half of what was written would be lost.",
        "Keep one of the two and merge what the other said into it.",
    ),
    _c(
        "C223",
        "A seed count is not valid",
        "karni spec validate (karni_cli.spec.validate)",
        "seed sets each entity's demo rows per karni seed run (a Seeder's Meta.count), where 0 skips the entity.",
        "Write a whole number, 0 or more.",
    ),
    _c(
        "C224",
        "A key reserved for a later release",
        "karni spec validate (karni_cli.spec.validate)",
        "Some keys are reserved for features Karni adds later (cross-entity search), so a spec written today keeps its meaning. pk, external and database were reserved before karni plan and are keys now, and so are taxonomies, aggregate and markdown.",
        "Remove the key, and write that part by hand in the project until the feature ships.",
    ),
    _c(
        "C225",
        "The app kind and the modules disagree",
        "karni spec validate (karni_cli.spec.validate)",
        "karni add site turns an app into a site+app, so a spec of kind app with the site module describes a project that cannot exist.",
        "Write kind: site+app (karni new --kind site+app adds the site module by itself), or drop the module.",
    ),
    _c(
        "C230",
        "A relation names an entity that does not exist",
        "karni spec validate (karni_cli.spec.validate)",
        "A fk, m2m or o2o field must point at something karni make model can import: an entity of the spec, the user model, or a model of a module the spec adds.",
        "Fix the name, add the entity, add the module, or point at User. A model of the project outside the spec cannot be named.",
    ),
    _c(
        "C231",
        "A relation name is ambiguous",
        "karni spec validate (karni_cli.spec.validate)",
        "Two apps of the spec define an entity of that name, so the bare name could mean either.",
        "Write app.Name, e.g. fk:shop.Product.",
    ),
    _c(
        "C232",
        "Access names a role the spec does not declare",
        "karni spec validate (karni_cli.spec.validate)",
        'role:<slug> becomes HasRole("<slug>"), which nobody would hold if no role of that slug exists. Without roles, the spec has Karni\'s shipped roles (staff, user, customer), plus the roles of the modules it adds.',
        "Declare the role under roles, or fix the slug.",
    ),
    _c(
        "C233",
        "A grant names an entity the spec does not have",
        "karni spec validate (karni_cli.spec.validate)",
        "A grant pattern that matches no model grants nothing, and Karni refuses it at startup (E206).",
        "Name an entity as app.entity (lowercase or as written), or add the module whose model it names.",
    ),
    _c(
        "C234",
        "A grant's scope does not fit the entity",
        "karni spec validate (karni_cli.spec.validate)",
        "own compares the entity's owner field with the user, and related:<key> its scope path <key> with the user's attribute <key>. own:<field> must name that owner field, and related:<key> a scope path the entity declares.",
        "Set owner: on the entity, add scope_paths: {<key>: <lookup>}, or change the scope.",
    ),
    _c(
        "C235",
        "A page names an entity that does not exist",
        "karni spec validate (karni_cli.spec.validate)",
        "An entity's pages compose its API resource, which only an entity of the spec has.",
        "Name an entity of the spec (app.Name when two apps define it), or add it.",
    ),
    _c(
        "C236",
        "A module Karni does not know",
        "karni spec validate (karni_cli.spec.validate)",
        "modules lists what karni add installs: the modules of the catalog (karni modules list), which are Karni's own (approvals, impersonation, payments and site) and any module installed next to karni-cli that ships a manifest.",
        "Fix the name. A module of your own joins the spec once it ships a karni.module.toml (docs/modules.md). Without one, add it with karni add and leave it out of the spec.",
    ),
    _c(
        "C237",
        "A field group names a field the entity does not have",
        "karni spec validate (karni_cli.spec.validate)",
        "groups become Karni.field_groups (the sections of the React form and detail page and the admin's fieldsets), and karni check refuses a name that is not a field or a field in two groups (karni.E551, karni.E552).",
        "Name the entity's fields, each in one group.",
    ),
    _c(
        "C238",
        "An entity option names a field the entity does not have",
        "karni spec validate (karni_cli.spec.validate)",
        "key, search, order, audit and scope_paths each name fields of the entity (key, search and order may also name id, created_at and updated_at).",
        "Name a field the entity declares, or add it under fields.",
    ),
    _c(
        "C239",
        "owner does not lead to the user",
        "karni spec validate (karni_cli.spec.validate)",
        "The own scope compares the owner field with the signed-in user, so it must be a relation to the user or a path through relations ending at one.",
        "Name a relation to the user (member: fk:User, then owner: member) or a path such as workspace__members.",
    ),
    _c(
        "C240",
        "owned:<path> in access does not lead to the user",
        "karni spec validate (karni_cli.spec.validate)",
        'owned:<path> becomes Owned("<path>"), which keeps the rows whose path points at the signed-in user.',
        "Name a relation to the user (owned:member) or a path through relations (owned:session__instructor).",
    ),
    _c(
        "C241",
        "seed names an entity that does not exist",
        "karni spec validate (karni_cli.spec.validate)",
        "seed counts demo rows per entity of the spec.",
        "Name an entity of the spec (app.Name when two apps define it).",
    ),
    _c(
        "C242",
        "Two pages share a route",
        "karni spec validate (karni_cli.spec.validate)",
        "Each page karni make page writes has a route (an entity's list at /<route>, its detail at /<route>/$id, its form at /<route>/new and /<route>/$id/edit, a named page at /<name>), and two pages cannot answer the same path.",
        "Rename the page or drop one of them.",
    ),
    _c(
        "C245",
        "karni spec export cannot read the project",
        "karni spec export",
        "The export reads the project through manage.py karni_facts, run by the project's interpreter, which needs this karni (the command is new in it).",
        "Upgrade the project's karni, then fix what the message shows (the command's last output lines): a settings error, a model that fails to import, or output printed at startup.",
    ),
    _c(
        "C246",
        "The output file exists",
        "karni spec export",
        "karni spec export does not overwrite a spec: it may hold edits of your own.",
        "Pass --force to replace it, or write to another file with -o.",
    ),
    _c(
        "C250",
        "karni plan cannot read the project",
        "karni plan",
        "The plan compares the spec with the project as karni spec export reads it: through manage.py karni_facts, run by the project's interpreter, which needs this karni.",
        "Upgrade the project's karni, then fix what the message shows (the command's last output lines): a settings error, a model that fails to import, or output printed at startup.",
    ),
    _c(
        "C251",
        "An external entity's keys do not fit",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "external: true is a table another system owns, so it needs table, its key is the table's own column (no pk), and karni seed skips it. table and writable mean nothing without external.",
        "Add table: <[schema.]table> to an external entity, remove pk and its seed count, or add external: true where table or writable is written.",
    ),
    _c(
        "C252",
        "database names an alias the project does not have",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "database sends an entity's reads, writes and migrations to an alias of DATABASES (class Karni: database). karni plan checks the name against the project's DATABASES, and karni spec validate checks that it is an alias name.",
        'Add the alias to config/settings.py (DATABASES["warehouse"] = env.db_url("WAREHOUSE_DATABASE_URL")), or fix the name.',
    ),
    _c(
        "C253",
        "A relation joins two databases",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "Django joins related tables in one database, so a fk, m2m or o2o between entities on different databases cannot work (karni.E276 at startup). The user and the modules' models are on the default database.",
        "Keep both entities on one database, or store the other row's key in a plain field and look it up in code.",
    ),
    _c(
        "C254",
        "A rename (was) is not valid",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "was: <old name> on a field or an entity tells karni plan and karni build to rename it and keep its data. The old name must be a valid name, differ from the new one, no longer be declared, and be claimed by one field or entity only.",
        "Write the old name once, on the field or entity that takes over the data, and remove the old declaration.",
    ),
    _c(
        "C540",
        "global_search names a field that is not a text field of the entity",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "Search across entities (class Karni: search) matches the query against the entity's own text fields and gives each a trigram index. Its fields come from global_search.fields, else from the entity's search list, which may name a related path (venue__name) or a non-text field that it cannot search.",
        "List the entity's own text fields (str, text, email, url, slug, choice, phone, country, currency, state) under global_search.fields, e.g. global_search: {fields: [name, sku]}.",
    ),
    _c(
        "C541",
        "global_search has no fields to search",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "global_search takes its fields from global_search.fields, else from the entity's search list. With both empty there is nothing to match the query against.",
        "Name the text fields under global_search.fields, or list them under search.",
    ),
    _c(
        "C542",
        "global_search's title or subtitle is not a field of the entity",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "Each hit of search across entities shows its title and subtitle, read from the entity's fields. A name the entity does not have, or a __ path through something that is not a foreign key, cannot be read.",
        "Name a field of the entity, or a path through one of its foreign keys (supplier__name). Leave title out to use the first searched field.",
    ),
    _c(
        "C270",
        "A risky change without --allow-destructive",
        "karni build (karni_cli.builder)",
        "A risky change can lose data or open it to more people: a field or an entity removed, a type narrowed, a choice dropped, a relation pointed elsewhere, access widened. karni plan marks each with ! and the rows it affects, and karni build applies none of them without being told.",
        "Check each change karni plan lists (a rename keeps its rows: write was: on the field or the entity), then run karni build --allow-destructive, or change karni.yaml.",
    ),
    _c(
        "C271",
        "A module removal",
        "karni build (karni_cli.builder)",
        "karni.yaml no longer lists a module the project has. Removing a module drops its tables, and karni remove (with the module catalog) is not built yet, so karni build refuses it.",
        "Put the module back in karni.yaml, or remove it by hand: migrate its app to zero, then take it out of the karni:apps block and its dependency out of pyproject.toml.",
    ),
    _c(
        "C272",
        "A key type switch",
        "karni build (karni_cli.builder)",
        "Switching an entity's pk between uuid and bigint rewrites every row and every relation to it: a data migration karni build does not write.",
        "Put pk back in karni.yaml. docs/models.md (choosing the key type) says how to write that migration by hand.",
    ),
    _c(
        "C273",
        "A Karni-owned file was edited by hand",
        "karni build (karni_cli.builder)",
        "karni build rewrites its own files (<app>/karni/, <app>/tests/karni/, frontend/src/pages/karni/, the karni:spec blocks) on every build, and records a sha256 of each in .karni/build.json. A file whose content no longer matches was edited by hand, and a build must not silently lose the edit. The message names the file and the changed lines, and nothing is written.",
        "Move the change into the project's own file (<app>/models.py, viewsets.py or seeds.py: the subclass of each class, a page or test of your own) or into karni.yaml, then run karni build. Or karni build --force replaces the file and keeps your copy as <file>.orig. Or karni build --adopt <file> makes it the project's: karni build stops managing it and says so on every run.",
    ),
    _c(
        "C274",
        "--adopt names a file karni build does not own",
        "karni build (karni_cli.builder)",
        "--adopt hands a Karni-owned file or block to the project. The files karni build owns are the ones .karni/build.json lists. Any other file is the project's already.",
        "Name a file the record lists (classes/karni/api.py), or config/settings.py and frontend/src/routes.tsx for their karni:spec blocks.",
    ),
    _c(
        "C275",
        "The project's code is in the way",
        "karni build (karni_cli.builder)",
        "karni.yaml asks for something the project already has as code of its own: a model of that name outside the spec, a class of that name in models.py, viewsets.py or seeds.py that does not extend Karni's, or a route a page of the project's holds. karni build never replaces the project's code.",
        "Rename the entity or page in karni.yaml, or rename (or remove) the project's own class or route. A page of the project's can stay in the spec as - <name>: code.",
    ),
    _c(
        "C276",
        "A module karni build added is not installed",
        "karni build (karni_cli.builder)",
        "karni build adds a new module the way karni add does: the dependency in pyproject.toml and the app in INSTALLED_APPS. The project's interpreter must have it installed before Django can start with it.",
        "Install the project's dependencies (uv pip install -r pyproject.toml, or docker compose build), then run karni build again: it continues from where it stopped.",
    ),
    _c(
        "C277",
        "makemigrations failed",
        "karni build (karni_cli.builder)",
        "karni build writes the migrations with manage.py karni_makemigrations: the renames first, then Django's makemigrations. A required field added to a table that holds rows needs values Django cannot invent.",
        "Read the output it shows. For a required field on a table with rows: add it as optional first (str?), fill it, then make it required. Then run karni build again.",
    ),
    _c(
        "C278",
        "migrate failed",
        "karni build (karni_cli.builder)",
        "karni build applies the migrations on the default database and on every alias its entities name.",
        "Read the output it shows (a database that does not answer, a constraint the rows break), fix it, then run karni build again.",
    ),
    _c(
        "C279",
        "Seeding failed",
        "karni build (karni_cli.builder)",
        "karni build seeds only the tables it created in this build, and only while they hold no row, so demo rows never mix with real data.",
        "Read the output it shows, fix it (karni seed --help), then run karni build again: it continues from seed.",
    ),
    _c(
        "C280",
        "karni types failed",
        "karni build (karni_cli.builder)",
        "karni build writes the TypeScript types and hooks from the API schema, as karni types does. It needs the backend to print its schema and Node for openapi-typescript.",
        "Read the output it shows. Install Node (and npm install in frontend/), then run karni build again.",
    ),
    _c(
        "C281",
        "The project's tests fail",
        "karni build (karni_cli.builder)",
        "karni build runs the project's own tests (karni test) after it built the code, including the API tests it wrote in <app>/tests/karni/.",
        "Run karni test to see every failure, fix the code (the project's files or karni.yaml), then run karni build again: it continues from test.",
    ),
    _c(
        "C282",
        "karni check fails",
        "karni build (karni_cli.builder)",
        "karni build ends with karni check: the architecture rules, the system checks and the frontend's lint. The code it writes passes them, so a failure comes from the project's code or its environment.",
        "Run karni check to see every finding, fix them, then run karni build again: it continues from check.",
    ),
    _c(
        "C283",
        "A project class karni build must change has code of its own",
        "karni build (karni_cli.builder)",
        "karni.yaml removes an entity, and the project's subclass of it (in models.py, viewsets.py or seeds.py) holds code of its own. karni build removes such a class only while it is still the one it wrote.",
        "Move that code elsewhere or delete the class, then run karni build again.",
    ),
    _c(
        "C284",
        "A marker karni build writes at is missing",
        "karni build (karni_cli.builder)",
        "The settings block goes right above karni_settings(globals()) in config/settings.py, where every setting takes effect. The pages' routes go before the // karni:page-imports and // karni:routes markers of frontend/src/routes.tsx.",
        "Restore the call or the markers (see the scaffold's files), or pass --adopt for the block and keep those settings or routes yourself.",
    ),
    _c(
        "C285",
        "The build record cannot be read",
        "karni build (karni_cli.builder)",
        ".karni/build.json holds the fingerprints of the files karni build owns. It is missing a part, is not JSON, or comes from a newer karni-cli.",
        "Restore it from version control, or upgrade karni-cli. Deleting it makes karni build treat every Karni-owned file as new: it stops on each one that exists (C273), and --force or --adopt settles them.",
    ),
    # C3xx karni ui
    _c(
        "C301",
        "No frontend found",
        "karni ui detect",
        "karni ui detect reads a frontend: its package.json, stylesheets and theme files. It "
        "looks in the current directory, in ./frontend, and in the Karni project's frontend/.",
        "Run it in the frontend directory (the one with package.json), or pass --frontend <dir>.",
    ),
    _c(
        "C302",
        "A generated file was edited, so karni ui detect does not overwrite it",
        "karni ui detect (karni-theme.css, karni-primitives.tsx)",
        "The files karni ui detect writes belong to the project. Each carries a digest of what "
        "was generated. A file whose content no longer matches it (or that has none) was edited "
        "by hand, and a re-run must not silently lose those edits.",
        "Compare with `karni ui detect --dry-run` and copy what you need, overwrite with --force, "
        "or write the new file elsewhere with --output.",
    ),
    _c(
        "C303",
        "A theme source cannot be read",
        "karni ui detect (components.json, the stylesheet it names, tailwind.config)",
        "karni ui detect maps the project's theme from its files: shadcn/ui's components.json "
        "and the stylesheet it names, or a tailwind.config that Node evaluates in the project "
        "(with the project's own packages). The message names the file and what failed.",
        "Fix the file the message names (or run npm install so a config's imports load), or "
        "pass --source to read another theme source.",
    ),
    _c(
        "C304",
        "The frontend has no theme of the --source kind",
        "karni ui detect --source",
        "--source makes karni ui detect read one source (shadcn, tailwind, mui, chakra, mantine) "
        "instead of detecting. That source is not in this frontend.",
        "Run karni ui detect without --source to detect what the frontend has, or name a "
        "source it uses.",
    ),
    # C31x debugging: karni why / karni why-empty
    _c(
        "C310",
        "karni why: the target is malformed",
        "karni why, karni why-empty",
        "A question names one thing: <resource>/<id> (a row), <resource>.<field> (a field), "
        "<resource> (its list), or a status followed by the request id of a recorded request.",
        "Use one of those forms, e.g. karni why events/42 --as alice@example.com or "
        "karni why 403 <request-id>.",
    ),
    _c(
        "C311",
        "karni why: --as is missing",
        "karni why, karni why-empty",
        "An access decision is always for one user, and only a recorded request carries its own.",
        "Pass --as with an email, username or primary key, or --as anonymous.",
    ),
    _c(
        "C312",
        "karni why: the project's karni is too old",
        "karni why, karni why-empty",
        "The question runs as manage.py karni_why in the project, which ships with karni. A "
        "project on an older karni does not have it.",
        "Upgrade karni in the project (pip install -U karni, or rebuild the image), then ask "
        "again.",
    ),
    # C313-C319 the module catalog: karni modules, karni add, karni remove
    _c(
        "C313",
        "No module or feature of that name in the catalog",
        "karni modules show, karni remove (karni_cli.catalog)",
        "The catalog holds Karni's modules and built-in features, the copies karni-cli bundles "
        "and the manifests (karni.module.toml) of the modules the project has installed.",
        "Run `karni modules list` for the names. A module of your own joins the catalog with a "
        "karni.module.toml and a karni.modules entry point (docs/modules.md).",
    ),
    _c(
        "C314",
        "A module manifest is not valid",
        "karni modules, karni add, karni remove (karni.catalog)",
        "Each module describes itself in karni.module.toml: its purpose, what it provides, the "
        "questions to ask and the wiring karni add performs. A manifest that does not follow "
        "the format, or that names a module or feature the catalog does not have, cannot be "
        "used.",
        "Fix the key the message names (docs/modules.md lists every key), then run `karni "
        "modules show <name>`. A module's own tests check it with "
        "karni.testing.assert_module_manifest.",
    ),
    _c(
        "C315",
        "The module conflicts with one the project has",
        "karni add",
        "A module's manifest lists the modules and features it cannot work next to "
        "(conflicts). karni add refuses before it writes anything.",
        "Remove the other one first (karni remove <name>, or turn the feature off), or choose "
        "another module.",
    ),
    _c(
        "C316",
        "Another module requires the one being removed",
        "karni remove",
        "A module's manifest lists what it needs (requires). Removing a module another added "
        "module needs would leave that one broken.",
        "Remove the module that requires it first (the message names it), then this one.",
    ),
    _c(
        "C317",
        "The module is not in this project",
        "karni remove",
        "karni remove takes out what karni add wrote: the dependency in pyproject.toml, the app "
        "in the # karni:apps block, its middleware, context processors and URL include, and "
        "its recorded agent guidance. None of that is in this project.",
        "Check the name with `karni modules list` (an added module says added).",
    ),
    _c(
        "C318",
        "A built-in feature is switched by a setting, not added or removed",
        "karni add, karni remove",
        "Features (two_factor, terms, api_cache and the others) ship with karni. There is no "
        "package to add and nothing to take out: one setting turns each on or off.",
        "Turn it on or off with its key under features: in karni.yaml, or its setting (karni "
        "modules show <name> names both).",
    ),
    _c(
        "C319",
        "The module's tables exist in the database",
        "karni remove",
        "karni remove never drops data. Once the module is out of INSTALLED_APPS, Django can no "
        "longer drop its tables, so the choice is made now: drop them while the module is "
        "still added, or keep them.",
        "To drop the tables and their rows, run the printed `karni migrate <app> zero`, then "
        "karni remove again. To keep them in the database, run karni remove --keep-tables.",
    ),
    # C32x debugging: trace, replay, explain --failure
    _c(
        "C320",
        "karni explain needs a code or --failure, not both",
        "karni explain",
        "karni explain explains one thing: an error code (E104, C101, PAY004, K106) or a "
        "captured failure (--failure <id>).",
        "Run `karni explain E104`, or `karni explain --failure <id>` (a failure id, a failed "
        "request's id, or `last`).",
    ),
    _c(
        "C321",
        "A --set value is not FIELD=VALUE",
        "karni replay --set",
        "--set supplies a value the capture redacted, by its place in the request.",
        "Write the body path, '=', then the value: --set password=s3cret, --set "
        "card.token=tok_1, or --set query:token=abc for a query parameter. The value is "
        "parsed as JSON when it can be (numbers, true/false), else used as text.",
    ),
    _c(
        "C322",
        "The project's karni has no debugging commands",
        "karni trace, karni replay, karni explain --failure",
        "These commands run manage.py karni_trace, karni_replay and karni_failure in the "
        "project's interpreter. A karni older than the CLI does not have them.",
        "Upgrade karni in the project: `karni upgrade`, or bump karni in pyproject.toml and "
        "reinstall (`uv pip install -r pyproject.toml`, or rebuild the image).",
    ),
    _c(
        "C323",
        "A debugging command failed in the project",
        "karni trace, karni replay, karni explain --failure",
        "The command ran in the project's interpreter and failed without a coded Karni "
        "error, usually because Django could not start (settings, imports, the database).",
        "Run the command it names with `karni manage ...` to see the full output, fix what "
        "it reports, then retry.",
    ),
    # C324-C339 the module catalog in karni.yaml
    _c(
        "C324",
        "A module or feature needs another, or cannot be next to one",
        "karni spec validate (karni_cli.spec.validate)",
        "The catalog's manifests say what each module and feature requires and conflicts with. "
        "The spec lists one without what it requires, or two that conflict.",
        "Add what the message says is required (under modules: or features:), or leave one of "
        "the two that conflict out. karni modules show <name> lists both.",
    ),
    # C500-C519 aggregations in karni.yaml (experimental)
    _c(
        "C500",
        "aggregate names a field or path the entity does not have",
        "karni spec validate (karni_cli.spec.validate)",
        "An entity's aggregate: lists what GET <resource>/aggregate/ may group by (group_by) and "
        "read (values). Each name is a field of the entity, or a path through its relations "
        "(category__parent), and group_by holds at least one.",
        "Name a field the entity declares, or follow a relation (fk, o2o, m2m) with __ to a "
        "field of the entity it points at.",
    ),
    _c(
        "C501",
        "aggregate names a metric that is not one",
        "karni spec validate (karni_cli.spec.validate)",
        "The metrics are count, sum, avg, min, max and distinct_count. aggregate.metrics lists "
        "the ones a request may name, all of them when it is left out.",
        "List metrics from count, sum, avg, min, max and distinct_count, or leave metrics out.",
    ),
    _c(
        "C502",
        "A date bucket in aggregate that does not fit",
        "karni spec validate (karni_cli.spec.validate)",
        "A group may take a bucket after a colon (launched_on:year) to group a date or datetime "
        "field by year, quarter or month. Another bucket, or one on a field that is not a date, "
        "cannot be grouped.",
        "Write <date field>:year, :quarter or :month, or the field alone to allow every bucket.",
    ),
    # C34x debugging: karni explain -, karni queries
    _c(
        "C340",
        "Nothing to explain",
        "karni explain",
        "karni explain answers for a code (karni explain E104) or for pasted text: a traceback, "
        "a test failure or a log line read from stdin. It got neither: no code, and stdin was "
        "a terminal or empty.",
        "Pass a code (karni explain E104), or pipe the text in: karni explain - < "
        "traceback.txt, or pbpaste | karni explain -. Agents: the explain_text MCP tool takes "
        "the text as an argument.",
    ),
    _c(
        "C341",
        "The project's karni has no karni_queries command",
        "karni queries",
        "karni queries runs manage.py karni_queries in the project's interpreter. That command "
        "ships with karni from the release that added karni queries, and the project has an older "
        "karni installed.",
        "Upgrade karni in the project (pip install -U karni, or bump it in pyproject.toml and "
        "reinstall), then run karni queries again. karni doctor shows both versions.",
    ),
    # C36x typed fields (karni.fields): the make model DSL and karni schema
    _c(
        "C360",
        "A typed-field argument in the model DSL is invalid",
        "karni make model (money, percent, email, slug, json, array fields)",
        "Typed fields take arguments that name the database guarantee: a money field's ISO "
        "4217 currency, a percentage's integer bounds, the field a slug is built from (it must "
        "be declared in the same command), an array's base type.",
        "Fix the field the message names: price:money:EUR, rate:percent:0:100, "
        "slug:slug:title, email:email:unique, meta:json:queried, tags:array:str:40. "
        "`karni make model --help` lists them.",
    ),
    _c(
        "C361",
        "The project's karni has no karni schema",
        "karni schema",
        "karni schema runs `manage.py karni_schema` in the project's interpreter. A karni older "
        "than the typed field layer does not have it.",
        "Upgrade the project's karni (karni upgrade, then reinstall the project's dependencies). "
        "`karni doctor` shows which karni the project uses.",
    ),
    # C37x field DSL: lifecycle columns and limited resources
    _c(
        "C370",
        "A state field spec is invalid",
        "karni make model (name:state:...)",
        "A state column lists its states (draft,confirmed,cancelled) or its moves "
        "(draft>confirmed|draft>cancelled). The first state is where rows start, so every other "
        "state must be reachable from it. A state column is never optional.",
        "Write e.g. 'status:state:draft>confirmed>refunded|draft>cancelled', or list the states "
        "and edit the generated transitions={...}.",
    ),
    _c(
        "C371",
        "A range field spec is invalid",
        "karni make model (name:daterange, name:datetimerange)",
        "Range columns take no arguments: daterange is a PostgreSQL daterange, "
        "datetimerange a tstzrange.",
        "Write 'during:datetimerange' or 'nights:daterange' (add ? for an optional one).",
    ),
    _c(
        "C372",
        "A capacity field spec is invalid",
        "karni make model (name:capacity[:total])",
        "A capacity counter can name the integer field holding the total, which must be declared "
        "in the same command. The counter is never optional.",
        "Write e.g. 'quantity:int remaining:capacity:quantity', or 'units:capacity' for a "
        "counter that starts at 0.",
    ),
    _c(
        "C373",
        "No such setting",
        "karni explain <SETTING>",
        "karni explain reads Karni's settings and every module's from the source "
        "docs/settings.md is generated from: Karni's karni/conf/base.py, each module's conf.py "
        "(installed next to karni-cli, or in the project), never Django.",
        "Check the name against docs/settings.md, and run it inside the project so the "
        "project's modules are found. A setting the project defines itself is in "
        "config/settings.py.",
    ),
    _c(
        "C374",
        "No such template tag",
        "karni explain <tag>",
        "karni explain reads the karni-site module's tags and filters from the source "
        "docs/public-site.md's table is rendered from (karni_site/tagref.py): in this "
        "checkout, installed next to karni-cli, or in the project.",
        "Check the name against the table in docs/public-site.md (karni_seo, image, editable, "
        "get_menu ...), and run it inside a project that installs karni-site. A tag of "
        "Django's own ({% if %}, {% url %}) is in Django's documentation.",
    ),
    _c(
        "C375",
        "No such content map key",
        "karni explain map.<key>",
        "A content map key is written at one level of the map (the map, a model, a source, "
        "a key, a value), and karni explain reads them from karni_cli/design/mapref.py, the "
        "source of docs/design-content.md's tables.",
        "Run `karni explain map` for every key by level, then `karni explain map.<key>` or "
        "`map.<level>.<key>` (map.source.key, map.value.by).",
    ),
    # C400-C419 clarifying questions: karni plan --questions, karni spec answer
    _c(
        "C400",
        "No open question has this id",
        "karni spec answer (karni_cli.spec.questions)",
        "karni spec answer writes the answer to a question karni plan --questions asks. The id "
        "is not one of them: it is mistyped, or karni.yaml settles that question already (an "
        "answered question is gone, and so is one the file was edited to settle).",
        "Run karni plan --questions --max 0 for the open ids, then karni spec answer <id> "
        "<value> with one of them.",
    ),
    _c(
        "C401",
        "The value is not an answer the question takes",
        "karni spec answer (karni_cli.spec.questions)",
        "A question with options takes one of them (several, comma-separated, when it says "
        "so). A question without options takes a value of the types it lists (string, "
        "integer, boolean, null, array).",
        "Pass one of the options karni plan --questions prints under the question, or a value "
        "of its type.",
    ),
    _c(
        "C402",
        "The answer cannot be written into karni.yaml",
        "karni spec answer (karni_cli.spec.edit)",
        "karni spec answer changes only the key the question names and keeps every other line "
        "of the file. It writes nothing when it cannot: an anchor or alias shares the key, the "
        "key sits in a layout it cannot place a key in, or the result would not pass karni "
        "spec validate.",
        "Set the key the message names in karni.yaml by hand, then run karni spec validate and "
        "karni plan --questions.",
    ),
    # C42x recipes and the app-builder MCP tools
    _c(
        "C420",
        "No recipe of that name",
        "karni recipes show, the MCP tool recipes (karni_cli.recipes)",
        "Recipes are the folders built into karni-cli and the karni.recipes entry points of "
        "its environment. blank is the blank start, the one name that is always there.",
        'Run karni recipes list for the names, or karni recipes list --match "<the request>" '
        "for the closest. A recipe of your own joins with a recipe.toml, a karni.yaml and an "
        "entry point (docs/app-spec.md#recipes).",
    ),
    _c(
        "C421",
        "A recipe cannot be used",
        "karni recipes list, karni recipes show, the MCP tool recipes (karni_cli.recipes)",
        "A recipe is a folder with a recipe.toml that follows its schema, a name that is the "
        "folder's (or the entry point's), and a karni.yaml. One that does not, or whose name "
        "another recipe has already, is left out and reported.",
        "Fix the key the message names (docs/app-spec.md#recipes lists every key), or rename "
        "the recipe, then run karni recipes show <name>.",
    ),
    # C440-C459 a new project from a recipe: karni new --recipe
    _c(
        "C440",
        "karni new --recipe with an option it cannot go with",
        "karni new --recipe (karni_cli.commands.new)",
        "A recipe is an app: its karni.yaml has entities, roles and pages for signed-in users. "
        "--design builds a public site from a designer's pages instead, and --kind site or "
        "--no-staff-app leave out the React app the recipe's pages live in.",
        "Leave the option out (--kind app or site+app go with a recipe), or make the project "
        "without --recipe and start karni.yaml from karni recipes show <name>.",
    ),
    _c(
        "C441",
        "A recipe's file would replace code of the project's",
        "karni build after karni new --recipe (karni_cli.recipes.apply)",
        "The first karni build after karni new --recipe writes the recipe's own files (its "
        "domain code, seeds and tests) over the stubs it writes itself. It never writes over "
        "anything else: a file that holds code of the project's stops the build, and nothing "
        "is written.",
        "Move your code out of the way (rename the file), run karni build again, then put your "
        "code back into the recipe's file. To build without the recipe's files, delete "
        '"recipe" from .karni/build.json.',
    ),
    # C460-C479 tree models in karni.yaml (experimental)
    _c(
        "C460",
        "A tree entity's keys do not fit",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "tree: true makes the entity a TreeModel, which adds a parent field (tree: ordered makes "
        "it an OrderedTreeModel, which adds position too). Karni adds that column, so it cannot "
        "be a table another system owns, and the entity cannot declare a field of that name.",
        "Remove tree from an external entity, and remove parent (and position) from the fields "
        "of a tree entity, or rename a field that means something else.",
    ),
    # C620-C639 the tree scope in karni.yaml (experimental)
    _c(
        "C620",
        "A role grant's tree:<path> does not lead to a tree entity",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "tree:<path> reaches the rows whose <path> is a node the user holds or a node below it. "
        "The path follows the entity's relation fields (fk, m2m, o2o) and taxonomies, each to an "
        "entity of the spec, and the last one must point at an entity with tree: true or tree: "
        "ordered. "
        "Karni refuses any other path at startup (E490).",
        "Name the entity's relation to the tree, through relations when needed: tree:region, "
        "tree:product__categories. Add tree: true to the entity the path ends at, or grant "
        "another scope.",
    ),
    # C640-C659 navigation from data in karni.yaml (experimental)
    _c(
        "C640",
        "A navigation entry names a page the spec does not have",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "Each menu entry links to the route of a page of pages: an entity's list page, or a "
        "named page. An entity whose pages all take an id (detail, form) has no route a menu can "
        "link to.",
        "Name a page of pages by its key (Product, shop.Product, home), add the page to pages, "
        "or add list to the entity's pages.",
    ),
    _c(
        "C641",
        "A navigation entry is not valid",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "An entry is a page's key, a page with its options ({label, icon, requires}), or a group: "
        "a label that names no page, with its entries (a list, or {items, icon, requires}). Each "
        "page is listed once, a group has entries, and an icon is a name such as home.",
        "Write e.g. - home, - Catalog: [Product, Category] or - Region: {icon: map}.",
    ),
    _c(
        "C642",
        "A navigation requirement is not valid",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "requires is public, authenticated or a permission pattern as in grants (app.entity:"
        "action, with * for a part), so role grants and per-user grants open the entry the way "
        "they open the API. A pattern that names an entity the spec does not have opens it for "
        "nobody.",
        "Write public, authenticated, or a pattern such as shop.product:view, or leave requires "
        "out: each page takes its requirement from its access.",
    ),
    # C700-C719 taxonomies in karni.yaml (experimental)
    _c(
        "C700",
        "A taxonomy key is not a field name the entity can take",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "Each key of taxonomies becomes a many-to-many field of that name and the list parameters "
        "?<key>= and ?<key>_descendants=, so it is a lowercase field name that does not end in "
        "_descendants, and it is not a field a mixin or the tree already gives the entity.",
        "Rename the key, e.g. taxonomies: {region: Region}.",
    ),
    _c(
        "C701",
        "A taxonomy does not point at a tree entity",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "A taxonomy tags rows with the nodes of a hierarchy, and its filters, facets and the "
        "tree:<key> scope walk the tree below a node. The target must be an entity of the spec "
        "with tree: true or tree: ordered. Karni refuses another target at startup (E571).",
        "Point the key at a tree entity (Name or app.Name), or add tree: true to the entity it "
        "names. For tags without a hierarchy, declare a plain m2m field instead.",
    ),
    _c(
        "C702",
        "A taxonomy key names a field that is not a many-to-many to its tree",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "When the entity declares a field under a taxonomy's key, Karni adopts that field instead "
        "of generating one. Only an m2m to the same tree entity can be adopted (E572).",
        "Remove the field and let the taxonomy generate it, declare it as m2m:<the tree entity>, "
        "or rename one of them.",
    ),
    _c(
        "C703",
        "An external entity declares taxonomies",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "A taxonomy adds a table of tags next to the entity's table and joins them. An external "
        "entity's table belongs to another system, and Karni never writes tables for it.",
        "Remove taxonomies from the external entity, or remove external and let Karni own the "
        "table.",
    ),
    # C520-C539 response caching in karni.yaml (experimental)
    _c(
        "C520",
        "An entity's cache value is not valid",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "cache: on an entity is its viewset's response caching: how many seconds a cached "
        "response lives (Cache(ttl=...)), or false (Uncached). true says nothing the setting "
        "does not, and a lifetime of 0 or less caches nothing.",
        "Write cache: 60 (any whole number of seconds above 0), or cache: false to never cache "
        "the entity. Leave the key out to follow KARNI_API_CACHE_TTL.",
    ),
    _c(
        "C521",
        "A cached entity reads a table Karni does not see written",
        "karni spec validate and karni plan (karni_cli.spec.validate)",
        "With api_cache on, a cached response is cleared when Karni sees a write to a table it "
        "reads. An external table, a table on another database, or an external entity reached "
        "through ?expand= is written by another system, so its cached responses would stay "
        "stale until they expire. karni check refuses the same viewset in the project.",
        "Add cache: <seconds> to the entity (how stale a response may be), or cache: false to "
        "never cache it.",
    ),
    # C560-C579 page blocks (large-apps item 11): related tabs on a detail page
    _c(
        "C560",
        "A related tab names no entity",
        "karni spec validate (karni_cli.spec.validate)",
        "A detail page's related tabs ({detail: {related: [...]}}) each list the rows of another "
        "entity that point at the page's entity. The name is not an entity of the spec, or "
        "several apps define it.",
        "Name an entity of the spec (app.Entity when two apps define it), or Entity.field.",
    ),
    _c(
        "C561",
        "A related tab names an entity with no fk to this one",
        "karni spec validate, karni make page --related (karni_cli.spec.validate)",
        "A related tab is a table of the other entity's rows filtered to this record, and the "
        "list of that entity filters by its fk fields. The entity has no fk to the page's "
        "entity, or the field named is not one (a m2m or an o2o cannot back a tab).",
        "Add a fk field to the page's entity on the other entity, or name the fk it has.",
    ),
    _c(
        "C562",
        "A related tab could be either of two relations",
        "karni spec validate, karni make page --related (karni_cli.spec.validate)",
        "The entity named has two or more fks to the page's entity (a deal's company and its "
        "partner), so the tab must say which rows it lists.",
        "Write Entity.field, one tab for each relation you want.",
    ),
    _c(
        "C563",
        "A related tab is listed twice",
        "karni spec validate, karni make page --related (karni_cli.spec.validate)",
        "Each related tab is one relation. Deal and Deal.company name the same one when Deal has "
        "one fk to the page's entity.",
        "List each related tab once.",
    ),
    _c(
        "C680",
        "A column set names a field the entity does not have, or one twice",
        "karni spec validate (karni_cli.spec.validate)",
        "column_sets become Karni.column_sets, the presets of the React table's column set menu, "
        "and karni check refuses a set that names a field the model does not have (karni.E551) "
        "or lists one twice (karni.E553).",
        "Name fields the entity declares (or id, created_at and updated_at), each once per set.",
    ),
    _c(
        "C681",
        "A column set has no columns, or a name that is not snake_case",
        "karni spec validate (karni_cli.spec.validate)",
        "A set's name is what a user's choice is remembered by and its label in the Columns "
        "menu (financial reads Financial), and a set without columns shows an empty table.",
        "Name the set in snake_case (default, financial) and list at least one field.",
    ),
    # C58x/C59x tooling for large projects (experimental)
    _c(
        "C580",
        "The project's karni has no context slices",
        "karni_cli.commands.context",
        "karni context --summary, --app and --model ask manage.py karni_context for a slice. "
        "The project's karni predates them.",
        "Upgrade karni in the project (pip install -U karni), or run karni context without "
        "those flags.",
    ),
    _c(
        "C581",
        "git cannot say which files changed",
        "karni_cli.commands.check.changed_files; karni check --changed",
        "karni check --changed asks git for the files changed in the working tree and the "
        "index (against HEAD or the ref given), plus untracked files. git is missing, the "
        "project is not in a git repository, or git does not know the ref.",
        "Run it inside a git repository (git init, then commit), pass a ref git knows (a "
        "branch, a tag, a commit), or run karni check without --changed.",
    ),
    _c(
        "C582",
        "The project's karni has no check cache",
        "karni_cli.commands.check",
        "karni check --changed and --no-cache pass options to manage.py karni_check that the "
        "project's karni predates.",
        "Upgrade karni in the project (pip install -U karni), or run karni check without "
        "those flags.",
    ),
    _c(
        "C720",
        "A protected file field needs the storage module",
        "karni spec validate, karni plan and karni make model (file:protected, image:protected)",
        "file:protected and image:protected are ProtectedFileField and ProtectedImageField of "
        "the karni-storage module: files stored privately and downloaded only through the "
        "row's own viewset. Without the module the model cannot import them.",
        "Add the module: modules: {storage: {provider: aws}} in karni.yaml, or karni add "
        "storage for karni make model. Or make the field a plain file or image.",
    ),
    # C74x production proof (API versions, deploy)
    _c(
        "C740",
        "app.api_version is not a version name",
        "karni spec validate (karni_cli.spec.validate)",
        "app.api_version is the API's current version. karni build writes it as KARNI_API_VERSION, "
        "and the API is then mounted at /api/<version>/. The name is a URL segment: lower case "
        "letters, digits and -, starting with a letter or digit, at most 16 characters, such as v1.",
        "Write a name like v1 or 2026-11, or leave the key out for an unversioned API.",
    ),
    # C780-C799 suggestions from code (experimental)
    _c(
        "C780",
        "The project's karni predates suggestions",
        "karni_cli.suggest.core_suggestions",
        "karni suggest and karni doctor ask the project's interpreter for its suggestions "
        "(manage.py karni_suggest), and the project's karni does not have that command.",
        "Upgrade karni in the project (pip install -U karni). karni check and karni doctor "
        "still run and print the suggestions that read karni.yaml and the README.",
    ),
    _c(
        "C781",
        "manage.py karni_suggest failed",
        "karni_cli.suggest.core_suggestions",
        "The project could not be started, or something in it prints to stdout at startup, so "
        "the command's JSON did not come back.",
        "Run python manage.py karni_suggest --json in the project to see the error. "
        "karni check shows the same startup problem.",
    ),
)


def core_source_dir() -> Path | None:
    """``karni/errorcodes``: the monorepo source, else the wheel's bundled copy."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni" / "karni" / "errorcodes"
        if (candidate / "__init__.py").is_file():
            return candidate
    packaged = resources.files("karni_cli") / "_errorcodes"
    with resources.as_file(packaged) as path:
        if (path / "__init__.py").is_file():
            return path
    return None


def core_module() -> ModuleType | None:
    """``karni.errorcodes`` loaded by path under a private name (no Django needed)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    directory = core_source_dir()
    if directory is None:
        return None
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, directory / "__init__.py")
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        return None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        del sys.modules[_MODULE_NAME]
        raise
    return loaded


def failures_module() -> ModuleType | None:
    """``karni.errorcodes.failures`` (the ``karni explain -`` catalogue), loaded by path.

    It sits beside the registry (and inside its bundled copy), imports only
    the stdlib and its parent package, so it loads under the same private
    name as :func:`core_module` without Django or a project.
    """
    name = f"{_MODULE_NAME}.failures"
    if name in sys.modules:
        return sys.modules[name]
    directory = core_source_dir()
    if directory is None or core_module() is None or not (directory / "failures.py").is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, directory / "failures.py")
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        return None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        del sys.modules[name]
        raise
    return loaded


def docs_url(code: str) -> str:
    """The docs link for any code (Karni's single DOCS_BASE_URL)."""
    core = core_module()
    if core is not None:
        return str(core.docs_url(code))
    return f"{_FALLBACK_BASE}errors/#{code.lower()}"


def _module_entries() -> list[Any]:
    found: list[Any] = []
    for entry_point in entry_points(group="karni.errorcodes"):
        try:
            found.extend(entry_point.load())
        except Exception:  # noqa: BLE001, S112 - a broken module must not break explain
            continue
    return found


def _from_project(code: str) -> dict[str, str] | None:
    """Ask the project interpreter (it has the project's modules installed)."""
    from karni_cli import project as project_mod

    project = project_mod.find_project()
    python = project_mod.venv_python(project) if project is not None else None
    if python is None:
        return None
    try:
        proc = subprocess.run(
            [str(python), "-m", "karni.errorcodes", code, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=project,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    data = json.loads(proc.stdout)
    return data if isinstance(data, dict) else None


def lookup(code: str) -> dict[str, str] | None:
    """The entry for ``code`` as a dict (code, title, kind, why, fix, source, url), or None.

    ``K`` codes are not handled here (``karni explain`` renders the rule).
    """
    wanted = code.strip().upper()
    for cli in CODES:
        if cli.code == wanted:
            return cli.as_dict()
    core = core_module()
    if core is not None:
        for entry in (*core.CODES, *_module_entries()):
            if entry.code == wanted:
                return dict(entry.as_dict())
    return _from_project(wanted)
