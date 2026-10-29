"""``karni make form``: a public form end to end, for any project.

First what the generator writes, refuses and suggests (no Django needed).
Then three forms in one scaffolded project, run for real through the project
interpreter: a contact form that emails a recipients setting, a newsletter
sign-up with one field and no email, and a booking request with a date and a
choice that replaces an imported design's own <form>. For each, the project's
generated tests pass, the form works without JavaScript (valid, invalid, a
filled honeypot, rate-limited), and the email goes out through the queue
(Celery eager). Where Node and Playwright are installed, the script submits
the forms in place in headless Chromium under the enforced
Content-Security-Policy, and a browser without JavaScript sends one too.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli.design.forms import best_match, forms_in, suggest_tag
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE, require_modules
from .test_make import fails, ok
from .test_make_gate import OVERLAY, _karni_importable

DESIGNS = Path(__file__).parent / "fixtures" / "designs"
CONTACT = ["contact", "name:str:120", "email:email", "subject:str:200", "message:text"]
NEWSLETTER = ["newsletter", "email:email"]
BOOKING = [
    "booking_request",
    "name:str:80",
    "email:email",
    "day:date",
    "service:choice:cut|colour|styling",
    "phone:phone?",
]
BOOKING_STATES = "requested>confirmed|requested>declined|confirmed>cancelled"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Form Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "form_check"
    monkeypatch.chdir(root)
    ok("make", "app", "website")
    return root


# what it writes


def test_a_contact_form_with_a_notification(project: Path) -> None:
    result = ok("make", "form", *CONTACT, "--notify", "ENQUIRY_RECIPIENTS")
    out = result.output
    models = (project / "website" / "models.py").read_text()
    assert "class Contact(BaseModel):" in models
    assert "    email = EmailField()\n" in models and "    message = models.TextField()\n" in models
    assert 'states=["new", "replied", "archived"]' in models
    assert 'transitions={"new": ["replied", "archived"], "replied": ["archived"]}' in models
    assert "notes = models.TextField(" in models and 'help_text="Staff only' in models
    assert '            "status": ("staff",),\n            "notes": ("staff",),\n' in models
    assert "        audit = True" in models and "        dashboard = True" in models
    assert 'search = SearchField(sources=["name", "email", "subject"])' in models
    assert 'list_filter = ("status",)' in models and 'ordering = ("-created_at",)' in models
    viewsets = (project / "website" / "viewsets.py").read_text()
    assert 'access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())' in (
        viewsets
    )
    assert "throttle" not in viewsets.lower()  # Karni limits a public create by itself
    listeners = (project / "website" / "listeners.py").read_text()
    assert "@on_created(Contact, queued=True)\ndef notify_contact(contact: Contact) -> None:" in (
        listeners
    )
    assert 'setting="ENQUIRY_RECIPIENTS"' in listeners and "reply_to=contact.email" in listeners
    email = project / "website" / "templates" / "website" / "email"
    assert "New contact: {{ submission.subject }}" in (email / "contact_subject.txt").read_text()
    body = (email / "contact_body.txt").read_text()
    assert "{% autoescape off %}" in body and "Message:\n{{ submission.message }}" in body
    assert "Staff app: {{ frontend_url }}/contacts/{{ submission.pk }}" in body
    settings = (project / "config" / "settings.py").read_text()
    assert 'ENQUIRY_RECIPIENTS = env.list("ENQUIRY_RECIPIENTS", default=[])  # noqa: F821' in (
        settings
    )
    assert '"karni_site",' in settings
    assert "# ENQUIRY_RECIPIENTS=team@example.com" in (project / ".env.example").read_text()
    assert "karni-site" in (project / "pyproject.toml").read_text()
    urls = (project / "config" / "urls.py").read_text()
    assert '    path("", include("karni_site.urls")),\n    # karni:urls' in urls
    tests = (project / "website" / "tests" / "test_contact_form.py").read_text()
    for name in (
        "test_anyone_may_send_it",
        "test_it_works_without_javascript",
        "test_the_recipients_are_emailed",
        "test_visitors_cannot_set_the_staff_fields",
        "test_sending_is_rate_limited",
        "test_only_the_role_reads_it",
        "test_the_role_works_the_inbox_through_the_api",
    ):
        assert f"def {name}(" in tests
    for page in ("contacts.tsx", "contact-detail.tsx", "contact-form.tsx"):
        assert (project / "frontend" / "src" / "pages" / page).is_file()
    assert 'tag: {% load karni_site %} then {% karni_form "contact" %}' in out
    assert "abuse: Karni limits each caller's creates" in out
    assert (project / ".karni" / "modules" / "site.md").is_file() or "karni-site" in out


def test_a_form_without_notify_sends_nothing(project: Path) -> None:
    out = ok("make", "form", *NEWSLETTER).output
    assert "notify: none" in out
    assert not (project / "website" / "listeners.py").exists()
    assert not (project / "website" / "templates" / "website" / "email").exists()
    assert "RECIPIENTS" not in (project / "config" / "settings.py").read_text()
    tests = (project / "website" / "tests" / "test_newsletter_form.py").read_text()
    assert "def test_nobody_is_emailed(" in tests and "assert mail.outbox == []" in tests
    models = (project / "website" / "models.py").read_text()
    assert "    email = EmailField()\n    status = StateField(" in models


def test_the_command_chooses_the_lifecycle_and_the_role(project: Path) -> None:
    ok("make", "form", *BOOKING, "--states", BOOKING_STATES, "--role", "front-desk")
    models = (project / "website" / "models.py").read_text()
    assert 'states=["requested", "confirmed", "declined", "cancelled"]' in models
    assert '"status": ("front-desk",)' in models
    assert "service = models.CharField(" in models and "phone = PhoneField(blank=True)" in models
    viewsets = (project / "website" / "viewsets.py").read_text()
    assert 'read=HasRole("front-desk"), write=HasRole("front-desk"), create=Public()' in viewsets
    tests = (project / "website" / "tests" / "test_booking_request_form.py").read_text()
    assert '"day": "2030-01-15",' in tests and '"service": "cut",' in tests
    assert '"phone"' not in tests  # optional: the sample sends only what is required
    assert 'client_as("front-desk")' in tests and 'status == "requested"' in tests


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (["contact"], "needs the fields a visitor fills"),
        (["contact", "status:str"], "karni make form adds status"),
        (["contact", "notes:text"], "karni make form adds status"),
        (["contact", "price:money:EUR"], "a public form takes what a visitor types"),
        (["contact", "owner:fk:User"], "a visitor cannot pick a user"),
        (["contact", "email:email", "--notify", "recipients"], "name a Django setting"),
        (["contact", "email:email", "--states", "new>new"], "moves a state to itself"),
        (["Contact Us!", "email:email"], "must be a word in snake_case"),
    ],
)
def test_wrong_input_names_the_fix(project: Path, args: list[str], match: str) -> None:
    fails("make", "form", *args, match=match)


def test_dry_run_writes_nothing(project: Path) -> None:
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    out = ok("make", "form", *CONTACT, "--notify", "ENQUIRY_RECIPIENTS", "--dry-run").output
    assert "would create website/tests/test_contact_form.py" in out
    assert "(dry run: nothing written)" in out
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == before


def test_a_site_made_afterwards_shares_the_root(project: Path) -> None:
    ok("make", "form", *NEWSLETTER)
    ok("make", "site", "website")
    urls = (project / "config" / "urls.py").read_text()
    karni_site = urls.index('path("", include("karni_site.urls")),')
    assert karni_site < urls.index('path("", include("website.urls")),')


# the imported design's <form>


def test_an_imported_design_records_its_forms_and_the_tag_that_keeps_them(
    project: Path,
) -> None:
    out = ok("import", "design", str(DESIGNS / "academy"), "--app", "website").output
    assert 'form: admissions.html:19 posts to "https://forms.example.org/hillside"' in out
    record = json.loads((project / ".karni" / "design.json").read_text())
    admissions = next(p for p in record["pages"] if p["source"] == "admissions.html")
    enquiry = admissions["forms"][0]
    assert [f["name"] for f in enquiry["fields"]] == [
        "parent_name",
        "email",
        "year_group",
        "message",
        "visit",
    ]
    assert enquiry["markup"]["input"] == "form-control" and enquiry["rows"] == [
        ["parent_name", "email"]
    ]
    out = ok(
        "make",
        "form",
        "admission",
        "parent_name:str:120",
        "email:email",
        "year_group:choice:reception|year-1",
        "message:text?",
        "visit:bool",
    ).output
    assert "design: website/templates/website/admissions.html:" in out
    assert "(the fields of admission)" in out
    tag = out.split("replace: in website/templates/website/admissions.html", 1)[1]
    assert (
        '{% karni_form "admission" classes="bootstrap" rows="parent_name,email" '
        'labels="parent_name: Your name | visit: We would like to visit" '
        'placeholders="email: you@example.com" button="Send enquiry" id="enquiry" %}'
    ) in tag
    # The footer's sign-up form is in the layout: a newsletter replaces that one.
    out = ok("make", "form", *NEWSLETTER).output
    assert "replace: in website/templates/website/" in out
    assert 'form_class="row g-2" field_class="col-auto" label_class="visually-hidden"' in out


def test_design_forms_are_read_from_plain_markup_too() -> None:
    forms = forms_in((DESIGNS / "salon" / "index.html").read_text())
    match = best_match(forms, ["name", "email", "day", "service"])
    assert match is not None and match.line == 14 and match.button == "Book now"
    tag = suggest_tag("booking", match, ["name", "email", "day", "service"])
    assert tag == (
        '{% karni_form "booking" form_class="booking-form" message_class="form-note" '
        'row_class="form-row" '
        'field_class="field" required_class="req" button_class="btn btn-accent" '
        'rows="name,email" labels="day: Preferred day" placeholders="name: Jane Doe" '
        'button="Book now" %}'
    )
    # A form that shares less than half its fields is not this form.
    assert best_match(forms, ["email"]) is None


# for real: three forms in one project


@dataclass
class Built:
    root: Path
    python: Path
    env: dict[str, str]
    outputs: dict[str, str]


def _free_port() -> int:
    reserved = {8000, 8765, 5173, 8431, 5432, 6379}
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in reserved:
            return port


def _tag_from(output: str) -> str:
    match = re.search(
        r"replace: in (\S+), replace that <form> .*?\n\s+(\{% karni_form .*? %\})", output
    )
    assert match, output
    return match.group(2)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Built]:
    """One project, three forms, the design's booking form replaced by its tag."""
    if not _karni_importable():
        pytest.skip("needs karni + Django in this interpreter")
    require_modules("karni-site")
    tmp = tmp_path_factory.mktemp("forms")
    env = {
        "KARNI_TEMPLATES": str(TEMPLATE),
        "DJANGO_SETTINGS_MODULE": "config.test_overlay",
        "DATABASE_URL": f"sqlite:///{tmp / 'db.sqlite3'}",
        "MEDIA_ROOT": str(tmp / "media"),
        "STATIC_ROOT": str(tmp / "static"),
        "DEBUG": "True",
    }
    outputs: dict[str, str] = {}
    with pytest.MonkeyPatch.context() as patch:
        for name, value in env.items():
            patch.setenv(name, value)
        patch.delenv("VIRTUAL_ENV", raising=False)
        result = CliRunner().invoke(app, ["new", "Form Lab", "-o", str(tmp)])
        assert result.exit_code == 0, result.output
        root = tmp / "form_lab"
        patch.chdir(root)
        python = root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        python.chmod(0o755)
        (root / "config" / "test_overlay.py").write_text(OVERLAY)
        ok("import", "design", str(DESIGNS / "salon"), "--app", "website")
        ok("make", "view", "contact", "--app", "website")
        outputs["contact"] = ok(
            "make", "form", *CONTACT, "--notify", "ENQUIRY_RECIPIENTS", "--app", "website"
        ).output
        outputs["newsletter"] = ok("make", "form", *NEWSLETTER, "--app", "website").output
        outputs["booking"] = ok(
            "make", "form", *BOOKING, "--states", BOOKING_STATES,
            "--notify", "BOOKING_RECIPIENTS", "--app", "website",
        ).output  # fmt: skip
        # The design's own <form> on the home page becomes the tag the command printed.
        templates = root / "website" / "templates" / "website"
        home = templates / "home.html"
        tag = _tag_from(outputs["booking"])
        html = home.read_text()
        html, count = re.subn(r"<form class=\"booking-form\".*?</form>", tag, html, flags=re.DOTALL)
        assert count == 1, html
        home.write_text(html)
        contact = templates / "contact.html"
        page = contact.read_text().replace(
            "{% block content %}\n",
            "{% block content %}{% load karni_site %}\n"
            '  {% karni_form "contact" rows="name,email" %}\n'
            '  {% karni_form "newsletter" button="Subscribe" success="You are on the list." %}\n',
        )
        contact.write_text(page)
        ok("make", "migration", "--app", "website")
        ok("migrate")
    full_env = {**os.environ, **env, "PYTHONPATH": str(root)}
    full_env.pop("VIRTUAL_ENV", None)
    yield Built(root, python, full_env, outputs)


def test_the_generated_tests_pass(built: Built) -> None:
    tests = subprocess.run(
        [str(built.python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "website/tests"],
        cwd=built.root,
        env=built.env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-3000:]
    # Seven per form, three forms, and the site's page test.
    assert "22 passed" in tests.stdout, tests.stdout[-2000:]
    check = subprocess.run(
        [str(built.python), "manage.py", "check"],
        cwd=built.root,
        env=built.env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "W967" not in check.stdout + check.stderr  # the inbox search is indexed


VERIFY = """
import re

import django

django.setup()

from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.test.utils import setup_test_environment

from website.models import BookingRequest, Contact, Newsletter

setup_test_environment()  # mail.outbox, as in a test
FORMS = {
    "contact": {
        "page": "/contact/",
        "h1": "<h1>Contact</h1>",
        "model": Contact,
        "valid": {"name": "Ada Lovelace", "email": "ada@example.com",
                  "subject": "Opening hours", "message": "Are you open on Sundays?"},
        "to": ["team@example.com"],
        "subject": "New contact: Opening hours",
    },
    "newsletter": {
        "page": "/contact/",
        "h1": "<h1>Contact</h1>",
        "model": Newsletter,
        "valid": {"email": "reader@example.com"},
        "to": None,
        "thanks": "You are on the list.",  # the tag's own success="..."
    },
    "booking_request": {
        "page": "/",
        "h1": "<h1>Book a visit</h1>",
        "model": BookingRequest,
        "valid": {"name": "Grace", "email": "grace@example.com", "day": "2030-02-01",
                  "service": "colour"},
        "to": ["desk@example.com", "owner@example.com"],
        "subject": "New booking request from Grace",
    },
}
with override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["*"],
    ENQUIRY_RECIPIENTS=["team@example.com"],
    BOOKING_RECIPIENTS="desk@example.com, owner@example.com",
    KARNI_PUBLIC_CREATE_RATE="3/hour",
):
    client = Client()
    for name, form in FORMS.items():
        cache.clear()  # each form starts with an empty rate-limit history
        mail.outbox.clear()
        model, page, anchor = form["model"], form["page"], f"#karni-form-{name}"
        shown = client.get(page)
        html = shown.content.decode()
        assert shown.status_code == 200 and f'data-karni-form="{name}"' in html, name
        policy = shown.headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
        assert html.count('<script src="/static/karni_site/forms.js" defer></script>') == 1
        post = {**form["valid"], "karni-next": page + anchor}

        # sent: back to the page, which says so, and the email went through the queue
        sent = client.post(f"/forms/{name}/", post)
        assert (sent.status_code, sent["Location"]) == (
            303, f"{page}?sent={name}{anchor}"
        ), (name, sent.status_code, sent.get("Location"))
        thanks = client.get(f"{page}?sent={name}").content.decode()
        block = thanks.split(f'data-karni-form="{name}"', 1)[1].split("</form>", 1)[0]
        status = re.search(r'<p class="([^"]*)" role="status"[^>]*>(.*?)</p>', block, re.S)
        expected = form.get("thanks", "Thank you. Your submission was received.")
        assert status and status.group(2) == expected, (name, block)
        assert "is-success" in status.group(1) and " hidden>" not in status.group(0), name
        assert model.objects.count() == 1, name
        if form["to"]:
            assert [m.to for m in mail.outbox] == [form["to"]], (name, mail.outbox)
            assert mail.outbox[0].subject == form["subject"], mail.outbox[0].subject
            assert mail.outbox[0].reply_to == [form["valid"]["email"]]
        else:
            assert mail.outbox == [], name

        # invalid: the page itself again, the error next to the field, the values kept
        bad = client.post(f"/forms/{name}/", {**post, "email": "a@b"})
        body = bad.content.decode()
        assert bad.status_code == 400, (name, bad.status_code)
        assert form["h1"] in body and "Enter a valid email address." in body, name
        assert 'value="a@b"' in body and 'aria-invalid="true"' in body, name
        assert model.objects.count() == 1, name

        # a filled honeypot looks sent and saves nothing
        trap = client.post(f"/forms/{name}/", {**post, "homepage": "https://spam.example"})
        assert trap.status_code == 303 and model.objects.count() == 1, name

        # the fourth request this hour: the page says so, with Retry-After
        limited = client.post(f"/forms/{name}/", post)
        assert limited.status_code == 429 and limited["Retry-After"], (name, limited.status_code)
        assert "sent several times in a short while" in limited.content.decode(), name
        assert model.objects.count() == 1, name

    # the design's own form, now the tag: its markup kept
    home = client.get("/").content.decode()
    for markup in ('class="booking-form"', 'class="form-row"', 'class="field"',
                   '<p class="form-note" role="status"',
                   'class="btn btn-accent"', ">Preferred day <", 'placeholder="Jane Doe"',
                   '<span class="req" aria-hidden="true">*</span>'):
        assert markup in home, (markup, home)
    row = BookingRequest.objects.get()
    assert (row.status, row.service, str(row.day)) == ("requested", "colour", "2030-02-01")
print("forms OK")
"""


def test_the_forms_work_without_javascript(built: Built) -> None:
    verify = subprocess.run(
        [str(built.python), "-c", textwrap.dedent(VERIFY)],
        cwd=built.root,
        env=built.env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stdout[-3000:] + verify.stderr[-3000:]
    assert "forms OK" in verify.stdout


# for real, in a browser

BROWSER = r"""
const { chromium } = require(process.argv[2]);
const base = process.argv[3];

// Each form: its page, how to fill it validly, and the email field the server refuses.
const FORMS = [
  {
    name: "contact",
    page: "/contact/",
    fill: async (page, n) => {
      await page.fill("#karni-form-contact-name", "Ada");
      await page.fill("#karni-form-contact-email", `ada${n}@example.com`);
      await page.fill("#karni-form-contact-subject", "Hours");
      await page.fill("#karni-form-contact-message", "Open on Sundays?");
    },
  },
  {
    name: "newsletter",
    page: "/contact/",
    fill: async (page, n) => page.fill("#karni-form-newsletter-email", `reader${n}@example.com`),
  },
  {
    name: "booking_request",
    page: "/",
    fill: async (page, n) => {
      await page.fill("#karni-form-booking_request-name", "Grace");
      await page.fill("#karni-form-booking_request-email", `grace${n}@example.com`);
      await page.fill("#karni-form-booking_request-day", "2030-02-01");
      await page.selectOption("#karni-form-booking_request-service", "colour");
    },
  },
];

async function send(page, name) {
  const form = `form[data-karni-form="${name}"]`;
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith(`/forms/${name}/`)),
    page.click(`${form} [type="submit"]`),
  ]);
  await page.waitForFunction((s) => !document.querySelector(s).disabled, `${form} [type="submit"]`);
  const status = page.locator(`${form} [data-karni-form-message]`);
  return { text: ((await status.textContent()) || "").trim(), cls: await status.getAttribute("class") };
}

(async () => {
  const browser = await chromium.launch();
  const out = { problems: [], forms: {} };

  // No JavaScript at all: the browser posts, the page comes back saying so.
  const plain = await browser.newContext({ javaScriptEnabled: false });
  const noScript = await plain.newPage();
  await noScript.goto(base + "/contact/");
  await FORMS[0].fill(noScript, 0);
  await Promise.all([
    noScript.waitForNavigation(),
    noScript.click('form[data-karni-form="contact"] [type="submit"]'),
  ]);
  out.noScriptUrl = noScript.url();
  out.noScript = (await noScript.textContent('form[data-karni-form="contact"] [data-karni-form-message]')).trim();

  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && /Content Security Policy/i.test(m.text())) out.problems.push(m.text());
  });
  page.on("pageerror", (e) => out.problems.push(String(e)));
  for (const form of FORMS) {
    const response = await page.goto(base + form.page);
    const result = { policy: response.headers()["content-security-policy"] || "" };
    const selector = `form[data-karni-form="${form.name}"]`;
    await page.waitForSelector(`${selector}[data-karni-enhanced]`);
    const start = page.url();
    const email = `#karni-form-${form.name}-email`;

    // Passes the browser's own checks, fails the server's: an inline error, in place.
    await form.fill(page, 1);
    await page.fill(email, "a@b");
    result.invalid = await send(page, form.name);
    result.error = (await page.textContent(`${email}-error`)).trim();
    result.ariaInvalid = await page.getAttribute(email, "aria-invalid");

    // Valid: the success message where the form is, the error gone, the form emptied.
    await form.fill(page, 2);
    result.success = await send(page, form.name);
    result.errorGone = (await page.locator(`${email}-error`).count()) === 0;
    result.emptied = (await page.inputValue(email)) === "";
    result.sameUrl = page.url() === start;

    // Until the rate limit answers (3 an hour here).
    await form.fill(page, 3);
    await send(page, form.name);
    await form.fill(page, 4);
    result.limited = await send(page, form.name);
    out.forms[form.name] = result;
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


THANKS = "Thank you. Your submission was received."


def _playwright() -> tuple[str, str] | None:
    """``(node, playwright module)`` when node, Playwright and its Chromium are installed.

    Playwright comes from the node_modules folder ``KARNI_TEST_PLAYWRIGHT``
    names (CI installs it there), else packages/karni-ui's (``npm ci``
    there), and its browser from ``npx playwright install chromium``.
    """
    node = shutil.which("node")
    if node is None:
        return None
    folders = [REPO_ROOT / "packages" / "karni-ui" / "node_modules"]
    if os.environ.get("KARNI_TEST_PLAYWRIGHT"):
        folders.insert(0, Path(os.environ["KARNI_TEST_PLAYWRIGHT"]))
    for folder in folders:
        module = folder / "playwright"
        if not (module / "package.json").is_file():
            continue
        probe = subprocess.run(
            [
                node,
                "-e",
                (
                    "const p = require(process.argv[1]);"
                    "process.exit(require('fs').existsSync(p.chromium.executablePath()) ? 0 : 1)"
                ),
                str(module),
            ],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return node, str(module)
    return None


def test_the_script_submits_in_place_under_the_enforced_policy(
    built: Built, tmp_path: Path
) -> None:
    found = _playwright()
    if found is None:
        pytest.skip(
            "needs node, Playwright and its Chromium (npm ci in packages/karni-ui, then "
            "npx playwright install chromium)"
        )
    node, playwright = found
    port = _free_port()
    env = {
        **built.env,
        "KARNI_CSP_REPORT_ONLY": "False",  # enforced, as in production
        "KARNI_PUBLIC_CREATE_RATE": "3/hour",
        "ENQUIRY_RECIPIENTS": "team@example.com",
        "BOOKING_RECIPIENTS": "desk@example.com",
    }
    server = subprocess.Popen(
        [str(built.python), "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=built.root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"{base}/health/", timeout=2) as reply:
                    if reply.status == 200:
                        break
            except OSError:
                if time.monotonic() > deadline or server.poll() is not None:
                    raise AssertionError("the dev server did not start") from None
                time.sleep(0.3)
        script = tmp_path / "browser.js"
        script.write_text(BROWSER)
        run = subprocess.run(
            [node, str(script), playwright, base],
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
        result = json.loads(run.stdout.strip().splitlines()[-1])
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    assert result["problems"] == [], result["problems"]
    assert result["noScriptUrl"].endswith("/contact/?sent=contact#karni-form-contact")
    assert result["noScript"] == "Thank you. Your submission was received."
    assert set(result["forms"]) == {"contact", "newsletter", "booking_request"}
    for name, form in result["forms"].items():
        script_src = next(d for d in form["policy"].split("; ") if d.startswith("script-src"))
        assert "'self'" in script_src and "'unsafe-inline'" not in script_src, name
        assert form["invalid"]["text"] == "Please correct the fields marked below.", name
        assert "is-error" in form["invalid"]["cls"], name
        assert form["error"] == "Enter a valid email address.", name
        assert form["ariaInvalid"] == "true", name
        thanks = "You are on the list." if name == "newsletter" else THANKS
        assert form["success"]["text"] == thanks, name
        assert "is-success" in form["success"]["cls"], name
        assert form["errorGone"] and form["emptied"] and form["sameUrl"], (name, form)
        assert form["limited"]["text"].startswith("This form was sent several times"), name
