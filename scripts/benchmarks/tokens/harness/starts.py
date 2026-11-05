"""The two starting projects, made by code so every run starts from the same state.

``plain``: django-admin startproject, DRF, a Vite React TypeScript frontend, no Karni.
``karni``: ``karni new`` from wheels built from this checkout, its agent files, and the Karni
MCP server in ``.mcp.json``.

Dependencies are installed once into cached folders under the bench home:
``starts/<name>/wheelhouse`` (every wheel, so a run installs offline in seconds) and
``starts/<name>/project`` (the files, with ``frontend/node_modules``). A run copies the project
(a copy-on-write clone on macOS), creates its own virtualenv from the wheelhouse, and commits.
Install time is not part of the measure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

CONDITIONS = ("plain", "karni")
PROJECT_NAME = "Bench App"

PLAIN_REQUIREMENTS = [
    "Django~=5.2.0",
    "djangorestframework",
    "djangorestframework-simplejwt",
    "psycopg[binary]",
    "pytest",
    "requests",
]
KARNI_MODULES = ["karni-payments", "karni-approvals", "karni-impersonation", "karni-site"]
KARNI_REQUIREMENTS = [
    "karni",
    "karni-cli[mcp]",
    *KARNI_MODULES,
    "psycopg[binary]",
    "pytest",
    "pytest-django",
    "requests",
]

GITIGNORE = """\
__pycache__/
*.py[cod]
.venv/
.env
node_modules/
frontend/node_modules/
frontend/dist/
db.sqlite3
"""

PLAIN_SETTINGS_TAIL = """

# --- API and database (the starting project) ---
import os
from urllib.parse import unquote, urlparse

INSTALLED_APPS += ["rest_framework"]
ALLOWED_HOSTS = ["*"]


def _database(url):
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": _database(os.environ["DATABASE_URL"])}
"""

FRONTEND_FILES = {
    "package.json": json.dumps(
        {
            "name": "bench-app-frontend",
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "scripts": {"dev": "vite", "build": "tsc && vite build", "preview": "vite preview"},
            "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
            "devDependencies": {
                "@types/react": "^18.3.5",
                "@types/react-dom": "^18.3.0",
                "@vitejs/plugin-react": "^4.3.1",
                "typescript": "^5.5.4",
                "vite": "^5.4.2",
            },
        },
        indent=2,
    )
    + "\n",
    "index.html": (
        '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        "    <title>Bench App</title>\n  </head>\n  <body>\n"
        '    <div id="root"></div>\n    <script type="module" src="/src/main.tsx"></script>\n'
        "  </body>\n</html>\n"
    ),
    "tsconfig.json": json.dumps(
        {
            "compilerOptions": {
                "target": "ES2020",
                "useDefineForClassFields": True,
                "lib": ["ES2020", "DOM", "DOM.Iterable"],
                "module": "ESNext",
                "skipLibCheck": True,
                "moduleResolution": "bundler",
                "allowImportingTsExtensions": True,
                "isolatedModules": True,
                "noEmit": True,
                "jsx": "react-jsx",
                "strict": True,
            },
            "include": ["src"],
        },
        indent=2,
    )
    + "\n",
    "vite.config.ts": (
        'import react from "@vitejs/plugin-react";\nimport { defineConfig } from "vite";\n\n'
        'export default defineConfig({ plugins: [react()], server: { proxy: { "/api": '
        '"http://127.0.0.1:8000" } } });\n'
    ),
    "src/main.tsx": (
        'import React from "react";\nimport ReactDOM from "react-dom/client";\n\n'
        'import App from "./App";\n\n'
        'ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(\n'
        "  <React.StrictMode>\n    <App />\n  </React.StrictMode>,\n);\n"
    ),
    "src/App.tsx": "export default function App() {\n  return <h1>Bench App</h1>;\n}\n",
    "src/vite-env.d.ts": '/// <reference types="vite/client" />\n',
}


@dataclass
class Start:
    """A starting project, ready to copy: the files, the wheelhouse and what to install."""

    name: str
    project: Path
    wheelhouse: Path | None = None
    requirements: list[str] = field(default_factory=list)
    mcp: bool = False  # the project has a .mcp.json for the Karni MCP server


def home_of(name: str) -> Path:
    return paths.home() / "starts" / name


def load(name: str) -> Start:
    """The cached starting project ``name`` (build it first with ``run.py --build-starts``)."""
    base = home_of(name)
    if not (base / "READY").is_file():
        raise SystemExit(f"The {name} starting project is not built: run.py --build-starts")
    requirements = (base / "requirements.txt").read_text().split("\n")
    return Start(
        name=name,
        project=base / "project",
        wheelhouse=base / "wheelhouse",
        requirements=[line for line in requirements if line],
        mcp=name == "karni",
    )


def clone(source: Path, target: Path) -> None:
    """Copy a folder, as a copy-on-write clone where the system offers one (macOS)."""
    if (
        sys.platform == "darwin"
        and subprocess.run(
            ["cp", "-cR", str(source), str(target)], capture_output=True, check=False
        ).returncode
        == 0
    ):
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)


def venv_python(project: Path) -> Path:
    return project / ".venv" / "bin" / "python"


def make_venv(project: Path, start: Start) -> Path:
    """The run's virtualenv, installed offline from the start's wheelhouse."""
    venv.EnvBuilder(with_pip=True, clear=True).create(project / ".venv")
    python = venv_python(project)
    if start.wheelhouse is not None and start.requirements:
        subprocess.run(
            [
                str(python), "-m", "pip", "install", "-q", "--no-index",
                "--disable-pip-version-check", "--find-links", str(start.wheelhouse),
                *start.requirements,
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
    return python


def write_mcp(project: Path) -> Path:
    """The Karni MCP server for a run: ``.mcp.json`` with the run's own ``karni``."""
    config = {
        "mcpServers": {
            "karni": {
                "command": str(project / ".venv" / "bin" / "karni"),
                "args": ["mcp", "--project", str(project)],
            }
        }
    }
    target = project / ".mcp.json"
    target.write_text(json.dumps(config, indent=2) + "\n")
    return target


# --- building the starts (once) ------------------------------------------------------------


def _run(argv: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        tail = (done.stdout + done.stderr)[-1500:]
        raise SystemExit(f"{' '.join(argv[:4])} failed ({done.returncode}):\n{tail}")


def _npm_env() -> dict[str, str]:
    base = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE")
    }
    return {**base, "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", ""), "CI": "1"}


def _fresh(base: Path) -> None:
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)


def _scratch_venv(base: Path, wheelhouse: Path, requirements: list[str]) -> Path:
    venv.EnvBuilder(with_pip=True, clear=True).create(base / "_venv")
    python = base / "_venv" / "bin" / "python"
    _run(
        [
            str(python), "-m", "pip", "install", "-q", "--no-index", "--find-links",
            str(wheelhouse), *requirements,
        ]
    )  # fmt: skip
    return python


def build_plain() -> Start:
    base = home_of("plain")
    _fresh(base)
    wheelhouse = base / "wheelhouse"
    _run([sys.executable, "-m", "pip", "wheel", "-q", "-w", str(wheelhouse), *PLAIN_REQUIREMENTS])
    _scratch_venv(base, wheelhouse, PLAIN_REQUIREMENTS)
    project = base / "project"
    project.mkdir()
    _run([str(base / "_venv" / "bin" / "django-admin"), "startproject", "config", "."], cwd=project)
    with (project / "config" / "settings.py").open("a") as handle:
        handle.write(PLAIN_SETTINGS_TAIL)
    (project / ".gitignore").write_text(GITIGNORE)
    for rel, text in FRONTEND_FILES.items():
        target = project / "frontend" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    _run(["npm", "install", "--no-audit", "--no-fund"], cwd=project / "frontend", env=_npm_env())
    _run(["npm", "run", "build"], cwd=project / "frontend", env=_npm_env())
    shutil.rmtree(project / "frontend" / "dist", ignore_errors=True)
    _finish(base, PLAIN_REQUIREMENTS)
    return load("plain")


def build_karni() -> Start:
    base = home_of("karni")
    _fresh(base)
    wheelhouse = base / "wheelhouse"
    local = base / "local-wheels"
    sources = [
        paths.REPO_ROOT / "packages" / "karni",
        paths.REPO_ROOT / "packages" / "karni-cli",
        *(paths.REPO_ROOT / "modules" / name for name in KARNI_MODULES),
    ]
    for source in sources:
        _run(
            [sys.executable, "-m", "pip", "wheel", "-q", "--no-deps", "-w", str(local), str(source)]
        )
    wheels = {path.name.split("-")[0].replace("_", "-"): path for path in local.glob("*.whl")}
    resolve = [str(wheels[name]) for name in ("karni", *KARNI_MODULES)]
    resolve.append(f"karni-cli[mcp] @ {wheels['karni-cli'].as_uri()}")
    resolve += ["psycopg[binary]", "pytest", "pytest-django", "requests"]
    _run([sys.executable, "-m", "pip", "wheel", "-q", "-w", str(wheelhouse), *resolve])
    _scratch_venv(base, wheelhouse, KARNI_REQUIREMENTS)
    env = {**_npm_env(), "KARNI_TEMPLATES": str(paths.REPO_ROOT / "templates" / "project")}
    env["PATH"] = f"{base / '_venv' / 'bin'}:{env['PATH']}"
    env["KARNI_UI_SRC"] = str(paths.REPO_ROOT / "packages" / "karni-ui")
    staging = base / "staging"
    staging.mkdir()
    _run(["karni", "new", PROJECT_NAME, "--kind", "app", "-o", str(staging)], env=env)
    project = base / "project"
    (staging / "bench_app").rename(project)
    _run(["npm", "install", "--no-audit", "--no-fund"], cwd=project / "frontend", env=_npm_env())
    shutil.rmtree(staging)
    _finish(base, KARNI_REQUIREMENTS)
    return load("karni")


def _finish(base: Path, requirements: list[str]) -> None:
    shutil.rmtree(base / "_venv", ignore_errors=True)
    (base / "requirements.txt").write_text("\n".join(requirements) + "\n")
    (base / "READY").write_text("ok\n")


def build(name: str) -> Start:
    return build_plain() if name == "plain" else build_karni()
