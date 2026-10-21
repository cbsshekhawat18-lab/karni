# Karni monorepo task runner.
#
#   make install     editable-install every Python package + dev tools, npm ci every UI package
#   make test        pytest per Python package, vitest per UI package
#   make lint        ruff check + ruff format --check, eslint + prettier --check
#   make typecheck   mypy (root mypy.ini) per Python package, tsc --noEmit per UI package
#   make format      ruff format + import sorting, prettier --write
#
# Point PYTHON at a virtualenv interpreter if you do not want the one on PATH:
#   make test PYTHON=.venv/bin/python
#
# Python packages are processed one directory at a time: each ships a
# top-level `tests` package, so they cannot share a single pytest/mypy run.
# test/lint/typecheck visit EVERY package and fail at the end if any failed.

PYTHON ?= python3
NPM    ?= npm

# Recipes `cd` into each package, so a relative interpreter path must be made
# absolute; a bare command name (python3) is left for PATH lookup.
PY := $(if $(findstring /,$(PYTHON)),$(abspath $(PYTHON)),$(PYTHON))
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
MYPY_CONFIG := $(ROOT)/mypy.ini

# "<package dir>:<import package>" pairs. Order matters for install
# (karni-payments depends on karni).
PY_PACKAGES := \
	packages/karni:karni \
	packages/karni-cli:karni_cli \
	modules/karni-payments:karni_payments \
	modules/karni-approvals:karni_approvals \
	modules/karni-impersonation:karni_impersonation

# Order matters: modules/karni-payments/ui resolves @karni/ui from source,
# which needs packages/karni-ui/node_modules installed first.
# CORE_ONLY=1: packages/ only, as a clone that never installs modules/ (CI's
# "Python core only" job). Tests that need a module skip and name it.
ifeq ($(CORE_ONLY),1)
PY_PACKAGES := $(filter packages/%,$(PY_PACKAGES))
endif

UI_PACKAGES := packages/karni-ui modules/karni-payments/ui modules/karni-approvals/ui modules/karni-impersonation/ui

KARNI_EXTRAS := s3,images,sentry,social,2fa
PY_DEV_TOOLS := pytest pytest-django factory-boy Pillow ruff mypy types-PyYAML pre-commit

pkg_dir = $(firstword $(subst :, ,$(1)))
pkg_mod = $(lastword $(subst :, ,$(1)))

.PHONY: help install install-py install-ui test test-py test-ui lint lint-py lint-ui \
	typecheck typecheck-py typecheck-ui format format-py format-ui build-ui

help:
	@LC_ALL=C grep -E '^#   make [a-z]+ +[a-z]' $(firstword $(MAKEFILE_LIST)) | sed 's/^#//'

# --- install -----------------------------------------------------------------

install: install-py install-ui

install-py:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install \
		-e "packages/karni[$(KARNI_EXTRAS)]" \
		$(foreach p,$(filter-out packages/karni:karni,$(PY_PACKAGES)),-e $(call pkg_dir,$(p))) \
		$(PY_DEV_TOOLS)

install-ui:
	@set -e; for d in $(UI_PACKAGES); do \
		echo "==> npm ci ($$d)"; (cd $$d && $(NPM) ci); \
	done

# --- test --------------------------------------------------------------------

test: test-py test-ui

test-py:
	@rc=0; for p in $(PY_PACKAGES); do \
		d=$${p%%:*}; echo "==> pytest ($$d)"; (cd $$d && $(PY) -m pytest -q) || rc=1; \
	done; exit $$rc

test-ui:
	@rc=0; for d in $(UI_PACKAGES); do \
		echo "==> vitest ($$d)"; (cd $$d && $(NPM) test) || rc=1; \
	done; exit $$rc

# --- lint --------------------------------------------------------------------
# Paths are explicit (package + tests) so ruff's Markdown formatting does not
# pull READMEs into the format check.

lint: lint-py lint-ui

lint-py:
	@rc=0; for p in $(PY_PACKAGES); do \
		d=$${p%%:*}; m=$${p##*:}; echo "==> ruff ($$d)"; \
		(cd $$d && $(PY) -m ruff check $$m tests && $(PY) -m ruff format --check $$m tests) || rc=1; \
	done; \
	echo "==> ruff (.github/ci, root ruff.toml)"; \
	($(PY) -m ruff check .github/ci && $(PY) -m ruff format --check .github/ci) || rc=1; \
	exit $$rc

lint-ui:
	@rc=0; for d in $(UI_PACKAGES); do \
		echo "==> eslint + prettier ($$d)"; (cd $$d && $(NPM) run lint && $(NPM) run format:check) || rc=1; \
	done; exit $$rc

# --- typecheck ---------------------------------------------------------------

typecheck: typecheck-py typecheck-ui

typecheck-py:
	@rc=0; for p in $(PY_PACKAGES); do \
		d=$${p%%:*}; m=$${p##*:}; echo "==> mypy ($$d)"; \
		(cd $$d && $(PY) -m mypy --config-file $(MYPY_CONFIG) $$m tests) || rc=1; \
	done; exit $$rc

typecheck-ui:
	@rc=0; for d in $(UI_PACKAGES); do \
		echo "==> tsc ($$d)"; (cd $$d && $(NPM) run typecheck) || rc=1; \
	done; exit $$rc

# --- format ------------------------------------------------------------------

format: format-py format-ui

format-py:
	@set -e; for p in $(PY_PACKAGES); do \
		d=$${p%%:*}; m=$${p##*:}; echo "==> ruff format ($$d)"; \
		(cd $$d && $(PY) -m ruff check --select I --fix $$m tests && $(PY) -m ruff format $$m tests); \
	done
	$(PY) -m ruff check --select I --fix .github/ci
	$(PY) -m ruff format .github/ci

format-ui:
	@set -e; for d in $(UI_PACKAGES); do \
		echo "==> prettier ($$d)"; (cd $$d && $(NPM) run format); \
	done

# --- build (used by CI) ------------------------------------------------------

build-ui:
	@set -e; for d in $(UI_PACKAGES); do \
		echo "==> build ($$d)"; (cd $$d && $(NPM) run build); \
	done
