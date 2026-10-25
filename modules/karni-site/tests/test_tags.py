"""{% ifactive %}, {% csp_hash %} and {% csp_allow %} on real requests."""

from __future__ import annotations

import pytest
from django.http import HttpResponseBase
from django.template import Context, Template, TemplateSyntaxError
from django.test import Client, RequestFactory
from karni.security import script_hash
from pytest_django import Settings

from karni_site.templatetags.karni_site import inline_source

pytestmark = pytest.mark.django_db

HEADER = "Content-Security-Policy"  # pytest-django runs with DEBUG off: enforced


def _script_src(response: HttpResponseBase) -> list[str]:
    for part in response.headers[HEADER].split(";"):
        name, *sources = part.split()
        if name == "script-src":
            return sources
    return []


def test_the_current_page_is_marked_with_the_designs_own_markup(client: Client) -> None:
    home = client.get("/").content.decode()
    assert '<a href="/" class="active">Home</a>' in home
    assert '<a class="link" href="/about/">About</a>' in home
    assert '<a href="/services/web/" data-idle>Web</a>' in home
    about = client.get("/about/").content.decode()
    assert '<a href="/">Home</a>' in about
    assert '<a class="link current" href="/about/">About</a>' in about
    web = client.get("/services/web/").content.decode()
    assert '<a href="/services/web/" aria-current="page">Web</a>' in web


def test_patterns_are_url_names_or_paths_with_wildcards() -> None:
    factory = RequestFactory()
    request = factory.get("/services/web/")
    from django.urls import resolve

    request.resolver_match = resolve("/services/web/")
    for source, expected in (
        (
            '{% ifactive "website:service_web" %}yes{% endifactive %}',
            "yes",
        ),
        ('{% ifactive "website:service_*" %}yes{% endifactive %}', "yes"),
        (
            '{% ifactive "website:about" "/services/*" %}yes{% endifactive %}',
            "yes",
        ),
        ("{% ifactive names %}yes{% else %}no{% endifactive %}", "yes"),
        (
            '{% ifactive "website:about" %}yes{% else %}no{% endifactive %}',
            "no",
        ),
    ):
        template = Template("{% load karni_site %}" + source)
        context = Context({"request": request, "names": ["website:home", "website:service_web"]})
        assert template.render(context) == expected, source
    # No request (an e-mail, a plain render): nothing is current.
    plain = Template('{% load karni_site %}{% ifactive "/*" %}yes{% else %}no{% endifactive %}')
    assert plain.render(Context()) == "no"


def test_the_matcher_is_swappable(client: Client, settings: Settings) -> None:
    settings.KARNI_SITE_IS_ACTIVE = lambda request, pattern: pattern == "website:about"
    assert 'class="active"' not in client.get("/").content.decode()
    assert "link current" in client.get("/").content.decode()


def test_inline_scripts_and_handlers_pass_the_policy_by_hash(client: Client) -> None:
    response = client.get("/about/")
    page = response.content.decode()
    # The markup is unchanged.
    assert '<script>document.documentElement.className = "js";</script>' in page
    assert 'onclick="history.back(); return &quot;x&quot;;"' in page
    sources = _script_src(response)
    assert script_hash('document.documentElement.className = "js";') in sources
    assert script_hash('\n  console.log("about");\n') in sources
    # A handler is hashed as the browser reads it: decoded, and only with 'unsafe-hashes'.
    assert "'unsafe-hashes'" in sources
    assert script_hash('history.back(); return "x";') in sources
    # The home page does not carry the about page's script.
    assert script_hash('\n  console.log("about");\n') not in _script_src(client.get("/"))


def test_other_origins_are_allowed_for_that_response(client: Client) -> None:
    policy = client.get("/").headers[HEADER]
    assert "https://fonts.example.com" in policy.split("style-src", 1)[1].split(";")[0]
    assert "https://fonts.example.net" in policy.split("font-src", 1)[1].split(";")[0]
    assert "fonts.example" not in client.get("/api/").headers.get(HEADER, "")


def test_line_endings_are_hashed_as_the_browser_reads_them() -> None:
    assert inline_source("a\r\nb\rc") == "a\nb\nc"
    assert inline_source("say(&quot;hi&quot;)", attribute=True) == 'say("hi")'


@pytest.mark.parametrize(
    "source",
    [
        "{% ifactive %}x{% endifactive %}",
        "{% csp_hash script %}x{% endcsp_hash %}",
        "{% csp_allow %}",
        '{% csp_allow "fonts.example.com" %}',
        '{% csp_allow "Font-Src x" %}',
    ],
)
def test_wrong_tags_name_the_code(source: str) -> None:
    with pytest.raises(TemplateSyntaxError, match="SITE003"):
        Template("{% load karni_site %}" + source)
