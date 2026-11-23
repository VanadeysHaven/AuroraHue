"""Errors meant for users: each carries a user-safe `.message`.

Commands raise them; one Discord error handler shows `.message` ephemerally.
"""


class AuroraHueError(Exception):
    """Base class for errors whose message may be shown to a Discord user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(AuroraHueError):
    """A named thing (light, scene) doesn't exist or isn't visible to the bot."""


class NameTaken(AuroraHueError):
    """A scene name is already used."""


class InvalidInput(AuroraHueError):
    """User input that breaks a rule (length, range, combination)."""


class NotAllowed(AuroraHueError):
    """A light the access file doesn't allow."""


class BridgeUnavailable(AuroraHueError):
    """The Hue bridge didn't answer, or answered with an error."""

    def __init__(self, message: str = "Can't reach the Hue bridge.") -> None:
        super().__init__(message)
