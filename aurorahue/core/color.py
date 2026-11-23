"""Colours (D9) and brightness (D10): parsing user text and converting for the Hue bridge.

Pure: no I/O. `str(color)` is the stored/displayed form (`#ff8800`, `2700K`); `parse_color` reads
both user text and that stored form.
"""

import re
from dataclasses import dataclass

from aurorahue.core.errors import InvalidInput

KELVIN_MIN = 2000
KELVIN_MAX = 6500

# Hue's usual `mirek_schema` (6500 K .. 2000 K); a light's own range narrows it.
MIREK_MIN = 153
MIREK_MAX = 500

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
_HEX_INPUT_RE = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$")
_BARE_NUMBER_RE = re.compile(r"^[0-9]{4}$")

_COLOR_HELP = "Use a hex colour like #ff8800 or a white temperature like 2700K."


class InvalidColor(InvalidInput):
    """Colour text that isn't a hex colour or a white temperature (D9)."""


@dataclass(frozen=True)
class Hex:
    """A colour as normalised `#rrggbb` (lowercase)."""

    value: str

    def __post_init__(self) -> None:
        if not _HEX_RE.fullmatch(self.value):
            raise ValueError(f"not a normalised #rrggbb colour: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Kelvin:
    """A white temperature in Kelvin, 2000–6500."""

    value: int

    def __post_init__(self) -> None:
        if not KELVIN_MIN <= self.value <= KELVIN_MAX:
            raise ValueError(f"temperature out of range: {self.value}K")

    def __str__(self) -> str:
        return f"{self.value}K"


type Color = Hex | Kelvin


def parse_color(text: str) -> Color:
    """Read a hex colour or a Kelvin temperature (D9); raises `InvalidColor` with a user message."""
    value = text.strip().lower()
    if not value:
        raise InvalidColor(f"Give a colour. {_COLOR_HELP}")
    if value.endswith("k"):
        return _parse_kelvin(value[:-1].strip())
    if _BARE_NUMBER_RE.fullmatch(value):
        raise InvalidColor(f"Add K for a temperature ({value}K) or use a hex colour (#ff8800).")
    match = _HEX_INPUT_RE.fullmatch(value)
    if match is None:
        raise InvalidColor(f"That isn't a colour. {_COLOR_HELP}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if digits == "000000":
        raise InvalidColor("#000000 is no colour; use /off to switch lights off.")
    return Hex(f"#{digits}")


def _parse_kelvin(number: str) -> Kelvin:
    if not number.isdecimal() or not number.isascii():
        raise InvalidColor("A temperature is a whole number followed by K, like 2700K.")
    kelvin = int(number)
    if not KELVIN_MIN <= kelvin <= KELVIN_MAX:
        raise InvalidColor(f"Temperatures go from {KELVIN_MIN}K to {KELVIN_MAX}K.")
    return Kelvin(kelvin)


def parse_brightness(percent: int) -> int:
    """Brightness as a whole percentage 0–100 (D10: 0 is the lowest glow, not off)."""
    if not 0 <= percent <= 100:
        raise InvalidInput("Brightness is a percentage from 0 to 100.")
    return percent


def hex_to_xy(color: Hex) -> tuple[float, float]:
    """CIE xy of a hex colour (sRGB, D65). Only hue and saturation count: `#330000` == `#ff0000`."""
    r, g, b = (_expand_gamma(int(color.value[i : i + 2], 16) / 255) for i in (1, 3, 5))
    x_ = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y_ = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z_ = 0.0193 * r + 0.1192 * g + 0.9505 * b
    total = x_ + y_ + z_
    if total == 0:
        raise ValueError("#000000 has no colour")
    return round(x_ / total, 4), round(y_ / total, 4)


def kelvin_to_mirek(kelvin: int, lo: int = MIREK_MIN, hi: int = MIREK_MAX) -> int:
    """`round(1_000_000 / K)`, clamped to the light's `mirek_schema` range."""
    return max(lo, min(hi, round(1_000_000 / kelvin)))


def mirek_to_kelvin(mirek: int) -> int:
    """`1_000_000 / mirek`, rounded to the nearest 50 K (for `/lights`)."""
    return round(1_000_000 / mirek / 50) * 50


def xy_to_hex(x: float, y: float) -> str:
    """The nearest `#rrggbb` of a CIE xy point at full brightness (for `/lights`)."""
    if y <= 0:
        raise ValueError(f"y must be positive: {y}")
    big_x, big_y, big_z = x / y, 1.0, (1 - x - y) / y
    rgb = (
        3.2406 * big_x - 1.5372 * big_y - 0.4986 * big_z,
        -0.9689 * big_x + 1.8758 * big_y + 0.0415 * big_z,
        0.0557 * big_x - 0.2040 * big_y + 1.0570 * big_z,
    )
    rgb = tuple(max(0.0, v) for v in rgb)
    largest = max(rgb)
    if largest == 0:
        return "#000000"
    return "#" + "".join(f"{round(_compress_gamma(v / largest) * 255):02x}" for v in rgb)


def _expand_gamma(v: float) -> float:
    return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92


def _compress_gamma(v: float) -> float:
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
