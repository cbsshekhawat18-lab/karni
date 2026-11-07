"""Experimental. Taxonomy tagging: one declaration tags a model to tree models.

Many models are tagged to the same hierarchies: products, articles and
suppliers to a region tree and a category tree. Each tag needs the same
many-to-many, filters, facet counts, import columns and access rule, so one
declaration gives them all::

    class Product(BaseModel):
        class Karni:
            taxonomies = {"region": "geo.Region", "category": "catalog.Category"}

Each key names a tree model (:class:`karni.models.TreeModel`), as an
``"app_label.Model"`` string or the class. For each one:

* The model gets a many-to-many named after the key (``product.region``).
  Karni adds it when the class is prepared (Django's ``class_prepared``
  signal), before ``makemigrations`` or any other code reads the model, so a
  migration writes it like a field of the class body. It is a plain
  ``ManyToManyField(<tree>, blank=True, related_name="+")``: no reverse
  accessor, so two taxonomies of one model on the same tree never clash.
  Its auto-created through table already holds the two indexes the queries
  here use: the unique (row, node) pair, which the facet counts read, and the
  index on the node column, where the filters and the node counts start.
  Karni adds no other index.
* A many-to-many the model declares itself under the key's name is adopted
  instead: its own ``through`` model, related name and indexes stay. That is
  the escape hatch. ``karni.E572`` reports one that does not point at the tree.
* The API (:mod:`karni.api.taxonomy`): the list filters ``?region=<key>,<key>``
  and ``?region_descendants=true``, ``GET <resource>/facets/`` (rows per node
  under the list's filters and access, rolled up to the ancestors on
  request) and ``GET <tree resource>/<key>/tagged/`` (rows tagged with a node,
  per tagging model, each under its own access).
* The key is a path of the ``tree:<path>`` scope (``tree:region``,
  :mod:`karni.accounts.tree_scope`), the import and export columns name nodes
  by their natural key with ``|`` between several (:mod:`karni.transfer`),
  and ``@karni/ui``'s forms show a ``TreeSelect`` for it.

``karni.E570`` is a malformed declaration (raised when the model class is
built), ``karni.E571`` a target that is not a tree model and ``karni.E572``
an adopted field that does not point at it (``karni check``).

Every query here follows only the nodes of the tree queryset it is given
(``nodes``, default: the tree's live rows): a node it leaves out hides its
branch, as in the tree endpoints. The API passes the nodes the requester may
read.

Override / escape hatch: declare the many-to-many yourself under the key's
name and Karni adopts it. :func:`tagged_rows`, :func:`facet_counts` and
:func:`facets` are the queries, for code outside the API. The viewset's
``facets`` and ``tagged`` actions and ``facet_queryset()`` can be overridden.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from django.core.exceptions import EmptyResultSet, FieldDoesNotExist
from django.db import connections, models
from django.db.migrations.state import StateApps
from django.db.models import F, Q
from django.db.models.expressions import RawSQL
from django.db.models.signals import class_prepared

from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

if TYPE_CHECKING:
    from django.db.models.fields.related import ManyToManyField

__all__ = [
    "DESCENDANTS_SUFFIX",
    "FacetNode",
    "Taxonomy",
    "declared_taxonomies",
    "facet_counts",
    "facets",
    "get_taxonomy",
    "tagged_rows",
    "tagging",
    "taxonomies",
]

#: The attribute a generated many-to-many carries: the key it was generated for.
GENERATED_ATTR: Final = "karni_taxonomy"

#: ``?<key><suffix>=true`` also reads the rows tagged under the nodes of ``?<key>=``.
DESCENDANTS_SUFFIX: Final = "_descendants"

_ROW: Final = "karni_row"
_NODE: Final = "karni_node"


# the declaration


def _malformed(model: type[models.Model], why: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(
        f"{model.__name__}.Karni.taxonomies {why} Write a dict of key -> tree model, e.g. "
        'taxonomies = {"region": "geo.Region"}: each key a field name, each value '
        '"app_label.Model" or the model class.',
        code="E570",
    )


def declared_taxonomies(model: type[models.Model]) -> dict[str, str]:
    """Experimental. ``Karni.taxonomies`` as key -> the target as written (``E570`` if malformed).

    A target given as a class comes back as its ``app_label.Model`` label.
    A key is a field name that does not start with ``_``, holds no ``__`` and
    does not end with ``_descendants`` (the suffix of the descendants filter).
    """
    value = karni_option(model, "taxonomies", None)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _malformed(model, f"is a {type(value).__name__}, not a dict.")
    found: dict[str, str] = {}
    for key, target in value.items():
        if (
            not isinstance(key, str)
            or not key.isidentifier()
            or key.startswith("_")
            or "__" in key
            or key.endswith(DESCENDANTS_SUFFIX)
        ):
            raise _malformed(
                model,
                f"has the key {key!r}, which is not a field name (no leading _, no __, not "
                f"ending in {DESCENDANTS_SUFFIX}).",
            )
        if isinstance(target, type) and issubclass(target, models.Model):
            found[key] = str(cast("type[models.Model]", target)._meta.label)
        elif isinstance(target, str) and target.strip():
            found[key] = target.strip()
        else:
            raise _malformed(model, f"maps {key!r} to {target!r}, which names no model.")
    return found


def _has_attribute(model: type[models.Model], name: str) -> bool:
    """Whether ``model`` already has a field (its own or a parent's) or attribute ``name``."""
    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        return hasattr(model, name)
    return True


def contribute_taxonomies(sender: type[models.Model], **kwargs: Any) -> None:
    """``class_prepared``: add the many-to-many of each declared key the model lacks.

    Skipped for abstract, proxy and swapped models (a concrete subclass gets
    its own) and for the historical models migrations build, whose fields
    come from the migration files.
    """
    if getattr(sender, "Karni", None) is None:
        return
    meta = sender._meta
    if meta.abstract or meta.proxy or meta.swapped or isinstance(meta.apps, StateApps):
        return
    for key, target in declared_taxonomies(sender).items():
        if _has_attribute(sender, key):
            continue  # adopted (karni.E572 checks it points at the tree)
        field = models.ManyToManyField(
            target, blank=True, related_name="+", verbose_name=key.replace("_", " ")
        )
        setattr(field, GENERATED_ATTR, key)
        sender.add_to_class(key, field)


class_prepared.connect(contribute_taxonomies, dispatch_uid="karni.taxonomy.contribute")


# one taxonomy


@dataclass(frozen=True)
class Taxonomy:
    """Experimental. One key of ``class Karni: taxonomies`` on one model.

    ``target`` is the tree model as declared. The other attributes read the
    model's field of that name: :attr:`field` (the many-to-many), :attr:`tree`
    (the model it points at), :attr:`through` and the through model's two
    foreign keys, :attr:`row_field` to the tagged model and :attr:`node_field`
    to the tree.
    """

    model: type[models.Model]
    key: str
    target: str

    @property
    def field(self) -> ManyToManyField[Any, Any]:
        """The model's many-to-many named after the key (``E572`` when it is not one)."""
        try:
            found = self.model._meta.get_field(self.key)
        except FieldDoesNotExist:
            found = None
        if found is None or not found.many_to_many or found.auto_created:
            raise KarniImproperlyConfigured(
                f"{self.model.__name__}.{self.key} is not a many-to-many field, so the "
                f"taxonomy {self.key!r} has nothing to tag with.",
                code="E572",
            )
        return cast("ManyToManyField[Any, Any]", found)

    @property
    def generated(self) -> bool:
        """Whether Karni generated the field (``False``: the model declares it, adopted)."""
        return getattr(self.field, GENERATED_ATTR, None) == self.key

    @property
    def tree(self) -> type[models.Model]:
        """The model the field points at (a tree model unless ``karni check`` says ``E571``)."""
        related = self.field.related_model
        if not isinstance(related, type):
            raise KarniImproperlyConfigured(
                f"{self.model.__name__}.{self.key} points at {related!r}, which is not an "
                "installed model.",
                code="E571",
            )
        return cast("type[models.Model]", related)

    @property
    def through(self) -> type[models.Model]:
        """The through model of the field (auto-created for a generated field)."""
        return cast("type[models.Model]", self.field.remote_field.through)

    @property
    def row_field(self) -> str:
        """The through model's foreign key to the tagged model."""
        return str(self.field.m2m_field_name())

    @property
    def node_field(self) -> str:
        """The through model's foreign key to the tree."""
        return str(self.field.m2m_reverse_field_name())

    @property
    def descendants_param(self) -> str:
        """The list parameter that adds the rows tagged under the nodes (``region_descendants``)."""
        return f"{self.key}{DESCENDANTS_SUFFIX}"

    def problem(self) -> tuple[str, str] | None:
        """``(code, message)`` when the taxonomy cannot work, else ``None`` (``karni check``)."""
        from karni.tree import is_tree_model

        try:
            field = self.model._meta.get_field(self.key)
        except FieldDoesNotExist:
            field = None
        name = f"{self.model.__name__}.Karni.taxonomies[{self.key!r}]"
        if field is None or not field.many_to_many or field.auto_created:
            kind = "no field" if field is None else type(field).__name__
            return (
                "E572",
                f"{name} adopts {self.model.__name__}.{self.key}, which is {kind}, not a "
                f"many-to-many to {self.target}.",
            )
        if not isinstance(field.related_model, type):
            return None  # Django's own check reports a target it cannot resolve (fields.E300)
        related = cast("type[models.Model]", field.related_model)
        if getattr(field, GENERATED_ATTR, None) != self.key and not _same_model(
            related, self.target, self.model
        ):
            return (
                "E572",
                f"{name} names {self.target}, but the adopted many-to-many "
                f"{self.model.__name__}.{self.key} points at {related._meta.label}.",
            )
        if not is_tree_model(related):
            return (
                "E571",
                f"{name} points at {related._meta.label}, which is not a tree model, so its "
                "filters, facets and the tree scope have no tree to walk.",
            )
        return None


def _same_model(model: type[models.Model], target: str, owner: type[models.Model]) -> bool:
    """Whether ``target`` (``"app.Model"``, ``"Model"`` in ``owner``'s app or ``"self"``) is it."""
    if target == "self":
        return model is owner
    label = target if "." in target else f"{owner._meta.app_label}.{target}"
    return str(model._meta.label_lower) == label.lower()


# the registry

_BY_MODEL: dict[type[models.Model], dict[str, Taxonomy]] = {}
_BY_TREE: dict[type[models.Model], list[Taxonomy]] = {}


def taxonomies(model: type[models.Model]) -> dict[str, Taxonomy]:
    """Experimental. The taxonomies of ``model``, by key, in declaration order (cached)."""
    cached = _BY_MODEL.get(model)
    if cached is None:
        cached = {
            key: Taxonomy(model, key, target) for key, target in declared_taxonomies(model).items()
        }
        _BY_MODEL[model] = cached
    return dict(cached)


def get_taxonomy(model: type[models.Model], key: str) -> Taxonomy | None:
    """Experimental. ``model``'s taxonomy ``key``, else ``None``."""
    return taxonomies(model).get(key)


def tagging(tree: type[models.Model]) -> list[Taxonomy]:
    """Experimental. Every taxonomy of an installed model that points at ``tree`` (cached).

    Proxy models are left out: they share their concrete model's rows. A
    taxonomy whose field is broken (``karni check`` reports it) is left out too.
    """
    from django.apps import apps

    concrete = tree._meta.concrete_model
    cached = _BY_TREE.get(concrete) if concrete is not None else None
    if cached is not None:
        return list(cached)
    found: list[Taxonomy] = []
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        for item in taxonomies(model).values():
            if item.problem() is not None:
                continue
            if item.tree._meta.concrete_model is concrete:
                found.append(item)
    if concrete is not None:
        _BY_TREE[concrete] = found
    return list(found)


# the queries


def _keys(nodes: Iterable[Any]) -> list[Any]:
    """Rows or keys as keys, once each, in order."""
    found: list[Any] = []
    for node in nodes:
        key = node.pk if isinstance(node, models.Model) else node
        if key not in found:
            found.append(key)
    return found


def _tree_rows(taxonomy: Taxonomy, nodes: models.QuerySet[Any] | None, db: str) -> Any:
    """The tree rows a query may use: ``nodes``, else the tree's live rows."""
    if nodes is not None:
        return nodes
    return taxonomy.tree._default_manager.db_manager(db).all()


def tagged_rows(
    taxonomy: Taxonomy,
    nodes: Iterable[Any],
    *,
    descendants: bool = False,
    within: models.QuerySet[Any] | None = None,
) -> Q:
    """Experimental. The rows tagged with one of ``nodes``, as one ``Q`` on the key.

    ``nodes`` are rows or keys of the tree. ``descendants=True`` also takes the
    rows tagged with any node below them (one cycle-safe walk). ``within``
    is the tree queryset the nodes and the walk are taken from (default: the
    live nodes): a node it leaves out matches nothing and hides its branch.
    ``Product.objects.filter(tagged_rows(region, [europe], descendants=True))``
    is one statement: the walk, inside the subquery of tagged keys.
    """
    keys = _keys(nodes)
    tree_rows = within if within is not None else taxonomy.tree._default_manager.all()
    if descendants:
        picked = tree_rows.descendants(keys, include_self=True)
    else:
        picked = tree_rows.filter(pk__in=keys)
    tagged = taxonomy.through._default_manager.filter(
        **{f"{taxonomy.node_field}__in": picked.values("pk")}
    ).values(taxonomy.row_field)
    return Q(pk__in=tagged)


@dataclass(frozen=True)
class _FacetSQL:
    """The SQL of one facet: the counts per node, and the keys of the counted nodes."""

    counts: str
    params: tuple[Any, ...]
    keys: str
    keys_params: tuple[Any, ...]


def _facet_sql(
    taxonomy: Taxonomy, rows: models.QuerySet[Any], *, rollup: bool, nodes: Any
) -> _FacetSQL | None:
    """The facet's statements, or ``None`` when no row or no node can count."""
    from karni.tree import compile_queryset, walk_sql

    db = rows.db
    connection = connections[db]
    quote = connection.ops.quote_name
    tree_rows = _tree_rows(taxonomy, nodes, db)
    through = taxonomy.through._default_manager.db_manager(db)
    pairs = through.filter(**{f"{taxonomy.row_field}__in": rows.order_by().values("pk")}).values(
        **{_ROW: F(taxonomy.row_field), _NODE: F(taxonomy.node_field)}
    )
    try:
        pairs_sql, pairs_params = pairs.query.get_compiler(using=db).as_sql()
        if not rollup:
            live_sql, live_params = (
                tree_rows.order_by().values("pk").query.get_compiler(using=db).as_sql()
            )
        else:
            restrict = compile_queryset(tree_rows)
    except EmptyResultSet:
        return None
    row, node = quote(_ROW), quote(_NODE)
    if not rollup:
        where = f"p.{node} IN ({live_sql})"
        params = (*pairs_params, *live_params)
        return _FacetSQL(
            counts=(
                f"SELECT p.{node}, COUNT(DISTINCT p.{row}) FROM ({pairs_sql}) p "
                f"WHERE {where} GROUP BY p.{node}"
            ),
            params=params,
            keys=f"SELECT p.{node} FROM ({pairs_sql}) p WHERE {where}",
            keys_params=params,
        )
    # Up from every tagged node at once: each row of the walk pairs a tagged node
    # (origin) with itself and each of its ancestors, through the nodes allowed.
    walk, walk_params = walk_sql(
        taxonomy.tree,
        connection,
        start=(f"SELECT p.{node} FROM ({pairs_sql}) p", pairs_params),
        up=True,
        restrict=restrict,
        include_self=True,
        select="origin, node_id",
        origin=True,
    )
    return _FacetSQL(
        counts=(
            f"SELECT w.node_id, COUNT(DISTINCT p.{row}) FROM ({pairs_sql}) p "
            f"INNER JOIN ({walk}) w ON w.origin = p.{node} GROUP BY w.node_id"
        ),
        params=(*pairs_params, *walk_params),
        keys=f"SELECT w.node_id FROM ({walk}) w",
        keys_params=tuple(walk_params),
    )


def facet_counts(
    taxonomy: Taxonomy,
    rows: models.QuerySet[Any],
    *,
    rollup: bool = False,
    nodes: models.QuerySet[Any] | None = None,
) -> dict[Any, int]:
    """Experimental. How many of ``rows`` each node counts: node key -> rows. One query.

    Without ``rollup`` a node counts the rows tagged with it. With
    ``rollup=True`` it counts the rows tagged with it or with any node below
    it, each row once (a row tagged with France and Lyon counts once for
    Europe). Only the nodes of ``nodes`` count (default: the live nodes), and
    a node with no row is left out.
    """
    found = _facet_sql(taxonomy, rows, rollup=rollup, nodes=nodes)
    return {} if found is None else _run_counts(taxonomy, found, rows.db)


def _run_counts(taxonomy: Taxonomy, found: _FacetSQL, db: str) -> dict[Any, int]:
    from karni.tree import pk_field

    with connections[db].cursor() as cursor:
        cursor.execute(found.counts, list(found.params))
        fetched = cursor.fetchall()
    pk = pk_field(taxonomy.tree)
    return {pk.to_python(key): int(count) for key, count in fetched if count}


@dataclass(frozen=True)
class FacetNode:
    """Experimental. One node of a facet: its key, label (``str()``), parent and row count."""

    key: Any
    label: str
    parent: Any
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.key, "label": self.label, "parent": self.parent, "count": self.count}


def facets(
    taxonomy: Taxonomy,
    rows: models.QuerySet[Any],
    *,
    rollup: bool = False,
    nodes: models.QuerySet[Any] | None = None,
) -> list[FacetNode]:
    """Experimental. :func:`facet_counts` with each node's label and parent, depth first.

    Two queries whatever the number of nodes: the counts, then the counted
    nodes (``str(node)`` is the label, so a ``__str__`` that reads a relation
    adds its own). The nodes come in the tree's order, each after its parent
    when its parent is counted too (always, with ``rollup``). ``parent`` is
    the node's parent key, counted or not.
    """
    from karni.tree import tree_order

    found = _facet_sql(taxonomy, rows, rollup=rollup, nodes=nodes)
    if found is None:
        return []
    counts = _run_counts(taxonomy, found, rows.db)
    if not counts:
        return []
    tree = taxonomy.tree
    tree_rows = _tree_rows(taxonomy, nodes, rows.db)
    fetched = list(
        tree_rows.filter(pk__in=RawSQL(found.keys, found.keys_params)).order_by(
            *tree.tree_ordering()  # type: ignore[attr-defined]
        )
    )
    by_key = {node.pk: node for node in fetched if node.pk in counts}
    order = tree_order([(key, by_key[key].parent_id) for key in by_key])
    return [
        FacetNode(key=key, label=str(by_key[key]), parent=by_key[key].parent_id, count=counts[key])
        for key, _depth in order
    ]
