"""``AdminMeta.can_add = False`` and ``can_delete = False`` (site report 2, item 11).

For a model whose rows code makes, nobody adds or deletes a row in the admin,
superusers and every role included: the Add button, the add page, import, the
Delete button and page, the bulk delete actions and the model's inlines all
follow. Changing a row is still allowed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.admin import KarniModelAdmin
from tests.adminapp.models import Survey, SurveyScore

pytestmark = pytest.mark.django_db

ROLES = {"scorer": {"grants": {"adminapp.surveyscore:*": "all", "adminapp.survey:*": "all"}}}


@pytest.fixture(autouse=True)
def _roles() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


@pytest.fixture
def root() -> Client:
    client = Client()
    client.force_login(
        get_user_model().objects.create_superuser(email="root@example.com", password="pw-12345678")
    )
    return client


@pytest.fixture
def score() -> SurveyScore:
    survey = Survey.objects.create(name="Spring survey")
    return SurveyScore.objects.create(survey=survey, label="Overall", value=7)


def url(model: type[Any], view: str, *args: Any) -> str:
    return reverse(f"admin:adminapp_{model._meta.model_name}_{view}", args=args)


def test_no_add_button_and_the_add_page_is_refused(root: Client, score: SurveyScore) -> None:
    page = root.get(url(SurveyScore, "changelist")).content.decode()
    assert url(SurveyScore, "add") not in page
    assert "Add survey score" not in page
    assert root.get(url(SurveyScore, "add")).status_code == 403
    response = root.post(url(SurveyScore, "add"), {"survey": score.survey.pk, "label": "x"})
    assert response.status_code == 403
    assert SurveyScore.objects.count() == 1


def test_no_delete_button_and_the_delete_page_is_refused(root: Client, score: SurveyScore) -> None:
    form = root.get(url(SurveyScore, "change", score.pk)).content.decode()
    assert url(SurveyScore, "delete", score.pk) not in form
    assert 'name="_addanother"' not in form and 'name="_saveasnew"' not in form
    assert root.get(url(SurveyScore, "delete", score.pk)).status_code == 403
    assert root.post(url(SurveyScore, "delete", score.pk), {"post": "yes"}).status_code == 403
    assert SurveyScore.objects.filter(pk=score.pk).exists()  # alive, not soft-deleted


def test_changing_a_row_still_works(root: Client, score: SurveyScore) -> None:
    response = root.post(
        url(SurveyScore, "change", score.pk),
        {"survey": score.survey.pk, "label": "Overall", "value": 9, "_save": "Save"},
    )
    assert response.status_code == 302, response.content[:400]
    score.refresh_from_db()
    assert score.value == 9


def test_no_bulk_delete_and_no_row_delete_button(root: Client, score: SurveyScore) -> None:
    response = root.get(url(SurveyScore, "changelist"))
    actions = [name for name, _label in response.context["action_form"].fields["action"].choices]
    assert "delete_selected" not in actions and "hard_delete_selected" not in actions
    assert "edit_selected" in actions  # changing many rows still works
    assert f"Delete {score}" not in response.content.decode()  # the row's own button
    posted = root.post(
        url(SurveyScore, "changelist"),
        {"action": "delete_selected", "_selected_action": [str(score.pk)], "post": "yes"},
    )
    assert posted.status_code in (200, 302)
    assert SurveyScore.objects.filter(pk=score.pk).exists()


def test_no_import(root: Client, score: SurveyScore) -> None:
    assert (
        url(SurveyScore, "import") not in root.get(url(SurveyScore, "changelist")).content.decode()
    )
    assert root.get(url(SurveyScore, "import")).status_code == 403
    actions = root.get(url(SurveyScore, "changelist")).context["action_form"].fields["action"]
    assert "export_csv" in [name for name, _label in actions.choices]  # export stays


def test_the_home_page_offers_no_add(root: Client, score: SurveyScore) -> None:
    home = root.get(reverse("admin:index")).content.decode()
    assert url(SurveyScore, "changelist") in home
    assert url(SurveyScore, "add") not in home


def test_a_role_that_grants_everything_cannot_add_or_delete(score: SurveyScore) -> None:
    user = get_user_model().objects.create_user(
        email="scorer@example.com", password="pw-12345678", is_staff=True
    )
    assign_role(user, "scorer")
    client = Client()
    client.force_login(user)
    assert client.get(url(SurveyScore, "add")).status_code == 403
    assert client.get(url(SurveyScore, "delete", score.pk)).status_code == 403
    assert client.get(url(SurveyScore, "change", score.pk)).status_code == 200


def test_the_inline_follows(root: Client, score: SurveyScore) -> None:
    survey = score.survey
    form = root.get(url(Survey, "change", survey.pk)).content.decode()
    assert "Overall" in form
    assert 'name="scores-0-DELETE"' not in form
    assert "scores-__prefix__" not in form  # no blank row to add from, so no Add another
    assert 'name="scores-1-label"' not in form  # and no extra row
    management = {
        "name": survey.name,
        "scores-TOTAL_FORMS": "2",
        "scores-INITIAL_FORMS": "1",
        "scores-MIN_NUM_FORMS": "0",
        "scores-MAX_NUM_FORMS": "1000",
        "scores-0-id": str(score.pk),
        "scores-0-survey": str(survey.pk),
        "scores-0-label": "Overall",
        "scores-0-value": "8",
        "scores-0-DELETE": "on",
        "scores-1-survey": str(survey.pk),
        "scores-1-label": "Sneaked in",
        "scores-1-value": "1",
        "_save": "Save",
    }
    response = root.post(url(Survey, "change", survey.pk), management)
    assert response.status_code == 302, response.content[:600]
    assert list(SurveyScore.objects.values_list("label", "value")) == [("Overall", 8)]


def test_a_subclass_registered_by_hand_follows_and_can_turn_it_back_on(
    score: SurveyScore,
) -> None:
    from django.test import RequestFactory

    request = RequestFactory().get("/admin/")
    request.user = get_user_model().objects.create_superuser(
        email="other-root@example.com", password="pw-12345678"
    )
    site = admin.AdminSite(name="karni-can-add")
    bare = type("Bare", (KarniModelAdmin,), {})(SurveyScore, site)
    assert not bare.has_add_permission(request)
    assert not bare.has_delete_permission(request, score)
    opened = type("Opened", (KarniModelAdmin,), {"karni_can_add": True, "karni_can_delete": True})
    opened_admin = opened(SurveyScore, site)
    assert opened_admin.has_add_permission(request)
    assert opened_admin.has_delete_permission(request, score)
