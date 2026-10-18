"""Each shipped codemod, and the data-driven Python codemods behind them.

For every codemod: fixture code before -> after, a second run changes
nothing, and code that merely looks similar (a local named ``all_objects``,
an unrelated class of the same name) is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from karni_cli.upgrades.codemod import load_codemod, source_files
from karni_cli.upgrades.python import PythonCodemod, RenameSetting, RenameSymbol


def _codemod(codemod_id: str) -> PythonCodemod:
    codemod = load_codemod(codemod_id)
    assert isinstance(codemod, PythonCodemod)
    return codemod


def _run(codemod: PythonCodemod, before: str, after: str, count: int) -> None:
    """``before`` becomes ``after`` with ``count`` rewrites, and a re-run is a no-op."""
    result, rewrites, sites = codemod.transform_source(before)
    assert result == after
    assert rewrites == count
    assert sites == []
    assert codemod.transform_source(result)[:2] == (result, 0), "not idempotent"


def _untouched(codemod: PythonCodemod, source: str) -> None:
    result, rewrites, _ = codemod.transform_source(source)
    assert (result, rewrites) == (source, 0)


# v1_0.all_objects_to_without

WITHOUT = 'objects.without("soft_delete", reason="<auto: migrated from all_objects>")'


def test_all_objects_on_class_like_receivers() -> None:
    before = """\
from library.models import Book


def report(model, shelf):
    everything = Book.all_objects.filter(shelf=shelf)  # comment kept
    count = (models.Book.all_objects).count()
    rows = model.all_objects.all()
    same = type(shelf).all_objects.first()
    return everything, count, rows, same


class BookAdmin:
    def get_queryset(self, request):
        return self.model.all_objects.all()
"""
    after = f"""\
from library.models import Book


def report(model, shelf):
    everything = Book.{WITHOUT}.filter(shelf=shelf)  # comment kept
    count = (models.Book.{WITHOUT}).count()
    rows = model.{WITHOUT}.all()
    same = type(shelf).{WITHOUT}.first()
    return everything, count, rows, same


class BookAdmin:
    def get_queryset(self, request):
        return self.model.{WITHOUT}.all()
"""
    _run(_codemod("v1_0.all_objects_to_without"), before, after, 5)


def test_all_objects_look_alikes_are_left_alone() -> None:
    _untouched(
        _codemod("v1_0.all_objects_to_without"),
        """\
def collect(report):
    all_objects = [1, 2]            # a local variable
    all_objects.append(3)
    report.all_objects = all_objects  # an attribute assignment
    print(report.all_objects)       # an instance attribute: not a manager
    return {"all_objects": all_objects}
""",
    )


def test_all_objects_needing_the_manager_is_reported_not_rewritten() -> None:
    source = "qs = Book.all_objects.get_queryset()\n"
    result, rewrites, sites = _codemod("v1_0.all_objects_to_without").transform_source(source)
    assert (result, rewrites) == (source, 0)
    assert [(s.line, "get_queryset" in s.note) for s in sites] == [(1, True)]


def test_a_project_defining_its_own_all_objects_gets_a_report(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text("class Ledger(Model):\n    all_objects = Manager()\n")
    (tmp_path / "views.py").write_text("rows = Ledger.all_objects.all()\n")
    outcome = _codemod("v1_0.all_objects_to_without").apply(tmp_path)
    assert outcome.files == {}
    assert (tmp_path / "views.py").read_text() == "rows = Ledger.all_objects.all()\n"
    (site,) = outcome.sites
    assert site.path == "views.py" and "models.py:2" in site.note


# v1_0.all_with_deleted_to_without / v1_0.deleted_only_to_without_dead


def test_all_with_deleted() -> None:
    _run(
        _codemod("v1_0.all_with_deleted_to_without"),
        "a = Book.objects.all_with_deleted()\nb = shelf.books.all_with_deleted().count()\n",
        'a = Book.objects.without("soft_delete", reason="<auto: migrated from all_with_deleted()>")\n'
        'b = shelf.books.without("soft_delete", reason="<auto: migrated from all_with_deleted()>")'
        ".count()\n",
        2,
    )


def test_deleted_only() -> None:
    _run(
        _codemod("v1_0.deleted_only_to_without_dead"),
        "dead = Book.objects.deleted_only().order_by('id')\n",
        'dead = Book.objects.without("soft_delete", reason="<auto: migrated from deleted_only()>")'
        ".dead().order_by('id')\n",
        1,
    )


@pytest.mark.parametrize(
    "codemod_id", ["v1_0.all_with_deleted_to_without", "v1_0.deleted_only_to_without_dead"]
)
def test_method_look_alikes_are_left_alone(codemod_id: str) -> None:
    _untouched(
        _codemod(codemod_id),
        """\
deleted_only = all_with_deleted = None    # names, not calls
archive.deleted_only(since=yesterday)     # takes arguments: not Karni's
archive.all_with_deleted(True)
deleted_only()                            # a function, not a method
""",
    )


def test_a_project_method_of_the_same_name_gets_a_report(tmp_path: Path) -> None:
    (tmp_path / "managers.py").write_text(
        "class Archive:\n    def deleted_only(self):\n        return []\n"
    )
    (tmp_path / "use.py").write_text("x = Archive().deleted_only()\n")
    outcome = _codemod("v1_0.deleted_only_to_without_dead").apply(tmp_path)
    assert outcome.files == {}
    assert [site.path for site in outcome.sites] == ["use.py"]


# v1_0.soft_delete_manager_mixin_to_scoped


def test_soft_delete_manager_mixin_every_spelling() -> None:
    before = """\
import karni.managers
from karni import managers
from karni.managers import BaseManager, SoftDeleteManagerMixin
from karni.managers import SoftDeleteManagerMixin as Mixin


class A(SoftDeleteManagerMixin, BaseManager):
    pass


class B(managers.SoftDeleteManagerMixin, Mixin):
    pass


C = karni.managers.SoftDeleteManagerMixin
DOTTED = "karni.managers.SoftDeleteManagerMixin"
"""
    after = """\
import karni.managers
from karni import managers
from karni.managers import BaseManager, ScopedManagerMixin
from karni.managers import ScopedManagerMixin as Mixin


class A(ScopedManagerMixin, BaseManager):
    pass


class B(managers.ScopedManagerMixin, Mixin):
    pass


C = karni.managers.ScopedManagerMixin
DOTTED = "karni.managers.ScopedManagerMixin"
"""
    # two imports, two bases, the module attribute, the dotted string; the alias stays
    _run(_codemod("v1_0.soft_delete_manager_mixin_to_scoped"), before, after, 6)


def test_soft_delete_manager_mixin_already_imported_new_name() -> None:
    _run(
        _codemod("v1_0.soft_delete_manager_mixin_to_scoped"),
        "from karni.managers import ScopedManagerMixin, SoftDeleteManagerMixin\n"
        "class A(SoftDeleteManagerMixin): ...\n",
        "from karni.managers import ScopedManagerMixin\nclass A(ScopedManagerMixin): ...\n",
        2,
    )


def test_soft_delete_manager_mixin_look_alikes_are_left_alone() -> None:
    _untouched(
        _codemod("v1_0.soft_delete_manager_mixin_to_scoped"),
        """\
from legacy.managers import SoftDeleteManagerMixin


class SoftDeleteManagerMixinTests:
    pass


class A(SoftDeleteManagerMixin):
    note = "karni.managers.SoftDeleteManagerMixin was renamed"
""",
    )


# the generic RenameSymbol / RenameSetting framework


def test_rename_symbol_across_modules_adds_the_new_import() -> None:
    codemod = RenameSymbol("karni.old.Thing", "karni.new.Thing2")
    _run(
        codemod,
        "from karni.old import Other, Thing\nimport karni.old\nx = Thing()\ny = karni.old.Thing\n",
        "from karni.old import Other\nimport karni.old\nimport karni.new\n"
        "from karni.new import Thing2\n\nx = Thing2()\ny = karni.new.Thing2\n",
        3,
    )


def test_rename_setting_where_it_is_defined_and_read(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.py").write_text("KARNI_OLD = 3\nKARNI_LIMIT = KARNI_OLD * 2\n")
    (tmp_path / "app.py").write_text(
        "from django.conf import settings\n"
        "from django.test import override_settings\n"
        "\n"
        "limit = settings.KARNI_OLD + getattr(settings, 'KARNI_OLD', 0)\n"
        'flag = hasattr(settings, "KARNI_OLD")\n'
        "\n"
        "@override_settings(KARNI_OLD=5)\n"
        "def test_it(settings):\n"
        "    settings.KARNI_OLD = 9\n"
        "    env = os.environ['KARNI_OLD']  # environment variables are not settings\n"
    )
    codemod = RenameSetting("KARNI_OLD", "KARNI_NEW")
    outcome = codemod.apply(tmp_path)
    assert (tmp_path / "config" / "settings.py").read_text() == (
        "KARNI_NEW = 3\nKARNI_LIMIT = KARNI_NEW * 2\n"
    )
    app = (tmp_path / "app.py").read_text()
    assert app.count("KARNI_NEW") == 5 and "os.environ['KARNI_OLD']" in app
    assert outcome.files == {"config/settings.py": 2, "app.py": 5}
    assert codemod.apply(tmp_path).files == {}


# detectors


def test_object_permission_classes_is_reported_not_rewritten(tmp_path: Path) -> None:
    source = (
        "class EventViewSet(BaseViewSet):\n"
        "    model = Event\n"
        "    object_permission_classes = [IsOwner]\n"
        "\n"
        "object_permission_classes = []  # module level: not a viewset\n"
    )
    (tmp_path / "views.py").write_text(source)
    codemod = load_codemod("v1_0.object_permission_classes_to_access")
    assert codemod.edits is False
    outcome = codemod.apply(tmp_path)
    assert outcome.files == {}
    assert [(s.path, s.line) for s in outcome.sites] == [("views.py", 3)]
    assert (tmp_path / "views.py").read_text() == source


def test_related_lookups_references_are_reported(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "from karni.api.expansion import related_lookups as lookups\n"
        "\n"
        "def related_lookups():  # the project's own function: not reported\n"
        "    return lookups(Event, ['venue'])\n"
    )
    (tmp_path / "b.py").write_text(
        "import karni.api.expansion\nkarni.api.expansion.scoped_related_lookups(M, [], s)\n"
    )
    plain = load_codemod("v1_0.related_lookups_to_optimize").apply(tmp_path)
    assert [(s.path, s.line) for s in plain.sites] == [("a.py", 1), ("a.py", 4)]
    scoped = load_codemod("v1_0.scoped_related_lookups_to_optimize").apply(tmp_path)
    assert [(s.path, s.line) for s in scoped.sites] == [("b.py", 2)]


# what a codemod may touch


def test_codemods_never_touch_dependencies_or_migrations(tmp_path: Path) -> None:
    rewritten = "rows = Book.all_objects.all()\n"
    for rel in (
        "app/views.py",
        "app/migrations/0002_data.py",
        ".venv/lib/python3.12/site-packages/x.py",
        "venv2/lib/y.py",
        "frontend/node_modules/pkg/z.py",
        ".karni/backup/w.py",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rewritten)
    (tmp_path / "venv2" / "pyvenv.cfg").write_text("home = /usr\n")
    assert source_files(tmp_path, (".py",)) == ["app/views.py"]
    outcome = _codemod("v1_0.all_objects_to_without").apply(tmp_path)
    assert list(outcome.files) == ["app/views.py"]
    assert (tmp_path / "app/migrations/0002_data.py").read_text() == rewritten


def test_a_file_that_does_not_parse_is_reported(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def f(:\n    Book.all_objects\n")
    outcome = _codemod("v1_0.all_objects_to_without").apply(tmp_path)
    assert outcome.files == {}
    assert [s.path for s in outcome.sites] == ["broken.py"]
