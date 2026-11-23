"""`python main.py lights` (D23): every bridge light with its UUID, for editing the access file.

Needs only the Hue settings, no Discord token or database. Writes the table to stdout (it is the
command's output, not a log message).
"""

import sys

from aurorahue.config import HueSettings, load_light_access
from aurorahue.core.access import LightAccess
from aurorahue.hue.hue_client import BridgeLight, HueClient

HEADERS = ("UUID", "Name", "Colour", "Temperature", "Dimming", "Allowed")


async def print_lights(settings: HueSettings) -> int:
    """Print the table; return the exit code. Raises `ConfigError` for a broken access file."""
    access = load_light_access(settings.lights_config)
    if not settings.bridge_ip or not settings.app_key:
        sys.stderr.write("HUE_BRIDGE_IP and HUE_APP_KEY must be set (see .env.example).\n")
        return 1

    client = HueClient(settings.bridge_ip, settings.app_key)
    try:
        lights = await client.list_lights()
    finally:
        await client.aclose()

    sys.stdout.write(format_table(lights, access) + "\n")
    unknown = access.unknown(light.id for light in lights)
    if unknown:
        sys.stdout.write(
            f"\nIn {settings.lights_config} but not on the bridge: "
            + ", ".join(str(light_id) for light_id in unknown)
            + "\n"
        )
    return 0


def format_table(lights: list[BridgeLight], access: LightAccess) -> str:
    rows = [
        (
            light.id,
            light.name,
            _yes_no(light.supports_color),
            _yes_no(light.supports_temperature),
            _yes_no(light.supports_dimming),
            _yes_no(access.allows(light.id)),
        )
        for light in sorted(lights, key=lambda light: (light.name.casefold(), light.id))
    ]
    widths = [max(len(row[i]) for row in [HEADERS, *rows]) for i in range(len(HEADERS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in [HEADERS, *rows]
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
