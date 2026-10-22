"""MkDocs hooks for the docs site's machine-readable surfaces (mkdocs.yml `hooks:`).

- Every page has a front-matter ``description``, and no two pages share a
  title or a description; a miss is a warning, which ``strict: true`` fails.
- The homepage carries schema.org ``SoftwareApplication`` JSON-LD; a page with
  ``faq: true`` in its front matter carries ``FAQPage`` JSON-LD built from its
  ``## Question?`` headings and the paragraphs under them.
- ``llms-full.txt`` is written at the site root: the plain-text Markdown of
  the pages listed in ``LLMS_FULL``, each under its URL.

The canonical description (docs/seo/description.txt) is the homepage's
description; scripts/check_description.py keeps every other surface equal to it.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.karni_seo")

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION = (ROOT / "docs" / "seo" / "description.txt").read_text(encoding="utf-8").strip()

#: The pages llms-full.txt concatenates, in reading order (docs-relative paths).
LLMS_FULL = [
    "index.md",
    "faq.md",
    "quickstart.md",
    "guide/with-ai.md",
    "agents.md",
    "api.md",
    "concepts/queryset-permissions.md",
    "ui.md",
    "testing.md",
    "stability.md",
    "compare/index.md",
    "compare/cookiecutter-django.md",
    "compare/saas-pegasus.md",
    "compare/django-drf.md",
    "compare/django-react-boilerplate.md",
]

_seen_titles: dict[str, str] = {}
_seen_descriptions: dict[str, str] = {}
_markdown: dict[str, str] = {}


def _version() -> str:
    data = tomllib.loads((ROOT / "packages" / "karni" / "pyproject.toml").read_text())
    return str(data["project"]["version"])


def _plain(markdown: str) -> str:
    """Markdown inline syntax to plain text, for JSON-LD answers."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__|\*|_)(\S(?:.*?\S)?)\1", r"\2", text)
    return re.sub(r"\s+", " ", text).strip()


def faq_pairs(markdown: str) -> list[tuple[str, str]]:
    """``(question, answer)`` for every ``## ...?`` heading and the paragraphs under it."""
    pairs: list[tuple[str, str]] = []
    for block in re.split(r"^## ", markdown, flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        question = _plain(heading)
        if not question.endswith("?"):
            continue
        answer = re.split(r"^#{1,6} ", body, maxsplit=1, flags=re.M)[0]
        # Prose only: tables, fences and indented code do not read as an answer.
        prose = (line for line in answer.splitlines() if not line.startswith(("|", "```", "    ")))
        answer = "\n".join(prose)
        if _plain(answer):
            pairs.append((question, _plain(answer)))
    return pairs


def _jsonld(data: dict[str, Any]) -> str:
    # "</" would end the <script> element early.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def on_config(config: Any) -> Any:
    _seen_titles.clear()
    _seen_descriptions.clear()
    _markdown.clear()
    return config


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    path = page.file.src_uri
    _markdown[path] = markdown
    description = str(page.meta.get("description") or "").strip()
    if not description:
        log.warning("%s has no front-matter description (every page needs its own).", path)
    elif description in _seen_descriptions:
        log.warning("%s repeats the description of %s.", path, _seen_descriptions[description])
    else:
        _seen_descriptions[description] = path
    title = page.title or ""
    if title in _seen_titles:
        log.warning("%s repeats the title %r of %s.", path, title, _seen_titles[title])
    else:
        _seen_titles[title] = path

    blocks: list[str] = []
    site = str(config["site_url"])
    if page.is_homepage:
        if description != DESCRIPTION:
            log.warning("index.md's description must be docs/seo/description.txt verbatim.")
        blocks.append(
            _jsonld(
                {
                    "@context": "https://schema.org",
                    "@type": "SoftwareApplication",
                    "name": "Karni",
                    "description": DESCRIPTION,
                    "url": site,
                    "applicationCategory": "DeveloperApplication",
                    "operatingSystem": "Linux, macOS, Windows",
                    "softwareVersion": _version(),
                    "license": "https://www.apache.org/licenses/LICENSE-2.0",
                    "isAccessibleForFree": True,
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                    "sameAs": [
                        str(config["repo_url"]),
                        "https://pypi.org/project/karni/",
                        "https://www.npmjs.com/package/@karni/ui",
                    ],
                }
            )
        )
    if page.meta.get("faq"):
        pairs = faq_pairs(markdown)
        if not pairs:
            log.warning("%s sets faq: true but has no '## Question?' headings.", path)
        blocks.append(
            _jsonld(
                {
                    "@context": "https://schema.org",
                    "@type": "FAQPage",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": question,
                            "acceptedAnswer": {"@type": "Answer", "text": answer},
                        }
                        for question, answer in pairs
                    ],
                }
            )
        )
    page.meta["karni_jsonld"] = blocks
    return markdown


def on_post_build(config: Any) -> None:
    site = str(config["site_url"])
    missing = [path for path in LLMS_FULL if path not in _markdown]
    if missing:
        log.warning("llms-full.txt lists pages that do not exist: %s", ", ".join(missing))
    parts = [f"# Karni\n\n> {DESCRIPTION}\n\nSource: {config['repo_url']}\n"]
    for path in LLMS_FULL:
        if path not in _markdown:
            continue
        url = site + re.sub(r"(^|/)index\.md$", r"\1", path).removesuffix(".md")
        url = url if url.endswith("/") else url + "/"
        body = re.sub(r"\A---\n.*?\n---\n", "", _markdown[path], flags=re.S).strip()
        parts.append(f"\n---\n\nURL: {url}\n\n{body}\n")
    Path(config["site_dir"], "llms-full.txt").write_text("".join(parts), encoding="utf-8")
