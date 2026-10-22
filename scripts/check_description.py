"""Karni's canonical description, identical on every surface.

docs/seo/description.txt holds the one description of what Karni is and who
it is for. Every surface that describes Karni carries it verbatim:

- exactly: the README's opening, the docs homepage (its meta description,
  which is also the Open Graph description, and its first paragraph),
  the FAQ's answer to "What is Karni?", llms.txt, mkdocs.yml's
  site_description, the `karni` package on PyPI, and the GitHub repository's
  About (with --github);
- after a one-sentence prefix naming the package: every other Python and npm
  package (karni-cli, @karni/ui, the modules), so each still says what it is
  first.

    python scripts/check_description.py            # fail on any drift
    python scripts/check_description.py --github   # also the GitHub About
    python scripts/check_description.py --write    # copy the canonical text everywhere

It also keeps the README's first sections in the shape that framing needs:
"Why Karni exists" (the story, under 180 words) directly before "What is
Karni", which answers the problem, how Karni solves it, what you get and
what you still write, in that order; and no marketing words anywhere above.

CI runs it with --github. The About cannot be written from here: --write
prints the `gh repo edit` command for it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FILE = ROOT / "docs" / "seo" / "description.txt"
REPO = "cbsshekhawat18-lab/karni"
#: GitHub's limit for a repository description.
ABOUT_LIMIT = 350
#: PyPI's limit for a package summary (a prefix sentence plus the description).
SUMMARY_LIMIT = 512

#: Every other package: the sentence that says what the package is, then the canonical text.
PREFIXES = {
    "packages/karni-cli/pyproject.toml": (
        "The karni command: scaffold, generate, run and upgrade Karni projects."
    ),
    "modules/karni-payments/pyproject.toml": (
        "Payments for Karni: hosted checkout, refunds and signature-verified webhooks "
        "for Stripe and Razorpay, with a test provider for CI."
    ),
    "modules/karni-approvals/pyproject.toml": (
        "Maker-checker approvals for Karni: a second person approves high-value changes "
        "before they are written, with a queue, an API and an audit trail."
    ),
    "modules/karni-impersonation/pyproject.toml": (
        "Safe 'log in as user' for Karni support staff: an explicit permission, no "
        "privilege escalation, a banner, a time limit, both identities in the audit trail."
    ),
    "packages/karni-ui/package.json": (
        "React components for Karni: schema-driven tables, forms, detail views and auth."
    ),
    "modules/karni-payments/ui/package.json": (
        "React components for the Karni payments module: CheckoutButton and PaymentStatus."
    ),
    "modules/karni-approvals/ui/package.json": (
        "React components for the Karni approvals module: ApprovalsQueue and ApprovalsBadge."
    ),
    "modules/karni-impersonation/ui/package.json": (
        "React components for the Karni impersonation module: ImpersonationBanner and its hook."
    ),
}

README_OPENING = re.compile(r'(</picture>\n</p>\n\n<p align="center">\n)(.*?)(\n</p>)', re.S)
# Quoted: an unquoted YAML value containing ": " is not a string, and MkDocs
# drops the whole front matter without a word.
INDEX_FRONT = re.compile(r'(\A---\n(?:.*\n)*?description: ")(.*)("\n(?:.*\n)*?---\n)')
INDEX_FIRST = re.compile(r"(^# Karni\n\n)((?:.+\n)+?)(\n)", re.M)
LLMS_SUMMARY = re.compile(r"(^> )(.*)$", re.M)
FAQ_WHAT = re.compile(r"(^## What is Karni\?\n\n)(.+)(\n)", re.M)
MKDOCS_SITE = re.compile(r'(^site_description: ")(.*)(")$', re.M)
TOML_DESCRIPTION = re.compile(r'(^description = ")(.*)(")$', re.M)
JSON_DESCRIPTION = re.compile(r'(^  "description": ")(.*)(",)$', re.M)


@dataclass(frozen=True)
class Surface:
    name: str
    path: str
    pattern: re.Pattern[str]
    #: "exact": the text is the description; "suffix": the package's PREFIXES sentence, then it.
    mode: str = "exact"

    def expected(self, text: str) -> str:
        return text if self.mode == "exact" else f"{PREFIXES[self.path]} {text}"


SURFACES = [
    Surface("README opening", "README.md", README_OPENING),
    Surface("docs homepage description (meta + Open Graph)", "docs/index.md", INDEX_FRONT),
    Surface("docs homepage first paragraph", "docs/index.md", INDEX_FIRST),
    Surface("llms.txt summary", "docs/llms.txt", LLMS_SUMMARY),
    Surface("FAQ: What is Karni? (also the FAQPage JSON-LD)", "docs/faq.md", FAQ_WHAT),
    Surface("mkdocs.yml site_description", "mkdocs.yml", MKDOCS_SITE),
    Surface("PyPI: karni", "packages/karni/pyproject.toml", TOML_DESCRIPTION),
    *(
        Surface(
            f"{'PyPI' if p.endswith('.toml') else 'npm'}: {Path(p).parent.as_posix()}",
            p,
            TOML_DESCRIPTION if p.endswith(".toml") else JSON_DESCRIPTION,
            "suffix",
        )
        for p in PREFIXES
    ),
]


def canonical() -> str:
    text = CANONICAL_FILE.read_text(encoding="utf-8").strip()
    problems = []
    if "\n" in text:
        problems.append("it must be one line")
    if len(text) > ABOUT_LIMIT:
        problems.append(f"it is {len(text)} characters; GitHub's About allows {ABOUT_LIMIT}")
    if '"' in text or "\\" in text:
        problems.append("it must not contain double quotes or backslashes (TOML/JSON/YAML values)")
    if problems:
        sys.exit(f"{CANONICAL_FILE.relative_to(ROOT)}: " + "; ".join(problems))
    return text


def _unwrap(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def check_surface(surface: Surface, text: str) -> str | None:
    """None when `surface` carries `text`, else what is wrong."""
    content = (ROOT / surface.path).read_text(encoding="utf-8")
    match = surface.pattern.search(content)
    if match is None:
        return f"{surface.path}: the {surface.name} was not found where expected"
    found = _unwrap(match.group(2))
    want = surface.expected(text)
    if surface.path.endswith(".toml") and len(want) > SUMMARY_LIMIT:
        return f"{surface.path}: {len(want)} characters; PyPI's summary allows {SUMMARY_LIMIT}"
    if found == want:
        return None
    return f"{surface.path} ({surface.name}):\n    is:     {found}\n    should: {want}"


def write_surface(surface: Surface, text: str) -> bool:
    path = ROOT / surface.path
    content = path.read_text(encoding="utf-8")
    match = surface.pattern.search(content)
    if match is None:
        return False
    value = surface.expected(text)
    if surface.name == "docs homepage first paragraph":
        value = _wrap(value) + "\n"
    new = content[: match.start(2)] + value + content[match.end(2) :]
    if new != content:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def _wrap(text: str, width: int = 76) -> str:
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    return "\n".join(lines)


#: The story's limit: it is a story, not an essay.
STORY_WORDS = 180
#: The questions "What is Karni" answers, in this order.
WHAT_IS_KARNI = ("The problem.", "How Karni solves it.", "What you get.", "What you still write.")
#: Words that make a claim instead of showing one.
MARKETING = ("revolutionary", "game-changing", "game changer", "supercharge")


def _section(readme: str, title: str) -> str | None:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## )", readme, re.S | re.M)
    return match.group(1) if match else None


def readme_problems(readme: str, text: str) -> list[str]:
    """What is wrong with the README's story and "What is Karni" (empty when nothing)."""
    problems: list[str] = []
    titles = re.findall(r"^## (.+)$", readme, re.M)
    if titles[:2] != ["Why Karni exists", "What is Karni"]:
        problems.append(
            'README.md: the first sections must be "Why Karni exists" then "What is Karni"; '
            f"they are {titles[:2]}"
        )
    story = _section(readme, "Why Karni exists")
    if story is not None:
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", story)
        words = len(plain.split())
        if words > STORY_WORDS:
            problems.append(
                f"README.md: Why Karni exists is {words} words; keep it under {STORY_WORDS}"
            )
    what = _section(readme, "What is Karni")
    if what is not None:
        found = re.findall(r"^\*\*(.+?)\*\*", what, re.M)
        if found != list(WHAT_IS_KARNI):
            problems.append(
                f"README.md: What is Karni must answer {list(WHAT_IS_KARNI)} in order; "
                f"it has {found}"
            )
    head = readme.split("## Show, don't tell")[0].lower() + " " + text.lower()
    problems += [
        f'README.md / description: "{word}" is a claim, not a fact'
        for word in MARKETING
        if word in head
    ]
    return problems


def github_about(fetch: Callable[[str], bytes] | None = None) -> str:
    url = f"https://api.github.com/repos/{REPO}"
    raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=20).read()  # noqa: S310
    return str(json.loads(raw).get("description") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--github", action="store_true", help="also check the GitHub About")
    parser.add_argument("--write", action="store_true", help="copy the canonical text everywhere")
    args = parser.parse_args(argv)
    text = canonical()
    if args.write:
        changed = [s.name for s in SURFACES if write_surface(s, text)]
        print("updated: " + (", ".join(changed) if changed else "nothing (already identical)"))
        print(f'GitHub About: gh repo edit {REPO} --description "{text}"')
    problems = [p for s in SURFACES if (p := check_surface(s, text)) is not None]
    problems += readme_problems((ROOT / "README.md").read_text(encoding="utf-8"), text)
    if args.github:
        about = github_about()
        if about != text:
            problems.append(
                f"GitHub About:\n    is:     {about}\n    should: {text}\n"
                f'    fix:    gh repo edit {REPO} --description "$(cat docs/seo/description.txt)"'
            )
    if problems:
        print(
            "Karni's description differs from docs/seo/description.txt on "
            f"{len(problems)} surface(s). Edit docs/seo/description.txt, then run "
            "`python scripts/check_description.py --write` (and the gh command for the About).\n"
        )
        print("\n".join(problems))
        return 1
    print(f"Karni's description is identical on {len(SURFACES) + int(args.github)} surfaces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
