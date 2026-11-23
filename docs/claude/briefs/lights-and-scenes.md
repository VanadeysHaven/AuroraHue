# Brief — Light access file, scenes, and the new light commands

**Status:** in progress (segments 1 and 2 done; 3 and 4 waiting for review, 2026-11-23).
**Slug:** `lights-and-scenes` · **Migrations:** `0001` (empty base), `0002` (scenes + settings)
Written by Claude (Opus 5.5), 2026-11-23.

**Goal:** AuroraHue stops hard-coding its lights. A config file says which lights the bot may touch.
Scenes (one action per light) are stored in PostgreSQL and can be added, edited, deleted and run
from Discord. `/color`, `/brightness`, `/reset` and `/settings` are new; `/on` and `/off` take an
optional set of lights; `/minimum` and `/soft` go away.

**Read first:** `CLAUDE.md` (all of it, it's short). Then §1–§8 below, then **only** your segment.

| Seg | Title | Branch | Status |
|---|---|---|---|
| 1 | Database foundation (Postgres, Alembic, tests) | `claude/lights-and-scenes-s1` | ✅ done |
| 2 | Light registry and the access file | `claude/lights-and-scenes-s2` | ✅ done |
| 3 | Direct light commands | `claude/lights-and-scenes-s3` | 👀 waiting for review |
| 4 | Scenes and settings: schema and services | `claude/lights-and-scenes-s4` | 👀 waiting for review |
| 5 | Scene commands, `/reset`, `/settings`, docs | `claude/lights-and-scenes-s5` | ⬜ todo |

Segments 1 and 2 are independent (either order). 3 needs 2. 4 needs 1 (and 2's light registry for
validation). 5 needs 3 and 4. Legend: ⬜ todo · 🔨 in progress · 👀 waiting for review · ✅ done.

---

## 1. Decisions

Source "Tim" = from the request. "Claude" = proposed default; Tim confirms or changes it via §9
before the brief goes `ready`.

| ID | Decision | Source |
|---|---|---|
| D1 | Light access lives in a file the bot only **reads, once at startup**: `configs/lights.json`, loaded and validated with pydantic. No command can change it. Restart the bot after editing. | Tim |
| D2 | The file is **either** a whitelist **or** a blacklist, never both: `"whitelist": true` = only the listed lights, `false` = every light except them. An empty `lights` list means every light on the bridge is allowed, whatever `whitelist` says. | Tim |
| D3 | No file at all = everything allowed, with a warning in the log. A broken file (invalid JSON, `whitelist` missing or not a boolean, an ID that isn't a UUID, an unknown key) = the bot **refuses to start** with pydantic's error, readably formatted. IDs that aren't on the bridge = a warning, not an error. | Claude |
| D4 | Lights are identified in the file by their CLIP v2 **UUID**; everywhere in Discord by their **name** (`metadata.name` from the bridge). A disallowed light never shows up in Discord: not in autocomplete, `/lights`, the scene builder or replies. | Tim (IDs), Claude (names) |
| D5 | The list of lights comes from the bridge (`GET /resource/light`), cached for 60 s. Bridge unreachable at startup → the bot still starts; commands report "Can't reach the Hue bridge." | Claude |
| D6 | Commands that take lights have an optional `lights` option: comma-separated light names (case-insensitive), picked from autocomplete: the list shows the allowed lights by name, and after a comma it offers the remaining ones as `"<already picked>, <next>"`, so several lights can be picked from the list one after another (typing still works). Empty = all allowed lights. An unknown or disallowed name → error naming it, nothing changes. | Tim |
| D7 | `/on [lights]` only switches lights on (`on: true`), keeping their last colour and brightness. The `ON_STATE` preset goes. `/off [lights]` only switches them off. | Tim |
| D8 | `/color color [lights]` sets a colour (D9); `/brightness percent [lights]` sets brightness. Both **also switch the lights on**. | Tim |
| D9 | **One colour field everywhere** (`/color`, the builder's Colour): either a **hex colour** (`#rrggbb`, `rrggbb`, `#rgb`, `rgb`, any case → stored `#rrggbb`) or a **white temperature** in Kelvin (`2700K`, `2700 k`, any case → stored `2700K`, range 2000–6500 K). The bot works out which one it is: a trailing `K` means temperature, anything else must be hex. A hex colour is sent as CIE xy; only its hue/saturation counts, its darkness is ignored (`#330000` = `#ff0000`), brightness is separate. A temperature is sent as `color_temperature.mirek = round(1 000 000 / K)`, clamped to that light's own range. Refused: `#000000` ("use /off"), out-of-range Kelvin, and a bare number like `2700` ("add K for a temperature (2700K) or use a hex colour (#ff8800)"). | Tim (one field, hex or K), Claude (details) |
| D10 | Brightness is a whole percentage 0–100. 0 is the lowest glow, **not off** (Hue behaviour; the option description says so). | Tim |
| D11 | A light that can't show what was asked skips the colour but still gets on/off and brightness, and the reply says "colour skipped for: …". Hex needs a colour bulb; a temperature needs a colour or white-ambiance bulb; a plain white bulb skips both. Tim's lights are all white and color ambiance today, so this is a safety net for bulbs added later. | Claude |
| D12 | `/minimum` and `/soft` are removed, with `MINIMUM_BRIGHTNESS`, `SOFT_BRIGHTNESS`, `ON_STATE` and `LIGHT_IDS`. | Tim |
| D13 | A **scene** has a unique name (1–50 chars, case-insensitive) and at most one **action** per light. An action is: on/off (required), colour (hex or temperature as in D9, optional), brightness (%, optional). Optional fields left empty keep the light's current value. An action with "off" has no colour or brightness. Lights not in the scene are left alone. | Tim |
| D14 | Scenes are global (one bridge, one home), not per Discord server. Stored in PostgreSQL with Alembic migrations, set up like Sidequest. | Tim |
| D15 | Scene commands: `/scene list [scene]`, `/scene add name`, `/scene edit scene [new-name]`, `/scene delete scene`, `/scene run scene`. A bare `/scene` isn't possible: Discord can't invoke a command group that has subcommands, so its job (see the scenes) goes to `/scene list`. | Tim |
| D16 | `/scene add` and `/scene edit` open a **scene builder** (an in-memory view, like Sidequest's week builder): an embed with one line per light in the scene, a **Set lights…** select (pick lights → a form with on/off, colour, brightness), a **Remove lights…** select, **Save** and **Cancel**. Owner-only; 14.5-minute timeout → "This scene editor expired; nothing was saved." Save needs at least one action. Last save wins. | Tim (builder), Claude (layout) |
| D17 | Running a scene applies each action to its light; actions for lights that are now disallowed or gone from the bridge are skipped and listed in the reply. Partial failures (a light didn't answer) are listed too; the others still change. | Tim |
| D18 | `/settings` holds bot-wide settings in the database. For now one: the **reset scene**. `/settings` with no options shows the settings; `/settings reset-scene:<scene>` sets it, `reset-scene:none` clears it. | Tim (reset scene), Claude (shape) |
| D19 | `/reset` runs the reset scene. None set → "No reset scene set. Pick one with `/settings reset-scene`." Deleting the reset scene asks for confirmation with an extra line ("This is the reset scene; `/reset` will do nothing until you pick another.") and clears the setting. | Tim |
| D20 | Who: `ALLOWED_USER_IDS` gates every light, scene and settings command (as today); no other permission levels. `/ping` stays open. | Tim |
| D21 | The daytime confirmation (same wording and sun check as today) applies to **every command that switches lights on**: `/on`, `/color`, `/brightness`, `/scene run`, `/reset`. It only asks when at least one targeted light that is **off right now** would go on (fresh bridge read, not the cache), so recolouring lights that are already on, or a scene that only switches lights off, doesn't ask. Buttons: **Go ahead** / **Cancel**. | Tim (all commands), Claude (only when something goes on) |
| D22 | Replies: light-changing commands (`/on`, `/off`, `/color`, `/brightness`, `/scene run`, `/reset`) reply publicly and short ("Turned on 3 lights."); everything else (lists, builder, settings, errors, confirmations) is ephemeral. No mentions ping. | Tim |
| D23 | New `/lights` command: the allowed lights with name, on/off, brightness and colour ("2700K" when the light is in white-temperature mode, otherwise the nearest hex at full brightness), ephemeral. And a CLI `python main.py lights` that prints **every** bridge light with its UUID, name, what it supports (colour / temperature / dimming) and whether the access file allows it, for editing the file. | Tim |
| D24 | The `ON_EXCLUDED_LIGHT_IDS` special case (one light skipped by `/on`) is dropped: with D7 there is no preset to protect it from. | Tim |

---

## 2. The access file

`configs/lights.json` (git-ignored; template `configs/lights.example.json` is tracked):

```json
{
  "whitelist": true,
  "lights": [
    "8a94b76b-eb9f-42fb-8b58-8c8701a80283",
    "0c836d0d-ad3e-4527-802b-b5d0911b7b33"
  ]
}
```

- `whitelist` (required, boolean): `true` = only these lights; `false` = all lights except these.
- `lights` (optional, default `[]`): CLIP v2 light UUIDs. Empty = every light is allowed (D2).
- JSON has no comments, so the file can't name the lights: `python main.py lights` (D23) shows which
  UUID is which, and the README explains the two keys.
- Model: `LightAccess` in `core/access.py`, a pydantic `BaseModel` with
  `model_config = ConfigDict(frozen=True, extra="forbid", strict=True)`, fields
  `whitelist: bool` and `lights: frozenset[UUID] = frozenset()`, and `allows(light_id: str) -> bool`
  (compares as `UUID`, so case doesn't matter). Pure: no file I/O in `core`.
- Loader `load_light_access(path) -> LightAccess` in `config.py`: missing file → allow-all
  (`LightAccess(whitelist=False)`) + warning; otherwise `LightAccess.model_validate_json(text)`;
  a `ValidationError` becomes a `ConfigError` whose message lists each problem as
  `lights.2: Input should be a valid UUID` (location + pydantic's message). Path from env
  `LIGHTS_CONFIG` (default `configs/lights.json`).
- Docker: compose mounts `./configs:/app/configs:ro` (the whole folder, so a missing file doesn't
  make Docker create a directory in its place). Add `configs/` to `.dockerignore` and
  `configs/lights.json` to `.gitignore`.
- Startup log: "Light access: whitelist, 6 lights" / "blacklist, 1 light" / "all lights (empty list)" /
  "all lights (no file)".

## 3. Colour and brightness (pure, `core/color.py`)

- Types: `Hex(value: str)` (normalised `#rrggbb`) and `Kelvin(value: int)` (2000–6500); `Color = Hex | Kelvin`.
  `str(color)` is the stored/displayed form (`#ff8800`, `2700K`); `parse_color(str)` reads it back.
- `parse_color(text) -> Color`, D9 rules: strip and lowercase; ends with `k` → the rest (spaces
  allowed) must be an integer 2000–6500 → `Kelvin`; otherwise hex (`#` optional, 3 or 6 hex digits,
  3 expands `f80` → `ff8800`) → `Hex`; `#000000` refused; a bare 4-digit number gets the "add K"
  hint. Errors are `InvalidColor` with a user-safe message.
- `hex_to_xy(hex) -> tuple[float, float]`: sRGB gamma expansion
  (`((v + 0.055) / 1.055) ** 2.4` if `v > 0.04045` else `v / 12.92`), then
  `X = .4124r + .3576g + .1805b`, `Y = .2126r + .7152g + .0722b`, `Z = .0193r + .1192g + .9505b`,
  `x = X/(X+Y+Z)`, `y = Y/(X+Y+Z)`, rounded to 4 decimals. The bridge clamps xy into each light's
  gamut; if manual testing shows it doesn't, clamp client-side with the light's `color.gamut` and
  note it in the Handoff.
- `xy_to_hex(x, y) -> str` (for `/lights`): `Y = 1`, `X = x/y`, `Z = (1-x-y)/y`;
  `r = 3.2406X - 1.5372Y - 0.4986Z`, `g = -0.9689X + 1.8758Y + 0.0415Z`,
  `b = 0.0557X - 0.2040Y + 1.0570Z`; negatives → 0, divide by the largest channel, sRGB gamma
  (`12.92v` if `v <= 0.0031308` else `1.055 v^(1/2.4) - 0.055`), × 255, round.
- `kelvin_to_mirek(k, lo=153, hi=500) -> int`: `round(1_000_000 / k)` clamped to `[lo, hi]` (the
  light's `mirek_schema`). `mirek_to_kelvin(m) -> int`: `1_000_000 / m` rounded to the nearest 50.
- `parse_brightness(int) -> int` 0–100 (the Discord option already has min/max; this is the guard).

## 4. Light state and the Hue client

- `hue/` (no discord): `HueClient.list_lights() -> list[BridgeLight]` (`id`, `name`, `on`,
  `brightness | None`, `xy | None`, `mirek | None` (only when `mirek_valid`), `supports_color`,
  `supports_temperature`, `mirek_range` (from `color_temperature.mirek_schema`), `supports_dimming`) and
  `HueClient.apply(light_id, LightState)` where `LightState(on: bool, xy | None, mirek | None,
  brightness | None)` (never both `xy` and `mirek`) becomes one PUT body (`on`, `dimming`, `color.xy`
  or `color_temperature.mirek`; keys left out when None). Close the client in
  `AuroraHue.close()` (today it's never closed).
- `services/lights.py` turns a `Color` into a `LightState` per light: `Hex` → `xy` if
  `supports_color`; `Kelvin` → `mirek` (clamped to that light's `mirek_range`) if
  `supports_temperature`; otherwise no colour and `color_skipped`.
- `services/lights.py`: `LightService` holds the client, the `LightAccess` and the 60 s cache (D5).
  - `allowed() -> list[BridgeLight]` (sorted by name)
  - `resolve(text | None) -> list[BridgeLight]` (D6; duplicates collapse; error lists every bad name)
  - `apply(targets, state_or_states) -> ApplyReport` (sequential PUTs; per-light result:
    `ok`, `color_skipped`, `failed`, `not_allowed`, `missing`). Every write goes through
    `LightAccess.allows` here, a second time, whatever the caller already checked.
- One reply formatter turns an `ApplyReport` into the D22 text ("Turned on 3 lights. Colour skipped
  for: Hallway. Didn't answer: Desk.").

## 5. Data model (migration `0002`)

```
scenes
  id            bigint identity PK
  name          text not null              -- 1–50 chars (check)
  created_by    bigint not null            -- Discord user id
  created_at    timestamptz not null
  updated_at    timestamptz not null
  unique index on lower(name)              -- uq_scenes_lower_name

scene_actions
  id            bigint identity PK
  scene_id      bigint not null FK scenes.id ON DELETE CASCADE
  light_id      text not null              -- CLIP v2 UUID; no FK (lights live on the bridge)
  is_on         boolean not null
  color         varchar(7) null            -- '#rrggbb' or '2700K' (D9);
                                           -- check ~ '^(#[0-9a-f]{6}|[0-9]{4}K)$'
  brightness    smallint null              -- check 0..100
  unique (scene_id, light_id)
  check (is_on or (color is null and brightness is null))     -- D13

bot_settings                                -- exactly one row, id = 1 (check), inserted by 0002
  id               smallint PK
  reset_scene_id   bigint null FK scenes.id ON DELETE SET NULL   -- D19
```

Timestamps come from a `Clock` (port `core/clock.py` + `tests/support/clock.py` from Sidequest),
not DB `now()`. Light IDs are stored even if a light later leaves the access list (D17 skips it).

## 6. Services (`services/scenes.py`, `services/settings.py`, no discord)

- `SceneInput(name, actions: tuple[ActionInput, ...])`, `ActionInput(light_id, on, color | None,
  brightness | None)`; `SceneView(id, name, actions, is_reset)`. Frozen pydantic models
  (`ConfigDict(frozen=True, extra="forbid")`), like Sidequest's `StrictModel`.
- `list_scenes()`, `get(name)`, `create(actor_id, input)`, `update(scene_id, input, new_name | None)`
  (replaces all actions), `delete(scene_id)`, `actions_for_run(scene_id)`.
- Validation: name length and uniqueness (`NameTaken`), ≥ 1 action, no duplicate light, hex/
  brightness per §3, "off" with colour/brightness refused, every light currently allowed **at
  save time** (`NotAllowed`).
- `get_settings()`, `set_reset_scene(scene_id | None)`.
- Errors: `AuroraHueError` with `.message`; subclasses `NotFound`, `NameTaken`, `InvalidInput`,
  `NotAllowed`, `BridgeUnavailable`.
- Running a scene (`/scene run`, `/reset`): load actions → `LightService.apply` with per-light states
  (colour → xy or mirek via `core/color`, per light) → report.

## 7. Discord layer

| Command | Options | Behaviour |
|---|---|---|
| `/on` | `lights?` | D7, D21 (daytime confirm), D22 |
| `/off` | `lights?` | D7 |
| `/color` | `color` ("Hex like #ff8800 or white temperature like 2700K"), `lights?` | D8, D9, D11, D21 |
| `/brightness` | `percent` (0–100), `lights?` | D8, D10, D21 |
| `/lights` | — | D23 |
| `/scene list` | `scene?` | No option: names + number of lights, reset scene marked ⟲. With one: its actions, one line per light ("Desk — on, #ff8800, 40%"; "Hallway — off"; disallowed lights shown as "(not controllable)"). |
| `/scene add` | `name` | Checks the name is free, then opens the builder (D16), empty. |
| `/scene edit` | `scene`, `new-name?` | Builder with the current actions; rename applied on Save. |
| `/scene delete` | `scene` | Confirm (Delete / Cancel), D19 line if it's the reset scene. |
| `/scene run` | `scene` | D17, D21, D22 |
| `/reset` | — | D19, D21 |
| `/settings` | `reset-scene?` | D18 |

- Cogs: keep `general.py`; replace `light_toggle.py` with `cogs/lights.py` (on/off/color/brightness/
  lights), `cogs/scenes.py` (the `/scene` group + `/reset`), `cogs/settings.py`. Move `is_allowed()`
  and `ConfirmView` to `cogs/common.py`, plus one helper `confirm_if_daytime(interaction, targets)`
  that every D21 command calls before applying. One `tree.on_error` handler for `AuroraHueError` and
  `CheckFailure`. Register new extensions in `bot.py`.
- Autocomplete: `scene` options from `list_scenes()` (prefix/substring, 25 max); `lights` per D6
  (suggest `"<names already typed>, <candidate>"`, values ≤ 100 chars).
- Builder form: a modal with **State** (on/off), **Colour** (hex or temperature, optional; placeholder `#ff8800 or 2700K`) and **Brightness**
  (0–100, optional), prefilled when all picked lights share the same action. Use a select inside the
  modal if discord.py 2.7's `ui.Label` supports it; otherwise a text input accepting `on`/`off`.
  Errors in the form keep the builder open and show the message ephemerally.
- Bot-built components keep `AllowedMentions.none()`; light and scene names are escaped.

## 8. Not in this brief

Scheduling scenes · scenes by sunrise/sunset · transitions/fade times · Hue rooms/zones and the
bridge's own scenes · `/scene add from-current` · a web UI.
Any of these may become a follow-up brief (see §9).

---

## 9. Tim's answers (2026-11-23) and what's still open

Answered: `/scene list` (D15) · `/lights` + `python main.py lights`, with light names picked from
autocomplete in every `lights` option (D6, D23) · drop the `/on` exception (D24) · `/color` and
`/brightness` switch lights on (D8) · brightness 0 = lowest glow (D10) · optional colour and
brightness in scene actions (D13) · scene builder (D16) · daytime confirmation on every command that
switches lights on (D21) · `ALLOWED_USER_IDS` only, no other permissions (D20) · global scenes (D14)
· skip and mention lights that are no longer allowed (D17) · deleting the reset scene asks and
clears it (D19) · one colour field that takes a hex colour or a Kelvin temperature (D9).

Also: all of Tim's lights are **white and color ambiance** (so hex and Kelvin both work on every
current bulb; D11 is a safety net) · no Hue rooms/zones in `lights` (§8) · light changes reply
publicly, the rest ephemerally (D22).

Nothing open.

---

## Segment 1 — Database foundation

**Branch:** `claude/lights-and-scenes-s1` · **Status:** ✅ done · **Migration:** `0001` (empty)

Bring Sidequest's database setup to AuroraHue, with no tables yet, plus a test harness (AuroraHue has
no tests today). Reference files in the Sidequest repo are named per item; port them, don't redesign.

**Checklist**
1. [x] **Dependencies** — main session: add `sqlalchemy[asyncio]>=2`, `asyncpg`, `alembic`,
   `pydantic>=2` to `dependencies`; `pytest`, `pytest-asyncio` to `dev`. Recompile both requirement files with
   `pip-compile --no-emit-index-url` (`requirements-dev.txt` is stale today: it lacks `astral` and
   `httpx2`). Add a `scripts/compile-requirements.sh` like Sidequest's.
2. [x] **Config** — main session: `Config` gets `database_url` (`DATABASE_URL`, required),
   `run_migrations` (`RUN_MIGRATIONS`, default true) and `lights_config` (`LIGHTS_CONFIG`, default
   `configs/lights.json`, used in segment 2). Add `aurorahue/db/url.py: database_url() -> str` that
   reads only `DATABASE_URL` (after `load_dotenv()`), so Alembic runs without a bot token.
3. [x] **DB package** — Haiku, port from Sidequest, reviewed: `aurorahue/db/base.py` (naming
   convention, TIMESTAMPTZ map), `session.py`, `migrate.py` (`alembic_config`, `upgrade_head`);
   `aurorahue/db/models.py` empty for now (imports `Base`).
4. [x] **Alembic** — Haiku, port, reviewed: `alembic.ini` (`prepend_sys_path = .`,
   `file_template = %%(rev)s_%%(slug)s`), `migrations/env.py` (async, URL from
   `config.attributes["database_url"]` else `db.url.database_url()`), `script.py.mako`,
   `migrations/versions/0001_initial.py` (empty).
5. [x] **Start-up** — main session: `main.py` runs `upgrade_head` **before** `bot.run` when
   `run_migrations` is true (it's sync and env.py calls `asyncio.run`, so not inside the event
   loop); the bot gets an engine + sessionmaker in `setup_hook`, disposed in `close()`. Port
   `core/clock.py` (`Clock`, `SystemClock`).
6. [x] **Docker** — Haiku, from this spec, reviewed: in `docker-compose.yml` enable a `db` service
   `postgres:17-alpine`, container `aurorahue-db`, `env_file: .env`, volume `aurorahue-db-data`,
   healthcheck `pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB`; bot gets `depends_on: db:
   service_healthy`, `init: true`, and `volumes: ["./configs:/app/configs:ro"]`. `Dockerfile` also
   copies `alembic.ini` and `migrations/`. `.dockerignore` adds `configs/`. `.env.example` adds
   `POSTGRES_USER=aurorahue`, `POSTGRES_PASSWORD=change-me`, `POSTGRES_DB=aurorahue`,
   `DATABASE_URL=postgresql+asyncpg://aurorahue:change-me@db:5432/aurorahue`, `RUN_MIGRATIONS=true`,
   `LIGHTS_CONFIG=configs/lights.json`, with comments like Sidequest's.
7. [x] **update.sh** — Haiku, reviewed: gzip backups and abort-on-failed-backup like Sidequest's
   (`backups/backup-<time>.sql.gz`, keep 14). No other changes.
8. [x] **Test harness** — Haiku, port, reviewed: `compose.test.yaml` (container
   `aurorahue-db-test`, user/password `aurorahue`, db `aurorahue_test`, port **55433** so it can run
   next to Sidequest's), `tests/integration/conftest.py` (same fixtures, `_test` guard, TRUNCATE list
   empty for now), `tests/integration/test_migrations.py` (up/down/up round trip),
   `tests/support/clock.py`, `tests/unit/test_layering.py` with the rules from `CLAUDE.md` §3
   (`core` ⊄ discord/sqlalchemy/httpx2; `services`, `db`, `hue` ⊄ discord). `[tool.pytest.ini_options]`
   `asyncio_mode = "auto"`.
9. [x] **Checks** — Haiku runs §7 checks of `CLAUDE.md`, including integration with Docker.
10. [x] **Docs** — Opus: `CLAUDE.md` §3/§7/§8 match what was built; Handoff below.

**Manual test (Tim)**
- [ ] Copy the new `.env.example` lines into `.env` (same password in `POSTGRES_PASSWORD` and
      `DATABASE_URL`). Postgres only reads the password when the volume is first created.
- [ ] `bash update.sh` on the Pi → `aurorahue-db` healthy, bot log shows the migration, bot online,
      `/ping` and `/on` still work. Second run → a `backups/backup-*.sql.gz` appears.

**Handoff (2026-11-23, Opus 5.5):**
- *Built:* items 1–10 as specified. Postgres 17 `db` service, Alembic (empty `0001`), migrations
  run in `main.py` before `bot.run`, the bot opens an engine/sessionmaker in `setup_hook` and
  disposes it in `close()`, `core/clock.py`, test harness (`compose.test.yaml` on 55433,
  `tests/integration` fixtures, migration round trip, layering test), gzip backups in `update.sh`.
- *Checks:* `ruff check .` and `ruff format --check .` clean; 11 tests passed, 0 skipped, with the
  integration tests run against `compose.test.yaml`; `alembic upgrade head` + `alembic check` clean.
- *Deviations:*
  - `requirements-dev.txt` pins were aligned to `requirements.txt` (httpx2 2.12.0, httpcore2,
    anyio, truststore); a fresh dev compile had picked httpx2 2.16.2. Production pins unchanged.
  - `ruff` failed on three files this segment doesn't otherwise touch (`cogs/light_toggle.py`,
    `helpers/sun_finder.py`, `hue/hue_client.py`): fixed mechanically (import order, quotes,
    `timezone.utc` → `UTC`, one long f-string split into a variable). No behaviour change.
  - Layering test: `core` also may not import `aurorahue.db` / `aurorahue.hue` (as in Sidequest,
    which forbids `sidequest.db` in core). `RUN_MIGRATIONS` accepts true/false/1/0/yes/no/on/off.
  - `update.sh` gained `set -o pipefail` (needed to notice a failed `pg_dump`) and dropped
    `docker exec -t` (a TTY corrupts the dump). The rest of its flow is unchanged.
  - The bot also gets `self.clock = SystemClock()` for the services in segment 4.
- *Open:* the layering test (like Sidequest's) only sees absolute imports; existing code uses
  relative ones (`from ..db import …`), which it would miss. Use absolute imports in
  `core`/`services`/`db`/`hue`, or extend the test in a later segment.
- *Note:* running the bot locally now needs `DATABASE_URL` in `.env` (see `CLAUDE.md` §7).

---

## Segment 2 — Light registry and the access file

**Branch:** `claude/lights-and-scenes-s2` · **Status:** ✅ done · **Migration:** none

**Checklist**
1. [x] **`core/errors.py`, `core/access.py`** — main session: errors from §6; `LightAccess` (§2).
2. [x] **Loader** — main session: `load_light_access(path) -> LightAccess` per D2/D3 and the startup
   log line (§2). Called from `main.py`; a `ConfigError` exits with the message, no traceback.
3. [x] **Access tests** — Haiku, table-driven, `tests/unit/test_access.py`, reviewed. Cases: no file →
   all; `{"whitelist": true}`, `{"whitelist": true, "lights": []}` and the same with `false` → all;
   whitelist with 2 IDs → only those; blacklist with 1 ID → all but that; uppercase UUID in the file
   matches the lowercase bridge ID (and the other way round); duplicate IDs fine; refused (each with
   a message naming the field): invalid JSON, `whitelist` missing, `"whitelist": "true"` (string),
   `"whitelist": 1`, a non-UUID string in `lights`, `lights` not a list, an unknown key
   (`"blacklist": true`). Writes the files to `tmp_path`.
4. [x] **Hue client** — main session (§4): `list_lights`, `apply`, `BridgeLight`, `LightState`,
   `aclose` on shutdown. Delete `LIGHT_IDS`, `ON_EXCLUDED_LIGHT_IDS`, `ON_STATE`,
   `MINIMUM_BRIGHTNESS`, `SOFT_BRIGHTNESS` (the old cog is rewired in segment 3; keep it compiling by
   having it go through `LightService` with the old behaviour minus the preset).
5. [x] **`services/lights.py`** — main session (§4): cache, `allowed`, `resolve`, `apply`,
   `ApplyReport`.
6. [x] **Service tests** — Haiku, reviewed, `tests/unit/test_light_service.py` with a fake client
   (no network): `resolve` (none → all allowed; "desk, Hallway" any case; duplicates; unknown name;
   disallowed name reported as unknown, D4); `apply` never sends a PUT for a disallowed ID even if
   passed one; hex on a non-colour light and a temperature on a plain white light → `color_skipped` and the PUT
   has no colour; a temperature on a white-ambiance light → `color_temperature.mirek`; 2000K on a
   light with `mirek_schema` 153–454 → mirek 454; a PUT never holds both `color` and
   `color_temperature`; a failing
   light doesn't stop the others; cache reused within 60 s and refreshed after (FixedClock).
7. [x] **CLI** — main session: `python main.py lights` prints a table (UUID, name, colour yes/no,
   allowed yes/no) of every bridge light, then exits; no Discord token needed for it.
8. [x] **Example file** — Haiku: `configs/lights.example.json` exactly as §2; `.gitignore` adds
   `configs/lights.json`.
9. [x] **Checks**, **Docs** (Opus: `CLAUDE.md` §8, Handoff).

**Manual test (Tim)**
- [x] `docker compose run --rm bot python main.py lights` → all your lights with IDs.
- [x] Create `configs/lights.json` with `"whitelist": true` and today's six lights to keep current
      behaviour:
      `8a94b76b-eb9f-42fb-8b58-8c8701a80283`, `0c836d0d-ad3e-4527-802b-b5d0911b7b33`,
      `e8ff6285-fc12-44da-aa8e-c5f98ec167dd`, `0fcfc949-4034-48f3-9f1d-fcba8bd31319`,
      `228a2039-ed8c-4e27-b36d-13db9758db22`, `217d73ed-695a-42f1-bbc1-20cf69c11ae2`.
      Restart → log says "whitelist, 6 lights".
- [x] Break the file (`"whitelist": "yes"`, then a typo in a UUID) → bot refuses to start with a
      readable error naming the field. Fix it again.
- [x] Remove one light from the whitelist, restart, `/on` → that light stays off.
      *All passed (Tim, 2026-11-23).*

**Handoff (2026-11-23, Opus 5.5):**
- *Built:* `core/errors.py`, `core/access.py` (`LightAccess` + `unknown()`, `describe()`),
  `load_light_access` + `ConfigError` + `HueSettings` in `config.py`, `HueClient.list_lights`/`apply`
  with `BridgeLight`/`LightState` (HTTP errors → `BridgeUnavailable`), `services/lights.py`
  (`LightService`, `LightRequest`, `Outcome`, `ApplyReport`), `cli.py` + `python main.py lights`,
  `configs/lights.example.json`, `.gitignore`. The bot builds the client and service in
  `setup_hook`, closes the client in `close()`, and at startup warns about file IDs not on the bridge
  (D3) or that the bridge is unreachable (D5, the bot still starts).
- *Checks:* `ruff check .`, `ruff format --check .` clean; 54 tests passed (21 access, 22 service),
  integration included (`compose.test.yaml`). No model changes, so no `alembic check`.
- *Deviations:*
  - **Part of `core/color.py` pulled forward from segment 3**: `Hex`, `Kelvin`, `Color`,
    `hex_to_xy`, `kelvin_to_mirek`, exactly per §3. Item 6's tests need hex/Kelvin handling in
    `apply`. `Hex`/`Kelvin` take already-normalised values and raise `ValueError`; segment 3 adds
    `parse_color` (with `InvalidColor`), `xy_to_hex`, `mirek_to_kelvin`, `parse_brightness` and the
    colour tests.
  - `apply(targets, request)`: targets are light **IDs** (so scenes can pass stored IDs);
    `request` is one `LightRequest(on, color, brightness)` or a dict ID → request. Colour →
    `LightState` happens per light inside the service.
  - Brightness is dropped silently for a light without dimming (on/off plugs); D11 only covers colour.
  - Two bridge lights with the same name: `resolve` returns both.
  - The cache holds names, capabilities **and state**, so state can be up to 60 s stale. D21's
    check and `/lights` should call `allowed(fresh=True)`.
  - CLI table also shows temperature and dimming (D23), plus file IDs that aren't on the bridge.
  - Old cog (until segment 3): `/on`, `/off` act on all allowed lights; `/minimum` = brightness 0,
    `/soft` = 30 % (was half the deleted preset, 29.84). D24: `/on` now also switches on
    `0c836d0d-…`, which used to be excluded. Per-light failures are ignored there (no report yet);
    an `AuroraHueError` is shown ephemerally.
  - New code and the touched `bot.py` use absolute imports (segment 1's open point).
- *Open:* `NotFound` messages quote user-typed names unescaped (`No light named "x".`); the error
  handler in segment 3 should escape markdown in user text.

---

## Segment 3 — Direct light commands

**Branch:** `claude/lights-and-scenes-s3` · **Status:** 👀 waiting for review · **Migration:** none

**Checklist**
1. [x] **`core/color.py`** — main session (§3).
2. [x] **Colour tests** — Haiku, table-driven, `tests/unit/test_color.py`, reviewed.
   `parse_color` → stored form: `#FF8800`, `ff8800`, `#f80`, `F80` → `#ff8800`; `2700K`, `2700k`,
   `2700 K`, ` 2700k ` → `2700K`; `2000K` and `6500K` accepted. Refused: `#ff880`, `#gg0000`, `""`,
   `#ff88001`, `#000000`, `000`, `1999K`, `6501K`, `K`, `27.5K`, `2700` (message mentions `2700K`).
   `hex_to_xy` (±0.001): `#ff0000` → (0.6401, 0.3300), `#00ff00` → (0.3000, 0.6000),
   `#0000ff` → (0.1500, 0.0600), `#ffffff` → (0.3127, 0.3290), `#ff8800` → (0.5336, 0.4145);
   `#330000` == `#ff0000`. `xy_to_hex(hex_to_xy(h)) == h` for `#ff0000`, `#00ff00`, `#0000ff`,
   `#ffffff`, `#ff8800`; `xy_to_hex(hex_to_xy("#336699")) == "#5badff"` (darkness dropped).
   `kelvin_to_mirek`: 2700 → 370, 6500 → 154, 2000 → 500, 2000 with `hi=454` → 454, 6500 with
   `lo=160` → 160. `mirek_to_kelvin`: 370 → 2700, 447 → 2250.
3. [x] **`cogs/common.py`** — main session: `is_allowed()`, `ConfirmView`, `confirm_if_daytime`
   (D21), the `tree.on_error` handler, the `lights` option + autocomplete (D6), the `ApplyReport` reply text (D22).
4. [x] **`cogs/lights.py`** — main session builds `/on` and `/color` (both with the D21 confirm);
   then **Haiku** adds `/off` (pattern of `/on`, never confirms) and `/brightness` (pattern of `/color`),
   reviewed. Then `/lights` (main session, D23). Delete `cogs/light_toggle.py`; update
   `INITIAL_EXTENSIONS`.
5. [x] **Reply tests** — Haiku, table-driven, `tests/unit/test_replies.py`: all ok (1 light /
   n lights), with colour skipped, with failures, everything failed, bridge unreachable; names are
   escaped (`*`, `_`, `@`).
6. [x] **Checks**, **Docs** (Opus: `CLAUDE.md` §4 command list, Handoff).

**Manual test (Tim)**
- [ ] `/minimum` and `/soft` are gone (guild sync: at once; global: up to an hour).
- [ ] `/on` in daytime → confirm; at night → straight on, with each light's previous colour.
- [ ] Daytime, all lights on: `/color` and `/brightness` → no question. One light off:
      `/color` → question; Cancel → nothing changes.
- [ ] `/on lights:` autocomplete shows only allowed lights; pick two → only those switch on.
- [ ] `/off lights: desk, nonsense` → error naming "nonsense", nothing changed.
- [ ] `/color color:#ff8800` → all allowed lights on and orange; a white-only bulb (if any) turns on
      and the reply says its colour was skipped.
- [ ] `/color color:2200k` → warm white on colour and white-ambiance bulbs; `/lights` shows
      "2200K" for them. `/color color:2700` → error suggesting `2700K`; `/color color:9000K` → refused.
- [ ] `/brightness percent:0` → lowest glow, not off. `/brightness percent:100 lights:<one>`.
- [ ] Unplug a bulb, `/on` → others go on, reply names the one that didn't answer.
- [ ] `/lights` lists allowed lights with their state.
- [ ] Someone not in `ALLOWED_USER_IDS` → "You are not allowed to use this command."

**Handoff** (Claude, Opus 5.5, 2026-11-23)
- *Built:* the rest of `core/color.py` (`parse_color` + `InvalidColor(InvalidInput)`, `xy_to_hex`,
  `mirek_to_kelvin`, `parse_brightness`); `cogs/common.py` (`is_allowed`, `ConfirmView`,
  `confirm_if_daytime`, `lights_option` + `lights_autocomplete`, `report_text`, `error_text`,
  `on_app_command_error`); `cogs/lights.py` (`/on`, `/off`, `/color`, `/brightness`, `/lights`).
  `bot.py` loads `cogs.lights` and registers the handler with `tree.error`; `cogs/light_toggle.py`
  deleted. Tests: `test_color.py` (47), `test_replies.py` (16).
- *Checks:* `ruff check .`, `ruff format --check .` clean; `pytest tests/unit` 116 passed.
  No model changes, so no `alembic check`.
- *Deviations:*
  - **D21 response flow.** The question must be ephemeral and the result public (D22), and
    Discord makes the first follow-up after a defer take the defer's visibility. So
    `confirm_if_daytime` runs *before* the interaction is answered: in daytime it reads the bridge
    (fresh, max 2 s, else `BridgeUnavailable`) and, if a target is off, answers with the ephemeral
    question; otherwise it defers publicly. The result always goes out with
    `interaction.followup.send`. Callers resolve names first, so a `NotFound` stays ephemeral.
  - Buttons **Go ahead** / **Cancel**; 60 s without an answer → "No answer; nothing changed."
  - Error handler escapes the whole `AuroraHueError` message (markdown + mentions), which closes
    segment 2's open point. Our own messages therefore can't use markdown (segment 5: D19's
    `/settings reset-scene` will show its backticks literally; word it without them).
    Unexpected errors: logged, user sees "Something went wrong; it has been logged."
  - `report_text(report, verb, suffix)`: one light → its name ("Turned on Desk."), more → a count.
    D17 lines are ready for segment 5: "Not controllable any more: …" and, since a missing light's
    name is its UUID, "2 lights aren't on the bridge any more."
  - `/lights`: one plain line per light ("**Desk** — on, 40%, 2700K"), ephemeral.
  - An error after the public defer (bridge drops between the name lookup and the write) shows
    publicly; rare, left as is.
  - Parallel run: `core/color.py` was finished first and copied byte-identical into segment 4's
    worktree (`../AuroraHue-s4`), so both branches add the same change.
- *Open:* does the bridge clamp xy into each bulb's gamut (§3)? Check with `/color #0000ff`.

---

## Segment 4 — Scenes and settings: schema and services

**Branch:** `claude/lights-and-scenes-s4` · **Status:** 👀 waiting for review · **Migration:** `0002`

**Checklist**
1. [x] **Models + migration `0002`** — main session (§5). `alembic revision --rev-id 0002 -m
   "scenes and settings"`, hand-checked; inserts the `bot_settings` row; downgrade drops all three.
   `alembic check` clean.
2. [x] **Services** — main session (§6): `services/scenes.py`, `services/settings.py`, scene run on
   top of `LightService.apply`.
3. [x] **Integration tests** — Haiku, reviewed, `tests/integration/test_scenes.py`,
   `test_settings.py`, `test_migration_0002.py`. Cases: create/list/get (case-insensitive);
   `NameTaken` on "Evening" vs "evening"; name of 0 and 51 chars refused; no actions refused; two
   actions for one light refused; "off" with colour refused; `2700K` and `#ff8800` stored as given, `1500K` refused; disallowed light refused at save;
   update replaces all actions and renames (and keeps the name free check, excluding itself);
   delete cascades actions; deleting the reset scene clears `reset_scene_id`; set/clear reset scene;
   unknown scene → `NotFound`; run builds the right `LightState`s (xy from hex, mirek from Kelvin, brightness, on) and
   skips a light that's no longer allowed (fake client); DB check constraints reject a bad colour (`#FF8800` uppercase, `2700k`)
   and brightness 101 written directly; migration up/down/up. Update the TRUNCATE list in conftest.
4. [x] **Checks**, **Docs** (Opus: Handoff; `CLAUDE.md` §3 package map).

**Manual test (Tim):** `bash update.sh` → migration `0002` applied, bot starts. (No commands yet.)

**Handoff (2026-11-23, Claude Opus 5.5; built in a local worktree in parallel with segment 3):**
- *Built:* `db/models.py` (`Scene`, `SceneAction`, `BotSettings`; checks named `ck_scenes_name_length`,
  `ck_scene_actions_color_format` / `_brightness_range` / `_off_is_plain`, `ck_bot_settings_single_row`),
  migration `0002_scenes_and_settings.py` (autogenerated, then tidied; inserts row 1; downgrade drops
  all three). `services/model.py` (`StrictModel` like Sidequest, `SessionFactory`),
  `services/scenes.py` (`SceneService`), `services/settings.py` (`SettingsService`). Tests:
  `tests/integration/test_scenes.py`, `test_settings.py`, `test_migration_0002.py`; shared helpers in
  `tests/support/hue.py` (fake bridge) and `tests/support/services.py` (light IDs, the test session
  as a `SessionFactory`); `conftest.py` gets `fake_bridge`, `scenes`, `settings` fixtures and the
  TRUNCATE list.
- *Checks:* `ruff check .`, `ruff format --check .` clean; 106 passed (53 unit, 53 integration);
  `alembic check` clean; migration up/down/up tested.
- *Deviations:*
  - Services are classes, like `LightService`: `SceneService(sessions, lights, clock)` and
    `SettingsService(sessions)`. Each call opens its own session from `sessions` (the bot's
    `async_sessionmaker`) and commits its own work. Segment 5 builds them in `setup_hook`.
  - **`update(scene_id, input)` has no `new_name` argument**: `input.name` is the name after the
    update (the same or a new one). The builder passes `new-name or the current name`.
  - Extra methods: `get_by_id(scene_id)` (the builder and confirm views hold an ID) and
    `run(scene_id) -> ApplyReport` (D17: `LightService.apply` with one `LightRequest` per light;
    stored colours read back with `parse_color`). `delete` returns the deleted `SceneView`, whose
    `is_reset` says the setting was cleared (D19). `SceneView.actions` reuses `ActionInput`, in
    stored form, in the order they were saved.
  - Colours are normalised on save (`#FF8800` → `#ff8800`, `2700 k` → `2700K`) with `parse_color`;
    bad ones raise `InvalidColor` (an `InvalidInput`). Brightness goes through `parse_brightness`.
    Names are trimmed before the 1–50 check.
  - "Allowed at save time" = on the bridge **and** allowed (`LightService.allowed()`), so saving
    needs the bridge (`BridgeUnavailable` otherwise). The `NotAllowed` message doesn't name the light
    (D4).
  - `SettingsView(reset_scene_id, reset_scene_name)`. `set_reset_scene` upserts row 1, so it
    doesn't depend on the row still being there; an unknown scene → `NotFound`.
  - `committed_sessions` re-inserts the settings row after its TRUNCATE (CASCADE empties
    `bot_settings` because it references `scenes`).
  - The integration tests were written in the main (forked) session, not by a Haiku subagent: the
    parallel worker couldn't spawn subagents.
  - `core/color.py` is byte-identical to segment 3's (copied from that branch, not edited here), so
    the two branches merge cleanly.
- *Open (for segment 5):* `/scene edit` on a scene that holds a now-disallowed light can't be saved
  until that light is removed (save-time rule); the builder should drop or flag such actions when it
  loads. `NotFound`/`NameTaken` messages quote user text unescaped, like segment 2's.

---

## Segment 5 — Scene commands, `/reset`, `/settings`, docs

**Branch:** `claude/lights-and-scenes-s5` · **Status:** ⬜ todo · **Migration:** none

**Checklist**
1. [ ] **Scene builder** — main session (`cogs/scene_builder.py`, D16, §7): embed, Set lights… →
   form, Remove lights…, Save, Cancel, timeout, owner-only.
2. [ ] **`cogs/scenes.py`** — main session builds `/scene add` and `/scene edit` (both open the
   builder) and the `scene` autocomplete; then **Haiku** adds `/scene list`, `/scene delete` (with
   the confirm view from `cogs/common.py`) and `/scene run` (with `confirm_if_daytime`, D21) from the
   existing pattern, reviewed.
3. [ ] **`/reset` and `/settings`** — Haiku, reviewed, from §7 and D18/D19/D21 (`/reset` confirms
   like `/scene run`) (thin wrappers over the
   services that exist).
4. [ ] **Render tests** — Haiku, table-driven: `/scene list` lines (with/without reset marker, a
   disallowed light), builder embed lines (on with all fields, on with only brightness, off), name
   escaping.
5. [ ] **Docs** — Opus: `README.md` (what the bot does, commands, `.env`, `configs/lights.json`,
   `python main.py lights`, deploy), `CLAUDE.md` §4 (domain rules) and §6 (D1–D24 one-liners),
   this brief's Status → `done`, then move it to `docs/claude/archive/briefs/`.
6. [ ] **Checks.**

**Manual test (Tim)**
- [ ] `/scene add name:Evening` → builder; set two lights on at `2700K` 40 %, one off; Save →
      `/scene list` shows "Evening (3 lights)"; `/scene list scene:evening` shows the three lines.
- [ ] `/scene add name:evening` → name taken.
- [ ] Builder: Save with nothing set → refused; Cancel → "Nothing saved."; wait 15 min → expired text.
- [ ] Form: colour `#zzz` or `2700` → error, builder stays open; "off" plus a colour → refused.
- [ ] `/scene edit scene:Evening new-name:Night` → rename + change one light → `/scene run
      scene:Night` → lights match; lights not in the scene untouched.
- [ ] Remove a scene light from `lights.json`, restart, `/scene run` → it's skipped and listed.
- [ ] Daytime: `/scene run` of a scene that switches an off light on → question; a scene with only
      "off" actions → no question. Same for `/reset`.
- [ ] `/reset` with nothing set → the hint. `/settings reset-scene:Night` → `/settings` shows it →
      `/reset` runs it. `/scene delete scene:Night` → warning line → Delete → `/settings` shows none.
- [ ] Another user opens your builder's buttons → refused (owner-only).

**Handoff:** —
