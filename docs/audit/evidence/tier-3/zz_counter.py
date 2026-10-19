"""Counter-test to tests/api/test_ordering.py::test_write_only_fields_are_not_orderable.

That test creates older(note="zzz") and newer(note="aaa"); ascending-by-note == default (-created_at),
so `assert result == default_order` passes whether or not the write-only field is orderable.
Here the notes are swapped so the two orders differ: if ordering by the write-only field is
refused, the default order survives; if it is honoured, the list flips.
"""

from __future__ import annotations

from tests.api.test_ordering import _default_ordering, _event, _listed_ids, pytestmark  # noqa: F401
from tests.testapp.models import Event


def test_write_only_field_is_in_fact_orderable() -> None:
    older = _event("Older", created_offset=-300, internal_note="aaa")
    newer = _event("Newer", internal_note="zzz")
    default_order = [str(pk) for pk in Event.objects.order_by(*_default_ordering()).values_list("pk", flat=True)]
    assert default_order == [str(newer.pk), str(older.pk)]
    result = _listed_ids({"ordering": "internal_note"})
    print("default:", default_order, "ordering=internal_note:", result)
    # Contract: write-only is not orderable, so result must equal default_order.
    assert result == default_order, "write-only field internal_note IS orderable: " + str(result)
