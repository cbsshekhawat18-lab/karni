"""``karni make model --order`` and ``--key``: the ordering and the field ``karni load`` matches.

A model's rows read in their designed order (``Meta.ordering``), and rows
nested under a parent in a content file (a project's gallery) are matched on
the parent plus a field such as ``position`` (``Karni.import_key``).
"""

from __future__ import annotations

from pathlib import Path

from .test_make import fails, ok, project  # noqa: F401 - the project fixture


def test_order_and_key_are_written_into_the_model(project: Path) -> None:  # noqa: F811
    ok("make", "app", "website")
    ok(
        "make",
        "model",
        "Project",
        "title:str:80",
        "position:int",
        "--app",
        "website",
        "--order",
        "position",
    )
    ok(
        "make", "model", "ProjectImage", "project:fk:Project", "image:image", "position:int",
        "--app", "website", "--order", "position", "--key", "position",
    )  # fmt: skip
    source = (project / "website" / "models.py").read_text()
    assert '    class Meta:\n        ordering = ["position"]\n' in source
    assert '    class Karni:\n        import_key = "position"\n' in source
    assert source.count("class Meta:") == 2 and source.count("class Karni:") == 1
    ok("make", "model", "Note", "body:text", "--app", "website", "--order", "-created_at")
    assert 'ordering = ["-created_at"]' in (project / "website" / "models.py").read_text()


def test_order_and_key_must_name_a_field(project: Path) -> None:  # noqa: F811
    ok("make", "app", "website")
    fails(
        "make", "model", "Slide", "title:str", "--app", "website", "--order", "position",
        match="C104",
    )  # fmt: skip
    message = fails(
        "make", "model", "Slide", "title:str", "--app", "website", "--key", "rank", match="C104"
    )
    assert "'rank' is not a field of the model (fields: title)" in message
