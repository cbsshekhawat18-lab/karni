"""The leads module: CRUD as a member, workspace isolation, the pipeline actions.

`assert_isolated` cannot drive a `custom:` scope (see FRICTION.md), so the
isolation this module promises is proved here by hand: two members of two
workspaces, each blind to the other's rows on every surface.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from karni.accounts.permissions import assign_role
from karni.testing import APITestCase
from karni.testing.factories import create

from crm.models import Contact, Lead, LeadActivity, Workspace


def member(email: str, *workspaces: Workspace) -> Any:
    user = get_user_model().objects.create_user(email=email, password="pass-word-123")
    assign_role(user, "member")
    for workspace in workspaces:
        workspace.members.add(user)
    return user


def lead_in(workspace: Workspace, **values: Any) -> Lead:
    contact = create(Contact, workspace=workspace)
    return create(Lead, workspace=workspace, contact=contact, **values)


class LeadIsolationTests(APITestCase):
    def setUp(self) -> None:
        self.alpha, self.beta = create(Workspace, name="Alpha"), create(Workspace, name="Beta")
        self.ann, self.bob = member("ann@example.com", self.alpha), member("bob@example.com", self.beta)
        self.mine, self.theirs = lead_in(self.alpha, name="Mine"), lead_in(self.beta, name="Theirs")

    def test_a_member_sees_only_their_workspaces_leads(self) -> None:
        client = self.client_as(user=self.ann)
        listed = client.get("/api/leads/").json()
        assert [row["name"] for row in listed["results"]] == ["Mine"]
        assert client.get(f"/api/leads/{self.theirs.pk}/").status_code == 404
        assert client.patch(f"/api/leads/{self.theirs.pk}/", {"notes": "x"}, format="json").status_code == 404
        assert client.get(f"/api/leads/{self.theirs.pk}/timeline/").status_code == 404
        assert client.post(f"/api/leads/{self.theirs.pk}/convert/", {"conversion_value": 1}, format="json").status_code == 404
        assert client.get("/api/leads/?search=Theirs").json()["count"] == 0
        export = client.get("/api/leads/export/?format=csv")
        assert export.status_code == 200 and b"Theirs" not in b"".join(export.streaming_content)

    def test_an_agency_member_of_both_workspaces_sees_both(self) -> None:
        agency = member("agency@example.com", self.alpha, self.beta)
        listed = self.client_as(user=agency).get("/api/leads/").json()
        assert sorted(row["name"] for row in listed["results"]) == ["Mine", "Theirs"]

    def test_staff_sees_everything(self) -> None:
        assert self.client_as("staff").get("/api/leads/").json()["count"] == 2

    def test_a_member_cannot_create_a_lead_in_another_workspace(self) -> None:
        client = self.client_as(user=self.ann)
        body = {"workspace": str(self.beta.pk), "contact": str(self.theirs.contact_id), "phone": "+91 1"}
        response = client.post("/api/leads/", body, format="json")
        assert response.status_code == 400 and "workspace" in response.json()

    def test_a_member_creates_and_edits_leads_in_their_workspace(self) -> None:
        client = self.client_as(user=self.ann)
        contact = create(Contact, workspace=self.alpha, phone="+91 98765")
        body = {"workspace": str(self.alpha.pk), "contact": str(contact.pk), "phone": "+91 98765", "name": "New"}
        created = client.post("/api/leads/", body, format="json")
        assert created.status_code == 201, created.content
        assert created.json()["status"] == "new" and created.json()["quality_score"] == 50
        lead_id = created.json()["id"]
        assert client.patch(f"/api/leads/{lead_id}/", {"notes": "called"}, format="json").status_code == 200
        assert client.get(f"/api/leads/{lead_id}/?expand=contact").json()["contact"]["phone"] == "+91 98765"
        assert client.delete(f"/api/leads/{lead_id}/").status_code == 204


class LeadPipelineTests(APITestCase):
    def setUp(self) -> None:
        self.workspace = create(Workspace, name="Alpha")
        self.ann = member("ann@example.com", self.workspace)
        self.sam = member("sam@example.com", self.workspace)
        self.lead = lead_in(
            self.workspace, name="Lead", status="new", tags=["hot"], budget="", interest="", email="", location=""
        )
        self.client_ann = self.client_as(user=self.ann)

    def test_status_change_writes_the_timeline(self) -> None:
        response = self.client_ann.post(
            f"/api/leads/{self.lead.pk}/status/", {"status": "contacted", "notes": "left a message"}, format="json"
        )
        assert response.status_code == 200 and response.json()["status"] == "contacted"
        assert "left a message" in response.json()["notes"]
        activity = LeadActivity.objects.get(lead=self.lead)
        assert activity.activity_type == "status_change" and activity.actor == self.ann
        assert activity.metadata == {"previous": "new", "new": "contacted"}
        bad = self.client_ann.post(f"/api/leads/{self.lead.pk}/status/", {"status": "bogus"}, format="json")
        assert bad.status_code == 400

    def test_assign_bulk_assign_and_unassign(self) -> None:
        response = self.client_ann.post(f"/api/leads/{self.lead.pk}/assign/", {"user_id": str(self.sam.pk)}, format="json")
        assert response.status_code == 200 and response.json()["assigned_to"] == str(self.sam.pk)
        other = lead_in(self.workspace, name="Other")
        bulk = self.client_ann.post(
            "/api/leads/bulk-assign/", {"lead_ids": [str(self.lead.pk), str(other.pk)], "user_id": str(self.sam.pk)}, format="json"
        )
        assert bulk.status_code == 200 and bulk.json() == {"updated": 2}
        assert Lead.objects.filter(assigned_to=self.sam).count() == 2
        unassigned = self.client_ann.post(f"/api/leads/{self.lead.pk}/assign/", {"user_id": None}, format="json")
        assert unassigned.json()["assigned_to"] is None
        ghost = "00000000-0000-0000-0000-000000000000"
        assert self.client_ann.post(f"/api/leads/{self.lead.pk}/assign/", {"user_id": ghost}, format="json").status_code == 400

    def test_convert_records_value_and_time(self) -> None:
        response = self.client_ann.post(f"/api/leads/{self.lead.pk}/convert/", {"conversion_value": "50000"}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "converted" and body["conversion_value"] == "50000.00" and body["converted_at"]
        assert "Converted" in LeadActivity.objects.get(lead=self.lead).content

    def test_activity_and_timeline(self) -> None:
        added = self.client_ann.post(
            f"/api/leads/{self.lead.pk}/activity/", {"activity_type": "call", "content": "10 min"}, format="json"
        )
        assert added.status_code == 201 and added.json()["activity_type"] == "call"
        timeline = self.client_ann.get(f"/api/leads/{self.lead.pk}/timeline/").json()
        assert timeline["bot_steps"] == [] and timeline["activities"][0]["content"] == "10 min"
        assert timeline["activities"][0]["actor_email"] == "ann@example.com"
        expanded = self.client_ann.get(f"/api/leads/{self.lead.pk}/?expand=activities").json()
        assert expanded["activities"][0]["content"] == "10 min"

    def test_scoring(self) -> None:
        low = self.client_ann.post(f"/api/leads/{self.lead.pk}/score-with-ai/", format="json").json()
        assert low["quality_score"] == 20 and "no budget" in low["quality_reason"]
        self.lead.refresh_from_db()
        self.lead.budget, self.lead.interest, self.lead.email = "1-2 lakh", "3BHK", "x@example.com"
        self.lead.save()
        high = self.client_ann.post(f"/api/leads/{self.lead.pk}/score-with-ai/", format="json").json()
        assert high["quality_score"] == 85 and "budget stated" in high["quality_reason"]

    def test_filters_search_and_tags(self) -> None:
        lead_in(self.workspace, name="Cold", status="lost", tags=[], interest="Villa")
        get = self.client_ann.get
        assert get("/api/leads/?status=lost").json()["count"] == 1
        assert get("/api/leads/?tag=hot").json()["results"][0]["name"] == "Lead"
        assert get("/api/leads/?search=Villa").json()["results"][0]["name"] == "Cold"
        assert get("/api/leads/?quality_score__gte=51").json()["count"] == 0
        assert get("/api/leads/?assigned_to=" + str(self.sam.pk)).json()["count"] == 0

    def test_export_and_import_are_served(self) -> None:
        export = self.client_ann.get("/api/leads/export/?format=csv")
        assert export.status_code == 200 and export["Content-Type"].startswith("text/csv")
        assert b"Lead" in b"".join(export.streaming_content)
        describe = self.client_ann.get("/api/leads/import/")
        assert describe.status_code == 200 and "fields" in describe.json()
