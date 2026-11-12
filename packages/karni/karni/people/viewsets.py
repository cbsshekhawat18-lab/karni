"""Experimental. The people API: ``/api/people/``, ``/api/organisations/`` and their rows.

Every endpoint answers the roles granted on it (``Granted()``): an admin with
``"*"`` sees everyone, a ``crm-rep`` granted ``people.person:view`` sees
who the grant's scope reaches, and a signed-in person granted ``own``
reaches the person linked to their account (``Person.Karni.owner_field`` is
``user``). A part shows person data inside its own records through its own
access rules, never through these endpoints.

Besides the CRUD of a :class:`~karni.api.viewsets.BaseViewSet`:

* ``GET/PATCH /api/people/me/``: the signed-in user's own person (names,
  phone, time zone, language), for every signed-in user; linked on the
  first call when the account's email is verified.
* ``?facts=orders,total_spent`` (or ``all``) adds ``facts`` to each person;
  ``?orders__gte=3`` filters and ``?ordering=-total_spent`` orders on a
  fact, in SQL. ``GET /api/people/facts/`` lists the registered facts.
* ``GET /api/people/{id}/merge-plan/?drop=<id>`` previews and
  ``POST /api/people/{id}/merge/ {"drop": "<id>"}`` merges (409 ``E250`` to
  ``E252``), with the explicit ``people.person:merge`` permission; the same
  pair exists on organisations.
* ``GET /api/people/duplicates/`` lists the groups of possible duplicates
  (``people.person:merge``).
* ``POST /api/people/{id}/erase/`` erases a person (``people.person:erase``).

``merge`` and ``erase`` are explicit actions (``Karni.explicit_actions``):
only a grant that names them reaches them, so ``"*"`` does not.

Override / escape hatch: ``KARNI_PEOPLE_API = False`` leaves these viewsets
out of the router; subclass them and route your own.
"""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal
from typing import Any, ClassVar

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import Access, Authenticated, BaseViewSet, Can, Granted
from karni.people import registry, services
from karni.people.models import Address, Membership, Organisation, Person

__all__ = [
    "AddressViewSet",
    "MembershipViewSet",
    "OrganisationViewSet",
    "PersonViewSet",
]

#: Routed by autodiscovery unless ``KARNI_PEOPLE_API`` is False (read at import).
_ROUTED = bool(getattr(settings, "KARNI_PEOPLE_API", True))
#: Lookups a fact filter takes: ``?orders__gte=3``.
FACT_LOOKUPS: tuple[str, ...] = ("gt", "gte", "lt", "lte", "isnull")
#: Person fields ``?ordering=`` may name next to a fact.
ORDERABLE: tuple[str, ...] = (
    "display_name",
    "given_name",
    "family_name",
    "email",
    "created_at",
    "updated_at",
)


class MergeInputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. The body of a merge: the record merged into this one."""

    drop = serializers.UUIDField(help_text="The id of the record merged into this one.")


class MoveSerializer(serializers.Serializer):  # type: ignore[type-arg]
    model = serializers.CharField()
    field = serializers.CharField()
    kind = serializers.CharField()
    rows = serializers.IntegerField()


class RefusalSerializer(serializers.Serializer):  # type: ignore[type-arg]
    code = serializers.CharField()
    message = serializers.CharField()


class MergePlanSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. What a merge moves, fills and refuses (``people.merge_plan``)."""

    keep = serializers.CharField()
    drop = serializers.CharField()
    allowed = serializers.BooleanField()
    moves = MoveSerializer(many=True)
    refusals = RefusalSerializer(many=True)
    fills = serializers.DictField(child=serializers.JSONField())


class FactSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One registered person fact."""

    name = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.CharField()
    source = serializers.CharField()
    description = serializers.CharField()


class DuplicateGroupSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. People one duplicate rule groups together, oldest first."""

    rule = serializers.CharField()
    people = serializers.ListField(child=serializers.CharField())


class PersonSelfSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    """Experimental. What a person reads and changes of their own row (``/api/people/me/``)."""

    class Meta:
        model = Person
        fields: ClassVar[list[str]] = [
            "id",
            "given_name",
            "family_name",
            "display_name",
            "email",
            "phone",
            "time_zone",
            "language",
            "organisation",
        ]
        read_only_fields: ClassVar[list[str]] = ["id", "email", "organisation"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """The person's own rules (``Person.clean``), as a 400."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        probe = copy.copy(self.instance)
        for name, value in attrs.items():
            setattr(probe, name, value)
        try:
            probe.clean()
        except DjangoValidationError as exc:
            raise ValidationError(serializers.as_serializer_error(exc)) from exc
        return attrs


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


class _MergeActions:
    """What ``merge-plan`` and ``merge`` do on a viewset of people or organisations.

    Both records are looked up through the viewset's read scope, so a merge
    reaches only records the caller may read.
    """

    def _pair(self, drop: Any) -> tuple[Any, Any]:
        keep = self.get_object()  # type: ignore[attr-defined]
        if not drop:
            raise ValidationError({"drop": ["Name the record to merge into this one: drop=<id>."]})
        found = self.get_queryset().filter(pk=drop).first()  # type: ignore[attr-defined]
        if found is None:
            raise NotFound(f"No record {drop} that you may read.")
        return keep, found

    def plan_response(self, request: Request) -> Response:
        keep, drop = self._pair(request.query_params.get("drop"))
        return Response(services.merge_plan(keep, drop).as_dict())

    def merge_response(self, request: Request) -> Response:
        body = MergeInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        keep, drop = self._pair(body.validated_data["drop"])
        return Response(services.merge(keep, drop).as_dict())


class PersonViewSet(_MergeActions, BaseViewSet):
    """Experimental. ``/api/people/``: the people, with facts, merge, duplicates and erase."""

    model = Person
    route = "people"
    auto_register = _ROUTED
    access = Access(read=Granted(), write=Granted())
    search_fields: ClassVar[list[str]] = ["display_name", "email", "phone"]

    _MERGE = Can("people.person:merge")

    def get_owner_fields(self) -> tuple[str, ...]:
        """Nothing is stamped: ``user`` is linked only through a verified email."""
        return ()

    # facts

    def _fact_names(self) -> tuple[list[str], list[str]]:
        """``(shown, used)``: the facts the response shows, and every fact the query needs."""
        request = getattr(self, "request", None)
        if request is None:
            return [], []
        registered = registry.facts()
        raw = str(request.query_params.get("facts", "") or "").strip()
        shown = list(registered) if raw == "all" else [n.strip() for n in raw.split(",") if n]
        unknown = [name for name in shown if name not in registered]
        if unknown:
            raise ValidationError(
                {
                    "facts": [
                        f"No person fact named {', '.join(unknown)}. Facts: "
                        f"{', '.join(registered) or 'none'}. (E257)"
                    ]
                }
            )
        used = list(shown)
        for key in request.query_params:
            name = key.split("__", 1)[0]
            if name in registered and name not in used:
                used.append(name)
        for term in str(request.query_params.get("ordering", "") or "").split(","):
            name = term.strip().lstrip("-")
            if name in registered and name not in used:
                used.append(name)
        return shown, used

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        if getattr(self, "action", None) not in ("list", "retrieve"):
            return queryset
        _shown, used = self._fact_names()
        if not used:
            return queryset
        queryset = registry.annotate_facts(queryset, used)
        registered = registry.facts()
        for key, value in self.request.query_params.items():
            name, _, lookup = key.partition("__")
            if name not in registered:
                continue
            if lookup and lookup not in FACT_LOOKUPS:
                raise ValidationError(
                    {key: [f"A fact filter takes {', '.join(FACT_LOOKUPS)} or nothing (equals)."]}
                )
            if lookup == "isnull":
                queryset = queryset.filter(**{key: value.lower() in ("1", "true", "yes")})
            else:
                queryset = queryset.filter(**{key: value})
        return queryset

    def filter_queryset(self, queryset: Any) -> Any:
        queryset = super().filter_queryset(queryset)
        request = getattr(self, "request", None)
        if request is None or getattr(self, "action", None) != "list":
            return queryset
        registered = registry.facts()
        terms = [t.strip() for t in str(request.query_params.get("ordering", "") or "").split(",")]
        if not any(term.lstrip("-") in registered for term in terms if term):
            return queryset
        ordering = [
            term for term in terms if term and term.lstrip("-") in (*registered, *ORDERABLE)
        ]
        return queryset.order_by(*ordering, "pk")

    def get_serializer_class(self) -> Any:
        base = super().get_serializer_class()
        if getattr(self, "action", None) not in ("list", "retrieve"):
            return base
        shown, _used = self._fact_names()
        if not shown:
            return base
        names = tuple(shown)

        class WithFacts(base):  # type: ignore[valid-type,misc]
            facts = serializers.SerializerMethodField()

            class Meta(base.Meta):  # type: ignore[name-defined,misc]
                fields: ClassVar[list[str]] = [*base.Meta.fields, "facts"]

            def get_facts(self, obj: Any) -> dict[str, Any]:
                return {name: _plain(getattr(obj, name, None)) for name in names}

        WithFacts.__name__ = base.__name__
        return WithFacts

    @extend_schema(responses={200: FactSerializer(many=True)})
    @action(detail=False, methods=["get"], pagination_class=None)
    def facts(self, request: Request) -> Response:
        """The person facts the installed parts contribute."""
        return Response([found.as_dict() for found in registry.facts().values()])

    # the signed-in person

    @extend_schema(request=PersonSelfSerializer, responses={200: PersonSelfSerializer})
    @action(detail=False, methods=["get", "patch"], access=Authenticated())
    def me(self, request: Request) -> Response:
        """The signed-in user's own person: read it, or change their names and preferences."""
        person = Person.objects.filter(user=request.user).first()
        if person is None:
            person = services.link_account(request.user, strict=False)
        if person is None:
            raise NotFound(
                "No person is linked to this account yet: it is linked once the account's "
                "email is verified."
            )
        if request.method == "PATCH":
            serializer = PersonSelfSerializer(person, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(PersonSelfSerializer(person).data)

    # merge, duplicates, erase

    @extend_schema(
        parameters=[OpenApiParameter("drop", OpenApiTypes.UUID, required=True)],
        responses={200: MergePlanSerializer},
        description="Preview merging `drop` into this person (people.person:merge).",
    )
    @action(detail=True, methods=["get"], url_path="merge-plan", access=_MERGE)
    def merge_plan(self, request: Request, pk: str | None = None) -> Response:
        return self.plan_response(request)

    @extend_schema(
        request=MergeInputSerializer,
        responses={200: MergePlanSerializer},
        description="Merge `drop` into this person (people.person:merge). 409 when refused.",
    )
    @action(detail=True, methods=["post"], access=_MERGE)
    def merge(self, request: Request, pk: str | None = None) -> Response:
        return self.merge_response(request)

    @extend_schema(
        parameters=[OpenApiParameter("rule", OpenApiTypes.STR, description="One rule only.")],
        responses={200: DuplicateGroupSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], access=_MERGE, pagination_class=None)
    def duplicates(self, request: Request) -> Response:
        """Groups of people that may be the same human, among the people you may read."""
        rule = request.query_params.get("rule")
        rules = [rule] if rule else None
        if rule and rule not in registry.duplicate_rules():
            raise ValidationError({"rule": [f"No duplicate rule {rule!r}. (E257)"]})
        visible = Person.objects.filter(pk__in=self.get_queryset().values("pk"))
        groups = services.duplicates(visible, rules=rules)
        return Response(
            [
                {"rule": group.rule, "people": [str(person.pk) for person in group.people]}
                for group in groups
            ]
        )

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"], access=Can("people.person:erase"))
    def erase(self, request: Request, pk: str | None = None) -> Response:
        """Erase this person's data, in every part that registered an erase hook."""
        services.erase(self.get_object())
        return Response(status=204)


class OrganisationViewSet(_MergeActions, BaseViewSet):
    """Experimental. ``/api/organisations/``: the organisations, with merge."""

    model = Organisation
    route = "organisations"
    auto_register = _ROUTED
    access = Access(read=Granted(), write=Granted())
    search_fields: ClassVar[list[str]] = ["name", "domain"]

    _MERGE = Can("people.organisation:merge")

    @extend_schema(
        parameters=[OpenApiParameter("drop", OpenApiTypes.UUID, required=True)],
        responses={200: MergePlanSerializer},
        description="Preview merging `drop` into this organisation (people.organisation:merge).",
    )
    @action(detail=True, methods=["get"], url_path="merge-plan", access=_MERGE)
    def merge_plan(self, request: Request, pk: str | None = None) -> Response:
        return self.plan_response(request)

    @extend_schema(
        request=MergeInputSerializer,
        responses={200: MergePlanSerializer},
        description="Merge `drop` into this organisation (people.organisation:merge).",
    )
    @action(detail=True, methods=["post"], access=_MERGE)
    def merge(self, request: Request, pk: str | None = None) -> Response:
        return self.merge_response(request)


class MembershipViewSet(BaseViewSet):
    """Experimental. ``/api/people-memberships/``: who belongs to which organisation."""

    model = Membership
    route = "people-memberships"
    auto_register = _ROUTED
    access = Access(read=Granted(), write=Granted())
    search_fields: ClassVar[list[str]] = ["title"]


class AddressViewSet(BaseViewSet):
    """Experimental. ``/api/people-addresses/``: addresses of people and organisations."""

    model = Address
    route = "people-addresses"
    auto_register = _ROUTED
    access = Access(read=Granted(), write=Granted())
    search_fields: ClassVar[list[str]] = ["label", "line1", "city", "postcode"]
