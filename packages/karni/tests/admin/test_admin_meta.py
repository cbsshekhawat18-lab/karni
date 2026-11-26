"""``AdminMeta`` reaches every Karni admin: the derived one and a subclass registered by hand.

A ``KarniModelAdmin`` subclass takes each option of the model's ``AdminMeta``,
and the inlines other models declare with ``inline_on``, unless the subclass
sets that option itself. ``AdminMeta.mixins`` adds behaviour to the derived
admin without registering one by hand. The derived admins keep exactly the
configuration the builder of 0.6.0 gave them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from karni.admin import KarniModelAdmin, autodiscover
from karni.admin.base import KarniAdminMixin, build_model_admin
from karni.admin.derive import admin_meta
from karni.admin.inlines import build_inline, collect_inlines
from karni.admin.soft_delete import SoftDeleteAdminMixin
from karni.errorcodes import KarniError
from karni.models import SoftDeleteModel
from tests.adminapp.admin import HandmadeAdmin
from tests.adminapp.admin_mixins import StampMixin
from tests.adminapp.models import (
    Gizmo,
    Handmade,
    HandmadePart,
    KitchenSink,
    Note,
    Stamped,
    Tuned,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_site() -> admin.AdminSite:
    return admin.AdminSite(name="karni-admin-meta")


def bare(model: type[Any], site: admin.AdminSite) -> Any:
    """What K103 tells a project to write: a ``KarniModelAdmin`` subclass that sets nothing."""
    return type("X", (KarniModelAdmin,), {"__module__": __name__})(model, site)


def inline_specs(model_admin: Any) -> list[tuple[str, str | None]]:
    return [(inline.model._meta.label, inline.fk_name) for inline in model_admin.inlines]


class TestASubclassHonoursAdminMeta:
    """The reproduction of the report: ``type("X", (KarniModelAdmin,), {})(Model, site)``."""

    def test_the_columns_filters_search_and_order(self, scratch_site: admin.AdminSite) -> None:
        model_admin = bare(Tuned, scratch_site)
        assert list(model_admin.list_display) == ["number", "total"]
        assert list(model_admin.list_filter) == ["status"]
        assert list(model_admin.search_fields) == ["number"]
        assert model_admin.date_hierarchy == "issued_at"
        assert list(model_admin.ordering) == ["-issued_at"]
        assert list(model_admin.readonly_fields)[-1] == "total"  # AdminMeta.read_only

    def test_extra_and_per_page(self, scratch_site: admin.AdminSite) -> None:
        assert bare(Tuned, scratch_site).list_per_page == 10  # AdminMeta.extra
        assert bare(Gizmo, scratch_site).list_per_page == 15  # AdminMeta.per_page

    def test_the_inlines_children_declare(self, scratch_site: admin.AdminSite) -> None:
        assert inline_specs(bare(KitchenSink, scratch_site)) == [("adminapp.Note", "kitchen")]

    def test_a_hand_registered_admin_has_them(self, site: admin.AdminSite) -> None:
        model_admin = site._registry[Handmade]
        assert type(model_admin) is HandmadeAdmin
        assert list(model_admin.list_display) == ["name", "code"]
        assert list(model_admin.search_fields) == ["name"]
        assert model_admin.list_per_page == 50
        assert model_admin.save_on_top is True  # its own attribute
        assert inline_specs(model_admin) == [("adminapp.HandmadePart", "handmade")]

    @pytest.mark.parametrize("model", [Tuned, Gizmo, KitchenSink, Note, Handmade])
    def test_a_bare_subclass_is_configured_as_the_derived_admin(
        self, model: type[Any], scratch_site: admin.AdminSite
    ) -> None:
        derived = configuration(build_model_admin(model)(model, scratch_site))
        soft = (SoftDeleteAdminMixin,) if issubclass(model, SoftDeleteModel) else ()
        own = configuration(type("X", (*soft, KarniModelAdmin), {})(model, scratch_site))
        for found in (derived, own):
            found.pop("_karni_autocomplete_managed")  # the second pass is for derived admins
        assert own == derived

    @pytest.mark.django_db
    def test_the_hand_registered_change_form_renders_the_inline(self, admin_client: Client) -> None:
        made = Handmade.objects.create(name="Lamp")
        HandmadePart.objects.create(handmade=made, label="Shade")
        page = admin_client.get(reverse("admin:adminapp_handmade_change", args=[made.pk]))
        assert page.status_code == 200
        assert b"Shade" in page.content


class TestWhatTheSubclassSetsWins:
    def test_its_own_attributes(self, scratch_site: admin.AdminSite) -> None:
        own = type(
            "Own",
            (KarniModelAdmin,),
            {"list_display": ["number"], "list_per_page": 40, "inlines": []},
        )
        model_admin = own(Tuned, scratch_site)
        assert list(model_admin.list_display) == ["number"]
        assert model_admin.list_per_page == 40
        assert list(model_admin.list_filter) == ["status"]  # not set by the class: AdminMeta's
        assert inline_specs(own(KitchenSink, scratch_site)) == []

    def test_a_mixin_of_its_own(self, scratch_site: admin.AdminSite) -> None:
        mixin = type("Columns", (), {"list_display": ["total"]})
        model_admin = type("Mixed", (mixin, KarniModelAdmin), {})(Tuned, scratch_site)
        assert list(model_admin.list_display) == ["total"]
        assert list(model_admin.search_fields) == ["number"]

    def test_a_parent_admin_class(self, scratch_site: admin.AdminSite) -> None:
        parent = type("Parent", (KarniModelAdmin,), {"search_fields": ["total"]})
        child = type("Child", (parent,), {})
        assert list(child(Tuned, scratch_site).search_fields) == ["total"]

    def test_the_hooks_turn_it_off(self, scratch_site: admin.AdminSite) -> None:
        class Plain(KarniModelAdmin):
            @classmethod
            def admin_meta_options(cls, model: type[Any]) -> dict[str, Any]:
                return {}

            @classmethod
            def derive_inlines(cls, model: type[Any]) -> list[Any]:
                return []

        tuned = Plain(Tuned, scratch_site)
        assert "status" in tuned.list_display  # derived, not AdminMeta's two columns
        assert tuned.list_per_page == 25
        assert list(Plain(KitchenSink, scratch_site).inlines) == []

    def test_extra_functions_become_methods(
        self, monkeypatch: pytest.MonkeyPatch, scratch_site: admin.AdminSite
    ) -> None:
        def shout(self: Any) -> str:
            return f"{self.model.__name__}!"

        meta = type("AdminMeta", (), {"extra": {"shout": shout, "list_per_page": 12}})
        monkeypatch.setattr(Gizmo, "AdminMeta", meta)
        for model_admin in (
            bare(Gizmo, scratch_site),
            build_model_admin(Gizmo)(Gizmo, scratch_site),
        ):
            assert model_admin.shout() == "Gizmo!"
            assert model_admin.list_per_page == 12

    def test_extra_formfield_overrides_join_djangos(
        self, monkeypatch: pytest.MonkeyPatch, scratch_site: admin.AdminSite
    ) -> None:
        from django import forms
        from django.db import models

        overrides = {models.CharField: {"widget": forms.Textarea}}
        monkeypatch.setattr(
            Gizmo, "AdminMeta", type("AdminMeta", (), {"extra": {"formfield_overrides": overrides}})
        )
        model_admin = bare(Gizmo, scratch_site)
        assert model_admin.formfield_overrides[models.CharField]["widget"] is forms.Textarea
        assert models.DateTimeField in model_admin.formfield_overrides  # Django's defaults kept

    def test_extra_inlines_beat_the_declared_ones(
        self, monkeypatch: pytest.MonkeyPatch, scratch_site: admin.AdminSite
    ) -> None:
        """What karni.admin.inlines always said: ``inlines`` in ``AdminMeta.extra`` wins."""
        own = build_inline(Note, "kitchen")
        meta = type("AdminMeta", (), {"extra": {"inlines": [own]}})
        monkeypatch.setattr(KitchenSink, "AdminMeta", meta, raising=False)
        assert build_model_admin(KitchenSink)(KitchenSink, scratch_site).inlines == [own]
        assert bare(KitchenSink, scratch_site).inlines == [own]

    def test_inlines_passed_to_the_builder_win(self, scratch_site: admin.AdminSite) -> None:
        assert build_model_admin(KitchenSink, inlines=[])(KitchenSink, scratch_site).inlines == []


class TestEitherDiscoveryFirst:
    def test_registered_before_karnis_discovery(self, scratch_site: admin.AdminSite) -> None:
        scratch_site.register(Handmade, type("H", (KarniModelAdmin,), {}))
        autodiscover(site=scratch_site)
        model_admin = scratch_site._registry[Handmade]
        assert not getattr(type(model_admin), "_karni_generated", False)
        assert list(model_admin.list_display) == ["name", "code"]
        assert inline_specs(model_admin) == [("adminapp.HandmadePart", "handmade")]

    def test_registered_after_karnis_discovery(self, scratch_site: admin.AdminSite) -> None:
        autodiscover(site=scratch_site)
        scratch_site.unregister(KitchenSink)
        scratch_site.register(KitchenSink, type("K", (KarniModelAdmin,), {}))
        assert inline_specs(scratch_site._registry[KitchenSink]) == [("adminapp.Note", "kitchen")]

    def test_karni_admin_listed_before_django_contrib_admin(self) -> None:
        """Django's discovery runs first anyway, so explicit registrations still win."""
        code = (
            "import json, django; django.setup()\n"
            "from django.contrib import admin\n"
            "from tests.adminapp.models import Explicit, Handmade\n"
            "made = admin.site._registry[Handmade]\n"
            "print(json.dumps({'explicit': type(admin.site._registry[Explicit]).__name__,"
            " 'handmade': type(made).__name__, 'columns': list(made.list_display),"
            " 'inlines': [i.model.__name__ for i in made.inlines],"
            " 'generated': getattr(type(made), '_karni_generated', False)}))\n"
        )
        path = os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p)
        env = {**os.environ, "KARNI_TEST_ADMIN_FIRST": "1", "PYTHONPATH": path}
        env.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        found = json.loads(result.stdout.strip().splitlines()[-1])
        assert found == {
            "explicit": "ExplicitAdmin",
            "handmade": "HandmadeAdmin",
            "columns": ["name", "code"],
            "inlines": ["HandmadePart"],
            "generated": False,
        }


class TestMixins:
    def test_the_mixin_is_in_front_of_the_derived_class(self, site: admin.AdminSite) -> None:
        cls = type(site._registry[Stamped])
        assert cls._karni_generated
        assert cls.__mro__[1] is StampMixin
        assert cls.__mro__.index(StampMixin) < cls.__mro__.index(SoftDeleteAdminMixin)
        assert cls.__mro__.index(SoftDeleteAdminMixin) < cls.__mro__.index(KarniModelAdmin)
        assert site._registry[Stamped].change_form_after_template == "adminapp/stamp_after.html"

    def test_a_class_works_as_well_as_a_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Gizmo, "AdminMeta", type("AdminMeta", (), {"mixins": [StampMixin]}))
        assert StampMixin in build_model_admin(Gizmo).__mro__

    @pytest.mark.django_db
    def test_the_reporters_use(self, admin_client: Client, admin_user: Any) -> None:
        """A block under the form, a value in its context, and a write of the mixin's own."""
        add = admin_client.get(reverse("admin:adminapp_stamped_add"))
        assert add.status_code == 200
        assert b'<p class="stamp-note">Rows saved here are stamped.</p>' in add.content
        saved = admin_client.post(reverse("admin:adminapp_stamped_add"), {"title": "Invoice"})
        assert saved.status_code == 302, saved.content[:500]
        assert Stamped.objects.get().stamp == f"stamped by {admin_user}"

    @pytest.mark.parametrize(
        ("mixins", "says"),
        [
            (["tests.adminapp.nowhere.Mixin"], "cannot be imported"),
            (["tests.adminapp.admin_mixins.Missing"], "cannot be imported"),
            (["tests.adminapp.admin_mixins.__doc__"], "is not a class"),
            ([42], "is not a class"),
            ("tests.adminapp.admin_mixins.StampMixin", "a list"),
        ],
    )
    def test_a_bad_mixin_is_a_coded_error(
        self, monkeypatch: pytest.MonkeyPatch, mixins: Any, says: str
    ) -> None:
        monkeypatch.setattr(Gizmo, "AdminMeta", type("AdminMeta", (), {"mixins": mixins}))
        with pytest.raises(KarniError) as raised:
            build_model_admin(Gizmo)
        assert raised.value.code == "E306"
        assert "adminapp.Gizmo" in raised.value.message
        assert says in raised.value.message

    def test_mixins_that_cannot_be_combined_are_a_coded_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = type("First", (admin.ModelAdmin,), {})
        second = type("Second", (first,), {})
        monkeypatch.setattr(Gizmo, "AdminMeta", type("AdminMeta", (), {"mixins": [first, second]}))
        with pytest.raises(KarniError) as raised:
            build_model_admin(Gizmo)
        assert raised.value.code == "E306"


# -- the derived admins keep the configuration the 0.6.0 builder gave them ---------------

_PASSTHROUGH_0_6_0 = ("list_display", "list_filter", "search_fields", "date_hierarchy", "ordering")


def build_model_admin_0_6_0(
    model: type[Any], *, inlines: Sequence[type[Any]] = ()
) -> type[KarniModelAdmin]:
    """``karni.admin.base.build_model_admin`` as Karni 0.6.0 shipped it, word for word."""
    meta = admin_meta(model)
    attrs: dict[str, Any] = {"__module__": __name__, "_karni_generated": True}
    explicit: set[str] = set()
    if meta is not None:
        for name in _PASSTHROUGH_0_6_0:
            if hasattr(meta, name):
                attrs[name] = getattr(meta, name)
                explicit.add(name)
        if hasattr(meta, "read_only"):
            attrs["karni_read_only"] = tuple(meta.read_only or ())
        per_page = getattr(meta, "per_page", None)
        if per_page is not None:
            attrs["list_per_page"] = int(per_page)
        choices = getattr(meta, "per_page_choices", None)
        if choices:
            attrs["karni_per_page_choices"] = tuple(int(n) for n in choices)
        extra = dict(getattr(meta, "extra", None) or {})
        attrs.update(extra)
        explicit.update(extra)
    if inlines:
        attrs["inlines"] = list(inlines)
    attrs["_karni_explicit"] = frozenset(explicit)
    attrs["_karni_autocomplete_managed"] = "autocomplete_fields" not in attrs
    bases: tuple[type, ...]
    if issubclass(model, SoftDeleteModel):
        bases = (SoftDeleteAdminMixin, KarniModelAdmin)
    else:
        bases = (KarniModelAdmin,)
    return type(f"{model.__name__}Admin", bases, attrs)


_COMPARED = (
    "list_display",
    "list_filter",
    "search_fields",
    "date_hierarchy",
    "ordering",
    "readonly_fields",
    "karni_read_only",
    "list_per_page",
    "karni_per_page_choices",
    "list_select_related",
    "actions",
    "fieldsets",
    "form",
    "karni_help",
    "_karni_autocomplete_managed",
)


def configuration(model_admin: Any) -> dict[str, Any]:
    found = {name: _plain(getattr(model_admin, name, None)) for name in _COMPARED}
    found["inlines"] = [
        (i.model._meta.label, i.fk_name, [b.__name__ for b in i.__mro__[1:4]])
        for i in model_admin.inlines
    ]
    found["formfield_overrides"] = sorted(repr(k) for k in model_admin.formfield_overrides)
    found["soft_delete"] = isinstance(model_admin, SoftDeleteAdminMixin)
    found["karni"] = isinstance(model_admin, KarniAdminMixin)
    meta = admin_meta(model_admin.model)
    for name in dict(getattr(meta, "extra", None) or {}):
        found[f"extra:{name}"] = _plain(getattr(model_admin, name, None))
    return found


def _plain(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    return value


def test_every_derived_admin_is_configured_as_in_0_6_0(site: admin.AdminSite) -> None:
    """The builder no longer copies AdminMeta into the class, and nothing else changed.

    Every model ``autodiscover()`` derives an admin for in this suite (Karni's own apps
    and every test app, the full ``AdminMeta`` surface of ``Tuned`` among them), built the
    0.6.0 way and the new way on a scratch site, has the same options.
    """
    inline_map = collect_inlines(django_apps.get_models())
    compared = 0
    for model, registered in site._registry.items():
        if not getattr(type(registered), "_karni_generated", False):
            continue
        old_inlines = [build_inline(child, fk) for child, fk in inline_map.get(model, [])]
        scratch = admin.AdminSite(name=f"karni-0-6-0-{model._meta.label_lower}")
        old = build_model_admin_0_6_0(model, inlines=old_inlines)(model, scratch)
        new = build_model_admin(model)(model, scratch)
        assert configuration(new) == configuration(old), model._meta.label
        assert configuration(registered) == configuration(old), model._meta.label
        compared += 1
    assert compared > 50
    assert get_user_model() in site._registry  # registered by karni.accounts, not compared
