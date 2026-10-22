"""Render the welcome page: one HTML document, inline CSS and SVG, no network.

It wears the same brand as ``@karni/ui`` and the admin: the token stylesheet
(``karni/tokens.css``, the copy of ``@karni/ui/styles.css`` described in
:mod:`karni.admin.theme`) is inlined, the page's own rules read only its
tokens, and dark mode is the ``dark`` class on ``<html>``, set by the same
rule as @karni/ui's (a stored choice, else the system preference).

Every dynamic string goes through :func:`html.escape`. The scripts are the
theme switch and the copy button (``navigator.clipboard`` with a selection
fallback).
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import karni.admin
from karni.admin.theme import tokens_css
from karni.welcome.inventory import Inventory
from karni.welcome.status import Status

__all__ = ["render_page"]

_MARK = Path(karni.admin.__file__).parent / "static" / "karni" / "brand" / "karni-mark.svg"

CSS = """
:root{--s:var(--karni-space-unit);--brand-accent:#FB5D08}
*{box-sizing:border-box}
body{margin:0;background:var(--karni-color-background);color:var(--karni-color-foreground);
font-family:var(--karni-font-sans);font-size:var(--karni-font-size-base);
line-height:var(--karni-font-leading-base);-webkit-font-smoothing:antialiased}
main{max-width:880px;margin:0 auto;padding:calc(var(--s)*8) calc(var(--s)*4) calc(var(--s)*12)}
header{display:flex;align-items:center;gap:calc(var(--s)*4);margin-bottom:calc(var(--s)*2)}
header svg{width:56px;height:56px;flex:none}
h1{font-size:1.75rem;line-height:2.25rem;margin:0;font-weight:var(--karni-font-weight-semibold);
letter-spacing:var(--karni-font-tracking-tight)}
.version{color:var(--karni-color-muted-foreground);font-size:var(--karni-font-size-sm);margin:0}
h2{font-size:var(--karni-font-size-lg);line-height:var(--karni-font-leading-lg);
margin:calc(var(--s)*9) 0 calc(var(--s)*3);font-weight:var(--karni-font-weight-semibold)}
p{margin:0 0 calc(var(--s)*3)}
a{color:var(--karni-color-primary);font-weight:var(--karni-font-weight-medium);
text-decoration:underline;text-underline-offset:var(--karni-font-underline-offset)}
a:focus-visible,.copy:focus-visible{outline:var(--karni-ring-width) solid var(--karni-color-ring);
outline-offset:var(--karni-ring-offset-width);border-radius:var(--karni-radius-sm)}
.muted{color:var(--karni-color-muted-foreground)}
table{border-collapse:collapse;width:100%;font-size:var(--karni-font-size-sm)}
td,th{text-align:left;padding:calc(var(--s)*2) calc(var(--s)*2.5);
border-bottom:var(--karni-border-width) solid var(--karni-color-border);vertical-align:top}
th{font-weight:var(--karni-font-weight-medium);color:var(--karni-color-muted-foreground)}
.tick,.cross{display:inline-flex;align-items:center;justify-content:center;width:1.25rem;
height:1.25rem;border-radius:var(--karni-radius-full);font-size:var(--karni-font-size-xs);
font-weight:var(--karni-font-weight-bold)}
.tick{background:var(--karni-color-muted);color:var(--karni-color-foreground)}
.cross{background:var(--karni-color-destructive);color:var(--karni-color-destructive-foreground)}
code,pre{font-family:var(--karni-font-mono);font-size:0.8125rem;line-height:1.5}
code{background:var(--karni-color-muted);padding:1px 5px;border-radius:var(--karni-radius-sm)}
pre{background:var(--karni-color-muted);border-radius:var(--karni-radius-lg);overflow:auto;margin:0;
padding:calc(var(--s)*3) calc(var(--s)*21) calc(var(--s)*3) calc(var(--s)*3.5);
white-space:pre-wrap;word-break:break-word}
.block{position:relative;margin:calc(var(--s)*2) 0 calc(var(--s)*4)}
.copy{position:absolute;top:calc(var(--s)*1.5);right:calc(var(--s)*1.5);min-height:calc(var(--s)*8);
padding:0 calc(var(--s)*3);font:inherit;font-size:var(--karni-font-size-xs);
font-weight:var(--karni-font-weight-medium);color:var(--karni-color-foreground);
background:var(--karni-color-background);border-radius:var(--karni-radius-md);
border:var(--karni-border-width) solid var(--karni-color-input);cursor:pointer}
.copy:hover{border-color:var(--brand-accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:calc(var(--s)*2.5)}
.card{background:var(--karni-color-card);color:var(--karni-color-card-foreground);
border:var(--karni-border-width) solid var(--karni-color-border);
border-radius:var(--karni-radius-lg);padding:calc(var(--s)*3) calc(var(--s)*3.5);
box-shadow:var(--karni-shadow-sm)}
.card a{display:block}
.card span{color:var(--karni-color-muted-foreground);font-size:var(--karni-font-size-sm)}
ul{padding-left:calc(var(--s)*5);margin:0 0 calc(var(--s)*3)}li{margin:var(--s) 0}
footer{margin-top:calc(var(--s)*10);padding-top:calc(var(--s)*4);font-size:var(--karni-font-size-sm);
color:var(--karni-color-muted-foreground);border-top:var(--karni-border-width) solid
var(--karni-color-border)}
.fix{white-space:nowrap}
@media (max-width:600px){header svg{width:44px;height:44px}h1{font-size:1.375rem}
.fix{white-space:normal}}
"""
"""The page's own rules. Every value is a @karni/ui token from the inlined
``karni/tokens.css``, except the brand accent: the orange of the mark's rings
(``assets/brand/README.md``), used once, as the copy button's hover highlight."""

THEME_SCRIPT = """
(function(){var d=document.documentElement,m=window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)');
function c(){try{return localStorage.getItem('karni-theme')}catch(e){return null}}
function s(){var t=c();d.classList.toggle('dark',t==='dark'||
((t===null||t==='system')&&!!(m&&m.matches)))}
s();if(m&&m.addEventListener){m.addEventListener('change',s)}})();
"""
"""Dark mode the way @karni/ui and the admin do it, the ``dark`` class on
``<html>``, with @karni/ui's rule (``KARNI_THEME_SCRIPT``): a choice its
``ThemeProvider`` stored under ``karni-theme`` on this origin, else the
system preference, followed live. It runs in ``<head>`` so the first paint
already has the right theme."""

SCRIPT = """
document.addEventListener('click',function(e){var b=e.target.closest('.copy');if(!b)return;
var t=document.getElementById(b.getAttribute('data-copy'));if(!t)return;var s=t.innerText;
function done(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1200)}
if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(s).then(done)}
else{var r=document.createRange();r.selectNodeContents(t);var sel=window.getSelection();
sel.removeAllRanges();sel.addRange(r);try{document.execCommand('copy');done()}catch(x){}
sel.removeAllRanges()}});
"""


def _mark_svg() -> str:
    try:
        svg = _MARK.read_text(encoding="utf-8")
    except OSError:
        return ""
    return svg.replace('width="1000" height="1000"', 'aria-hidden="true"', 1)


def _block(block_id: str, text: str) -> str:
    return (
        f'<div class="block"><pre id="{block_id}">{escape(text)}</pre>'
        f'<button class="copy" type="button" data-copy="{block_id}">Copy</button></div>'
    )


def _status_rows(statuses: list[Status]) -> str:
    rows = []
    for status in statuses:
        mark = '<span class="tick">✓</span>' if status.ok else '<span class="cross">✗</span>'
        fix = ""
        if not status.ok and status.fix:
            fix = f'<code class="fix">{escape(status.fix)}</code>'
            if status.hint:
                fix += f' <span class="muted">{escape(status.hint)}</span>'
        rows.append(
            f"<tr><td>{mark}</td><td>{escape(status.name)}</td>"
            f'<td class="muted">{escape(status.detail)}</td><td>{fix}</td></tr>'
        )
    return "".join(rows)


def _models_section(inventory: Inventory) -> str:
    if not inventory.models:
        return (
            "<p>No models yet. That is the normal first state. "
            '<a href="#first-model">Add your first model</a> and this list fills itself.</p>'
        )
    rows = []
    for link in inventory.models:
        admin = f'<a href="{escape(link.admin_url)}">admin</a>' if link.admin_url else "none"
        api = (
            f'<a href="{escape(link.api_url)}">{escape(link.api_url)}</a>'
            if link.api_url
            else "none"
        )
        rows.append(
            f"<tr><td><code>{escape(link.name)}</code></td><td>{admin}</td><td>{api}</td></tr>"
        )
    count = len(inventory.models)
    noun = "model" if count == 1 else "models"
    return (
        f"<p>{count} {noun}.</p><table><tr><th>Model</th><th>Admin</th><th>API</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _modules_section(inventory: Inventory) -> str:
    if not inventory.modules:
        return (
            '<p class="muted">No modules installed. <code>karni add payments</code> installs one '
            "with a single command and one URL include.</p>"
        )
    items = "".join(
        f"<li><code>{escape(module.name)}</code> · "
        f'<a href="{escape(module.docs_url)}">docs</a></li>'
        for module in inventory.modules
    )
    return f"<ul>{items}</ul>"


def _links_section(inventory: Inventory) -> str:
    links = inventory.links
    cards = [
        (links["admin"], "Admin", "every model, derived"),
        (links["api_docs"], "API browser", "Swagger UI over the live schema"),
        (links["schema"], "/api/schema/", "OpenAPI document"),
        (links["ready"], "/health/ready/", "database, cache, worker"),
    ]
    if links["frontend"]:
        cards.append((links["frontend"], "Frontend dev server", "Vite, proxied to this API"))
    cards.append((links["docs"], "Docs site", "guides and reference"))
    return (
        '<div class="cards">'
        + "".join(
            f'<div class="card"><a href="{escape(href)}">{escape(title)}</a>'
            f"<span>{escape(note)}</span></div>"
            for href, title, note in cards
        )
        + "</div>"
    )


FIRST_MODEL_CODE = """# events/models.py
from django.db import models
from karni.models import BaseModel


class Event(BaseModel):
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()


# events/viewsets.py
from karni.api import BaseViewSet, Granted
from events.models import Event


class EventViewSet(BaseViewSet):
    model = Event
    access = Granted()
"""


def _first_model_section() -> str:
    return (
        "<p>A model and its viewset are the whole backend of an entity. Write them, or let the "
        "CLI write both (and a test): <code>karni make model Event title:str:200 "
        "starts_at:datetime --with viewset,test</code>.</p>"
        + _block("first-model-code", FIRST_MODEL_CODE)
        + "<p>Then the two commands that follow every model change:</p>"
        + _block("first-model-commands", "make migrate && karni types")
        + "<p>What you get for free: an admin page at <code>/admin/events/event/</code>, "
        "<code>/api/events/</code> with list, detail, filtering, ordering, search and pagination "
        "under the roles' grants, its OpenAPI entry, a typed client, and a working table: "
        '<code>&lt;ResourceTable resource="events" /&gt;</code>.</p>'
    )


def _agent_section(inventory: Inventory) -> str:
    prompt = (
        f"You are working in the Karni project `{inventory.project}`. Run `karni context` and "
        "`karni rules` first and follow them. Then add an Event model (title, starts_at) with "
        "its viewset and test using `karni make`, run `make migrate && karni types`, and run "
        "`karni check`. Never write serializers, routers, admin classes or permission checks "
        "by hand: Karni derives them."
    )
    present = [adapter for adapter in inventory.adapters if adapter.present]
    missing = [adapter for adapter in inventory.adapters if not adapter.present]
    adapters_html = ""
    if present:
        adapters_html += (
            "<ul>"
            + "".join(
                f"<li><code>{escape(adapter.path)}</code> · {escape(adapter.tool)}</li>"
                for adapter in present
            )
            + "</ul>"
        )
    if missing and not present:
        adapters_html += (
            '<p class="muted">No adapter files found next to this project. '
            "<code>karni rules sync</code> writes them.</p>"
        )
    elif missing:
        adapters_html += (
            '<p class="muted">Not written: '
            + ", ".join(escape(adapter.tool) for adapter in missing)
            + " (<code>karni rules sync</code> adds every adapter).</p>"
        )
    return (
        "<p>An agent that reads this project's context and rules writes only the domain code. "
        "The live output of <code>karni context</code> for this project right now:</p>"
        + _block("context", inventory.context)
        + "<p>The first prompt to paste into your agent:</p>"
        + _block("prompt", prompt)
        + "<p>Adapter files generated for this project, and the tools they cover:</p>"
        + adapters_html
        + "<p>The rules an agent works to, and the check it runs on each file it touches:</p>"
        + _block("rules", "karni rules\nkarni rules --check events/viewsets.py")
    )


def render_page(inventory: Inventory, statuses: list[Status]) -> str:
    versions = inventory.versions
    version_line = (
        f"Karni {versions['karni']} · Django {versions['django']} · Python {versions['python']}"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>Karni is running · {escape(inventory.project)}</title>"
        f"<style>{tokens_css()}</style><style>{CSS}</style>"
        f"<script>{THEME_SCRIPT}</script></head><body><main>"
        f"<header>{_mark_svg()}<div><h1>Karni is running</h1>"
        f'<p class="version">{escape(version_line)}</p></div></header>'
        f'<p class="muted">Project <code>{escape(inventory.project)}</code>, '
        "as it is right now.</p>"
        "<h2>Status</h2><table>" + _status_rows(statuses) + "</table>"
        '<p class="muted">A cross always comes with the command that turns it into a tick.</p>'
        "<h2>Where to go next</h2>"
        + _links_section(inventory)
        + "<h2>Models</h2>"
        + _models_section(inventory)
        + "<h2>Modules</h2>"
        + _modules_section(inventory)
        + '<h2 id="first-model">Add your first model</h2>'
        + _first_model_section()
        + "<h2>Build it with your agent</h2>"
        + _agent_section(inventory)
        + "<footer>This page is served only while <code>DEBUG</code> is on and no route of yours "
        "answers <code>/</code>. Define one and it is gone.</footer>"
        f"</main><script>{SCRIPT}</script></body></html>"
    )
