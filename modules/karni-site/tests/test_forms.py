"""{% karni_form %}: what it renders, and its view without and with JavaScript.

The forms come from tests/formapp: an appointment request (a clinic), a newsletter
sign-up (a school), a job application with a file (a joinery workshop) and a members-only feedback
form. The pages are tests/formapp/templates/website/book.html and apply.html.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, RequestContext, Template, TemplateSyntaxError
from django.test import Client, RequestFactory
from pytest_django import Settings

from karni_site import forms
from karni_site.forms import SiteForm, UnknownForm, resolve_form
from tests.formapp.models import Application, AppointmentRequest, Subscriber

pytestmark = pytest.mark.django_db

FORM = "/forms/appointment_request/"
VALID = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": "+14155550123",
    "reason": "checkup",
    "day": "2030-01-15",
    "message": "First time here.",
    "karni-next": "/book/#karni-form-appointment_request",
}
JSON = {"HTTP_ACCEPT": "application/json"}


def page(client: Client, path: str = "/book/") -> str:
    response = client.get(path)
    assert response.status_code == 200, response.content
    return response.content.decode()


def field_block(html: str, form: str, name: str) -> str:
    match = re.search(
        rf'<div[^>]*data-karni-field="{name}" data-karni-field-id="karni-form-{form}-{name}">'
        r"(.*?)\n</div>",
        html,
        re.S,
    )
    assert match, f"no field {name} in {form}:\n{html}"
    return match.group(1)


# rendering


def test_the_tag_renders_the_fields_a_visitor_fills(client: Client) -> None:
    html = page(client)
    form = html.split('<form id="karni-form-appointment_request"', 1)[1].split("</form>", 1)[0]
    # CSRF, the page to come back to, the honeypot, no staff-only field.
    assert 'name="csrfmiddlewaretoken"' in form
    assert 'name="karni-next" value="/book/#karni-form-appointment_request"' in form
    assert 'name="homepage" tabindex="-1" autocomplete="off"' in form
    assert 'name="status"' not in form and 'name="notes"' not in form
    # Labels, required marks, limits and autofill from the model and the serializer.
    name = field_block(form, "appointment_request", "name")
    assert '>Your name <span class="karni-required" aria-hidden="true">*</span></label>' in name
    assert 'maxlength="80"' in name and 'autocomplete="name"' in name and " required" in name
    email = field_block(form, "appointment_request", "email")
    assert 'type="email"' in email and 'placeholder="you@example.com"' in email
    phone = field_block(form, "appointment_request", "phone")
    assert 'type="tel"' in phone and "required" not in phone and "karni-required" not in phone
    reason = field_block(form, "appointment_request", "reason")
    assert '<option value="">Choose one</option><option value="checkup">Check-up</option>' in reason
    assert 'type="date"' in field_block(form, "appointment_request", "day")
    message = field_block(form, "appointment_request", "message")
    assert "<textarea" in message and "Anything the doctor should know." in message
    assert 'aria-describedby="karni-form-appointment_request-message-help"' in message
    visit = field_block(form, "appointment_request", "first_visit")
    assert 'type="checkbox" value="true"' in visit
    # rows="name,email" puts both in one row element, in the form's order.
    assert form.index('<div class="karni-form-row">') < form.index('data-karni-field="name"')


def test_one_script_per_page_from_the_site_itself(client: Client) -> None:
    response = client.get("/book/")
    html = response.content.decode()
    assert html.count('<script src="/static/karni_site/forms.js" defer></script>') == 1
    policy = response.headers["Content-Security-Policy"]  # enforced: DEBUG is off in tests
    script_src = next(d for d in policy.split("; ") if d.startswith("script-src"))
    assert "'self'" in script_src and "'unsafe-inline'" not in script_src


def test_a_preset_and_the_tags_texts(client: Client) -> None:
    html = page(client)
    form = html.split('<form id="karni-form-subscriber"', 1)[1].split("</form>", 1)[0]
    email = field_block(form, "subscriber", "email")
    assert 'class="form-label"' in email and 'class="form-control"' in email
    assert '<button type="submit" class="btn btn-primary">Subscribe</button>' in form
    assert 'data-karni-success="You are on the list."' in form


def test_a_staff_member_sees_the_publics_form(client: Client) -> None:
    staff = get_user_model().objects.create_user(email="staff@example.com", password="pw-12345678")
    staff.groups.add(Group.objects.get_or_create(name="staff")[0])
    client.force_login(staff)
    html = page(client)
    assert 'name="notes"' not in html and 'name="status"' not in html


def test_settings_and_arguments_set_the_classes(settings: Settings, rf: RequestFactory) -> None:
    settings.KARNI_SITE_FORM_CLASSES = {"field": "field", "input": "input"}
    settings.KARNI_SITE_FORM_PRESETS = {"workshop": {"row": "form-row", "button": "btn"}}
    request = rf.get("/book/")
    html = Template(
        '{% load karni_site %}{% karni_form "subscriber" classes="workshop" input_class="text" %}'
    ).render(RequestContext(request))
    assert 'class="field"' in html and 'class="text"' in html and 'class="btn"' in html
    with pytest.raises(Exception, match="SITE021"):
        Template('{% load karni_site %}{% karni_form "subscriber" classes="nope" %}').render(
            RequestContext(request)
        )


def test_editable_texts_are_blocks_the_client_changes(rf: RequestFactory) -> None:
    from karni_site.models import Block

    source = (
        '{% load karni_site %}{% karni_form "appointment_request" editable="book.appointment" '
        'labels="name: Your name | day: Preferred day" placeholders="email: you@clinic.example" '
        'button="Book now" success="See you soon & thanks." %}'
    )
    html = Template(source).render(RequestContext(rf.get("/book/")))
    # The tag's texts are the defaults, stored as blocks under the prefix.
    assert ">Preferred day <span" in html and 'placeholder="you@clinic.example"' in html
    assert ">Book now</button>" in html
    assert 'data-karni-success="See you soon &amp; thanks."' in html
    keys = set(Block.objects.filter(page="book").values_list("key", flat=True))
    assert {
        "book.appointment.name.label",
        "book.appointment.day.label",
        "book.appointment.email.label",
        "book.appointment.email.placeholder",
        "book.appointment.button",
        "book.appointment.success",
    } <= keys
    # A field without a label in the tag starts from the model's.
    stored = Block.objects.get(key="book.appointment.reason.label")
    assert stored.default_html == "Reason"
    # The client's edits show on the next render, as text.
    for key, text in (("book.appointment.day.label", "Which day suits you?"),
                      ("book.appointment.button", "Request <b>it</b>")):  # fmt: skip
        block = Block.objects.get(key=key)
        block.html = text
        block.save()
    html = Template(source).render(RequestContext(rf.get("/book/")))
    assert ">Which day suits you? <span" in html and ">Request it</button>" in html
    with pytest.raises(Exception, match="SITE021"):
        Template('{% load karni_site %}{% karni_form "subscriber" editable="Book Form" %}').render(
            RequestContext(rf.get("/book/"))
        )


def test_a_choice_as_radios_keeps_the_choice_on_a_second_render(rf: RequestFactory) -> None:
    template = Template(
        '{% load karni_site %}{% karni_form "appointment_request" widgets="reason: radios" %}'
    )
    html = template.render(RequestContext(rf.get("/")))
    reason = field_block(html, "appointment_request", "reason")
    assert "<legend>Reason <span" in reason
    assert reason.count('type="radio"') == 3 and reason.count(" required") == 3
    request = rf.post("/", {"reason": "vaccine"})
    forms.states(request)["appointment_request"] = forms.FormState(
        request.POST, forms.Outcome(400, "invalid", {"reason": ["Pick one."]})
    )
    again = field_block(template.render(RequestContext(request)), "appointment_request", "reason")
    assert 'value="vaccine" checked' in again and 'value="checkup" required' in again
    assert "Pick one." in again


def test_attrs_keep_the_designs_own_attributes_on_a_control(rf: RequestFactory) -> None:
    template = Template(
        '{% load karni_site %}{% karni_form "appointment_request" '
        "attrs=\"message: rows=4 cols='40' | day: min=2030-01-01 | phone: pattern='[0-9 +]+'\" %}"
    )
    html = template.render(RequestContext(rf.get("/")))
    message = field_block(html, "appointment_request", "message")
    assert "<textarea" in message and ' rows="4"' in message and ' cols="40"' in message
    day = field_block(html, "appointment_request", "day")
    assert 'type="date"' in day and ' min="2030-01-01"' in day
    assert ' pattern="[0-9 +]+"' in field_block(html, "appointment_request", "phone")
    # The form's own attributes cannot be replaced, and every field named must be one.
    for spec, found in (
        ("message: name=other", "SITE021.*name cannot be set here"),
        ("message: rows", "SITE021.*'rows' is not attribute=value"),
        ("notes: rows=2", "SITE021.*notes"),
    ):
        bad = Template(
            '{% load karni_site %}{% karni_form "appointment_request" attrs="' + spec + '" %}'
        )
        with pytest.raises(Exception, match=found):
            bad.render(RequestContext(rf.get("/")))


def test_wrong_tags_fail_when_the_template_compiles() -> None:
    for source in (
        "{% karni_form %}",
        '{% karni_form "subscriber" colour="red" %}',
        '{% karni_form "subscriber" button="a" button="b" %}',
    ):
        with pytest.raises(TemplateSyntaxError, match="SITE021"):
            Template("{% load karni_site %}" + source)


def test_a_field_a_visitor_does_not_fill_is_refused(rf: RequestFactory) -> None:
    template = Template(
        '{% load karni_site %}{% karni_form "appointment_request" fields="notes" %}'
    )
    with pytest.raises(Exception, match="SITE021.*notes"):
        template.render(RequestContext(rf.get("/")))


def test_an_unknown_form_names_the_fix(rf: RequestFactory) -> None:
    template = Template('{% load karni_site %}{% karni_form "brochure" %}')
    with pytest.raises(UnknownForm, match="SITE020.*karni make form brochure"):
        template.render(RequestContext(rf.get("/")))


def test_one_field_takes_a_template_of_its_own(settings: Settings, tmp_path: Path, rf: Any) -> None:
    folder = tmp_path / "karni_site" / "forms" / "subscriber"
    folder.mkdir(parents=True)
    (folder / "email.html").write_text(
        '<p class="own">{{ field.label }}<input{{ field.attrs }}></p>'
    )
    settings.TEMPLATES = [
        {**settings.TEMPLATES[0], "DIRS": [tmp_path, *settings.TEMPLATES[0]["DIRS"]]}
    ]
    html = Template('{% load karni_site %}{% karni_form "subscriber" %}').render(
        RequestContext(rf.get("/"))
    )
    assert '<p class="own">Email<input' in html


def test_the_form_class_is_swappable(settings: Settings, rf: RequestFactory) -> None:
    settings.KARNI_SITE_FORM_CLASS = "tests.test_forms.LoudForm"
    html = Template('{% load karni_site %}{% karni_form "subscriber" %}').render(
        RequestContext(rf.get("/"))
    )
    assert "LOUD" in html


class LoudForm(SiteForm):
    def render(self, request: Any, options: Any) -> str:
        return "LOUD" + super().render(request, options)


def test_names_resolve_by_model_label_and_setting(settings: Settings) -> None:
    assert resolve_form("subscriber").model is Subscriber
    assert resolve_form("formapp.subscriber").model is Subscriber
    settings.KARNI_SITE_FORMS = {
        "newsletter": "formapp.Subscriber",
        "jobs": "tests.formapp.viewsets.ApplicationViewSet",
    }
    assert resolve_form("newsletter").model is Subscriber
    assert resolve_form("jobs").model is Application
    settings.KARNI_SITE_FORMS = {"broken": "nowhere.Nothing"}
    with pytest.raises(UnknownForm, match="SITE020"):
        resolve_form("broken")


# without JavaScript


def test_a_sent_form_redirects_back_and_says_so(client: Client) -> None:
    response = client.post(FORM, VALID)
    assert response.status_code == 303
    assert response["Location"] == (
        "/book/?sent=appointment_request#karni-form-appointment_request"
    )
    row = AppointmentRequest.objects.get()
    assert (row.name, row.status, str(row.day)) == ("Ada Lovelace", "new", "2030-01-15")
    html = page(client, response["Location"].split("#")[0])
    status = re.search(r'<p class="karni-form-message is-success"[^>]*>(.*?)</p>', html)
    assert status and status.group(1) == "Thank you. Your submission was received."
    # Only the form that was sent says so.
    subscriber = html.split('<form id="karni-form-subscriber"', 1)[1]
    assert re.search(
        r'<p class="alert" role="status" aria-live="polite" data-karni-form-message hidden>',
        subscriber,
    )


def test_an_invalid_form_comes_back_with_its_errors_and_values(client: Client) -> None:
    response = client.post(FORM, {**VALID, "email": "not-an-address", "day": ""})
    assert response.status_code == 400
    html = response.content.decode()
    assert "<h1>Book an appointment</h1>" in html  # the page itself, rendered again
    email = field_block(html, "appointment_request", "email")
    assert 'value="not-an-address"' in email and 'aria-invalid="true"' in email
    assert 'id="karni-form-appointment_request-email-error"' in email
    assert "Enter a valid email address." in email
    day = field_block(html, "appointment_request", "day")
    assert "This field is required." in day or "Date has wrong format" in day
    assert 'value="Ada Lovelace"' in field_block(html, "appointment_request", "name")
    assert '<option value="checkup" selected>' in field_block(html, "appointment_request", "reason")
    assert "Please correct the fields marked below." in html
    assert AppointmentRequest.objects.count() == 0


def test_a_filled_honeypot_looks_sent_and_saves_nothing(client: Client) -> None:
    response = client.post(FORM, {**VALID, "homepage": "https://spam.example"})
    assert response.status_code == 303 and "sent=appointment_request" in response["Location"]
    assert AppointmentRequest.objects.count() == 0


def test_visitors_cannot_set_the_staff_fields(client: Client) -> None:
    client.post(FORM, {**VALID, "status": "declined", "notes": "VIP"})
    row = AppointmentRequest.objects.get()
    assert (row.status, row.notes) == ("new", "")


def test_the_rate_limit_shows_its_message(client: Client, settings: Settings) -> None:
    settings.KARNI_PUBLIC_CREATE_RATE = "2/hour"
    codes = [client.post(FORM, VALID).status_code for _ in range(2)]
    limited = client.post(FORM, VALID)
    assert codes == [303, 303] and limited.status_code == 429
    assert limited["Retry-After"]
    assert "This form was sent several times in a short while." in limited.content.decode()
    # The API shares the limit: the form and /api/ count the same visitor.
    api = client.post("/api/appointment-requests/", {k: v for k, v in VALID.items()})
    assert api.status_code == 429


def test_the_csrf_check_applies() -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.post(FORM, VALID).status_code == 403
    html = client.get("/book/").content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert token
    response = client.post(FORM, {**VALID, "csrfmiddlewaretoken": token.group(1)})
    assert response.status_code == 303


def test_a_page_that_cannot_render_again_falls_back_to_a_plain_page(client: Client) -> None:
    response = client.post(FORM, {**VALID, "email": "", "karni-next": "/no-such-page/"})
    assert response.status_code == 400
    html = response.content.decode()
    assert "<title>Appointment_request</title>" in html
    assert "This field may not be blank." in field_block(html, "appointment_request", "email")


def test_a_refused_form_says_so(client: Client) -> None:
    response = client.post("/forms/feedback/", {"message": "Hi", "karni-next": "/feedback/"})
    assert response.status_code == 403
    assert "This form cannot be sent." in response.content.decode()


def test_an_unknown_form_is_a_404(client: Client) -> None:
    assert client.post("/forms/brochure/", {}).status_code == 404
    assert client.get(FORM).status_code == 405


def test_a_file_upload_and_a_next_page(client: Client) -> None:
    html = page(client, "/apply/")
    assert 'enctype="multipart/form-data"' in html and "data-karni-follow" in html
    assert 'name="karni-next" value="/about/"' in html
    cv = SimpleUploadedFile("cv.txt", b"Ten years of joinery.", content_type="text/plain")
    response = client.post(
        "/forms/application/", {"name": "Grace", "cv": cv, "karni-next": "/about/"}
    )
    assert response.status_code == 303 and response["Location"] == "/about/?sent=application"
    assert Application.objects.get().cv.read() == b"Ten years of joinery."


def test_next_never_leaves_the_site(client: Client) -> None:
    response = client.post(FORM, {**VALID, "karni-next": "https://evil.example/"})
    assert response["Location"] == "/?sent=appointment_request"


# with JavaScript: the same view answers JSON


def test_json_answers_for_the_script(client: Client, settings: Settings) -> None:
    sent = client.post(FORM, VALID, **JSON)
    assert sent.status_code == 201
    body = sent.json()
    assert body["ok"] is True and body["status"] == "success"
    assert body["redirect"] == "/book/?sent=appointment_request#karni-form-appointment_request"
    invalid = client.post(FORM, {**VALID, "email": "nope"}, **JSON)
    assert invalid.status_code == 400
    assert invalid.json()["errors"] == {"email": ["Enter a valid email address."]}
    settings.KARNI_PUBLIC_CREATE_RATE = "1/hour"
    limited = client.post(FORM, VALID, **JSON)
    assert limited.status_code == 429 and limited.json()["status"] == "throttled"
    refused = client.post("/forms/feedback/", {"message": "Hi"}, **JSON)
    assert refused.status_code == 401 and refused.json()["status"] == "refused"  # as the API


# the notification


def test_the_recipients_are_emailed_after_commit(
    client: Client, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        client.post(FORM, VALID)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["desk@example.com", "doctor@example.com"]
    assert message.reply_to == ["ada@example.com"]
    assert message.subject == "New appointment request from Ada Lovelace"
    assert "asks for an appointment on 15 Jan 2030." in message.body
    assert "Reason: Check-up" in message.body and "First visit: no" in message.body
    row = AppointmentRequest.objects.get()
    assert f"/admin/formapp/appointmentrequest/{row.pk}/change/" in message.body or (
        "In the admin: " in message.body
    )


def test_the_admin_link_is_a_full_address(settings: Settings, rf: RequestFactory) -> None:
    from karni.middleware import _current_request

    from karni_site.notify import notification_context

    row = AppointmentRequest.objects.create(
        name="A", email="a@example.com", reason="other", day="2030-01-01"
    )
    path = f"/admin/formapp/appointmentrequest/{row.pk}/change/"
    # No site address and no request (a shell, beat): the path is all there is.
    assert notification_context(row)["admin_url"] == path
    # Queued from a request: the host the visitor came to, which the task carries.
    settings.ALLOWED_HOSTS = ["clinic.example"]
    token = _current_request.set(rf.get("/", HTTP_HOST="clinic.example", secure=True))
    try:
        assert notification_context(row)["admin_url"] == f"https://clinic.example{path}"
        # The site's own address wins over the request's.
        settings.KARNI_SITE_URL = "https://www.clinic.example/"
        context = notification_context(row)
    finally:
        _current_request.reset(token)
    assert context["admin_url"] == f"https://www.clinic.example{path}"
    assert context["admin_path"] == path


def test_no_recipients_sends_nothing(
    client: Client, settings: Settings, django_capture_on_commit_callbacks: Any
) -> None:
    settings.APPOINTMENT_RECIPIENTS = ""
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(FORM, VALID).status_code == 303
    assert mail.outbox == []


def test_a_missing_recipients_setting_names_the_fix(settings: Settings) -> None:
    from karni_site.notify import notify_recipients

    del settings.APPOINTMENT_RECIPIENTS
    row = AppointmentRequest.objects.create(
        name="A", email="a@example.com", reason="other", day="2030-01-01"
    )
    with pytest.raises(Exception, match="SITE023.*APPOINTMENT_RECIPIENTS"):
        notify_recipients(
            row, setting="APPOINTMENT_RECIPIENTS", template="formapp/email/appointment"
        )


# karni check


def test_the_check_reports_a_form_that_does_not_exist(settings: Settings, tmp_path: Path) -> None:
    from karni_site.form_checks import unknown_forms

    (tmp_path / "broken.html").write_text(
        '{% load karni_site %}\n{% karni_form "brochure" %}\n{% karni_form "subscriber" %}\n'
        "{% karni_form form_name %}\n"
    )
    settings.TEMPLATES = [{**settings.TEMPLATES[0], "DIRS": [tmp_path]}]
    failures = unknown_forms()
    assert len(failures) == 1 and failures[0].startswith(f"SITE020: {tmp_path / 'broken.html'}:2:")


def test_the_plain_render_needs_no_request() -> None:
    html = Template('{% load karni_forms %}{% karni_form "subscriber" %}').render(Context({}))
    assert 'action="/forms/subscriber/"' in html and "csrfmiddlewaretoken" not in html


def test_forms_module_exports() -> None:
    assert forms.class_names()["field"] == "karni-field"
    assert forms.messages({"success": "Done."})["success"] == "Done."


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"HTTP_REFERER": "http://testserver/forms/appointment_request/"},
    ],
)
def test_a_post_without_a_page_never_redirects_to_the_form_itself(
    client: Client, extra: dict[str, str]
) -> None:
    """The form endpoint answers 405 to a GET, so it is never where a sent form goes back to."""
    without_next = {k: v for k, v in VALID.items() if k != "karni-next"}
    response = client.post(FORM, without_next, **extra)
    assert response.status_code == 303
    assert response["Location"].startswith("/?sent=appointment_request")
    assert client.get(response["Location"].split("?")[0]).status_code == 200
    posted = client.post(FORM, {**VALID, "karni-next": FORM})
    assert posted["Location"].startswith("/?sent=")
