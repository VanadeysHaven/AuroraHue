"""Light access rules (D1-D3): `LightAccess` and parsing via `load_light_access`."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from aurorahue.config import ConfigError, load_light_access
from aurorahue.core.access import LightAccess

A = "8a94b76b-eb9f-42fb-8b58-8c8701a80283"
B = "0c836d0d-ad3e-4527-802b-b5d0911b7b33"
C = "e8ff6285-fc12-44da-aa8e-c5f98ec167dd"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "lights.json"
    path.write_text(text, encoding="utf-8")
    return path


def _access_for(path: Path) -> LightAccess:
    return load_light_access(path)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(None, {A: True, B: True, C: True}, id="no-file"),
        pytest.param({"whitelist": True}, {A: True, B: True, C: True}, id="whitelist-no-lights"),
        pytest.param(
            {"whitelist": True, "lights": []}, {A: True, B: True, C: True}, id="whitelist-empty"
        ),
        pytest.param({"whitelist": False}, {A: True, B: True, C: True}, id="blacklist-no-lights"),
        pytest.param(
            {"whitelist": False, "lights": []}, {A: True, B: True, C: True}, id="blacklist-empty"
        ),
        pytest.param(
            {"whitelist": True, "lights": [A, B]},
            {A: True, B: True, C: False},
            id="whitelist-A-B",
        ),
        pytest.param(
            {"whitelist": False, "lights": [A]},
            {A: False, B: True, C: True},
            id="blacklist-A",
        ),
        pytest.param(
            {"whitelist": True, "lights": [A, A]},
            {A: True, B: False, C: False},
            id="duplicate-ids",
        ),
    ],
)
def test_allows(tmp_path: Path, content: dict | None, expected: dict[str, bool]) -> None:
    path = tmp_path / "missing.json"
    if content is not None:
        path = _write(tmp_path, json.dumps(content))

    access = _access_for(path)

    for light_id, allowed in expected.items():
        assert access.allows(light_id) is allowed, light_id


def test_listed_uppercase_id_matches_lowercase_bridge_id(tmp_path: Path) -> None:
    path = _write(tmp_path, json.dumps({"whitelist": True, "lights": [A.upper()]}))

    access = _access_for(path)

    assert access.allows(A) is True
    assert access.allows(B) is False


def test_listed_lowercase_id_matches_uppercase_bridge_id(tmp_path: Path) -> None:
    path = _write(tmp_path, json.dumps({"whitelist": True, "lights": [A]}))

    access = _access_for(path)

    assert access.allows(A.upper()) is True
    assert access.allows(B.upper()) is False


@pytest.mark.parametrize(
    ("text", "field"),
    [
        pytest.param('{"whitelist": tr', "(file): Invalid JSON", id="invalid-json"),
        pytest.param("{}", "whitelist", id="whitelist-missing"),
        pytest.param('{"whitelist": "true"}', "whitelist", id="whitelist-string"),
        pytest.param('{"whitelist": 1}', "whitelist", id="whitelist-int"),
        pytest.param('{"whitelist": true, "lights": ["not-a-uuid"]}', "lights.0", id="bad-uuid"),
        pytest.param('{"whitelist": true, "lights": "x"}', "lights", id="lights-not-list"),
        pytest.param('{"whitelist": true, "blacklist": true}', "blacklist", id="unknown-field"),
    ],
)
def test_invalid_file_is_refused(tmp_path: Path, text: str, field: str) -> None:
    path = _write(tmp_path, text)

    with pytest.raises(ConfigError) as excinfo:
        load_light_access(path)

    # Match the problem line, not the path (the file name itself contains "lights").
    assert f"\n  {field}" in str(excinfo.value)


def test_describe_whitelist() -> None:
    access = LightAccess(whitelist=True, lights=frozenset({UUID(A)}))

    assert access.describe() == "whitelist, 1 light"


def test_describe_blacklist() -> None:
    access = LightAccess(whitelist=False, lights=frozenset({UUID(A), UUID(B)}))

    assert access.describe() == "blacklist, 2 lights"


def test_describe_empty() -> None:
    assert LightAccess(whitelist=True).describe() == "all lights (empty list)"


def test_unknown_returns_listed_ids_missing_from_bridge() -> None:
    access = LightAccess(whitelist=True, lights=frozenset({UUID(A), UUID(B)}))

    assert access.unknown([A.upper(), C]) == [UUID(B)]
