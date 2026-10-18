"""The machine-readable changelog (karni.changelog) and the deprecations it records.

Four guarantees ``karni upgrade`` and the deprecation policy rely on:

* the shipped changelog matches its schema;
* every ``warn_deprecated`` call in Karni has a changelog entry with the same
  ``removed_in``, and every deprecation entry still has its warning;
* every warning's ``doc_anchor`` and every entry's ``migration`` resolve to a
  heading in ``docs/migrations/``;
* links inside the migration notes resolve.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import karni
from karni import changelog
from karni.changelog import Change, ChangelogError, version_key

PACKAGE = Path(karni.__file__).resolve().parent
DOCS = Path(__file__).resolve().parents[3] / "docs"
MIGRATIONS = DOCS / "migrations"

needs_docs = pytest.mark.skipif(
    not MIGRATIONS.is_dir(), reason="docs/ is not shipped with the package"
)


# helpers


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lower-case, punctuation dropped, spaces -> hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(markdown: Path) -> set[str]:
    anchors: set[str] = set()
    fenced = False
    for line in markdown.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"^#{1,6} (.+)$", line)):
            slug = _slug(match.group(1))
            assert slug not in anchors, f"{markdown.name}: duplicate heading anchor #{slug}"
            anchors.add(slug)
    return anchors


def _resolves(doc_anchor: str) -> bool:
    page, _, anchor = doc_anchor.partition("#")
    path = DOCS / page
    return path.is_file() and (not anchor or anchor in _anchors(path))


def _literal(node: ast.expr, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    raise AssertionError(
        f"line {node.lineno}: removed_in/doc_anchor must be a string literal or a "
        "module-level string constant, so the changelog test can read it"
    )


def _warnings_in_code() -> list[tuple[str, str, str]]:
    """``(location, removed_in, doc_anchor)`` of every ``warn_deprecated`` call."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "deprecation.py" and path.parent == PACKAGE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "warn_deprecated":
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            location = f"{path.relative_to(PACKAGE)}:{node.lineno}"
            found.append(
                (
                    location,
                    _literal(keywords["removed_in"], constants),
                    _literal(keywords["doc_anchor"], constants),
                )
            )
    return found


# the shipped changelog


def test_the_shipped_changelog_is_valid() -> None:
    releases = changelog.load()
    assert releases, "no release files in karni/changelog/"
    assert [r.version for r in releases] == sorted((r.version for r in releases), key=version_key)
    for release in releases:
        assert release.changes, f"{release.version}.toml records no change"


def test_karni_records_its_0_2_deprecations() -> None:
    by_id = {change.id: change for change in changelog.changes()}
    for change_id in ("all-objects", "all-with-deleted", "deleted-only"):
        assert by_id[change_id].mechanical and by_id[change_id].removed_in == "1.0"
    assert by_id["soft-delete-manager-mixin"].replacement == "karni.managers.ScopedManagerMixin"
    # Not safely mechanical: reported with its note, never guessed.
    assert by_id["object-permission-classes"].mechanical is False


def test_every_deprecation_in_code_has_an_entry() -> None:
    warnings = _warnings_in_code()
    assert len(warnings) >= 6, warnings  # the 0.2 deprecations, at least
    entries: dict[str, list[Change]] = {}
    for change in changelog.changes():
        entries.setdefault(change.migration, []).append(change)
    for location, removed_in, doc_anchor in warnings:
        matching = entries.get(doc_anchor, [])
        assert matching, f"{location}: no changelog entry has migration = {doc_anchor!r}"
        assert any(c.removed_in == removed_in for c in matching), (
            f"{location}: warns removal in {removed_in}, the changelog says "
            f"{[c.removed_in for c in matching]}"
        )


def test_every_deprecation_entry_still_warns() -> None:
    anchors = {doc_anchor for _, _, doc_anchor in _warnings_in_code()}
    for change in changelog.changes():
        if change.is_deprecation:
            assert change.migration in anchors, (
                f"{change.id}: deprecated until {change.removed_in}, but no "
                f"warn_deprecated(..., doc_anchor={change.migration!r}) is left in karni"
            )


def test_every_warning_carries_its_removal_version_and_a_migration_note() -> None:
    for location, removed_in, doc_anchor in _warnings_in_code():
        version_key(removed_in)  # a release version
        assert doc_anchor.startswith("migrations/"), (
            f"{location}: doc_anchor {doc_anchor!r} must link the migration note"
        )


@needs_docs
def test_every_warning_anchor_resolves_to_a_migration_heading() -> None:
    for location, _, doc_anchor in _warnings_in_code():
        assert _resolves(doc_anchor), f"{location}: docs/{doc_anchor} has no such heading"


@needs_docs
def test_every_migration_note_anchor_exists() -> None:
    for change in changelog.changes():
        assert _resolves(change.migration), f"{change.id}: docs/{change.migration} not found"


@needs_docs
def test_links_inside_the_migration_notes_resolve() -> None:
    for page in sorted(MIGRATIONS.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://")):
                continue
            file, _, anchor = target.partition("#")
            path = (page.parent / file).resolve() if file else page
            assert path.is_file(), f"{page.name}: broken link {target}"
            if anchor:
                assert anchor in _anchors(path), f"{page.name}: no heading for {target}"


# the schema rejects what the tooling cannot trust

GOOD = """\
version = "0.3.0"

[[change]]
id = "renamed-setting"
kind = "setting-rename"
symbol = "KARNI_OLD"
replacement = "KARNI_NEW"
summary = "Renamed."
removed_in = "1.0"
mechanical = true
codemod = "v1_0.renamed_setting"
migration = "migrations/0.3.md#karni_old"
"""


def _write(tmp_path: Path, text: str, name: str = "0.3.0.toml") -> Path:
    (tmp_path / name).write_text(text)
    return tmp_path


def test_a_valid_release_loads(tmp_path: Path) -> None:
    (change,) = changelog.changes(_write(tmp_path, GOOD))
    assert change.release == "0.3.0" and change.breaks_in == "1.0"
    assert change.is_deprecation


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (('kind = "setting-rename"', 'kind = "rename"'), "is not one of"),
        (('codemod = "v1_0.renamed_setting"\n', ""), "needs a codemod"),
        (('removed_in = "1.0"', 'removed_in = "0.2"'), "later than 0.3.0"),
        (('replacement = "KARNI_NEW"\n', ""), "needs a replacement"),
        (('id = "renamed-setting"', 'id = "Renamed_Setting"'), "kebab-case"),
        (('migration = "migrations/0.3.md#karni_old"', 'migration = "0.3.md"'), "migration"),
        (('codemod = "v1_0.renamed_setting"', 'codemod = "renamed"'), "codemod must"),
        (("mechanical = true", 'mechanical = "yes"'), "true or false"),
        (('summary = "Renamed."', 'summary = "Renamed."\nnote = "x"'), "unknown key"),
        (('version = "0.3.0"', 'version = "0.3.1"'), "match the file name"),
    ],
)
def test_schema_violations_are_reported(
    tmp_path: Path, edit: tuple[str, str], message: str
) -> None:
    old, new = edit
    assert old in GOOD
    with pytest.raises(ChangelogError, match=message):
        changelog.load(_write(tmp_path, GOOD.replace(old, new)))


def test_ids_are_unique_across_releases(tmp_path: Path) -> None:
    _write(tmp_path, GOOD)
    _write(tmp_path, GOOD.replace("0.3.0", "0.4.0"), name="0.4.0.toml")
    with pytest.raises(ChangelogError, match="duplicate id 'renamed-setting'"):
        changelog.load(tmp_path)


def test_version_keys() -> None:
    assert version_key("1.0") == (1, 0, 0) == version_key("1.0.0")
    assert version_key("0.10") > version_key("0.9.9")
    with pytest.raises(ChangelogError):
        version_key("1.0rc1")
