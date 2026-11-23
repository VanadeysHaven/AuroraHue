"""Colours (D9): a hex colour or a white temperature, and their conversion for the Hue bridge.

Pure: no I/O. Parsing user text (`parse_color`) and the reverse conversions for `/lights`
arrive with the direct light commands.
"""

import re
from dataclasses import dataclass

KELVIN_MIN = 2000
KELVIN_MAX = 6500

# Hue's usual `mirek_schema` (6500 K .. 2000 K); a light's own range narrows it.
MIREK_MIN = 153
MIREK_MAX = 500

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


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


def _expand_gamma(v: float) -> float:
    return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92
