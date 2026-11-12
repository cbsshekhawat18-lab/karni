"""``dashboard:`` of ``karni.yaml`` (experimental): the home tiles karni build writes.

A shop's staff home: parcels to send and products sold out (entities of the
spec, counted for the roles that may read them), and the revenue tile an app
declares in code, placed and shown to managers only.
"""

from __future__ import annotations

import textwrap

from karni_cli.builder import render
from karni_cli.spec import dashboard, normal
from karni_cli.spec.schema import Spec
from karni_cli.spec.validate import validate_text

SPEC = """\
version: 1
app: {name: Corner}
roles:
  admin: {name: Admin, system: true, grants: {"*": all}}
  shop-manager: {name: Manager, grants: {"shop.*": all}}
  shop-staff: {name: Staff, grants: {"shop.*": all}}
apps:
  shop:
    entities:
      Shipment:
        fields: {status: "state:processing>shipped"}
      Product:
        fields: {name: str, stock: int}
pages:
  - home: dashboard
  - Shipment: [list]
  - Product: [list]
"""

TILES = """\
dashboard:
  - {key: shop.to_send, title: Parcels to send, kind: stat, entity: Shipment,
     filters: {status: processing}, link: /shipments, order: 2}
  - {key: shop.sold_out, title: Sold out, entity: shop.Product, filters: {stock__lte: 0},
     requires: "shop.product:change", roles: [shop-manager]}
  - {key: commerce.revenue, order: 1, size: half, roles: [shop-manager]}
"""


def _spec(text: str = TILES) -> Spec:
    report = validate_text(SPEC + textwrap.dedent(text))
    assert report.ok and report.spec is not None, [i.render("spec") for i in report.issues]
    return report.spec


def test_no_dashboard_writes_no_tiles() -> None:
    spec = _spec("")
    assert dashboard.tiles(spec) is None
    assert "KARNI_DASHBOARD_TILES" not in render.settings_block(spec, 100)
    assert normal.normalise(spec)["dashboard"] is None


def test_an_entity_becomes_its_resource_with_its_view_permission() -> None:
    tiles = dashboard.tiles(_spec())
    assert tiles == [
        {
            "key": "shop.to_send",
            "title": "Parcels to send",
            "kind": "stat",
            "resource": "shipments",
            "filters": {"status": "processing"},
            "link": "/shipments",
            "requires": "shop.shipment:view",
            "order": 2,
        },
        {
            "key": "shop.sold_out",
            "title": "Sold out",
            "resource": "products",
            "filters": {"stock__lte": 0},
            "requires": "shop.product:change",
            "roles": ["shop-manager"],
        },
        {"key": "commerce.revenue", "roles": ["shop-manager"], "order": 1, "size": "half"},
    ]
    block = render.settings_block(_spec(), 100)
    assert "KARNI_DASHBOARD_TILES = [" in block and '"resource": "shipments"' in block


def test_the_setting_reads_back_as_the_same_entries() -> None:
    spec = _spec()
    left_out: list[str] = []
    entries = dashboard.entries_from_setting(dashboard.tiles(spec), spec, left_out)
    assert left_out == []
    again = _spec("dashboard:\n" + "".join(f"  - {_flow(entry)}\n" for entry in entries or []))
    assert dashboard.tiles(again) == dashboard.tiles(spec)
    lost = dashboard.entries_from_setting(
        [{"key": "crm.deals", "resource": "deals"}], spec, left_out
    )
    assert lost is None and left_out == ["dashboard: crm.deals, on deals, a resource no entity has"]


def _flow(entry: dict[str, object]) -> str:
    import json

    return json.dumps(entry)


def test_a_tile_on_something_the_spec_lacks_is_c643() -> None:
    report = validate_text(
        SPEC
        + textwrap.dedent(
            """\
            dashboard:
              - {key: shop.deals, entity: Deal}
              - {key: shop.deals, roles: [crm-rep]}
            """
        )
    )
    codes = sorted(issue.code for issue in report.issues)  # type: ignore[attr-defined]
    assert codes == ["C643", "C643", "C643"]


def test_a_key_without_its_part_is_refused() -> None:
    report = validate_text(SPEC + "dashboard:\n  - {key: revenue}\n")
    assert not report.ok  # type: ignore[attr-defined]
