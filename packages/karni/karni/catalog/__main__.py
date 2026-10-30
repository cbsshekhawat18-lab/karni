"""``python -m karni.catalog``: the installed modules' manifests as JSON, for karni-cli.

The CLI runs this in the project's interpreter when it runs outside the
project's environment, so ``karni modules list`` and ``karni add`` see the
modules installed there. It prints ``{name: {"source": ..., "text": ...}}``
with each manifest's TOML text (the CLI parses it), and exits 2 with the
problem on stderr when one cannot be read.
"""

from __future__ import annotations

import json
import sys

from karni.catalog import ManifestError, installed_texts


def main() -> int:
    try:
        found = installed_texts()
    except ManifestError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    payload = {name: {"source": source, "text": text} for name, (source, text) in found.items()}
    sys.stdout.write(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
