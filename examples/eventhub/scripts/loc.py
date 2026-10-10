"""Count EventHub's project code — the number the README reports.

    python scripts/loc.py [--pristine DIR]

Counted: non-blank, non-comment lines of the files EventHub wrote or
generated-and-kept, grouped as models / viewsets / pages / other. Left out:
tests, migrations, lockfiles, node_modules, the e2e suite, this script, and
the scaffold `karni new` produced. A scaffold file EventHub edited
(config/settings.py, config/urls.py, frontend/src/routes.tsx) counts only the
lines it added, measured against a pristine `karni new "EventHub"` output
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
    "models": ("events/models.py",),
    "viewsets": ("events/viewsets.py",),
    "pages": (
        "frontend/src/pages/login.tsx",
        "frontend/src/pages/events.tsx",
        "frontend/src/pages/event-detail.tsx",
        "frontend/src/pages/event-form.tsx",
        "frontend/src/pages/event-dashboard.tsx",
        "frontend/src/pages/bookings.tsx",
        "frontend/src/pages/booking-detail.tsx",
        "frontend/src/pages/booking-form.tsx",
        "frontend/src/components/TierList.tsx",
    ),
    "other": (
        "events/apps.py",
        "events/listeners.py",
        "events/payments.py",
        "events/seeds.py",
        "events/factories.py",
    ),
}
#: Scaffold files EventHub edited: only added lines count.
EDITED_SCAFFOLD: dict[str, str] = {
    "config/settings.py": "other",
    "config/urls.py": "other",
    "frontend/src/routes.tsx": "pages",
}


def code_lines(text: str) -> list[str]:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", '"""')):
            continue
        kept.append(line)
    return kept


def added_lines(path: str, pristine: Path | None) -> int:
    ours = code_lines((ROOT / path).read_text(encoding="utf-8"))
    if pristine is None or not (pristine / path).is_file():
        return len(ours)
    theirs = code_lines((pristine / path).read_text(encoding="utf-8"))
    return sum(1 for line in difflib.ndiff(theirs, ours) if line.startswith("+ "))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pristine", type=Path, help="an untouched `karni new EventHub` output")
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
