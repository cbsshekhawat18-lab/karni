"""``karni.facts`` and ``manage.py karni_facts`` (experimental): the project as JSON facts."""

from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.test import override_settings

from karni.facts import project_apps, project_facts


@override_settings(KARNI_FACTS_APPS=["testapp"])
def test_facts_describe_models_viewsets_and_settings() -> None:
    facts = project_facts()
    assert json.loads(json.dumps(facts)) == facts  # JSON-safe throughout
    assert [config.label for config in project_apps()] == ["testapp"]
    (testapp,) = facts["apps"]
    models = {model["name"]: model for model in testapp["models"]}
    event = models["Event"]
    assert event["base_model"] is True
    names = [field["name"] for field in event["fields"]]
    assert "id" not in names and "created_by" not in names  # BaseModel's own fields
    venue = next(field for field in event["fields"] if field.get("related") == "testapp.Venue")
    assert venue["class"] == "django.db.models.fields.related.ForeignKey"
    assert venue["kwargs"]["on_delete"].startswith("django.db.models.deletion.")
    assert models["Stamp"]["base_model"] is False
    routes = {viewset["route"]: viewset for viewset in facts["viewsets"]}
    assert any(viewset["model"] == "testapp.Event" for viewset in routes.values())
    assert all("access" in viewset for viewset in routes.values())
    assert set(facts["settings"]) >= {"KARNI_ROLES", "KARNI_2FA", "KARNI_TERMS"}
    assert facts["user_model"] == "karni_accounts.User"


@override_settings(KARNI_FACTS_APPS=["testapp"])
def test_karni_facts_prints_the_facts() -> None:
    out = StringIO()
    call_command("karni_facts", stdout=out)
    printed = json.loads(out.getvalue())
    assert printed["apps"][0]["label"] == "testapp"
