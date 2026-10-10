"""``python -m karni.errorcodes CODE [--json]``: one registry entry, modules included.

karni-cli's ``karni explain`` runs this in the project interpreter for codes
it does not bundle (an installed module's, such as ``PAY004``).
"""

from __future__ import annotations

import argparse
import json
import sys

from karni.errorcodes import get


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m karni.errorcodes")
    parser.add_argument("code")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    entry = get(args.code)
    if entry is None:
        print(f"Unknown code {args.code!r}.", file=sys.stderr)
        return 1
    data = entry.as_dict()
    if args.json:
        print(json.dumps(data))
    else:
        print("\n".join(f"{key}: {value}" for key, value in data.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
