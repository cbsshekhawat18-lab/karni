"""Count Medintel's project code — the number the README reports.

    python scripts/loc.py [--pristine DIR]

Counted: non-blank, non-comment lines of the files Medintel wrote or
generated-and-kept, grouped as spec / models / seeds / pages. Left out:
tests, migrations, lockfiles, node_modules, the e2e suite, this script, and
the scaffold `karni new` produced. A scaffold file Medintel edited
(config/settings.py, config/urls.py, frontend/src/routes.tsx) counts only the
lines it added, measured against a pristine `karni new "Medintel"` output
when ``--pristine`` points at one; without it those files count whole, which
overstates.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GROUPS: dict[str, tuple[str, ...]] = {
    "spec": ("karni.yaml",),
    "models": ("intel/models.py",),
    "seeds": ("intel/seeds.py",),
    "pages": (
        "frontend/src/pages/insights.tsx",
        "frontend/src/pages/players.tsx",
        "frontend/src/pages/deals-chart.tsx",
        "frontend/src/pages/search.tsx",
        "frontend/src/pages/login.tsx",
        "frontend/src/components/CategoryTree.tsx",
        "frontend/src/google.ts",
    ),
}
#: Scaffold files Medintel edited by hand: only added lines count. The settings
#: block, intel/karni/, the generated pages and tests are written by `karni build`
#: and not counted, nor is intel/viewsets.py, which stays the stub build wrote.
EDITED_SCAFFOLD: dict[str, str] = {
    "frontend/src/routes.tsx": "pages",
    "frontend/src/App.tsx": "pages",
    "frontend/src/layout.tsx": "pages",
}


def code_lines(text: str) -> list[str]:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", '"""')):
            continue
        kept.append(line)
    return kept


def without_spec_blocks(text: str) -> str:
    """Drop what `karni build` writes between its `karni:spec ... start` and `end` markers."""
    kept, skipping = [], False
    for line in text.splitlines():
        skipping = skipping or ("karni:spec" in line and line.rstrip().endswith("start"))
        if not skipping:
            kept.append(line)
        skipping = skipping and not ("karni:spec" in line and line.rstrip().endswith("end"))
    return "\n".join(kept)


def added_lines(path: str, pristine: Path | None) -> int:
    ours = code_lines(without_spec_blocks((ROOT / path).read_text(encoding="utf-8")))
    if pristine is None or not (pristine / path).is_file():
        return len(ours)
    theirs = code_lines((pristine / path).read_text(encoding="utf-8"))
    return sum(1 for line in difflib.ndiff(theirs, ours) if line.startswith("+ "))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pristine", type=Path, help="an untouched `karni new Medintel` output")
    args = parser.parse_args(argv)
    totals: dict[str, int] = {group: 0 for group in GROUPS}
    rows: list[tuple[str, str, int]] = []
    for group, files in GROUPS.items():
        for path in files:
            count = len(code_lines((ROOT / path).read_text(encoding="utf-8")))
            totals[group] += count
            rows.append((group, path, count))
    for path, group in EDITED_SCAFFOLD.items():
        count = added_lines(path, args.pristine)
        totals[group] += count
        rows.append((group, f"{path} (added)", count))
    width = max(len(path) for _, path, _ in rows)
    for group, path, count in rows:
        print(f"{group:<9} {path:<{width}} {count:>5}")
    print("-" * (width + 16))
    for group, count in totals.items():
        print(f"{group:<9} {'':<{width}} {count:>5}")
    print(f"{'total':<9} {'':<{width}} {sum(totals.values()):>5}")
    if args.pristine is None:
        print("(no --pristine: edited scaffold files counted whole)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
