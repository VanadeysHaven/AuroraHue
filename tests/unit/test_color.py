"""Table-driven tests for colour parsing and conversion in `aurorahue.core.color`."""

import pytest

from aurorahue.core.color import (
    Hex,
    InvalidColor,
    Kelvin,
    hex_to_xy,
    kelvin_to_mirek,
    mirek_to_kelvin,
    parse_brightness,
    parse_color,
    xy_to_hex,
)
from aurorahue.core.errors import InvalidInput


@pytest.mark.parametrize(
    ("text", "expected", "kind"),
    [
        ("#FF8800", "#ff8800", Hex),
        ("ff8800", "#ff8800", Hex),
        ("#f80", "#ff8800", Hex),
        ("F80", "#ff8800", Hex),
        ("2700K", "2700K", Kelvin),
        ("2700k", "2700K", Kelvin),
        ("2700 K", "2700K", Kelvin),
        (" 2700k ", "2700K", Kelvin),
        ("2000K", "2000K", Kelvin),
        ("6500K", "6500K", Kelvin),
    ],
)
def test_parse_color_accepts(text: str, expected: str, kind: type) -> None:
    result = parse_color(text)
    assert str(result) == expected
    assert isinstance(result, kind)


@pytest.mark.parametrize(
    "text",
    [
        "#ff880",
        "#gg0000",
        "",
        "#ff88001",
        "#000000",
        "000",
        "1999K",
        "6501K",
        "K",
        "27.5K",
        "2700",
    ],
)
def test_parse_color_rejects(text: str) -> None:
    with pytest.raises(InvalidColor):
        parse_color(text)


def test_bare_number_error_suggests_kelvin() -> None:
    with pytest.raises(InvalidColor) as exc:
        parse_color("2700")
    assert "2700K" in exc.value.message


def test_invalid_color_is_invalid_input() -> None:
    assert issubclass(InvalidColor, InvalidInput)


@pytest.mark.parametrize(
    ("hex_value", "expected_xy"),
    [
        ("#ff0000", (0.6401, 0.3300)),
        ("#00ff00", (0.3000, 0.6000)),
        ("#0000ff", (0.1500, 0.0600)),
        ("#ffffff", (0.3127, 0.3290)),
        ("#ff8800", (0.5336, 0.4145)),
    ],
)
def test_hex_to_xy(hex_value: str, expected_xy: tuple[float, float]) -> None:
    assert hex_to_xy(Hex(hex_value)) == pytest.approx(expected_xy, abs=0.001)


def test_hex_to_xy_ignores_brightness() -> None:
    assert hex_to_xy(Hex("#330000")) == hex_to_xy(Hex("#ff0000"))


@pytest.mark.parametrize("hex_value", ["#ff0000", "#00ff00", "#0000ff", "#ffffff", "#ff8800"])
def test_xy_round_trip(hex_value: str) -> None:
    assert xy_to_hex(*hex_to_xy(Hex(hex_value))) == hex_value


def test_xy_round_trip_blue_grey() -> None:
    assert xy_to_hex(*hex_to_xy(Hex("#336699"))) == "#5badff"


@pytest.mark.parametrize(
    ("kelvin", "kwargs", "expected"),
    [
        (2700, {}, 370),
        (6500, {}, 154),
        (2000, {}, 500),
        (2000, {"hi": 454}, 454),
        (6500, {"lo": 160}, 160),
    ],
)
def test_kelvin_to_mirek(kelvin: int, kwargs: dict[str, int], expected: int) -> None:
    assert kelvin_to_mirek(kelvin, **kwargs) == expected


@pytest.mark.parametrize(("mirek", "expected"), [(370, 2700), (447, 2250)])
def test_mirek_to_kelvin(mirek: int, expected: int) -> None:
    assert mirek_to_kelvin(mirek) == expected


@pytest.mark.parametrize(("percent", "expected"), [(0, 0), (100, 100), (55, 55)])
def test_parse_brightness_accepts(percent: int, expected: int) -> None:
    assert parse_brightness(percent) == expected


@pytest.mark.parametrize("percent", [-1, 101])
def test_parse_brightness_rejects(percent: int) -> None:
    with pytest.raises(InvalidInput):
        parse_brightness(percent)
