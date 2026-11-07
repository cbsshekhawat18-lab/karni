"""``karni make model --pk`` and ``KARNI_PK``: the key type shows in the model's class line.

``uuid`` writes ``BaseModel`` and ``bigint`` writes ``BigIntBaseModel``
(experimental). ``KARNI_PK`` in config/settings.py picks the default, read
statically like ``KARNI_ROLES``, and ``--pk`` overrides it for one model.
"""

from __future__ import annotations

from pathlib import Path

from .test_make import fails, ok, project  # noqa: F401 - the project fixture


def _settings(root: Path, line: str) -> None:
    settings = root / "config" / "settings.py"
    settings.write_text(settings.read_text() + f"\n{line}\n")


def test_pk_bigint_writes_bigintbasemodel_next_to_basemodel(project: Path) -> None:  # noqa: F811
    ok("make", "app", "sensors")
    ok("make", "model", "Reading", "value:int", "--app", "sensors", "--pk", "bigint")
    ok("make", "model", "Sensor", "name:str:80", "--app", "sensors")
    source = (project / "sensors" / "models.py").read_text()
    assert "class Reading(BigIntBaseModel):" in source
    assert "class Sensor(BaseModel):" in source
    assert "BigIntBaseModel" in source.split("class Reading")[0]  # imported once, above
    assert "BaseModel" in source.split("class Reading")[0]


def test_karni_pk_picks_the_default_and_pk_overrides_it(project: Path) -> None:  # noqa: F811
    _settings(project, 'KARNI_PK = "bigint"')
    ok("make", "app", "sensors")
    ok("make", "model", "Reading", "value:int", "--app", "sensors")
    ok("make", "model", "Sensor", "name:str:80", "--app", "sensors", "--pk", "uuid")
    source = (project / "sensors" / "models.py").read_text()
    assert "class Reading(BigIntBaseModel):" in source
    assert "class Sensor(BaseModel):" in source


def test_the_last_assignment_wins(project: Path) -> None:  # noqa: F811
    _settings(project, 'KARNI_PK = "bigint"\nKARNI_PK = "uuid"')
    ok("make", "app", "sensors")
    ok("make", "model", "Reading", "value:int", "--app", "sensors")
    assert "class Reading(BaseModel):" in (project / "sensors" / "models.py").read_text()


def test_an_unknown_key_type_is_refused(project: Path) -> None:  # noqa: F811
    ok("make", "app", "sensors")
    message = fails(
        "make", "model", "Reading", "value:int", "--app", "sensors", "--pk", "int", match="C106"
    )
    assert "uuid, bigint" in message
    _settings(project, 'KARNI_PK = "serial"')
    message = fails("make", "model", "Reading", "value:int", "--app", "sensors", match="C106")
    assert "KARNI_PK = 'serial'" in message
    assert not (project / "sensors" / "models.py").read_text().count("class Reading")


def test_a_computed_karni_pk_is_named_and_uuid_is_written(project: Path) -> None:  # noqa: F811
    _settings(project, 'import os\nKARNI_PK = os.environ.get("KARNI_PK", "uuid")')
    ok("make", "app", "sensors")
    result = ok("make", "model", "Reading", "value:int", "--app", "sensors")
    assert "KARNI_PK in config/settings.py is computed" in result.output
    assert "class Reading(BaseModel):" in (project / "sensors" / "models.py").read_text()
