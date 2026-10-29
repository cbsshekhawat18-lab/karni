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
        "The wheel bundles the project template, agent rules, changelog and error codes. One is "
        "missing, so the install is broken.",
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
        "Grants map onto KARNI_ROLES: a pattern app.entity[:action] (with * for a part, or * alone) to a scope all, own, own:<owner field>, related:<scope path key> or custom:<name>. A spec grants the standard actions view, add, change and delete.",
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
        "Each entry of pages is one key: an entity with the pages karni make page makes for it (list, detail, form), or a page name with its kind (dashboard for the scaffold's home, blank, login).",
        "Write e.g. - Session: [list, detail, form], - about: blank or - home: dashboard, each entity or page once.",
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
        "Some keys are reserved for features Karni adds later (trees, taxonomies, aggregation, integer keys, external tables, a second database, cross-entity search, markdown fields), so a spec written today keeps its meaning.",
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
        "modules lists what karni add installs, and this release knows approvals, impersonation, payments and site.",
        "Fix the name. A module of your own is added with karni add and stays out of the spec until the module catalog lets modules declare themselves.",
    ),
    _c(
        "C237",
        "A field group names a field the entity does not have",
        "karni spec validate (karni_cli.spec.validate)",
        "groups become the admin form's fieldsets, and a name that is not a field (or a field in two groups) makes that form fail to render.",
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
