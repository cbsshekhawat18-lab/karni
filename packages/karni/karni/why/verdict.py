"""Verdicts: what the API decides for one user, why, where in the code, and how to change it.

Each builder runs a :func:`~karni.why.probe.run_probe` — the router's view,
DRF's ``initial()``, the real lookup — and reads the decision from it: the
status the view's own exception handling produced and the events the access
layer recorded while deciding. The explanation then takes each recorded
predicate apart with :meth:`~karni.api.access.Predicate.explain`, which
evaluates every leaf with the leaf's own ``allows()``/``rows()`` and
recombines them with the folds the predicate itself uses; a mismatch with
the recorded decision is printed, never hidden.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Model, QuerySet
from rest_framework.generics import GenericAPIView

from karni.api.access import (
    Access,
    AccessEvent,
    AccessPermission,
    Can,
    Explained,
    Granted,
    Unscoped,
    action_override,
    action_slot,
    predicate_leaves,
)
from karni.api.viewsets import BaseViewSet
from karni.rows import apply_rows
from karni.why.leaves import Leaf, explain_leaves, grant_lines, predicate_text
from karni.why.probe import Probe, run_probe
from karni.why.resolve import (
    Resource,
    WhyError,
    load_record,
    resolve_action,
    resolve_resource,
    resources,
)
from karni.why.source import (
    Location,
    attribute_location,
    callable_location,
    class_location,
    display_user,
)

__all__ = [
    "Section",
    "Verdict",
    "explain_field",
    "explain_list",
    "explain_record",
    "explain_row",
]

_STATUS_TEXT = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Server Error",
}


@dataclass
class Section:
    """One labelled block of the text verdict; the first line sits next to the label."""

    label: str
    lines: list[str]


@dataclass
class Verdict:
    """The answer: ``status`` the API sends (``None`` for a field), ``outcome`` in one word."""

    kind: str
    outcome: str = ""
    status: int | None = None
    summary: str = ""
    sections: list[Section] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, label: str, *lines: str | None) -> None:
        kept = [line for line in lines if line]
        if kept:
            self.sections.append(Section(label, kept))

    def fix(self, *candidates: str) -> None:
        for candidate in candidates:
            if candidate and candidate not in self.fixes:
                self.fixes.append(candidate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "outcome": self.outcome,
            "status": self.status,
            "summary": self.summary,
            **self.data,
            "fix": self.fixes[:2],
            "notes": self.notes,
        }

    def text(self) -> str:
        """The verdict for a person (or an agent's context window): label, value, aligned."""
        sections = list(self.sections)
        sections.append(Section("result", [self.summary]))
        if self.fixes:
            first, *rest = self.fixes[:2]
            sections.append(Section("fix", [first, *(f"or: {more}" for more in rest)]))
        if self.notes:
            sections.append(Section("note", list(self.notes)))
        out: list[str] = []
        for section in sections:
            first, *rest = section.lines
            out.append(f"{section.label:<8} {first}".rstrip())
            out.extend(f"{'':<9}{line}".rstrip() for line in rest)
        return "\n".join(out)


def _status(code: int) -> str:
    return f"{code} {_STATUS_TEXT.get(code, '')}".strip()


# who is asking


def _user_data(user: Any) -> dict[str, Any] | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return {
        "id": str(user.pk),
        "login": display_user(user),
        "email": getattr(user, "email", None),
        "is_active": bool(getattr(user, "is_active", True)),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
    }


def _who(verdict: Verdict, user: Any) -> list[str]:
    from karni.accounts.permissions import user_roles

    roles = user_roles(user)
    verdict.data["user"] = _user_data(user)
    verdict.data["roles"] = roles
    if not getattr(user, "is_authenticated", False):
        verdict.add("user", "anonymous (not signed in)")
        verdict.add("roles", "none")
        return roles
    flags = []
    if not getattr(user, "is_active", True):
        flags.append("inactive: cannot sign in")
    if getattr(user, "is_superuser", False):
        flags.append("superuser")
    elif getattr(user, "is_staff", False):
        flags.append("is_staff")
    extra = f", {', '.join(flags)}" if flags else ""
    verdict.add("user", f"{display_user(user)}  (pk {user.pk}{extra})")
    note = (
        "; superuser: holds every grant at scope all and sees every field"
        if getattr(user, "is_superuser", False)
        else ""
    )
    verdict.add("roles", (", ".join(roles) or "none") + note)
    return roles


# the declaration


def _slot(probe: Probe) -> str:
    view = probe.view
    if action_override(view) is not None:
        return "action"
    if probe.action.name in getattr(view, "write_or_create_actions", ()):
        return "create|write"
    return action_slot(probe.action.name, probe.action.method)


def _access(verdict: Verdict, probe: Probe) -> Location | None:
    view = probe.view
    cls = type(view)
    declaration = view.get_access()
    location = attribute_location(cls, "access") or class_location(cls)
    where = f"  {location}" if location else ""
    data: dict[str, Any] = {
        "viewset": cls.__name__,
        "where": location.as_dict() if location else None,
    }
    if declaration is None:
        verdict.add("access", f"{cls.__name__} declares no access{where}: every request is refused")
        data["declaration"] = None
    elif isinstance(declaration, Unscoped):
        verdict.add(
            "access",
            f"{cls.__name__}.access = Unscoped(reason={declaration.reason!r}){where}",
            "Karni's access layer is off here: the viewset's permission_classes (else DRF's "
            "DEFAULT_PERMISSION_CLASSES) decide, rows are limited by model scopes and "
            "filter_queryset_for_user only",
        )
        data["declaration"] = {"unscoped": declaration.reason}
    else:
        lines = [f"{cls.__name__}.access{where}"]
        current = _slot(probe)
        for slot in ("read", "write", "create"):
            lines.append(f"  {slot:<6} = {_slot_text(view, declaration, slot, current)}")
        override = action_override(view)
        if override is not None:
            handler = getattr(cls, probe.action.name, None)
            at = callable_location(handler) if handler is not None else None
            lines.append(
                f"  @action {probe.action.name}(access={predicate_text(override)})"
                + (f"  {at}" if at else "")
            )
        if cls.get_access is not BaseViewSet.get_access:
            at = callable_location(cls.get_access)
            lines.append(
                f"  get_access() is overridden{f' ({at})' if at else ''}: shown is its answer"
            )
        verdict.add("access", *lines)
        data["declaration"] = {
            slot: predicate_text(declaration.slot(slot)) for slot in ("read", "write", "create")
        }
    verdict.data["access"] = data
    return location


def _slot_text(view: Any, declaration: Access, slot: str, current: str) -> str:
    """The slot as declared, and — for ``Granted()`` — the permission it binds to here."""
    predicate = declaration.slot(slot)
    text = predicate_text(predicate)
    if not any(isinstance(leaf, Granted) for leaf in predicate_leaves(predicate)):
        return text
    try:
        if slot == "read":
            bound = predicate.bind(view, "view")
        elif slot == "create":
            bound = predicate.bind(view, "create")
        elif current == "write":
            bound = predicate.bind(view)
        else:
            label = view.get_model()._meta.label_lower
            return f"{text}  (binds to {label}:change / :delete, or a declared @action's own)"
    except Exception:  # noqa: BLE001 - an unbindable action is reported by the gate
        return text
    return f"{text}  (binds to {predicate_text(bound)})"


def _request_line(verdict: Verdict, probe: Probe) -> None:
    view = probe.view
    slot = _slot(probe)
    governs = {
        "read": "access.read",
        "write": "access.write"
        + ("; the row is looked up through access.read" if probe.action.detail else ""),
        "create": "access.create",
        "create|write": "access.create or access.write",
        "action": "its @action(access=...)"
        + ("; the row is looked up through access.read" if probe.action.detail else ""),
    }.get(slot, slot)
    query = "&".join(f"{k}={v}" for k, values in probe.query.items() for v in values)
    path = probe.path + (f"?{query}" if query else "")
    verdict.add(
        "request",
        f"{probe.action.method} {path} → {type(view).__name__}.{probe.action.name} ({governs})",
    )
    verdict.data["request"] = {
        "method": probe.action.method,
        "path": probe.path,
        "query": probe.query,
        "resource": probe.resource.prefix,
        "basename": probe.resource.basename,
        "action": probe.action.name,
        "pk": None if probe.pk is None else str(probe.pk),
        "slot": slot,
    }


# predicates, part by part


def _explain(event: AccessEvent | None, request: Any) -> Explained | None:
    predicate = event.data.get("predicate") if event is not None else None
    if predicate is None:
        return None
    return predicate.explain(request)


def _consistent(
    verdict: Verdict, what: str, explained: Explained, decided: Any, *, exempt: bool = False
) -> None:
    """Note (never hide) an explanation that disagrees with the recorded decision.

    ``gate`` compares the request-level answer; a row filter compares the
    compiled rows (``scope_exempt`` turns them into the gate's answer).
    """
    if what == "gate":
        agrees = explained.allows == decided
    elif exempt:
        agrees = explained.allows == (decided is True)
    else:
        agrees = explained.rows == decided
    if agrees:
        return
    verdict.notes.append(
        f"the {what} explanation ({explained.allows}/{explained.rows!r}) differs from what the "
        f"access layer decided ({decided!r}): the predicate is not deterministic (a Where reading "
        "the clock or random state?). The status above is the access layer's."
    )


def _leaf_rows(leaves: Iterable[Leaf], *, show_row: bool) -> list[str]:
    lines = []
    for leaf in leaves:
        if show_row:
            mark = {True: "yes", False: "no", None: "-"}[leaf.matches_row]
            values = ", ".join(f"{k}={v}" for k, v in leaf.row_values.items())
            row = f"; row has {values}" if values else ""
            lines.append(f"  {mark:<3}  {predicate_text(leaf.predicate)}: {leaf.rows_text}{row}")
        else:
            lines.append(f"  {predicate_text(leaf.predicate)}: {leaf.rows_text}")
    return lines


def _gate(verdict: Verdict, probe: Probe) -> tuple[AccessEvent | None, list[Leaf]]:
    event = probe.first("gate")
    if event is None:
        if isinstance(probe.view.get_access(), Unscoped):
            names = ", ".join(type(p).__name__ for p in probe.view.get_permissions()) or "none"
            verdict.add("gate", f"no Karni gate (Unscoped): permission_classes decide: {names}")
        else:
            verdict.add(
                "gate", f"not reached: the request ended with {_status(probe.status)} first"
            )
        verdict.data["gate"] = None
        return None, []
    allowed = bool(event.data.get("allowed"))
    explained = _explain(event, probe.request)
    if explained is None:
        verdict.data["gate"] = {"allowed": allowed, "predicate": None, "leaves": []}
        return event, []
    _consistent(verdict, "gate", explained, allowed)
    leaves = explain_leaves(explained, user=probe.user, model=probe.resource.model)
    head = "passed" if allowed else "refused"
    lines = [f"{head}: {predicate_text(explained.predicate)}"]
    for leaf in leaves:
        lines.append(
            f"  {'yes' if leaf.explained.allows else 'no':<3}  "
            f"{predicate_text(leaf.predicate)}: {leaf.gate}"
        )
    verdict.add("gate", *lines)
    verdict.data["gate"] = {
        "allowed": allowed,
        "predicate": predicate_text(explained.predicate),
        "leaves": [leaf.as_dict() for leaf in leaves],
    }
    return event, leaves


def _grants(verdict: Verdict, probe: Probe, trees: Iterable[Explained | None]) -> None:
    seen: set[str] = set()
    lines: list[str] = []
    data: list[dict[str, Any]] = []
    any_can = False
    for tree in trees:
        if tree is None:
            continue
        for leaf in tree.leaves():
            if not isinstance(leaf.predicate, Can):
                continue
            any_can = True
            for line in grant_lines(leaf, user=probe.user, model=probe.resource.model):
                if line.key in seen:
                    continue
                seen.add(line.key)
                lines.extend(line.text)
                data.append(line.data)
    if not any_can:
        if getattr(probe.user, "is_authenticated", False) and isinstance(
            probe.view.get_access(), Access
        ):
            _insert_after_gate(
                verdict,
                Section(
                    "grants",
                    [
                        "not consulted: this access names no Granted()/Can(), so KARNI_ROLES "
                        "grants do not apply here (roles count only through HasRole)"
                    ],
                ),
            )
        verdict.data["grants"] = []
        return
    _insert_after_gate(verdict, Section("grants", lines))
    verdict.data["grants"] = data


def _insert_after_gate(verdict: Verdict, section: Section) -> None:
    """Grants read best right after the gate (and veto) that consulted them."""
    labels = [s.label for s in verdict.sections]
    index = max((i for i, label in enumerate(labels) if label in ("gate", "veto")), default=-1)
    verdict.sections.insert(index + 1, section)


def _veto(verdict: Verdict, probe: Probe) -> AccessEvent | None:
    from karni.vetoes import vetoes

    event = probe.first("veto")
    if event is None:
        return None
    name = str(event.data["name"])
    fn = vetoes().get(name)
    location = callable_location(fn) if fn is not None else None
    at = f"  {location}" if location else ""
    verdict.add("veto", f"{name}{at}", f"refused: {event.data['reason']}")
    verdict.data["veto"] = {
        "name": name,
        "reason": event.data["reason"],
        "where": location.as_dict() if location else None,
    }
    return event


# rows


@dataclass
class _RowState:
    row: Model | None
    state: str  # invalid | missing | scoped-out | base | present
    detail: str = ""
    scope: Any = None


def _row_state(resource: Resource, pk: Any, view: Any) -> _RowState:
    from karni.scopes import registry

    model = resource.model
    try:
        raw = model._base_manager.filter(pk=pk).first()
    except (ValidationError, ValueError, TypeError):
        kind = type(model._meta.pk).__name__
        return _RowState(None, "invalid", f"{pk!r} is not a valid {model.__name__} key ({kind})")
    if raw is None:
        return _RowState(None, "missing", f"no {model.__name__} has primary key {pk}")
    queryset = model._base_manager.filter(pk=pk)
    for scope in registry.for_model(model):
        queryset = scope.filter(queryset)
        if not queryset.exists():
            detail = scope.name
            if scope.name == "soft_delete":
                detail = f"soft_delete (deleted_at={getattr(raw, 'deleted_at', None)})"
            return _RowState(raw, "scoped-out", detail, scope)
    if view is not None and not view.base_queryset().filter(pk=pk).exists():
        return _RowState(raw, "base")
    return _RowState(raw, "present")


def _base_location(view: Any) -> Location | None:
    """Where the viewset narrows its own queryset (``queryset =``, ``get_queryset``), or None."""
    for klass in type(view).__mro__:
        if klass is BaseViewSet:
            return None
        if "get_queryset" in vars(klass):
            return callable_location(vars(klass)["get_queryset"])
        if "queryset" in vars(klass) and vars(klass)["queryset"] is not None:
            return attribute_location(klass, "queryset")
    return None


def _base(view: Any, model: type[Model]) -> QuerySet[Any]:
    try:
        base: QuerySet[Any] = view.base_queryset()
    except Exception:  # noqa: BLE001 - fall back to the default manager for the explanation
        base = model._default_manager.all()
    return base


def _where_lines(verdict: Verdict, *given: tuple[str, Location | None]) -> None:
    entries: list[tuple[str, Location]] = []
    for what, at in given:
        if at is not None and all(str(at) != str(seen) for _w, seen in entries):
            entries.append((what, at))
    lines = [f"{at}  {what}" for what, at in entries]
    verdict.add("where", *lines)
    verdict.data["where"] = [{"what": what, **at.as_dict()} for what, at in entries]


def _enforcement(name: str) -> Location | None:
    target = {
        "gate": AccessPermission.has_permission,
        "object": AccessPermission.has_object_permission,
        "read": BaseViewSet.read_scope,
        "lookup": BaseViewSet.get_object,
    }[name]
    return callable_location(target)  # type: ignore[arg-type]


def _leaf_where(
    leaves: Iterable[Leaf], *, only: bool | None = None
) -> list[tuple[str, Location | None]]:
    found: list[tuple[str, Location | None]] = []
    for leaf in leaves:
        if only is not None and leaf.matches_row is not only and leaf.explained.allows is not only:
            continue
        entry = (predicate_text(leaf.predicate), leaf.location)
        if entry not in found:
            found.append(entry)
    return found


def _access_label(probe: Probe) -> str:
    return f"{type(probe.view).__name__}.access"


def _change_access(probe: Probe, slot: str, location: Location | None) -> str:
    at = f" ({location})" if location else ""
    return f"change {type(probe.view).__name__}.access.{slot}{at}"


def _read_section(
    verdict: Verdict, probe: Probe, row: Model | None, *, label: str = "read"
) -> tuple[AccessEvent | None, Explained | None, list[Leaf]]:
    event = probe.first("read_scope")
    if event is None:
        return None, None, []
    if event.data.get("predicate") is None:
        verdict.add(label, "no row policy (Unscoped): every row the model scopes leave")
        return event, None, []
    explained = _explain(event, probe.request)
    if explained is None:  # a predicate was recorded, so this cannot happen; stay silent
        return event, None, []
    _consistent(
        verdict, "read scope", explained, event.data["rows"], exempt=bool(event.data.get("exempt"))
    )
    base = _base(probe.view, probe.resource.model)
    leaves = explain_leaves(
        explained, user=probe.user, model=probe.resource.model, row=row, base=base
    )
    rows = event.data["rows"]
    lines = [f"access.read = {predicate_text(explained.predicate)}"]
    if event.data.get("exempt"):
        reason = getattr(probe.view, "scope_exempt_reason", "")
        lines.append(
            f"  scope_exempt = True ({reason!r}): the read filter is off, the gate decides"
        )
    lines.extend(_leaf_rows(leaves, show_row=row is not None))
    if event.data.get("hook"):
        at = callable_location(type(probe.view).filter_queryset_for_user)
        lines.append(
            f"  then filter_queryset_for_user(){f' ({at})' if at else ''} narrows it further"
        )
    verdict.add(label, *lines)
    verdict.data[label] = {
        "predicate": predicate_text(explained.predicate),
        "rows": _rows_repr(rows, probe.user),
        "exempt": bool(event.data.get("exempt")),
        "hook": bool(event.data.get("hook")),
        "leaves": [leaf.as_dict() for leaf in leaves],
    }
    return event, explained, leaves


def _rows_repr(rows: Any, user: Any) -> str:
    from karni.why.source import q_text

    return q_text(rows, you=user)


def _row_section(verdict: Verdict, probe: Probe, row: Model, leaves: Iterable[Leaf]) -> None:
    values: dict[str, str] = {}
    for leaf in leaves:
        values.update(leaf.row_values)
    shown = "  ".join(f"{k}={v}" for k, v in values.items())
    verdict.add("row", f"{type(row).__name__} {row.pk}" + (f"  {shown}" if shown else ""))
    verdict.data["row"] = {"pk": str(row.pk), "exists": True, "values": values}


# the verdicts


def explain_row(
    resource: Resource | str,
    pk: Any,
    user: Any,
    action: str | None = None,
    *,
    method: str | None = None,
    query: dict[str, list[str]] | None = None,
) -> Verdict:
    """Why ``user`` gets what they get for ``action`` (default ``view``) on row ``pk``."""
    found = resolve_resource(resource) if isinstance(resource, str) else resource
    spec = resolve_action(found, action, method=method)
    use_pk = pk if (spec.detail or spec.name == "list") else None
    probe = run_probe(found, spec, user, pk=use_pk, query=query)
    kind = "row" if use_pk is not None else "action"
    return _build(Verdict(kind=kind), probe)


def _build(verdict: Verdict, probe: Probe) -> Verdict:
    _who(verdict, probe.user)
    _request_line(verdict, probe)
    access_at = _access(verdict, probe)
    gate_event, gate_leaves = _gate(verdict, probe)
    veto = _veto(verdict, probe)
    verdict.status = probe.status
    verdict.data["result"] = {"status": probe.status, "detail": _jsonable(probe.detail)}
    model = probe.resource.model
    view = probe.view
    slot = _slot(probe)

    if probe.uncaught is not None:
        verdict.outcome = "error"
        verdict.summary = (
            f"500 — {type(view).__name__}.{probe.action.name} raised "
            f"{type(probe.uncaught).__name__}: {probe.uncaught}"
        )
        verdict.fix("fix the error the message names; `karni explain <code>` explains a Karni code")
        _grants(verdict, probe, [])
        _where_lines(verdict, (_access_label(probe), access_at))
        return verdict

    gate_tree = _explain(gate_event, probe.request) if gate_event else None
    if gate_event is not None and not gate_event.data.get("allowed"):
        return _gate_refused(verdict, probe, gate_event, gate_leaves, gate_tree, access_at, slot)
    if veto is not None:
        verdict.outcome = "veto"
        verdict.summary = (
            f"{_status(probe.status)} — the access declaration admits the request, but the veto "
            f"{veto.data['name']!r} refuses it (AccessPermission consults karni.vetoes after the "
            "predicate)"
        )
        fn_at = (verdict.data.get("veto") or {}).get("where")
        verdict.fix(
            "end the condition the veto checks (for karni_impersonation: stop impersonating — "
            "the action is blocked for the whole session)",
            f"unregister_veto({veto.data['name']!r}) or narrow the veto"
            + (f" ({fn_at['file']}:{fn_at['line']})" if fn_at else ""),
        )
        _grants(verdict, probe, [gate_tree])
        _where_lines(
            verdict,
            (_access_label(probe), access_at),
            ("AccessPermission (vetoes)", _enforcement("gate")),
        )
        return verdict
    if probe.status in (401, 403) and probe.first("object") is None:
        return _extra_permission(verdict, probe, access_at, gate_tree)

    row_state = _row_state(probe.resource, probe.pk, view) if probe.pk is not None else None
    row = row_state.row if row_state is not None else None
    read_event: AccessEvent | None = None
    read_tree: Explained | None = None
    read_leaves: list[Leaf] = []
    if probe.pk is not None and row_state is not None and row_state.state == "present":
        read_event, read_tree, read_leaves = _read_section(verdict, probe, row)
    elif probe.pk is None and probe.first("read_scope") is not None and probe.action.name == "list":
        read_event, read_tree, read_leaves = _read_section(verdict, probe, None)

    object_event = probe.first("object")
    write_tree = _explain(object_event, probe.request) if object_event else None
    write_leaves: list[Leaf] = []
    if write_tree is not None and object_event is not None:
        _consistent(
            verdict,
            "write",
            write_tree,
            object_event.data["rows"],
            exempt=bool(getattr(view, "scope_exempt", False)),
        )
        write_leaves = explain_leaves(
            write_tree,
            user=probe.user,
            model=model,
            row=object_event.data.get("row") or probe.instance,
            base=_base(view, model),
        )
        label = "write" if slot == "write" else "action" if slot == "action" else slot
        lines = [
            f"access.{slot} = {predicate_text(write_tree.predicate)}"
            if slot != "action"
            else f"@action(access={predicate_text(write_tree.predicate)})"
        ]
        lines.extend(_leaf_rows(write_leaves, show_row=True))
        verdict.add(label, *lines)
        verdict.data["write"] = {
            "predicate": predicate_text(write_tree.predicate),
            "allowed": bool(object_event.data.get("allowed")),
            "leaves": [leaf.as_dict() for leaf in write_leaves],
        }
    if row is not None and row_state is not None and row_state.state == "present":
        _row_section(verdict, probe, row, [*read_leaves, *write_leaves])
    _grants(verdict, probe, [gate_tree, read_tree, write_tree])

    if probe.status == 404:
        return _not_found(verdict, probe, row_state, read_event, read_leaves, access_at)
    if object_event is not None and not object_event.data.get("allowed"):
        verdict.outcome = "write-refused"
        verdict.summary = (
            f"{_status(probe.status)} — the row is readable (found through access.read) but "
            f"access.{slot} refuses it (AccessPermission.has_object_permission)"
        )
        for leaf in write_leaves:
            if not leaf.matches_row:
                verdict.fix(*leaf.fixes)
        verdict.fix(_change_access(probe, slot if slot != "action" else "write", access_at))
        _where_lines(
            verdict,
            (f"{type(view).__name__}.access", access_at),
            *_leaf_where(write_leaves),
            ("AccessPermission.has_object_permission (the refusal)", _enforcement("object")),
        )
        return verdict
    if probe.status in (401, 403):
        return _object_extra(verdict, probe, access_at)
    if 200 <= probe.status < 300:
        return _allowed(verdict, probe, row, read_leaves, write_leaves, access_at)
    verdict.outcome = "other"
    verdict.summary = f"{_status(probe.status)}: {_detail_text(probe.detail)}"
    _where_lines(verdict, (_access_label(probe), access_at))
    return verdict


def _gate_refused(
    verdict: Verdict,
    probe: Probe,
    event: AccessEvent,
    leaves: list[Leaf],
    tree: Explained | None,
    access_at: Location | None,
    slot: str,
) -> Verdict:
    view = probe.view
    _grants(verdict, probe, [tree])
    if event.data.get("declaration") is None:
        verdict.outcome = "no-access"
        verdict.summary = (
            f"{_status(probe.status)} — {type(view).__name__} declares no access, so every request "
            "is refused (E101)"
        )
        verdict.fix(
            f"declare access on {type(view).__name__}: `access = Granted()` (the roles' grants) "
            "or `Access(read=..., write=...)`"
        )
        _where_lines(verdict, (type(view).__name__, class_location(type(view))))
        return verdict
    signed_in = bool(getattr(probe.user, "is_authenticated", False))
    verdict.outcome = "unauthenticated" if probe.status == 401 or not signed_in else "gate"
    shown = predicate_text(tree.predicate) if tree is not None else "the predicate"
    where = "AccessPermission.has_permission, before any query"
    if not signed_in:
        verdict.summary = (
            f"{_status(probe.status)} — not signed in, and {shown} admits only signed-in users "
            f"({where})"
        )
    else:
        target = f"access.{slot}" if slot != "action" else "the @action's access"
        verdict.summary = (
            f"{_status(probe.status)} — {target} = {shown} refuses this user ({where})"
        )
    for leaf in leaves:
        if not leaf.explained.allows:
            verdict.fix(*leaf.fixes)
    verdict.fix(
        _change_access(probe, slot if slot in ("read", "write", "create") else "write", access_at)
    )
    _where_lines(
        verdict,
        (f"{type(view).__name__}.access", access_at),
        *_leaf_where(leaves),
        ("AccessPermission.has_permission (the refusal)", _enforcement("gate")),
    )
    return verdict


def _extra_permission(
    verdict: Verdict, probe: Probe, access_at: Location | None, gate_tree: Explained | None
) -> Verdict:
    """The gate and the vetoes passed, yet a 401/403: a ``permission_classes`` entry refused."""
    view = probe.view
    _grants(verdict, probe, [gate_tree])
    refusing = []
    for permission in view.get_permissions():
        if isinstance(permission, AccessPermission):
            continue
        try:
            allowed = permission.has_permission(probe.request, view)
        except Exception:  # noqa: BLE001 - a raising permission refuses
            allowed = False
        if not allowed:
            refusing.append(permission)
    verdict.outcome = "permission-class"
    unscoped = isinstance(view.get_access(), Unscoped)
    if refusing:
        names = ", ".join(type(p).__name__ for p in refusing)
        before = "" if unscoped else "the access gate passed, then "
        verdict.summary = (
            f"{_status(probe.status)} — {before}permission_classes refused: "
            f"{names} ({_detail_text(probe.detail)})"
        )
        entries = [(type(p).__name__, class_location(type(p))) for p in refusing]
        if unscoped:
            verdict.fix(
                f"satisfy {names} (sign in, for IsAuthenticated)",
                f"set {type(view).__name__}.permission_classes, or declare an access instead "
                "of Unscoped",
            )
        else:
            verdict.fix(
                f"satisfy {names}, or drop it from {type(view).__name__}.permission_classes "
                "(they are ANDed after the access gate and can only narrow it)"
            )
        _where_lines(verdict, (_access_label(probe), access_at), *entries)
    else:
        verdict.summary = f"{_status(probe.status)} — {_detail_text(probe.detail)}"
        _where_lines(verdict, (_access_label(probe), access_at))
    return verdict


def _object_extra(verdict: Verdict, probe: Probe, access_at: Location | None) -> Verdict:
    view = probe.view
    verdict.outcome = "object-permission"
    verdict.summary = (
        f"{_status(probe.status)} — access admits the row, then an object permission refused it "
        f"({_detail_text(probe.detail)})"
    )
    names = ", ".join(cls.__name__ for cls in getattr(view, "object_permission_classes", ()) or ())
    if names:
        verdict.fix(
            f"{type(view).__name__}.object_permission_classes ({names}) is deprecated: express the "
            "rule in access instead"
        )
    _where_lines(
        verdict,
        (_access_label(probe), access_at),
        ("check_object_permissions", class_location(type(view))),
    )
    return verdict


def _not_found(
    verdict: Verdict,
    probe: Probe,
    state: _RowState | None,
    read_event: AccessEvent | None,
    read_leaves: list[Leaf],
    access_at: Location | None,
) -> Verdict:
    view = probe.view
    model = probe.resource.model
    name = type(view).__name__
    if state is None:
        verdict.outcome = "not-found"
        verdict.summary = f"404 — {_detail_text(probe.detail)}"
        return verdict
    if state.state in ("invalid", "missing"):
        verdict.outcome = state.state
        verdict.add("row", state.detail + " (the table has no such row, deleted or not)")
        verdict.data["row"] = {"pk": str(probe.pk), "exists": False}
        verdict.summary = f"404 Not Found — {state.detail}: there is nothing to see"
        verdict.fix(f"use an id the API lists: karni why-empty {probe.resource.prefix} --as <user>")
        return verdict
    row = state.row
    if row is None:  # only "invalid" and "missing" carry no row, handled above
        verdict.outcome = "not-found"
        verdict.summary = f"404 — {_detail_text(probe.detail)}"
        return verdict
    if state.state == "scoped-out":
        verdict.outcome = "model-scope"
        verdict.add(
            "row", f"{model.__name__} {row.pk} exists, hidden by the model scope {state.detail}"
        )
        verdict.data["row"] = {"pk": str(row.pk), "exists": True, "scope": state.detail}
        verdict.summary = (
            f"404 Not Found — the {state.detail.split(' ')[0]} model scope hides the row from "
            "every query; no access rule can reach it"
        )
        if state.detail.startswith("soft_delete"):
            verdict.fix(
                f"restore it: {model.__name__}.objects.without('soft_delete', reason='...')"
                f".filter(pk='{row.pk}').restore(), or the admin's restore action"
            )
        _where_lines(
            verdict,
            (f"the {state.scope.name} model scope", class_location(type(state.scope))),
            ("the model's default manager", class_location(type(model._default_manager))),
        )
        return verdict
    if state.state == "base":
        verdict.outcome = "base-queryset"
        verdict.add("row", f"{model.__name__} {row.pk} exists")
        verdict.data["row"] = {"pk": str(row.pk), "exists": True}
        at = _base_location(view)
        verdict.summary = (
            f"404 Not Found — {name}'s own queryset/get_queryset() leaves the row out, before "
            "access applies"
        )
        verdict.fix(f"widen {name}'s queryset/get_queryset(){f' ({at})' if at else ''}")
        _where_lines(verdict, (f"{name} base queryset", at))
        return verdict
    rows = read_event.data["rows"] if read_event is not None else True
    base = _base(view, model)
    in_scope = bool(apply_rows(base.filter(pk=row.pk), rows).exists()) if rows is not True else True
    if not in_scope:
        verdict.outcome = "filtered"
        verdict.summary = (
            "404 Not Found — the row exists but access.read filters it out at queryset level "
            "(BaseViewSet.get_queryset): the API answers 404, never 403, so it does not confirm "
            "the row exists"
        )
        for leaf in read_leaves:
            if leaf.matches_row is False:
                verdict.fix(*leaf.fixes)
        verdict.fix(_change_access(probe, "read", access_at))
        _where_lines(
            verdict,
            (f"{name}.access", access_at),
            *_leaf_where(read_leaves),
            ("BaseViewSet.read_scope (the filter)", _enforcement("read")),
        )
        return verdict
    scoped = apply_rows(base, rows)
    if read_event is not None and read_event.data.get("hook"):
        hooked = view.filter_queryset_for_user(scoped)
        if not hooked.filter(pk=row.pk).exists():
            at = callable_location(type(view).filter_queryset_for_user)
            verdict.outcome = "filter-hook"
            verdict.summary = (
                f"404 Not Found — access.read admits the row, then "
                f"{name}.filter_queryset_for_user() removes it"
            )
            verdict.fix(f"change {name}.filter_queryset_for_user(){f' ({at})' if at else ''}")
            _where_lines(verdict, (f"{name}.filter_queryset_for_user", at))
            return verdict
        scoped = hooked
    if not view.filter_queryset(scoped).filter(pk=row.pk).exists():
        verdict.outcome = "filters"
        verdict.summary = (
            "404 Not Found — the row is readable, but this request's filter parameters "
            f"({_query_text(probe.query)}) exclude it (the detail lookup applies "
            "filter_queryset too)"
        )
        verdict.fix("drop the query parameters from the request")
        _where_lines(verdict, ("GenericAPIView.get_object", _enforcement("lookup")))
        return verdict
    verdict.outcome = "not-found"
    verdict.summary = (
        f"404 Not Found — the row is readable; the action's own code answered 404: "
        f"{_detail_text(probe.detail)}"
    )
    handler = getattr(type(view), probe.action.name, None)
    _where_lines(
        verdict, (f"{name}.{probe.action.name}", callable_location(handler) if handler else None)
    )
    return verdict


def _allowed(
    verdict: Verdict,
    probe: Probe,
    row: Model | None,
    read_leaves: list[Leaf],
    write_leaves: list[Leaf],
    access_at: Location | None,
) -> Verdict:
    name = type(probe.view).__name__
    action = probe.action.name
    admitting = [leaf for leaf in (write_leaves or read_leaves) if leaf.matches_row]
    via = ", ".join(predicate_text(leaf.predicate) for leaf in admitting)
    if action == "list" and probe.pk is not None:
        if probe.in_list:
            verdict.outcome = "listed"
            admitted = f", admitted by {via}" if via else ""
            verdict.summary = f"200 — the row is in the list ({probe.count} row(s)){admitted}"
        else:
            verdict.outcome = "not-listed"
            verdict.summary = (
                f"200 — the list answers ({probe.count} row(s)) but this row is not in it"
            )
        _where_lines(verdict, (f"{name}.access", access_at), *_leaf_where(read_leaves, only=True))
        return verdict
    verdict.outcome = "allowed"
    if action in ("retrieve",) or (probe.action.detail and _slot(probe) == "read"):
        what = "readable"
    elif probe.action.method in ("GET", "HEAD"):
        what = "allowed"
    else:
        what = "admitted by the access layer"
    reason = f" through {via}" if via else ""
    tail = ""
    if probe.action.method not in ("GET", "HEAD"):
        tail = "; the handler still validates the body (a 400 there is not an access decision)"
    verdict.summary = f"{_status(probe.status)} — {what}{reason}{tail}"
    _where_lines(
        verdict, (f"{name}.access", access_at), *_leaf_where(write_leaves or read_leaves, only=True)
    )
    return verdict


def _query_text(query: dict[str, list[str]]) -> str:
    return "&".join(f"{k}={v}" for k, values in query.items() for v in values) or "none"


def _detail_text(detail: Any) -> str:
    if isinstance(detail, dict) and "detail" in detail:
        return str(detail["detail"])
    if isinstance(detail, dict):
        return "; ".join(
            f"{key}: {' '.join(str(item) for item in value) if isinstance(value, list) else value}"
            for key, value in detail.items()
        )
    return str(detail)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


# fields


def explain_field(resource: Resource | str, name: str, user: Any) -> Verdict:
    """Whether ``user`` sees and may change field ``name`` of ``resource``, and why."""
    from karni.accounts.visibility import allowed_roles, hidden_fields, protected_fields
    from karni.meta import field_roles

    found = resolve_resource(resource) if isinstance(resource, str) else resource
    model = found.model
    listing = run_probe(found, resolve_action(found, "list"), user)
    view = listing.view
    verdict = Verdict(kind="field")
    _who(verdict, user)
    access_at = _access(verdict, listing)
    serializer_class = view.get_serializer_class()
    everyone = serializer_class(context={}).fields
    mine = view.get_serializer().fields
    model_fields = {f.name for f in model._meta.get_fields()}
    if name not in everyone and name not in model_fields:
        raise WhyError(
            f"{found.prefix} has no field {name!r}. Its API fields: {', '.join(everyone)}.",
            code="E905",
        )
    explicit = view.serializer_class is not None
    serializer_at = class_location(serializer_class) if explicit else None
    source = (
        f"{serializer_class.__name__}{f' ({serializer_at})' if serializer_at else ''}"
        if explicit
        else "the generated serializer"
    )
    verdict.add(
        "field", f"{model.__name__}.{name} on {found.prefix} ({type(view).__name__}, {source})"
    )
    gate_lines = [
        f"list: {_status(listing.status)}"
        + ("" if listing.allowed else " — the user cannot read this resource at all"),
    ]
    update = resolve_action(found, "partial_update") if _routes(found, "partial_update") else None
    if update is not None:
        writing = run_probe(found, update, user)
        gate_lines.append(
            "update: gate "
            + ("passes" if writing.allowed else f"refuses ({_status(writing.status)})")
        )
    verdict.add("rows", "; ".join(gate_lines))

    rules = field_roles(model)
    rule = rules.get(name)
    roles = verdict.data.get("roles", [])
    readable = name in mine and not mine[name].write_only
    writable = name in mine and not mine[name].read_only
    reason = ""
    where: list[tuple[str, Location | None]] = [(f"{type(view).__name__}.access", access_at)]
    karni_at = (
        attribute_location(model.Karni, "field_roles") if hasattr(model, "Karni") and rule else None
    )
    api_meta = getattr(model, "APIMeta", None)

    def meta_at(attr: str) -> Location | None:
        return (
            attribute_location(api_meta, attr)
            if api_meta is not None and attr in vars(api_meta)
            else None
        )

    if name not in everyone:
        verdict.outcome = "absent"
        if explicit:
            reason = f"{serializer_class.__name__} does not declare it"
            where.append((serializer_class.__name__, serializer_at))
            verdict.fix(f"add {name!r} to {serializer_class.__name__}.Meta.fields")
        elif api_meta is not None and getattr(api_meta, "fields", None) is not None:
            reason = f"{model.__name__}.APIMeta.fields does not list it"
            where.append((f"{model.__name__}.APIMeta.fields", meta_at("fields")))
            verdict.fix(f"add {name!r} to {model.__name__}.APIMeta.fields")
        elif api_meta is not None and name in (getattr(api_meta, "exclude", None) or ()):
            reason = f"{model.__name__}.APIMeta.exclude lists it"
            where.append((f"{model.__name__}.APIMeta.exclude", meta_at("exclude")))
            verdict.fix(f"remove {name!r} from {model.__name__}.APIMeta.exclude")
        elif name in ("password", "deleted_at"):
            reason = "generated serializers never expose password or deleted_at"
        else:
            reason = (
                "not a forward field: generated serializers expose concrete fields and forward "
                "many-to-manys (expand reverse relations through expandable_fields)"
            )
        verdict.summary = f"absent for everyone — {reason}"
    elif name not in mine and rule is None:
        # Only field_roles removes a field per user; anything else is a hand-written get_fields().
        verdict.outcome = "hidden"
        reason = f"{serializer_class.__name__}.get_fields() leaves it out for this user"
        verdict.summary = f"hidden — {reason}"
        where.append((serializer_class.__name__, class_location(serializer_class)))
    elif name not in mine and rule is not None:
        verdict.outcome = "hidden"
        reason = (
            f"{model.__name__}.Karni.field_roles[{name!r}]: read needs one of "
            f"{', '.join(rule.read)}; {display_user(user)} holds {', '.join(roles) or 'no role'}"
        )
        where.append((f"{model.__name__}.Karni.field_roles", karni_at))
        verdict.summary = (
            f"hidden — {name} is absent from every response, ?expand= and the schema for this "
            "user (never null), and is ignored in filters, ordering and search"
        )
        verdict.fix(
            f"give {display_user(user)} one of the roles {', '.join(rule.read)}",
            f"add a role {display_user(user)} holds to field_roles[{name!r}]['read'] in "
            f"{model.__name__}.Karni{f' ({karni_at})' if karni_at else ''}",
        )
    elif mine[name].write_only:
        verdict.outcome = "write-only"
        if not everyone[name].write_only and rule is not None:
            reason = (
                f"field_roles[{name!r}]: may write (one of {', '.join(rule.write)}) but not read "
                f"(needs one of {', '.join(rule.read)})"
            )
            where.append((f"{model.__name__}.Karni.field_roles", karni_at))
        else:
            reason = f"{model.__name__}.APIMeta.write_only lists it"
            where.append((f"{model.__name__}.APIMeta.write_only", meta_at("write_only")))
        verdict.summary = f"write-only — accepted on writes, never in responses ({reason})"
    elif mine[name].read_only:
        verdict.outcome = "read-only"
        if not everyone[name].read_only and rule is not None:
            reason = (
                f"{model.__name__}.Karni.field_roles[{name!r}]: write needs one of "
                f"{', '.join(rule.write)}; {display_user(user)} holds "
                f"{', '.join(roles) or 'no role'}"
            )
            where.append((f"{model.__name__}.Karni.field_roles", karni_at))
            verdict.fix(
                f"give {display_user(user)} one of the roles {', '.join(rule.write)}",
                f"add a role {display_user(user)} holds to field_roles[{name!r}]['write'] in "
                f"{model.__name__}.Karni{f' ({karni_at})' if karni_at else ''}",
            )
            verdict.notes.append(
                f'sending it anyway is a 400: "Only roles {", ".join(allowed_roles(model, name))} '
                f'may change {name}."'
            )
        else:
            reason, at, fix = _read_only_reason(view, model, name, explicit, serializer_class)
            where.append(at)
            verdict.fix(fix)
        verdict.summary = f"read-only — shown, never written through the API ({reason})"
    else:
        verdict.outcome = "visible"
        verdict.summary = (
            f"visible and writable — {name} is read and written like any field for this user"
        )
        if rule is not None:
            reason = (
                f"field_roles[{name!r}] admits {display_user(user)}: read {', '.join(rule.read)}, "
                f"write {', '.join(rule.write)}"
            )
    if reason:
        verdict.add("rule", reason)
    hidden = hidden_fields(model, user)
    protected = protected_fields(model, user)
    verdict.data["field"] = {
        "name": name,
        "model": model._meta.label,
        "readable": readable,
        "writable": writable,
        "in_schema": name in mine,
        "reason": reason,
        "field_roles": {"read": list(rule.read), "write": list(rule.write)} if rule else None,
        "hidden_for_user": sorted(hidden),
        "protected_for_user": sorted(protected),
    }
    _where_lines(verdict, *where)
    return verdict


def _routes(resource: Resource, action: str) -> bool:
    try:
        resolve_action(resource, action)
    except WhyError:
        return False
    return True


def _read_only_reason(
    view: Any, model: type[Model], name: str, explicit: bool, serializer_class: type[Any]
) -> tuple[str, tuple[str, Location | None], str]:
    from karni.api.serializers import USER_FORCED_READ_ONLY

    api_meta = getattr(model, "APIMeta", None)
    if explicit:
        at = class_location(serializer_class)
        return (
            f"{serializer_class.__name__} marks it read-only",
            (serializer_class.__name__, at),
            f"change {serializer_class.__name__}{f' ({at})' if at else ''}",
        )
    if api_meta is not None and name in (getattr(api_meta, "read_only", None) or ()):
        at = attribute_location(api_meta, "read_only")
        return (
            f"{model.__name__}.APIMeta.read_only lists it",
            (f"{model.__name__}.APIMeta.read_only", at),
            f"remove {name!r} from {model.__name__}.APIMeta.read_only{f' ({at})' if at else ''} "
            "if clients may set it",
        )
    if name in view.get_owner_fields():
        at = attribute_location(type(view), "access")
        return (
            f"the owner field of {type(view).__name__}.access: stamped from request.user on "
            "create, never from the body",
            (f"{type(view).__name__}.access", at),
            "nothing to fix: owners are stamped server-side (override perform_create to choose "
            "another owner)",
        )
    if name in {
        model._meta.pk.name,
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_at",
    }:
        return (
            "the key, timestamps and audit stamps are always read-only",
            ("karni.api.serializers", class_location(type(view))),
            "nothing to fix: Karni sets these fields itself",
        )
    if name in USER_FORCED_READ_ONLY and model is get_user_model():
        return (
            "a user model's permission flags are read-only in generated serializers",
            ("karni.api.serializers.USER_FORCED_READ_ONLY", None),
            "change them in the admin, or write an explicit serializer_class for that endpoint",
        )
    return (
        "the generated serializer marks it read-only (a nested ?expand= relation, or a property)",
        ("karni.api.serializers", None),
        "write through the relation's primary key instead",
    )


# lists


def explain_list(
    resource: Resource | str, user: Any, *, query: dict[str, list[str]] | None = None
) -> Verdict:
    """Why ``user``'s list of ``resource`` is empty (or how each step narrows it)."""
    from karni.scopes import registry

    found = resolve_resource(resource) if isinstance(resource, str) else resource
    spec = resolve_action(found, "list")
    probe = run_probe(found, spec, user, query=query)
    verdict = Verdict(kind="list")
    _who(verdict, user)
    _request_line(verdict, probe)
    access_at = _access(verdict, probe)
    gate_event, gate_leaves = _gate(verdict, probe)
    veto = _veto(verdict, probe)
    verdict.status = probe.status
    if not probe.allowed:
        gate_tree = _explain(gate_event, probe.request) if gate_event else None
        if probe.status == 400:
            verdict.outcome = "bad-request"
            verdict.summary = (
                f"400 Bad Request — the access layer admits the list, but the query parameters are "
                f"invalid: {_detail_text(probe.detail)}"
            )
            verdict.fix("pass a value the filter accepts, or drop the parameter")
            return verdict
        if gate_event is not None and not gate_event.data.get("allowed"):
            _gate_refused(verdict, probe, gate_event, gate_leaves, gate_tree, access_at, "read")
        elif veto is not None:
            verdict.outcome = "veto"
            verdict.summary = (
                f"{_status(probe.status)} — the veto {veto.data['name']!r} refuses the list"
            )
        else:
            _extra_permission(verdict, probe, access_at, gate_tree)
        verdict.summary = f"not empty, refused: {verdict.summary}"
        return verdict

    view = probe.view
    model = found.model
    steps: list[dict[str, Any]] = []

    def step(label: str, count: int, detail: str = "", where: Location | None = None) -> None:
        before = steps[-1]["rows"] if steps else count
        steps.append(
            {
                "step": label,
                "rows": count,
                "removed": before - count,
                "detail": detail,
                "where": where.as_dict() if where else None,
            }
        )

    queryset = model._base_manager.all()
    step(f"table {model._meta.db_table}", queryset.count(), "every row, soft-deleted included")
    for scope in registry.for_model(model):
        queryset = scope.filter(queryset)
        step(f"model scope {scope.name}", queryset.count(), "", class_location(type(scope)))
    base = _base(view, model)
    base_at = _base_location(view)
    base_detail = (
        "queryset / get_queryset()"
        if base_at is not None
        else f"{model.__name__}._default_manager.all(): no queryset or get_queryset() declared"
    )
    step(f"{type(view).__name__} base queryset", base.count(), base_detail, base_at)
    read_event = probe.first("read_scope")
    rows = read_event.data["rows"] if read_event is not None else True
    read_tree = _explain(read_event, probe.request) if read_event is not None else None
    leaf_counts: list[tuple[Leaf, int]] = []
    if read_tree is not None:
        _consistent(
            verdict,
            "read scope",
            read_tree,
            rows,
            exempt=bool(read_event and read_event.data.get("exempt")),
        )
        leaves = explain_leaves(read_tree, user=user, model=model)
        for leaf in leaves:
            leaf_counts.append((leaf, apply_rows(base, leaf.explained.rows).count()))
    scoped = apply_rows(base, rows)
    read_label = (
        f"access.read = {predicate_text(read_tree.predicate)}"
        if read_tree is not None
        else "no row policy (Unscoped)"
    )
    if read_event is not None and read_event.data.get("exempt"):
        read_label += " (scope_exempt: off)"
    step(read_label, scoped.count(), "", access_at)
    if read_event is not None and read_event.data.get("hook"):
        scoped = view.filter_queryset_for_user(scoped)
        step(
            "filter_queryset_for_user()",
            scoped.count(),
            "",
            callable_location(type(view).filter_queryset_for_user),
        )
    if type(view).filter_queryset is not GenericAPIView.filter_queryset:
        scoped = view.filter_queryset(scoped)
        step(
            "filter_queryset() (overridden)",
            scoped.count(),
            _query_text(probe.query),
            callable_location(type(view).filter_queryset),
        )
    else:
        for backend in list(view.filter_backends):
            scoped = backend().filter_queryset(probe.request, scoped, view)
            step(
                f"{backend.__name__}",
                scoped.count(),
                _query_text(probe.query) if probe.query else "no parameters",
            )
    final = probe.count if probe.count is not None else scoped.count()
    if steps[-1]["rows"] != final:
        verdict.notes.append(
            f"the steps end at {steps[-1]['rows']} row(s) but the API's list has {final}: an "
            "override changes rows in a way this breakdown cannot split; the API's count is the "
            "answer"
        )

    width = max(4, *(len(str(s["rows"])) for s in steps))
    gone = max(7, *(len(str(s["removed"])) + 1 for s in steps))
    lines = [f"{'rows':>{width}}  {'removed':>{gone}}  step"]
    for entry in steps:
        removed = f"-{entry['removed']}" if entry["removed"] else ""
        at = entry["where"]
        loc = f"  ({at['file']}:{at['line']})" if at else ""
        detail = f"  [{entry['detail']}]" if entry["detail"] else ""
        lines.append(f"{entry['rows']:>{width}}  {removed:>{gone}}  {entry['step']}{detail}{loc}")
        if entry["step"] == read_label:
            for leaf, count in leaf_counts:
                lines.append(
                    f"{'':>{width}}  {'':>{gone}}    {count:>{width}} rows: "
                    f"{predicate_text(leaf.predicate)}: {leaf.rows_text}"
                )
    verdict.add("steps", *lines)
    _grants(verdict, probe, [read_tree])
    verdict.data["steps"] = steps
    verdict.data["read"] = {
        "predicate": predicate_text(read_tree.predicate) if read_tree else None,
        "leaves": [{**leaf.as_dict(), "rows_count": count} for leaf, count in leaf_counts],
    }
    verdict.data["count"] = final

    if final:
        verdict.outcome = "not-empty"
        verdict.summary = f"not empty: the list has {final} row(s) for this user"
        _where_lines(verdict, (f"{type(view).__name__}.access", access_at))
        return verdict
    verdict.outcome = "empty"
    culprit = next((s for s in steps if s["rows"] == 0), steps[0])
    if culprit is steps[0]:
        verdict.summary = f"empty: the table {model._meta.db_table} has no rows at all"
        verdict.fix("create rows: karni seed, the API, or the admin")
    elif culprit["step"].startswith("model scope"):
        verdict.summary = (
            f"empty: the {culprit['step']} removes the last {culprit['removed']} row(s)"
        )
        verdict.fix(
            "every remaining row is soft-deleted: restore rows (the admin's restore action, or "
            f"{model.__name__}.objects.without('soft_delete', reason='...').restore())"
        )
    elif culprit["step"] == read_label:
        verdict.summary = (
            f"empty: access.read removes all {culprit['removed']} row(s) the viewset's queryset "
            f"holds — none is readable by {display_user(user)}"
        )
        for leaf, _count in leaf_counts:
            verdict.fix(*leaf.fixes)
        verdict.fix(_change_access(probe, "read", access_at))
    elif culprit["step"].endswith("base queryset"):
        verdict.summary = f"empty: {type(view).__name__}'s queryset/get_queryset() selects no row"
        verdict.fix(
            f"widen {type(view).__name__}'s queryset/get_queryset()"
            + (f" ({base_at})" if base_at else "")
        )
    elif culprit["step"] == "filter_queryset_for_user()":
        verdict.summary = (
            f"empty: {type(view).__name__}.filter_queryset_for_user() removes the last "
            f"{culprit['removed']} row(s)"
        )
        verdict.fix(f"change {type(view).__name__}.filter_queryset_for_user()")
    else:
        verdict.summary = (
            f"empty: the request's parameters ({_query_text(probe.query)}) match none of the "
            f"{culprit['removed']} readable row(s) ({culprit['step']})"
        )
        verdict.fix("drop or change the query parameters (a page's params={...}, a default filter)")
    _where_lines(
        verdict,
        (f"{type(view).__name__}.access", access_at),
        ("BaseViewSet.read_scope", _enforcement("read")),
    )
    return verdict


# request records


def explain_record(request_id: str, *, asked: int | None = None) -> Verdict:
    """Replay a recorded request's access decision (``karni why 403 <request-id>``)."""
    from django.urls import Resolver404, resolve

    record = load_record(request_id)
    method = str(record["method"]).upper()
    path = str(record["path"])
    resource: Resource | None = None
    if record.get("resource"):
        try:
            resource = resolve_resource(str(record["resource"]))
        except WhyError:
            resource = None
    action_name = record.get("action")
    kwargs: dict[str, Any] = dict(record.get("view_kwargs") or {})
    if resource is None or not action_name:
        try:
            match = resolve(path)
        except Resolver404:
            match = None
        cls = getattr(getattr(match, "func", None), "cls", None)
        if match is not None and cls is not None:
            basename = getattr(match.func, "initkwargs", {}).get("basename")
            resource = resource or next(
                (
                    r
                    for r in resources()
                    if r.viewset is cls and (basename is None or r.basename == basename)
                ),
                None,
            )
            action_name = action_name or getattr(match.func, "actions", {}).get(method.lower())
            kwargs = kwargs or dict(match.kwargs)
    if resource is None:
        raise WhyError(
            f"The recorded request {method} {path} (view {record.get('view')!r}) is not served "
            "by a routed Karni BaseViewSet, so its refusal is not an access-layer decision: read "
            "that view's permission_classes. karni why explains BaseViewSet routes.",
            code="E907",
        )
    spec = resolve_action(resource, str(action_name or "retrieve"), method=method)
    user: Any = AnonymousUser()
    recorded_user = record.get("user")
    if isinstance(recorded_user, dict) and recorded_user.get("id") is not None:
        user = get_user_model()._default_manager.filter(pk=recorded_user["id"]).first()
        if user is None:
            raise WhyError(
                f"The recorded request was made by user {recorded_user.get('id')} "
                f"({recorded_user.get('email') or recorded_user.get('username')}), who no longer "
                "exists, so the decision cannot be replayed. Ask about the row for another user: "
                "karni why <resource>/<id> --as <user>.",
                code="E902",
            )
    pk = kwargs.get(spec.lookup)
    query = {
        str(k): [str(v) for v in (vs if isinstance(vs, list) else [vs])]
        for k, vs in (record.get("query") or {}).items()
    }
    probe = run_probe(
        resource,
        spec,
        user,
        pk=pk if (spec.detail or spec.name == "list") else None,
        query=query,
        path=path,
    )
    verdict = _build(Verdict(kind="record"), probe)
    recorded = int(record["status"])
    code = record.get("error_code")
    header = [
        f"{record['request_id']} at {record.get('at', '?')}: {method} {path} → {_status(recorded)}"
        + (f" (error_code {code})" if code else "")
    ]
    if asked is not None and asked != recorded:
        header.append(f"you asked about a {asked}; the recorded request got {recorded}")
    same = probe.status == recorded
    header.append(
        f"replayed now with the same user, method, path and query: {_status(probe.status)}"
        + (" (the same answer)" if same else f" — differs from the recorded {recorded}")
    )
    verdict.sections.insert(0, Section("record", header))
    if not same:
        cause = "roles, grants or the row changed since"
        if code and str(code).upper().startswith("IMP"):
            cause = (
                f"the recorded refusal ({code}) came from an impersonated session; a replay has no "
                "impersonation, so the veto that refused it does not fire now"
            )
        elif recorded in (401, 403) and probe.allowed:
            cause += ", or a veto refused it on request state a replay does not have"
        verdict.notes.insert(
            0, f"the answer changed: {cause}. The explanation is for the answer now."
        )
    if 200 <= recorded < 300:
        verdict.notes.insert(0, f"the recorded request was not refused ({_status(recorded)})")
    verdict.data["record"] = {
        "request_id": record["request_id"],
        "at": record.get("at"),
        "status": recorded,
        "error_code": code,
        "replayed_status": probe.status,
        "reproduced": same,
    }
    return verdict


def is_field_target(resource: Resource, name: str) -> bool:
    """Whether ``name`` names a field of ``resource``'s model (for target parsing)."""
    try:
        resource.model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True
