"""Data-driven Python codemods (libcst): a mechanical breaking change is one line of data.

    CODEMOD = RenameSymbol("karni.managers.SoftDeleteManagerMixin",
                           "karni.managers.ScopedManagerMixin")

libcst keeps every comment, blank line and quote style; only the rewritten
nodes change. Each codemod is idempotent (its output never matches its own
pattern) and conservative: where the project's own code makes a rewrite
ambiguous, it reports the site instead of guessing.

* :class:`RenameSymbol` — a moved import, a renamed class or base class.
* :class:`RenameSetting` — a renamed setting, where it is defined and read.
* :class:`ReplaceAttribute` — ``Model.<attr>`` becomes another expression.
* :class:`ReplaceMethodCall` — ``<expr>.<method>()`` becomes another expression.
* :class:`FindClassAttribute`, :class:`FindReferences` — detectors for manual
  changes: they report every site and edit nothing.

Override / escape hatch: subclass :class:`PythonCodemod` (``needles``,
``analyse``, ``recorder``) for a change no data-driven codemod covers.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import libcst as cst
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.helpers import get_full_name_for_node
from libcst.metadata import (
    ClassScope,
    ExpressionContext,
    ExpressionContextProvider,
    GlobalScope,
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    ProviderT,
    QualifiedNameProvider,
    ScopeProvider,
)

from karni_cli.upgrades.codemod import Codemod, Outcome, Site, source_files

__all__ = [
    "FindClassAttribute",
    "FindReferences",
    "PythonCodemod",
    "Recorder",
    "RenameSetting",
    "RenameSymbol",
    "ReplaceAttribute",
    "ReplaceMethodCall",
]

_PLACEHOLDER = "__karni_receiver__"


class Recorder(cst.CSTTransformer):
    """A transformer that counts its rewrites and records sites with line numbers."""

    METADATA_DEPENDENCIES: ClassVar[Collection[ProviderT]] = (PositionProvider,)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.count = 0
        self.sites: list[Site] = []

    def site(self, node: cst.CSTNode, note: str) -> None:
        line = self.get_metadata(PositionProvider, node).start.line
        found = Site(self.path, line, note)
        if found not in self.sites:
            self.sites.append(found)


class PythonCodemod(Codemod):
    """A codemod over the project's own ``.py`` files (migrations excluded)."""

    @abstractmethod
    def needles(self) -> tuple[str, ...]:
        """A file is parsed only when it contains one of these strings."""

    def analyse(self, modules: Mapping[str, cst.Module]) -> Any:
        """Project-wide pre-pass over every candidate file; the result reaches :meth:`recorder`."""
        return None

    @abstractmethod
    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        """The transformer for one file."""

    def transform_module(
        self, module: cst.Module, path: str, analysis: Any
    ) -> tuple[cst.Module, Recorder]:
        context = CodemodContext()
        recorder = self.recorder(path, analysis, context)
        result = MetadataWrapper(module).visit(recorder)
        if context.scratch.get(AddImportsVisitor.CONTEXT_KEY):
            result = AddImportsVisitor(context).transform_module(result)
        return result, recorder

    def transform_source(self, source: str, path: str = "module.py") -> tuple[str, int, list[Site]]:
        """Rewrite one file's text on its own (its analysis sees only this file)."""
        module = cst.parse_module(source)
        new, recorder = self.transform_module(module, path, self.analyse({path: module}))
        return new.code, recorder.count, recorder.sites

    def apply(self, root: Path) -> Outcome:
        outcome = Outcome()
        modules: dict[str, cst.Module] = {}
        needles = [needle.encode() for needle in self.needles()]
        for rel in source_files(root, (".py",)):
            raw = (root / rel).read_bytes()
            if not any(needle in raw for needle in needles):
                continue
            try:
                modules[rel] = cst.parse_module(raw)
            except cst.ParserSyntaxError as exc:
                note = f"not parsed ({exc.message}). Check it by hand"
                outcome.sites.append(Site(rel, exc.raw_line, note))
        analysis = self.analyse(modules)
        for rel, module in modules.items():
            new, recorder = self.transform_module(module, rel, analysis)
            outcome.sites += recorder.sites
            if recorder.count and new.code != module.code:
                (root / rel).write_bytes(new.bytes)
                outcome.files[rel] = recorder.count
        return outcome


def _visit(recorder: Recorder, modules: Mapping[str, cst.Module]) -> list[Site]:
    """Run a site-recording visitor (built per path) over every module."""
    sites: list[Site] = []
    for path, module in modules.items():
        recorder.path = path
        recorder.sites = []
        MetadataWrapper(module).visit(recorder)
        sites += recorder.sites
    return sites


class _Substitute(cst.CSTTransformer):
    def __init__(self, receiver: cst.BaseExpression) -> None:
        super().__init__()
        self.receiver = receiver

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.BaseExpression:
        return self.receiver if updated_node.value == _PLACEHOLDER else updated_node


def _attach(
    receiver: cst.BaseExpression, replacement: str, like: cst.BaseExpression
) -> cst.BaseExpression:
    """``<receiver>.<replacement>``, keeping the parentheses ``like`` had."""
    template = cst.parse_expression(f"{_PLACEHOLDER}.{replacement}")
    built = template.visit(_Substitute(receiver))
    assert isinstance(built, cst.BaseExpression)
    return built.with_changes(lpar=like.lpar, rpar=like.rpar)


def _class_like(node: cst.BaseExpression) -> bool:
    """Does ``node`` name a class: ``Book``, ``models.Book``, ``cls``, ``self.model``, ``type(x)``?"""
    if isinstance(node, cst.Call):
        func = node.func
        return isinstance(func, cst.Name) and func.value == "type" and len(node.args) == 1
    if isinstance(node, cst.Attribute):
        name = node.attr.value
    elif isinstance(node, cst.Name):
        name = node.value
    else:
        return False
    return (
        name.lstrip("_")[:1].isupper()
        or name in {"cls", "klass", "__class__"}
        or name.endswith(("model", "_cls", "_class"))
    )


# finders (analysis passes and detectors)


class _ClassAttributeFinder(Recorder):
    """Sites where a class body assigns ``name``."""

    METADATA_DEPENDENCIES = (PositionProvider, ScopeProvider)

    def __init__(self, name: str, note: str) -> None:
        super().__init__("")
        self.name = name
        self.note = note

    def _check(self, node: cst.CSTNode, targets: Sequence[cst.BaseExpression]) -> None:
        named = any(isinstance(t, cst.Name) and t.value == self.name for t in targets)
        if named and isinstance(self.get_metadata(ScopeProvider, node, None), ClassScope):
            self.site(node, self.note)

    def visit_Assign(self, node: cst.Assign) -> None:
        self._check(node, [target.target for target in node.targets])

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._check(node, [node.target])


class _FunctionFinder(Recorder):
    """Sites where a function or method named ``name`` is defined."""

    def __init__(self, name: str, note: str) -> None:
        super().__init__("")
        self.name = name
        self.note = note

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        if node.name.value == self.name:
            self.site(node, self.note)


class _GlobalAssignmentFinder(Recorder):
    """Sites where module-level code assigns ``name``."""

    METADATA_DEPENDENCIES = (PositionProvider, ScopeProvider)

    def __init__(self, name: str) -> None:
        super().__init__("")
        self.name = name

    def _check(self, node: cst.CSTNode, targets: Sequence[cst.BaseExpression]) -> None:
        named = any(isinstance(t, cst.Name) and t.value == self.name for t in targets)
        if named and isinstance(self.get_metadata(ScopeProvider, node, None), GlobalScope):
            self.site(node, "defines it")

    def visit_Assign(self, node: cst.Assign) -> None:
        self._check(node, [target.target for target in node.targets])

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._check(node, [node.target])

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self._check(node, [node.target])


class _ReferenceFinder(Recorder):
    """Sites that import or reference any of ``names`` (qualified, so aliases count)."""

    METADATA_DEPENDENCIES = (PositionProvider, QualifiedNameProvider)

    def __init__(self, path: str, names: frozenset[str], note: str) -> None:
        super().__init__(path)
        self.names = names
        self.note = note

    def _matches(self, node: cst.CSTNode) -> bool:
        qualified = self.get_metadata(QualifiedNameProvider, node, set())
        return any(q.name in self.names for q in qualified)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        if (
            node.module is not None
            and not node.relative
            and not isinstance(node.names, cst.ImportStar)
        ):
            module = get_full_name_for_node(node.module)
            if any(f"{module}.{get_full_name_for_node(a.name)}" in self.names for a in node.names):
                self.site(node, self.note)
        return False

    def visit_Name(self, node: cst.Name) -> None:
        if self._matches(node):
            self.site(node, self.note)

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        if self._matches(node):
            self.site(node, self.note)
            return False
        return True


# RenameSymbol


def _imports_unaliased(module: cst.Module, from_module: str, name: str) -> bool:
    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if (
                isinstance(small, cst.ImportFrom)
                and small.module is not None
                and not small.relative
                and get_full_name_for_node(small.module) == from_module
                and not isinstance(small.names, cst.ImportStar)
                and any(
                    a.asname is None and get_full_name_for_node(a.name) == name for a in small.names
                )
            ):
                return True
    return False


class _RenameSymbol(Recorder):
    METADATA_DEPENDENCIES = (PositionProvider, QualifiedNameProvider)

    def __init__(self, path: str, old: str, new: str, context: CodemodContext) -> None:
        super().__init__(path)
        self.old, self.new, self.context = old, new, context
        self.old_module, self.old_name = old.rsplit(".", 1)
        self.new_module, self.new_name = new.rsplit(".", 1)
        self.moved = self.old_module != self.new_module
        self.in_import = 0
        self.attr_names: set[int] = set()
        self.new_imported = False

    def _is_old(self, node: cst.CSTNode) -> bool:
        return any(
            q.name == self.old for q in self.get_metadata(QualifiedNameProvider, node, set())
        )

    def visit_Module(self, node: cst.Module) -> None:
        self.new_imported = _imports_unaliased(node, self.new_module, self.new_name)

    def visit_Import(self, node: cst.Import) -> None:
        self.in_import += 1

    def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
        self.in_import -= 1
        return updated_node

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        self.in_import += 1

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel:
        self.in_import -= 1
        names = updated_node.names
        if (
            updated_node.relative
            or updated_node.module is None
            or isinstance(names, cst.ImportStar)
            or get_full_name_for_node(updated_node.module) != self.old_module
        ):
            return updated_node
        kept: list[cst.ImportAlias] = []
        touched = False
        for alias in names:
            if get_full_name_for_node(alias.name) != self.old_name:
                kept.append(alias)
                continue
            touched = True
            self.count += 1
            asname = alias.asname.name if alias.asname else None
            alias_name = asname.value if isinstance(asname, cst.Name) else None
            if self.moved:
                AddImportsVisitor.add_needed_import(
                    self.context, self.new_module, self.new_name, alias_name
                )
            elif alias_name is not None or not self.new_imported:
                kept.append(alias.with_changes(name=cst.Name(self.new_name)))
                self.new_imported = self.new_imported or alias_name is None
            # else: the new name is already imported here; the old alias just goes.
        if not touched:
            return updated_node
        if not kept:
            return cst.RemoveFromParent()
        if get_full_name_for_node(names[-1].name) == self.old_name:
            kept[-1] = kept[-1].with_changes(comma=names[-1].comma)
        return updated_node.with_changes(names=kept)

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self.attr_names.add(id(node.attr))

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if (
            self.in_import
            or id(original_node) in self.attr_names
            or updated_node.value != self.old_name
            or not self._is_old(original_node)
        ):
            return updated_node
        self.count += 1
        return updated_node.with_changes(value=self.new_name)

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if self.in_import or not self._is_old(original_node):
            return updated_node
        self.count += 1
        if not self.moved:
            return updated_node.with_changes(attr=cst.Name(self.new_name))
        AddImportsVisitor.add_needed_import(self.context, self.new_module)
        dotted = cst.parse_expression(self.new)
        return dotted.with_changes(lpar=updated_node.lpar, rpar=updated_node.rpar)

    def leave_SimpleString(
        self, original_node: cst.SimpleString, updated_node: cst.SimpleString
    ) -> cst.SimpleString:
        if self.in_import or updated_node.evaluated_value != self.old:
            return updated_node
        self.count += 1
        quote = updated_node.quote
        return updated_node.with_changes(value=f"{updated_node.prefix}{quote}{self.new}{quote}")


@dataclass(frozen=True)
class RenameSymbol(PythonCodemod):
    """``old`` -> ``new`` (dotted paths): a moved import, a renamed class or base class.

    Rewrites ``from`` imports (an ``as`` alias is kept), every reference that
    resolves to ``old`` (bare names, ``module.Name`` access, base-class
    lists) and string literals equal to the dotted path (settings name
    classes that way). References are matched by what they import, never by
    spelling, so a name the project defines itself is not touched. When the
    module changes too, ``from new.module import Name`` is added.
    """

    old: str
    new: str

    def needles(self) -> tuple[str, ...]:
        return (self.old.rsplit(".", 1)[1],)

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        return _RenameSymbol(path, self.old, self.new, context)


# RenameSetting

_SETTINGS_OBJECTS = frozenset({"settings", "conf.settings", "django.conf.settings"})
_SETTINGS_CALLS = frozenset({"override_settings", "modify_settings", "settings"})
_ATTR_FUNCTIONS = frozenset({"getattr", "hasattr", "setattr", "delattr"})


def _is_settings(node: cst.BaseExpression) -> bool:
    return get_full_name_for_node(node) in _SETTINGS_OBJECTS


class _RenameSetting(Recorder):
    def __init__(self, path: str, old: str, new: str, defines: bool) -> None:
        super().__init__(path)
        self.old, self.new, self.defines = old, new, defines
        self.skip: set[int] = set()

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self.skip.add(id(node.attr))

    def visit_Arg(self, node: cst.Arg) -> None:
        if node.keyword is not None:
            self.skip.add(id(node.keyword))

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if self.defines and updated_node.value == self.old and id(original_node) not in self.skip:
            self.count += 1
            return updated_node.with_changes(value=self.new)
        return updated_node

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.Attribute:
        if updated_node.attr.value == self.old and _is_settings(updated_node.value):
            self.count += 1
            return updated_node.with_changes(attr=cst.Name(self.new))
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        name = (get_full_name_for_node(updated_node.func) or "").rsplit(".", 1)[-1]
        args = list(updated_node.args)
        changed = False
        if name in _SETTINGS_CALLS:
            for index, arg in enumerate(args):
                if arg.keyword is not None and arg.keyword.value == self.old:
                    args[index] = arg.with_changes(keyword=cst.Name(self.new))
                    changed = True
        elif name in _ATTR_FUNCTIONS and len(args) >= 2 and _is_settings(args[0].value):
            literal = args[1].value
            if isinstance(literal, cst.SimpleString) and literal.evaluated_value == self.old:
                quoted = f"{literal.prefix}{literal.quote}{self.new}{literal.quote}"
                args[1] = args[1].with_changes(value=literal.with_changes(value=quoted))
                changed = True
        if not changed:
            return updated_node
        self.count += 1
        return updated_node.with_changes(args=args)


@dataclass(frozen=True)
class RenameSetting(PythonCodemod):
    """Setting ``old`` -> ``new``, where it is defined and wherever it is read.

    Rewrites a module-level assignment (and every use of that name in the
    module that assigns it), ``settings.OLD`` (django.conf's ``settings``
    or pytest-django's ``settings`` fixture), ``getattr``/``hasattr``/
    ``setattr``/``delattr(settings, "OLD", ...)``, and ``OLD=`` keywords of
    ``override_settings``/``modify_settings``/``self.settings``. Environment
    variable names are not settings and are left alone.
    """

    old: str
    new: str

    def needles(self) -> tuple[str, ...]:
        return (self.old,)

    def analyse(self, modules: Mapping[str, cst.Module]) -> set[str]:
        return {site.path for site in _visit(_GlobalAssignmentFinder(self.old), modules)}

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        return _RenameSetting(path, self.old, self.new, path in analysis)


# ReplaceAttribute


class _ReplaceAttribute(Recorder):
    METADATA_DEPENDENCIES = (PositionProvider, ExpressionContextProvider, ParentNodeProvider)

    def __init__(self, path: str, spec: ReplaceAttribute, definitions: list[Site]) -> None:
        super().__init__(path)
        self.spec = spec
        self.definitions = definitions

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        spec = self.spec
        if original_node.attr.value != spec.attr or not _class_like(original_node.value):
            return updated_node
        if self.get_metadata(ExpressionContextProvider, original_node, None) is not (
            ExpressionContext.LOAD
        ):
            return updated_node
        if self.definitions:
            first = self.definitions[0]
            self.site(
                original_node,
                f"left as is: the project defines its own {spec.attr} "
                f"({first.path}:{first.line}). If this is Karni's, use .{spec.replacement}",
            )
            return updated_node
        parent = self.get_metadata(ParentNodeProvider, original_node, None)
        if (
            isinstance(parent, cst.Attribute)
            and parent.value is original_node
            and parent.attr.value in spec.manager_only
        ):
            self.site(
                original_node,
                f"left as is: .{parent.attr.value}() needs the manager {spec.attr} returned. "
                "Rewrite it by hand",
            )
            return updated_node
        self.count += 1
        return _attach(updated_node.value, spec.replacement, updated_node)


@dataclass(frozen=True)
class ReplaceAttribute(PythonCodemod):
    """``Model.<attr>`` -> ``Model.<replacement>`` wherever the receiver names a class.

    Only class-like receivers are rewritten (``Book``, ``models.Book``,
    ``cls``, ``self.model``, ``type(obj)``): Django never exposes a manager
    through an instance, so ``obj.<attr>`` is someone else's attribute and is
    left alone. Reported instead of rewritten: every use, when the project
    defines ``<attr>`` on a class itself (a reference could reach either);
    and a use followed by a ``manager_only`` call, which needs what ``<attr>``
    returned rather than what ``replacement`` returns.
    """

    attr: str
    replacement: str
    manager_only: frozenset[str] = frozenset()

    def needles(self) -> tuple[str, ...]:
        return (self.attr,)

    def analyse(self, modules: Mapping[str, cst.Module]) -> list[Site]:
        return _visit(_ClassAttributeFinder(self.attr, "defines it"), modules)

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        return _ReplaceAttribute(path, self, analysis)


# ReplaceMethodCall


class _ReplaceMethodCall(Recorder):
    def __init__(self, path: str, spec: ReplaceMethodCall, definitions: list[Site]) -> None:
        super().__init__(path)
        self.spec = spec
        self.definitions = definitions

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        spec = self.spec
        func = updated_node.func
        if not isinstance(func, cst.Attribute) or func.attr.value != spec.method:
            return updated_node
        if updated_node.args:
            return updated_node  # not the argument-less method this codemod replaces
        if self.definitions:
            first = self.definitions[0]
            self.site(
                original_node,
                f"left as is: the project defines its own {spec.method}() "
                f"({first.path}:{first.line}). If this is Karni's, use .{spec.replacement}",
            )
            return updated_node
        self.count += 1
        return _attach(func.value, spec.replacement, updated_node)


@dataclass(frozen=True)
class ReplaceMethodCall(PythonCodemod):
    """``<expr>.<method>()`` -> ``<expr>.<replacement>``, on any receiver.

    Only argument-less calls match. When the project defines a function or
    method named ``<method>`` itself, every call is reported instead (it
    could be either).
    """

    method: str
    replacement: str

    def needles(self) -> tuple[str, ...]:
        return (self.method,)

    def analyse(self, modules: Mapping[str, cst.Module]) -> list[Site]:
        return _visit(_FunctionFinder(self.method, "defines it"), modules)

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        return _ReplaceMethodCall(path, self, analysis)


# detectors


@dataclass(frozen=True)
class FindClassAttribute(PythonCodemod):
    """Detector: every class body that assigns ``name``."""

    edits = False

    name: str
    note: str

    def needles(self) -> tuple[str, ...]:
        return (self.name,)

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        finder = _ClassAttributeFinder(self.name, self.note)
        finder.path = path
        return finder


@dataclass(frozen=True)
class FindReferences(PythonCodemod):
    """Detector: every import of, or reference to, one of ``qualified_names``."""

    edits = False

    qualified_names: tuple[str, ...]
    note: str

    def needles(self) -> tuple[str, ...]:
        return tuple(name.rsplit(".", 1)[-1] for name in self.qualified_names)

    def recorder(self, path: str, analysis: Any, context: CodemodContext) -> Recorder:
        return _ReferenceFinder(path, frozenset(self.qualified_names), self.note)
