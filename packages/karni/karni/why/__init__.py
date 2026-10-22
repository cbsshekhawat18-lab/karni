"""``karni why``: explain an access decision with the code that made it — never a guess.

Permission and scope bugs are the hardest to debug because nothing fails:
the row is just absent. ``karni why`` answers, for one user, one resource and
one action, what the API does and why:

* :func:`explain_row` — ``karni why events/<id> --as alice [--action update]``:
  a row filtered out by the read scope (404), a request refused at the gate
  (no grant, a veto, not signed in), a write refused on a readable row (403);
* :func:`explain_field` — ``karni why events.internal_note --as alice``: a
  field hidden by ``Karni.field_roles`` or read-only, and why;
* :func:`explain_list` — ``karni why-empty events --as alice``: which step of
  the read pipeline (model scopes, the viewset's queryset, ``access.read``,
  ``filter_queryset_for_user``, the request's filters) empties the list, and
  how many rows each removes;
* :func:`explain_record` — ``karni why 403 <request-id>``: replays a request
  the dev server recorded (``.karni/requests/<id>.json``).

How it stays honest: :mod:`karni.why.probe` builds the viewset the way the
router does and runs DRF's own ``initial()`` and the action's lookup, with
the access layer recording every decision it makes
(:data:`karni.api.access.TRACE_ATTR`); the status and the outcome come from
that run. The explanation takes the recorded predicates apart with
:meth:`karni.api.access.Predicate.explain`, which evaluates each leaf with its
own ``allows()``/``rows()`` and recombines them with the folds ``|`` and
``&`` use. A test matrix (``tests/why``) asserts the verdict equals what the
API returns for every (user, resource, action, row) case of the test app.

Dev tooling: it reads the database, never writes (every probe runs in a
transaction that is rolled back) and consumes no rate limit.

Override / escape hatch: every builder takes a :class:`~karni.why.resolve.Resource`
or a name and any user object; :func:`karni.why.probe.run_probe` is the raw
answer for custom reports.
"""

from __future__ import annotations

from karni.why.probe import Probe, run_probe
from karni.why.resolve import (
    Resource,
    WhyError,
    load_record,
    resolve_action,
    resolve_resource,
    resolve_user,
)
from karni.why.verdict import (
    Verdict,
    explain_field,
    explain_list,
    explain_record,
    explain_row,
)

__all__ = [
    "Probe",
    "Resource",
    "Verdict",
    "WhyError",
    "explain_field",
    "explain_list",
    "explain_record",
    "explain_row",
    "load_record",
    "resolve_action",
    "resolve_resource",
    "resolve_user",
    "run_probe",
]
