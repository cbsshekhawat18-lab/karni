from __future__ import annotations

from typing import Any

import requests
from conftest import BASE, Api, money, rows, unique

STAGES = ["lead", "qualified", "proposal", "won", "lost"]


def make_company(api: Api) -> dict[str, Any]:
    reply = api.post("companies/", {"name": unique("co"), "website": "https://example.test"})
    assert reply.status_code == 201, reply.text
    return reply.json()


def make_deal(api: Api, company: dict[str, Any], value: str = "100.00") -> dict[str, Any]:
    reply = api.post(
        "deals/", {"title": unique("deal"), "company": company["id"], "value": value}
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def ids(reply: requests.Response) -> list[Any]:
    return [row["id"] for row in rows(reply)]


def upload(api: Api, text: str) -> requests.Response:
    return api.call(
        "POST", "contacts/import/", files={"file": ("contacts.csv", text, "text/csv")}
    )


def test_sign_in_and_protection(anonymous):
    assert anonymous.get(f"{BASE}/api/deals/").status_code in (401, 403)
    assert anonymous.get(f"{BASE}/api/companies/").status_code in (401, 403)
    bad = anonymous.post(
        f"{BASE}/api/auth/login/", json={"email": "admin@bench.test", "password": "wrong"}
    )
    assert bad.status_code in (400, 401)


def test_every_role_works_with_companies_and_sees_all_of_them(api):
    company = make_company(api("sales"))
    for role in ("sales2", "manager", "admin"):
        assert company["id"] in ids(api(role).get("companies/"))
    assert company["name"] and "website" in company
    assert api("sales2").patch(f"companies/{company['id']}/", {"website": "https://b.test"}).status_code == 200
    assert api("sales").get(f"companies/{company['id']}/").json()["website"] == "https://b.test"


def test_company_names_are_required_and_unique(api):
    sales = api("sales")
    company = make_company(sales)
    assert sales.post("companies/", {"name": company["name"]}).status_code == 400
    assert sales.post("companies/", {"website": "https://x.test"}).status_code == 400


def test_only_managers_and_admins_delete_companies(api):
    company = make_company(api("sales"))
    assert api("sales").delete(f"companies/{company['id']}/").status_code == 403
    assert api("manager").delete(f"companies/{company['id']}/").status_code == 204
    assert api("admin").get(f"companies/{company['id']}/").status_code == 404


def test_contacts_validate_and_filter_by_company(api):
    sales = api("sales")
    company = make_company(sales)
    email = f"{unique('c')}@example.test"
    reply = sales.post(
        "contacts/",
        {"company": company["id"], "first_name": "Ada", "last_name": "L", "email": email, "phone": "1"},
    )
    assert reply.status_code == 201, reply.text
    contact = reply.json()
    assert contact["email"] == email and contact["company"] == company["id"]
    assert sales.post("contacts/", {"first_name": "B", "last_name": "B", "email": email}).status_code == 400
    assert sales.post("contacts/", {"first_name": "B", "last_name": "B", "email": "nope"}).status_code == 400
    assert sales.post("contacts/", {"first_name": "B", "last_name": "B"}).status_code == 400
    found = rows(api("manager").get("contacts/", params={"company": company["id"]}))
    assert [c["id"] for c in found] == [contact["id"]]
    assert api("sales2").patch(f"contacts/{contact['id']}/", {"phone": "9"}).status_code == 200


def test_a_new_deal_is_a_lead_owned_by_its_creator(api):
    sales = api("sales")
    company = make_company(sales)
    reply = sales.post(
        "deals/",
        {"title": unique("d"), "company": company["id"], "value": "250.00", "stage": "won", "owner": 1},
    )
    assert reply.status_code == 201, reply.text
    deal = reply.json()
    assert deal["stage"] == "lead"
    assert money(deal["value"]) == money("250.00")
    mine = rows(sales.get("deals/"))
    assert deal["id"] in [d["id"] for d in mine]
    assert {d["owner"] for d in mine} == {deal["owner"]}
    assert sales.post("deals/", {"company": company["id"], "value": "1"}).status_code == 400
    assert sales.post("deals/", {"title": "x", "company": company["id"], "value": "-5"}).status_code == 400


def test_sales_see_only_their_own_deals_managers_and_admins_see_all(api):
    company = make_company(api("sales"))
    mine, theirs = make_deal(api("sales"), company), make_deal(api("sales2"), company)
    assert mine["id"] in ids(api("sales").get("deals/"))
    assert theirs["id"] not in ids(api("sales").get("deals/"))
    assert api("sales").get(f"deals/{theirs['id']}/").status_code in (403, 404)
    assert api("sales").get(f"deals/{mine['id']}/").status_code == 200
    for role in ("manager", "admin"):
        seen = ids(api(role).get("deals/"))
        assert mine["id"] in seen and theirs["id"] in seen
        assert api(role).get(f"deals/{theirs['id']}/").status_code == 200


def test_sales_edit_only_their_own_deals_and_not_stage_or_owner(api):
    company = make_company(api("sales"))
    mine, theirs = make_deal(api("sales"), company), make_deal(api("sales2"), company)
    assert api("sales").patch(f"deals/{mine['id']}/", {"title": "renamed"}).status_code == 200
    assert api("sales").get(f"deals/{mine['id']}/").json()["title"] == "renamed"
    assert api("sales").patch(f"deals/{theirs['id']}/", {"title": "x"}).status_code in (403, 404)
    api("sales").patch(f"deals/{mine['id']}/", {"stage": "won", "owner": theirs["owner"]})
    after = api("sales").get(f"deals/{mine['id']}/").json()
    assert after["stage"] == "lead" and after["owner"] == mine["owner"]


def test_managers_reassign_deals(api):
    company = make_company(api("sales"))
    deal = make_deal(api("sales"), company)
    other = make_deal(api("sales2"), company)
    changed = api("manager").patch(f"deals/{deal['id']}/", {"owner": other["owner"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["owner"] == other["owner"]
    assert deal["id"] in ids(api("sales2").get("deals/"))
    assert deal["id"] not in ids(api("sales").get("deals/"))


def test_only_admins_delete_deals(api):
    company = make_company(api("sales"))
    deal = make_deal(api("sales"), company)
    assert api("sales").delete(f"deals/{deal['id']}/").status_code == 403
    assert api("manager").delete(f"deals/{deal['id']}/").status_code == 403
    assert api("admin").delete(f"deals/{deal['id']}/").status_code == 204
    assert api("admin").get(f"deals/{deal['id']}/").status_code == 404


def test_the_pipeline_allows_forward_steps_and_lost(api):
    sales = api("sales")
    deal = make_deal(sales, make_company(sales))
    for stage in ("qualified", "proposal", "won"):
        reply = sales.post(f"deals/{deal['id']}/move/", {"stage": stage})
        assert reply.status_code == 200, reply.text
        assert reply.json()["stage"] == stage
    assert sales.get(f"deals/{deal['id']}/").json()["stage"] == "won"
    for start in ("lead", "qualified", "proposal"):
        lost = make_deal(sales, make_company(sales))
        if start != "lead":
            sales.post(f"deals/{lost['id']}/move/", {"stage": "qualified"})
        if start == "proposal":
            sales.post(f"deals/{lost['id']}/move/", {"stage": "proposal"})
        assert sales.post(f"deals/{lost['id']}/move/", {"stage": "lost"}).status_code == 200


def test_the_pipeline_refuses_other_moves_and_changes_nothing(api):
    sales = api("sales")
    deal = make_deal(sales, make_company(sales))
    for stage in ("proposal", "won", "lead", "nowhere"):
        assert sales.post(f"deals/{deal['id']}/move/", {"stage": stage}).status_code == 400
    assert sales.get(f"deals/{deal['id']}/").json()["stage"] == "lead"
    sales.post(f"deals/{deal['id']}/move/", {"stage": "qualified"})
    assert sales.post(f"deals/{deal['id']}/move/", {"stage": "lead"}).status_code == 400
    sales.post(f"deals/{deal['id']}/move/", {"stage": "lost"})
    for stage in ("lead", "qualified", "won", "lost"):
        assert sales.post(f"deals/{deal['id']}/move/", {"stage": stage}).status_code == 400
    assert sales.get(f"deals/{deal['id']}/").json()["stage"] == "lost"
    assert sales.post(f"deals/{deal['id']}/move/", {}).status_code == 400


def test_moving_follows_visibility(api):
    deal = make_deal(api("sales"), make_company(api("sales")))
    assert api("sales2").post(f"deals/{deal['id']}/move/", {"stage": "qualified"}).status_code in (403, 404)
    assert api("manager").post(f"deals/{deal['id']}/move/", {"stage": "qualified"}).status_code == 200


def test_the_pipeline_report_counts_what_the_user_may_see(api):
    sales2 = api("sales2")
    company = make_company(sales2)
    before = {r["stage"]: r for r in api("sales2").get("deals/pipeline/").json()}
    assert list(before) == STAGES
    first, second = make_deal(sales2, company, "10.00"), make_deal(sales2, company, "5.50")
    sales2.post(f"deals/{second['id']}/move/", {"stage": "qualified"})
    make_deal(api("sales"), company, "1000.00")
    after = {r["stage"]: r for r in api("sales2").get("deals/pipeline/").json()}
    assert after["lead"]["count"] == before["lead"]["count"] + 1
    assert money(after["lead"]["value"]) == money(before["lead"]["value"]) + money("10.00")
    assert after["qualified"]["count"] == before["qualified"]["count"] + 1
    assert money(after["qualified"]["value"]) == money(before["qualified"]["value"]) + money("5.50")
    everything = {r["stage"]: r for r in api("manager").get("deals/pipeline/").json()}
    assert everything["lead"]["count"] >= after["lead"]["count"] + 1
    assert first["id"]


def test_importing_contacts_creates_updates_and_skips_bad_rows(api):
    tag = unique("imp")
    one, two = f"one-{tag}@example.test", f"two-{tag}@example.test"
    csv = (
        "first_name,last_name,email,phone,company\n"
        f"Ann,One,{one},111,Acme {tag}\n"
        f"Bob,Two,{two},222,Acme {tag}\n"
        "Bad,Row,not-an-email,333,Acme\n"
        "Empty,Row,,444,Acme\n"
    )
    reply = upload(api("manager"), csv)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert (body["created"], body["updated"], len(body["errors"])) == (2, 0, 2)
    companies = [c for c in rows(api("manager").get("companies/")) if c["name"] == f"Acme {tag}"]
    assert len(companies) == 1
    contacts = rows(api("manager").get("contacts/", params={"company": companies[0]["id"]}))
    assert {c["email"] for c in contacts} == {one, two}
    again = upload(api("admin"), f"first_name,last_name,email,phone,company\nAnna,One,{one},999,Acme {tag}\n")
    assert again.status_code == 200, again.text
    assert (again.json()["created"], again.json()["updated"]) == (0, 1)
    contacts = rows(api("manager").get("contacts/", params={"company": companies[0]["id"]}))
    changed = next(c for c in contacts if c["email"] == one)
    assert changed["first_name"] == "Anna" and changed["phone"] == "999"
    assert len(contacts) == 2
    assert len([c for c in rows(api("manager").get("companies/")) if c["name"] == f"Acme {tag}"]) == 1


def test_sales_cannot_import(api):
    reply = upload(api("sales"), "first_name,last_name,email,phone,company\nA,B,x@example.test,1,Z\n")
    assert reply.status_code == 403
