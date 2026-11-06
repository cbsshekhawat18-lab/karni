"""The list screen's basics: pages, page size, select across, order, chips, plurals."""

from __future__ import annotations

import re
import warnings
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.paginator import UnorderedObjectListWarning
from django.db.migrations.state import ModelState
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from karni.admin import listing
from karni.admin.base import build_model_admin
from karni.admin.plurals import plural_of
from tests.adminapp.models import Category, Gizmo, KitchenSink, Metric, Note, Widget
from tests.testapp.models import Price

pytestmark = pytest.mark.django_db


def _client() -> Client:
    users = get_user_model()
    user = users.objects.filter(email="root@example.com").first() or users.objects.create_superuser(
        email="root@example.com", password="pw-123456"
    )
    client = Client()
    client.force_login(user)
    return client


def _list(model: type[Any]) -> str:
    opts = model._meta
    return reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")


def _page(model: type[Any], **query: Any) -> str:
    return _client().get(_list(model), query).content.decode()


def _widgets(count: int) -> None:
    Widget.objects.bulk_create([Widget(name=f"Widget {i:03d}") for i in range(count)])


def _notes(count: int, prefix: str = "Note") -> list[Note]:
    return [Note.objects.create(title=f"{prefix} {i}") for i in range(count)]


# -- AP1: pagination ----------------------------------------------------------------


def test_a_list_shows_25_rows_and_says_which() -> None:
    _widgets(60)
    html = _page(Widget)
    assert "Showing 1 to 25 of 60 widgets" in html
    assert html.count('class="field-name"') + html.count("field-name") >= 25
    assert "karni-pages" in html and 'rel="next"' in html


def test_the_last_page_says_so() -> None:
    _widgets(60)
    assert "Showing 51 to 60 of 60 widgets" in _page(Widget, p=3)


def test_one_page_has_no_page_links() -> None:
    _notes(8)
    html = _page(Note)
    assert "Showing 1 to 8 of 8 notes" in html
    assert "karni-pages" not in html


def test_one_row_uses_the_singular() -> None:
    _notes(1)
    assert "Showing 1 to 1 of 1 note" in _page(Note)


def test_page_size_comes_from_the_url_and_only_from_the_choices() -> None:
    _widgets(120)
    assert "Showing 1 to 50 of 120 widgets" in _page(Widget, per_page=50)
    assert "Showing 101 to 120 of 120 widgets" in _page(Widget, per_page=100, p=2)
    assert "Showing 1 to 25 of 120 widgets" in _page(Widget, per_page=7)  # not a choice
    assert "Showing 1 to 25 of 120 widgets" in _page(Widget, per_page="100000")
    assert "Showing 1 to 25 of 120 widgets" in _page(Widget, per_page="abc")


def test_the_page_links_and_sizes_keep_the_page_size_in_the_url() -> None:
    _widgets(120)
    html = _page(Widget, per_page=50, q="Widget")
    assert re.search(r'href="\?[^"]*per_page=50[^"]*p=2', html) or re.search(
        r'href="\?[^"]*p=2[^"]*per_page=50', html
    )
    assert re.search(r'href="\?[^"]*per_page=100', html)
    assert "Rows per page" in html


def test_a_page_beyond_the_end_after_a_size_change_does_not_break() -> None:
    _widgets(60)
    response = _client().get(_list(Widget), {"per_page": 100, "p": 3})
    assert response.status_code in (200, 302)


def test_page_numbers_have_gaps() -> None:
    _widgets(25 * 13)
    html = _page(Widget)
    numbers = re.findall(r'aria-label="Page (\d+)"', html)
    assert numbers == ["2", "3", "13"]
    assert "&hellip;" in html
    middle = _page(Widget, p=7)
    assert re.findall(r'aria-label="Page (\d+)"', middle) == ["1", "6", "8", "13"]


def test_the_default_page_size_is_a_setting() -> None:
    with override_settings(KARNI_ADMIN_PER_PAGE=10):
        built = build_model_admin(Widget)(Widget, AdminSite())
    assert built.list_per_page == 10
    assert built.karni_page_sizes() == [10, 25, 50, 100]


def test_the_page_size_is_25_without_a_setting() -> None:
    assert build_model_admin(Widget)(Widget, AdminSite()).list_per_page == 25


def test_admin_meta_sets_a_models_page_size() -> None:
    assert admin.site._registry[Gizmo].list_per_page == 15
    Gizmo.objects.bulk_create([Gizmo(name=f"G{i}") for i in range(40)])
    assert "Showing 1 to 15 of 40 gizmos" in _page(Gizmo)
    assert "Showing 1 to 25 of 40 gizmos" in _page(Gizmo, per_page=25)


def test_an_admin_class_page_size_beats_the_setting() -> None:
    class Own(build_model_admin(Widget)):  # type: ignore[misc]
        list_per_page = 100

    with override_settings(KARNI_ADMIN_PER_PAGE=10):
        assert Own(Widget, AdminSite()).list_per_page == 100


def test_the_count_is_exact_off_postgresql_and_below_the_threshold() -> None:
    _widgets(3)
    assert listing.count_rows(Widget.objects.all()) == (3, False)
    with override_settings(KARNI_ADMIN_COUNT_ESTIMATE_ABOVE=1):
        assert listing.count_rows(Widget.objects.all())[0] == 3


def test_a_very_large_postgresql_table_shows_an_estimate() -> None:
    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("the estimate is PostgreSQL only")
    _widgets(60)
    with connection.cursor() as cursor:
        cursor.execute(f'ANALYZE "{Widget._meta.db_table}"')
    with override_settings(KARNI_ADMIN_COUNT_ESTIMATE_ABOVE=10):
        html = _page(Widget)
        assert re.search(r"Showing 1 to 25 of about \d+ widgets", html)
        assert listing.count_rows(Widget.objects.all())[1] is True
        # a filter that matches a few rows is counted exactly
        assert "Showing 1 to 1 of 1 widget" in _page(Widget, q="Widget 007")
    with override_settings(KARNI_ADMIN_COUNT_ESTIMATE_ABOVE=0):
        assert "Showing 1 to 25 of 60 widgets" in _page(Widget)


# -- AP2: select across --------------------------------------------------------------


def _act(client: Client, model: type[Any], action: str, *pks: Any, **extra: Any) -> Any:
    query = extra.pop("query", "")
    data = {"action": action, "_selected_action": [str(pk) for pk in pks], **extra}
    return client.post(_list(model) + query, data, follow=extra.pop("follow", False))


def test_the_page_offers_select_all_across_pages() -> None:
    _widgets(60)
    html = _page(Widget)
    assert "Select all 60 widgets" in html


def test_select_across_delete_reaches_every_row_of_the_list() -> None:
    _notes(30, "Alpha")
    _notes(30, "Beta")
    client = _client()
    first = Note.objects.filter(title__startswith="Alpha").first()
    assert first is not None
    page = _act(
        client, Note, "delete_selected", first.pk, select_across="1", index="0", query="?q=Alpha"
    )
    html = page.content.decode()
    assert "Delete 30 notes?" in html
    assert 'name="select_across" value="1"' in html
    assert html.count('name="_selected_action"') == 1  # one row stands in, not all 30
    _act(
        client,
        Note,
        "delete_selected",
        first.pk,
        select_across="1",
        post="yes",
        query="?q=Alpha",
    )
    assert Note.objects.count() == 30
    assert not Note.objects.filter(title__startswith="Alpha").exists()


def test_select_across_restore_reaches_every_deleted_row() -> None:
    notes = _notes(40)
    for note in notes:
        note.delete()
    assert Note.objects.count() == 0
    _act(
        _client(),
        Note,
        "restore_selected",
        notes[0].pk,
        select_across="1",
        index="0",
        query="?deleted=deleted",
    )
    assert Note.objects.count() == 40


def test_select_across_edit_changes_every_row_of_the_list() -> None:
    Price.objects.bulk_create([Price(amount=i, currency="EUR") for i in range(1, 61)])
    client = _client()
    first = Price.objects.first()
    assert first is not None
    page = _act(client, Price, "edit_selected", first.pk, select_across="1", index="0")
    html = page.content.decode()
    assert "applies to 60 selected prices" in html
    assert 'name="select_across" value="1"' in html
    _act(
        client,
        Price,
        "edit_selected",
        first.pk,
        select_across="1",
        post="yes",
        apply__currency="on",
        currency="USD",
    )
    assert set(Price.objects.values_list("currency", flat=True)) == {"USD"}
    assert Price.objects.count() == 60


def test_select_across_edit_over_the_limit_changes_nothing_and_says_why() -> None:
    Price.objects.bulk_create([Price(amount=i, currency="EUR") for i in range(1, 61)])
    first = Price.objects.first()
    assert first is not None
    with override_settings(KARNI_ADMIN_BULK_EDIT_MAX=10):
        response = _client().post(
            _list(Price),
            {
                "action": "edit_selected",
                "_selected_action": [str(first.pk)],
                "select_across": "1",
                "index": "0",
                "post": "yes",
                "apply__currency": "on",
                "currency": "USD",
            },
            follow=True,
        )
    assert set(Price.objects.values_list("currency", flat=True)) == {"EUR"}
    text = " ".join(str(m) for m in response.context["messages"])
    assert "You selected 60 rows" in text and "at most 10" in text


def test_select_across_export_writes_every_row_of_the_list() -> None:
    Price.objects.bulk_create([Price(amount=i, currency="EUR") for i in range(1, 61)])
    first = Price.objects.first()
    assert first is not None
    response = _act(_client(), Price, "export_csv", first.pk, select_across="1", index="0")
    body = b"".join(response.streaming_content).decode()
    assert len(body.strip().splitlines()) == 61


# -- AP3: sorting and a stable order -------------------------------------------------


def _request() -> Any:
    request = RequestFactory().get("/")
    users = get_user_model()
    request.user = users.objects.filter(
        is_superuser=True
    ).first() or users.objects.create_superuser(email="o@example.com", password="x-1")
    return request


def test_a_list_without_an_order_gets_newest_updated_first() -> None:
    assert admin.site._registry[Widget].get_ordering(_request()) == ["-updated_at"]


def test_a_model_without_timestamps_is_ordered_by_its_key() -> None:
    assert admin.site._registry[Metric].get_ordering(_request()) == ["-pk"]


def test_the_models_own_ordering_and_the_admins_win() -> None:
    assert not admin.site._registry[Note].get_ordering(_request())  # Meta.ordering is used
    _notes(3)
    titles = [n.title for n in _client().get(_list(Note)).context["cl"].result_list]
    assert titles == sorted(titles)

    class Own(build_model_admin(Widget)):  # type: ignore[misc]
        ordering = ["name"]

    assert Own(Widget, AdminSite()).get_ordering(_request()) == ["name"]


def test_pages_never_shuffle_and_never_warn() -> None:
    _widgets(60)
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnorderedObjectListWarning)
        first = _page(Widget, per_page=25)
        second = _page(Widget, per_page=25, p=2)
    one = set(re.findall(r"Widget \d{3}", first))
    two = set(re.findall(r"Widget \d{3}", second))
    assert len(one) == len(two) == 25 and not one & two


def test_a_sortable_column_says_so_and_the_sorted_one_shows_its_direction() -> None:
    _widgets(3)
    html = _page(Widget, o="1")
    assert "sortable" in html and "sorted ascending" in html
    assert "sorted descending" in _page(Widget, o="-1")


# -- AP4: chips, search and the no-results state ------------------------------------


def test_active_filters_show_as_chips_with_remove_and_clear_all() -> None:
    KitchenSink.objects.create(name="One", status="draft", featured=True)
    html = _page(KitchenSink, status__exact="draft", featured__exact="1")
    assert html.count('class="karni-chip"') == 2
    assert "Status: Draft" in html and "Featured: Yes" in html
    assert 'class="karni-chip-all"' in html
    removes = re.findall(r'class="karni-chip-remove" href="([^"]*)"', html)
    assert len(removes) == 2
    assert all("status__exact" not in r or "featured__exact" not in r for r in removes)
    assert any("featured__exact" in r for r in removes) and any(
        "status__exact" in r for r in removes
    )


def test_no_chips_and_no_strip_without_a_filter() -> None:
    _widgets(3)
    html = _page(Widget)
    assert "karni-chips" not in html and "karni-chip-all" not in html


def test_one_filter_has_a_chip_but_no_clear_all() -> None:
    KitchenSink.objects.create(name="One", status="draft")
    html = _page(KitchenSink, status__exact="draft")
    assert html.count('class="karni-chip"') == 1 and "karni-chip-all" not in html


def test_search_keeps_its_term_counts_results_and_clears() -> None:
    _widgets(30)
    html = _page(Widget, q="Widget 00")
    assert "10 results for “Widget 00”" in html
    assert 'value="Widget 00"' in html
    assert "Clear search" in html
    one = _page(Widget, q="Widget 007")
    assert "1 result for “Widget 007”" in one


def test_a_search_or_filter_with_no_rows_is_not_the_empty_state() -> None:
    _widgets(3)
    html = _page(Widget, q="zzz")
    assert "No widgets match these filters" in html
    assert "No widgets yet." not in html
    assert "Clear search and filters" in html
    sink = _page(KitchenSink, status__exact="live")
    assert "No kitchen sinks yet." in sink or "No kitchen sinks match" in sink


def test_a_table_with_no_rows_says_none_yet() -> None:
    html = _page(Widget)
    assert "No widgets yet." in html and "match these filters" not in html


def test_the_changelist_survives_the_page_size_with_filters() -> None:
    KitchenSink.objects.create(name="One", status="draft")
    response = _client().get(_list(KitchenSink), {"status__exact": "draft", "per_page": 50})
    assert response.status_code == 200
    assert response.context["cl"].result_count == 1


# -- AP5: table polish ---------------------------------------------------------------


def test_the_row_count_sits_with_the_pagination_and_the_bar_is_at_the_bottom() -> None:
    _widgets(3)
    html = _page(Widget)
    assert 'class="karni-pagination"' in html
    assert html.index("Showing 1 to 3 of 3 widgets") > html.index('id="result_list"')


# -- AP6: plurals ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("singular", "plural"),
    [
        ("category", "categories"),
        ("entry", "entries"),
        ("country", "countries"),
        ("log entry", "log entries"),
        ("day", "days"),
        ("key", "keys"),
        ("box", "boxes"),
        ("quiz", "quizes"),
        ("church", "churches"),
        ("dish", "dishes"),
        ("bus", "buses"),
        ("address", "addresses"),
        ("status", "statuses"),
        ("person", "people"),
        ("child", "children"),
        ("analysis", "analyses"),
        ("series", "series"),
        ("staff", "staff"),
        ("settings", "settings"),
        ("note", "notes"),
        ("API key", "API keys"),
        ("leaf", "leaves"),
        ("hero", "heroes"),
    ],
)
def test_english_plurals(singular: str, plural: str) -> None:
    assert plural_of(singular) == plural


def test_the_menu_and_the_home_page_show_correct_plurals() -> None:
    html = _client().get("/admin/").content.decode()
    assert "Categorys" not in html and "Entrys" not in html
    assert "Categories" in html


def test_titles_use_the_plural_too() -> None:
    assert str(Category._meta.verbose_name_plural) == "categories"
    html = _page(Category)
    assert "Categorys" not in html and "categorys" not in html


def test_a_models_own_plural_always_wins() -> None:
    own = [m for m in admin.site._registry if "verbose_name_plural" in m._meta.original_attrs]
    assert own, "some registered model declares its own plural"
    for model in own:
        assert not getattr(model._meta, "_karni_plural", False), model
    from django.contrib.auth.models import Group

    assert str(Group._meta.verbose_name_plural) == "groups"


def test_no_migration_comes_from_a_corrected_plural() -> None:
    options = ModelState.from_model(Category).options
    assert "verbose_name_plural" not in options


def test_another_language_keeps_djangos_rule() -> None:
    from django.utils import translation

    with translation.override("de"):
        assert str(Category._meta.verbose_name_plural) == "categorys"
    with translation.override("en"):
        assert str(Category._meta.verbose_name_plural) == "categories"


# -- plurals in messages and file names -----------------------------------------------


def test_the_plural_reaches_messages_and_export_file_names() -> None:
    cats = [Category.objects.create(name=f"C{i}") for i in range(3)]
    client = _client()
    export = client.post(
        _list(Category),
        {"action": "export_csv", "_selected_action": [str(c.pk) for c in cats], "index": "0"},
    )
    assert "categories.csv" in export["Content-Disposition"]
    page = client.post(
        _list(Category),
        {"action": "delete_selected", "_selected_action": [str(c.pk) for c in cats]},
    )
    assert "Delete 3 categories?" in page.content.decode()


# -- AP10: a deleted row offers Restore, not Edit -------------------------------------


def test_a_deleted_row_shows_restore_alone_and_a_live_row_edit_and_delete() -> None:
    live, gone = _notes(2)
    gone.delete()
    html = _page(Note, deleted="all")
    row_gone = html[html.index(f'aria-label="Restore {gone}"') - 400 :]
    assert f'aria-label="Edit {gone}"' not in html
    assert f'aria-label="Delete {gone}"' not in html
    assert f'aria-label="Restore {gone}"' in html
    assert f'aria-label="Edit {live}"' in html and f'aria-label="Delete {live}"' in html
    assert row_gone


# -- AP11: names axe wants, added by the admin's script -------------------------------


def test_the_accessibility_script_names_select2_search_boxes_tooltips_and_blank_headings() -> None:
    from pathlib import Path

    import karni.admin as admin_package

    script = Path(admin_package.__file__).parent / "static" / "karni" / "admin-a11y.js"
    text = script.read_text()
    assert ".select2-search__field" in text  # a label for the many-to-many search box
    assert ".help-tooltip[aria-label]:not([role])" in text  # aria-label needs a role
    assert "th:not([data-karni-named])" in text  # blank table headings get text
