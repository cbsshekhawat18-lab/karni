"""``python -m karni.agent`` — JSON bridge for the karni CLI.

The CLI uses this when karni is not importable in its own environment: it
runs the project's interpreter, so the project's karni version answers.

    python -m karni.agent dump [--root DIR]
    python -m karni.agent check [--root DIR] FILE [FILE ...]

Exit status: 0 on success (``check`` prints ``[]`` when clean), 2 on bad
input (malformed karni.rules.py, unreadable or unparsable file).
"""

from __future__ import annotations

import argparse
import json
import sys

from . import OverrideError, check_paths, dump


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m karni.agent")
    sub = parser.add_subparsers(dest="command", required=True)
    dump_cmd = sub.add_parser("dump")
    dump_cmd.add_argument("--root", default=None)
    check_cmd = sub.add_parser("check")
    check_cmd.add_argument("--root", default=None)
    check_cmd.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            payload: object = dump(args.root)
        else:
            payload = check_paths(args.files, args.root)
    except (OverrideError, OSError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
