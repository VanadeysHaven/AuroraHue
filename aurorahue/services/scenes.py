"""Scenes (D13–D17): saving, listing, deleting and running named sets of light actions.

No discord here. Every rule is checked when a scene is saved; running a scene goes through
`LightService.apply`, which checks the access file again and skips what is no longer allowed.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aurorahue.core.clock import Clock
from aurorahue.core.color import parse_brightness, parse_color
from aurorahue.core.errors import InvalidInput, NameTaken, NotAllowed, NotFound
from aurorahue.db.models import SCENE_NAME_MAX, SETTINGS_ROW_ID, BotSettings, Scene, SceneAction
from aurorahue.services.lights import ApplyReport, LightRequest, LightService
from aurorahue.services.model import SessionFactory, StrictModel


class ActionInput(StrictModel):
    """What one light does in a scene (D13). Empty colour/brightness keep the light's value."""

    light_id: str
    on: bool
    color: str | None = None  # hex or Kelvin as typed (D9); stored normalised
    brightness: int | None = None  # percent (D10)


class SceneInput(StrictModel):
    name: str
    actions: tuple[ActionInput, ...]


class SceneView(StrictModel):
    id: int
    name: str
    actions: tuple[ActionInput, ...]  # stored form: colour '#rrggbb' / '2700K'
    is_reset: bool  # the reset scene (D19)


class SceneService:
    def __init__(self, sessions: SessionFactory, lights: LightService, clock: Clock) -> None:
        self._sessions = sessions
        self._lights = lights
        self._clock = clock

    async def list_scenes(self) -> list[SceneView]:
        """Every scene, sorted by name (any case)."""
        async with self._sessions() as session:
            reset_id = await _reset_scene_id(session)
            scenes = await session.scalars(
                select(Scene)
                .options(selectinload(Scene.actions))
                .order_by(func.lower(Scene.name), Scene.id)
            )
            return [_view(scene, reset_id) for scene in scenes]

    async def get(self, name: str) -> SceneView:
        """The scene with this name, any case (D13). Raises `NotFound`."""
        async with self._sessions() as session:
            scene = await session.scalar(
                select(Scene)
                .options(selectinload(Scene.actions))
                .where(func.lower(Scene.name) == func.lower(name.strip()))
            )
            if scene is None:
                raise NotFound(f'No scene named "{name.strip()}".')
            return _view(scene, await _reset_scene_id(session))

    async def get_by_id(self, scene_id: int) -> SceneView:
        """Raises `NotFound` if the scene was deleted meanwhile."""
        async with self._sessions() as session:
            return await _load_view(session, scene_id)

    async def create(self, actor_id: int, data: SceneInput) -> SceneView:
        """Save a new scene. Raises `InvalidInput`, `NameTaken`, `NotAllowed`,
        `BridgeUnavailable` (the allowed lights are read from the bridge)."""
        name, actions = await self._validate(data)
        now = self._clock.now()
        async with self._sessions() as session:
            await _check_name_free(session, name, exclude_id=None)
            scene = Scene(
                name=name,
                created_by=actor_id,
                created_at=now,
                updated_at=now,
                actions=[_row(action) for action in actions],
            )
            session.add(scene)
            await _flush_or_name_taken(session, name)
            await session.commit()
            return await _load_view(session, scene.id)

    async def update(self, scene_id: int, data: SceneInput) -> SceneView:
        """Replace the scene's name and all its actions (D16: last save wins).

        `data.name` is the name after the update (the same one, or a new one).
        Raises like `create`, plus `NotFound` if the scene was deleted meanwhile.
        """
        name, actions = await self._validate(data)
        async with self._sessions() as session:
            scene = await session.get(Scene, scene_id)
            if scene is None:
                raise _gone()
            await _check_name_free(session, name, exclude_id=scene_id)
            scene.name = name
            scene.updated_at = self._clock.now()
            # Delete first, so a light kept in the scene doesn't hit uq (scene_id, light_id).
            await session.execute(delete(SceneAction).where(SceneAction.scene_id == scene_id))
            session.add_all(_row(action, scene_id) for action in actions)
            await _flush_or_name_taken(session, name)
            await session.commit()
            return await _load_view(session, scene_id)

    async def delete(self, scene_id: int) -> SceneView:
        """Delete a scene and its actions. If it was the reset scene, the setting is cleared by
        the database (D19); the returned view's `is_reset` says so. Raises `NotFound`."""
        async with self._sessions() as session:
            view = await _load_view(session, scene_id)
            await session.execute(delete(Scene).where(Scene.id == scene_id))
            await session.commit()
            return view

    async def actions_for_run(self, scene_id: int) -> tuple[ActionInput, ...]:
        """The scene's stored actions (callers use them for D21's "does anything go on?")."""
        return (await self.get_by_id(scene_id)).actions

    async def run(self, scene_id: int) -> ApplyReport:
        """Apply each action to its light (D17). Lights now disallowed or gone are skipped and
        reported by `LightService.apply`; a light that fails doesn't stop the others."""
        actions = await self.actions_for_run(scene_id)
        requests = {
            action.light_id: LightRequest(
                on=action.on,
                color=parse_color(action.color) if action.color is not None else None,
                brightness=action.brightness,
            )
            for action in actions
        }
        return await self._lights.apply(list(requests), requests)

    async def _validate(self, data: SceneInput) -> tuple[str, list[ActionInput]]:
        """Check every D13 rule; return the trimmed name and the actions in stored form."""
        name = data.name.strip()
        if not 1 <= len(name) <= SCENE_NAME_MAX:
            raise InvalidInput(f"A scene name is 1 to {SCENE_NAME_MAX} characters.")
        if not data.actions:
            raise InvalidInput("A scene needs at least one light.")
        light_ids = [action.light_id for action in data.actions]
        if len(set(light_ids)) != len(light_ids):
            raise InvalidInput("Each light can only be in a scene once.")

        actions: list[ActionInput] = []
        for action in data.actions:
            if not action.on and (action.color is not None or action.brightness is not None):
                raise InvalidInput("A light that's switched off takes no colour or brightness.")
            actions.append(
                action.model_copy(
                    update={
                        "color": str(parse_color(action.color))
                        if action.color is not None
                        else None,
                        "brightness": parse_brightness(action.brightness)
                        if action.brightness is not None
                        else None,
                    }
                )
            )

        # Every light must be allowed now, at save time (brief §6). A disallowed light has no
        # name the user may see (D4), so the message doesn't name it.
        allowed_ids = {light.id for light in await self._lights.allowed()}
        if any(light_id not in allowed_ids for light_id in light_ids):
            raise NotAllowed("This scene has a light the bot may not control.")
        return name, actions


def _row(action: ActionInput, scene_id: int | None = None) -> SceneAction:
    row = SceneAction(
        light_id=action.light_id,
        is_on=action.on,
        color=action.color,
        brightness=action.brightness,
    )
    if scene_id is not None:
        row.scene_id = scene_id
    return row


def _view(scene: Scene, reset_id: int | None) -> SceneView:
    return SceneView(
        id=scene.id,
        name=scene.name,
        actions=tuple(
            ActionInput(
                light_id=action.light_id,
                on=action.is_on,
                color=action.color,
                brightness=action.brightness,
            )
            for action in scene.actions
        ),
        is_reset=scene.id == reset_id,
    )


async def _load_view(session: AsyncSession, scene_id: int) -> SceneView:
    scene = await session.scalar(
        select(Scene)
        .options(selectinload(Scene.actions))
        .where(Scene.id == scene_id)
        .execution_options(populate_existing=True)
    )
    if scene is None:
        raise _gone()
    return _view(scene, await _reset_scene_id(session))


async def _reset_scene_id(session: AsyncSession) -> int | None:
    return await session.scalar(
        select(BotSettings.reset_scene_id).where(BotSettings.id == SETTINGS_ROW_ID)
    )


async def _check_name_free(session: AsyncSession, name: str, *, exclude_id: int | None) -> None:
    query = select(Scene.name).where(func.lower(Scene.name) == func.lower(name))
    if exclude_id is not None:
        query = query.where(Scene.id != exclude_id)
    existing = await session.scalar(query)
    if existing is not None:
        raise NameTaken(f'There is already a scene named "{existing}".')


async def _flush_or_name_taken(session: AsyncSession, name: str) -> None:
    """Flush; a concurrent save that took the name first trips `uq_scenes_lower_name`."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_scenes_lower_name" in str(exc.orig):
            raise NameTaken(f'There is already a scene named "{name}".') from exc
        raise


def _gone() -> NotFound:
    return NotFound("That scene doesn't exist any more.")
