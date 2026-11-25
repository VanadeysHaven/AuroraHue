# AuroraHue — what Claude Code needs to know

> Written by Claude (Opus 5.5), 2026-11-23. Read this file, then **only** the brief (and the segment)
> you're working on. Finished briefs live in `docs/claude/archive/briefs/` (read one only when a
> decision's details matter).

AuroraHue is a small Discord bot that controls Philips Hue lights through one Hue bridge on Tim's
home network: Python 3.12, discord.py, the Hue CLIP v2 API, Docker Compose, deployed with
`update.sh`. Tim develops on Windows. Its sibling project is **Sidequest** (same author, same
deploy style); when this file says "like Sidequest", that repo is the reference.

---

## 1. How to work

### Feature workflow
1. Every feature has a brief: `docs/claude/briefs/<slug>.md`. Its **Status** line (top of the file)
   says where it stands: `drafting` → `ready` → `in progress` → `waiting for review` → `done`.
   Don't build from a brief that is still `drafting`.
2. A brief may hold several **segments** (Segment 1, 2, …). Work through **one segment per session**,
   in the brief's order. Read this file, the brief's shared sections (decisions, design) and only
   the segment you're on.
3. Check git with read-only commands (`git status`, `git branch --show-current`, `git diff --stat`).
   If earlier changes are still uncommitted, stop and ask Tim to commit first. Otherwise create the
   branch the segment names (`claude/<slug>-s<n>`).
4. Turn the segment's checklist into a task list and work through it.
5. Run the checks (§7). Never call a segment done with failing checks.
6. At the end: tick the checklist, update the brief's Status and the segment's status, add a short
   **Handoff** to the segment (what was built, deviations and why, open questions). If a decision
   changed something this file describes, update this file too.
7. Stop and report to Tim: what was built, files changed, deviations, open questions, the manual test
   checklist and a suggested commit message. Don't start the next segment.
8. A finished brief moves (plain `mv`) to `docs/claude/archive/briefs/<slug>.md` with Status `done`.
   `docs/claude/briefs/` only holds live briefs.

A new feature request from Tim starts with a brief, not code: ask the design questions that matter,
write the brief with the answers, set it to `ready`, and stop.

If the spec is unclear, **ask Tim rather than guessing.** Subagents stop and report instead of deciding.

### Git (hard rules)
- Allowed: `status`, `diff`, `log`, `show`, `branch`, and creating a branch (`git switch -c`).
- **Never**: `commit`, `push`, `merge`, `rebase`, `reset`, `stash`, `clean`, `checkout -- <file>`,
  `restore`, `cherry-pick`, `tag`, `git mv`/`git rm`/`git add`, or anything touching remotes. **No worktrees.**
- Never switch branches with uncommitted changes.
- New executable files: tell Tim to run `git add --chmod=+x <file>` (Windows loses the bit).

### Models and context
| Work | Who |
|---|---|
| Documentation (this file, briefs, `README.md`) | **Opus 5.5** only |
| Design, schema, Hue client, light access rules, services, reviews | Main session |
| Boilerplate from an exact spec; porting a file from Sidequest; repeating an established pattern | Haiku subagent, reviewed |
| Table-driven tests from a case list in the brief | Haiku subagent, reviewed |
| Running checks and summarising failures; mechanical lint fixes | Haiku subagent |
| Broad codebase searches | Explore agent |

Subagent prompts are self-contained (paste the exact spec excerpt, paths, conventions from §5 and the
acceptance check; don't say "read the brief"), ask for a short report (files, commands, results), and
spawn Haiku with `model: "haiku"`. Haiku never makes design decisions. Review every subagent diff
before ticking its task. Keep context small: targeted `grep`/reads, files under ~400 lines, bulky
runs in subagents.

---

## 2. Hard constraints (Tim)

- Python 3.12 backend; Discord **slash commands**.
- Runs in Docker Compose; `update.sh` pulls, backs up the database, rebuilds and restarts.
- Database is PostgreSQL (17, like Sidequest), with Alembic migrations. Not SQLite.
- Requirements are compiled from `pyproject.toml` with pip-tools
  (`pip-compile --no-emit-index-url ...`). Edit `pyproject.toml`, never hand-edit `requirements*.txt`.
- The light access file (`configs/lights.json`, `{"whitelist": bool, "lights": [uuid, …]}`,
  loaded with pydantic) is **read-only for the bot**: edited on the filesystem, read once at
  startup. No command may change it.
- Only users in `ALLOWED_USER_IDS` may use light and scene commands (empty = everyone).
- English only.

---

## 3. Architecture

### Today
```
main.py                     `python main.py`: logging + Config.from_env() + load_light_access (a
                            ConfigError exits without traceback) + Alembic upgrade head
                            (RUN_MIGRATIONS) + bot.run. `python main.py lights`: aurorahue/cli.py
aurorahue/config.py         frozen dataclass Config, from .env (python-dotenv); HueSettings (bridge +
                            access file only, no token, for the CLI); load_light_access + ConfigError
aurorahue/cli.py            `main.py lights`: every bridge light (UUID, name, colour/temperature/
                            dimming, allowed) + access-file IDs not on the bridge
aurorahue/bot.py            AuroraHue(commands.Bot): DB engine + sessionmaker, HueClient,
                            LightService, SceneService, SettingsService (setup_hook; closed in
                            close()), warns about unknown access IDs at startup, SystemClock, loads
                            cogs, syncs commands
aurorahue/core/clock.py     Clock protocol, SystemClock (tests: tests/support/clock.py FixedClock)
aurorahue/core/errors.py    AuroraHueError(.message) + NotFound, NameTaken, InvalidInput, NotAllowed,
                            BridgeUnavailable
aurorahue/core/access.py    LightAccess (pydantic, strict): allows(), unknown(), describe()
aurorahue/core/color.py     Hex, Kelvin, Color, parse_color (InvalidColor), hex_to_xy, xy_to_hex,
                            kelvin_to_mirek, mirek_to_kelvin, parse_brightness
aurorahue/services/lights.py  LightService: 60 s light cache, allowed(), resolve(),
                            apply(fresh=) -> ApplyReport; LightRequest (on True/False/None = keep,
                            colour, brightness %); Outcome.QUEUED (D35); on_targets() (D31); every
                            write checks LightAccess again
aurorahue/services/pending.py PendingChanges: in-memory queued colour/brightness per light, 30 min
                            (D35-D38); owned by LightService, lost on restart
aurorahue/services/scenes.py  SceneService (sessions, LightService, clock): list/get/get_by_id/
                            create/update/delete/actions_for_run/run; validates on save (D13)
aurorahue/services/settings.py  SettingsService: get_settings(), set_reset_scene(),
                            set_daytime_confirm(), set_on_exclude() (D18, D19, D25, D31)
aurorahue/services/model.py StrictModel (frozen, strict pydantic), SessionFactory
aurorahue/db/               base.py (Base, naming convention, TIMESTAMPTZ), session.py, migrate.py,
                            url.py (DATABASE_URL only, for Alembic), models.py (Scene, SceneAction,
                            BotSettings)
migrations/                 Alembic (async env.py); revisions named 0001_initial.py, 0002_…, 0003_…
aurorahue/cogs/general.py   /ping
aurorahue/cogs/common.py    is_allowed(), ConfirmView, confirm_if_daytime (D21, D25), lights option +
                            autocomplete (D6), scene autocomplete, service accessors, report_text
                            (D22), the tree error handler
aurorahue/cogs/lights.py    /on /off /color /brightness [lights], /lights
aurorahue/cogs/scenes.py    /scene list|add|edit|delete|run, /reset; scene list rendering
aurorahue/cogs/scene_builder.py  SceneBuilder view (D16), ActionForm modal, parse_action, rendering
aurorahue/cogs/settings.py  /settings [reset-scene] [daytime-confirm] [on-exclude] (D18, D26, D32)
aurorahue/hue/hue_client.py HueClient (httpx2, CLIP v2, verify=False): list_lights() -> BridgeLight,
                            apply(id, LightState) (one PUT; on=None leaves `on` out); HTTP errors
                            -> BridgeUnavailable
aurorahue/helpers/sun_finder.py  astral sunrise/sunset; is_daytime() (±30 min)
```
Tables (migrations `0002`–`0004`): `scenes`, `scene_actions`, `bot_settings` (one row, id 1).
Tests: `tests/unit` (layering, access file, colour, light service with a fake client, reply and
scene rendering), `tests/integration` (migrations, scenes and settings services;
fixtures in `conftest.py`, fake bridge in `tests/support/`). New code in `core`/`services`/`hue` uses absolute imports (the layering test only
sees those).

### Layers
```
cogs/ (discord)  — commands, views, autocomplete, rendering
      |
services/        — every rule: light access, resolving names, applying states, scenes, settings
   /     |      \
db/     hue/     core/ (pure: colour maths, access rules, parsing, errors, limits)
```
- `core` imports neither `discord`, `sqlalchemy` nor `httpx2`.
- `services`, `db` and `hue` never import `discord`. Only `cogs/` and `bot.py` do.
- Enforced by `tests/unit/test_layering.py` (ported from Sidequest).
- The flat `aurorahue/` package stays (no `src/` layout).

### Hue notes
- CLIP v2: `GET /clip/v2/resource/light` lists lights (`id` UUID, `metadata.name`, `on`, `dimming`,
  and `color` / `color_temperature` only if the light supports them).
  `PUT /clip/v2/resource/light/<id>` changes one light. Header `hue-application-key`.
- `dimming.brightness` 0 means "lowest possible", **not off**.
- Colour is CIE `xy`, not RGB: hex is converted in `core` (see the brief).
- The bridge handles roughly 10 light commands per second; send per-light requests sequentially.
- Light IDs are the v2 UUIDs (`python main.py lights` lists them). Users see light **names**;
  IDs only appear in `configs/lights.json`.

---

## 4. Domain rules

**Light commands** (all gated by `ALLOWED_USER_IDS`, D20):
| Command | Does |
|---|---|
| `/on [lights]` | switch on, keeping colour and brightness (D7); without `lights`, leaves the `on-exclude` lights alone, without saying so (D31, D33) |
| `/off [lights]` | switch off; never asks (D7) |
| `/color color [lights]` | hex (`#ff8800`, `f80`) or temperature (`2700K`, 2000–6500); lights that are on change, off lights queue it (D9, D28, D35) |
| `/brightness percent [lights]` | 0–100, 0 = lowest glow, not off; lights that are on change, off lights queue it (D10, D28, D35) |
| `/lights` | allowed lights with on/off, brightness, colour; ephemeral (D23) |

- `lights`: comma-separated names, autocomplete per D6; empty = all allowed lights.
- `/color`, `/brightness` never switch a light on (D28): they defer publicly, then
  `apply(…, fresh=True)`. Off lights come back as `Outcome.QUEUED` ("Queued until switched on
  (30 min): …"); the next switch-on **by the bot** (`/on`, `/scene run`, `/reset`) sends it in the
  same PUT (D35, D36). No daytime confirmation (D30).
- Daytime confirmation (D21) only when the setting is on (D25, default off), it's daytime and a
  targeted light is off right now (fresh bridge read,
  2 s limit so Discord's 3 s answer window holds). `confirm_if_daytime` answers the interaction;
  callers reply with `interaction.followup`.
- Light changes reply publicly via `report_text` (D22); errors and `/lights` are ephemeral.
- Errors: one `tree.error` handler (`cogs/common.on_app_command_error`); `AuroraHueError`
  messages are markdown/mention-escaped as a whole, so they must not rely on markdown.

**Scenes and settings** (also gated by `ALLOWED_USER_IDS`):
| Command | Does |
|---|---|
| `/scene list [scene]` | names + light count, reset scene ⟲; with `scene`: one line per action, disallowed lights as "(not controllable)" |
| `/scene add name` / `/scene edit scene [new-name]` | open the scene builder (D16); rename applied on Save |
| `/scene delete scene` | Delete / Cancel; extra line and the setting cleared if it's the reset scene (D19) |
| `/scene run scene` · `/reset` | apply the actions (D17); daytime confirmation if an off light goes on (D21) |
| `/settings [reset-scene] [daytime-confirm] [on-exclude]` | show; set or `none` to clear the reset scene (D18); daytime confirmation `on`/`off` (D25, D26); lights a bare `/on` leaves alone, comma-separated names replacing the list, `none` clears (D31, D32, D34) |

- A scene: unique name (1–50, any case), ≥ 1 action, one per light; an action is on/off + optional
  colour (hex or Kelvin, stored `#rrggbb` / `2700K`) + optional brightness; "off" takes neither
  (D13). Global, not per server (D14).
- Every light in a scene must be allowed **at save time**; running skips lights that are now
  disallowed or gone and lists them (D17). The builder drops such actions when it opens and says
  how many, without naming them (D4).
- Builder: ephemeral, owner-only, in memory until Save (last save wins), 14.5-minute timeout
  (Discord's interaction token lasts 15). Form errors reply ephemerally; the builder stays open.
  Selects hold at most 25 lights (Discord's limit).

---

## 5. Code conventions

- Python 3.12, full type hints, ruff lint + format, line length 100 (`pyproject.toml`).
- Logging via `logging`, never `print`.
- Bot replies set `allowed_mentions=discord.AllowedMentions.none()`; user text (scene names, light
  names) is escaped.
- Errors meant for users are `AuroraHueError` subclasses with a user-safe `.message`; commands raise,
  one error handler shows them ephemerally and logs the rest.
- Database code follows Sidequest: SQLAlchemy 2 async + asyncpg, `Base` with a naming convention,
  `expire_on_commit=False`, relationships `lazy="raise"`, services commit their own work.
- Code comments cite decisions (`D<n>`) from the brief, not segment numbers.

---

## 6. Decisions still in force

From `lights-and-scenes` (the archived brief has the details). Each finished brief adds its own.

- **D1** Light access file `configs/lights.json`, read once at startup with pydantic; no command changes it.
- **D2** Whitelist **or** blacklist (`whitelist` bool); empty `lights` = every light.
- **D3** No file = all allowed + warning; broken file = refuse to start; unknown IDs = warning.
- **D4** UUIDs in the file, names in Discord; a disallowed light never shows up in Discord.
- **D5** Light list from the bridge, cached 60 s; bridge down at startup → bot starts anyway.
- **D6** `lights` option: comma-separated names, autocomplete appends; empty = all; bad name = error, nothing changes.
- **D7** `/on` only switches on (keeps colour/brightness); `/off` only switches off.
- **D8** Replaced by D28.
- **D9** One colour field: hex (`#rrggbb`/`rgb`) or Kelvin (`2700K`, 2000–6500); hex → xy, Kelvin → mirek clamped per light.
- **D10** Brightness 0–100 %; 0 = lowest glow, not off.
- **D11** A light that can't show the colour still gets on/off + brightness; reply says "colour skipped for".
- **D12** `/minimum`, `/soft` and their presets are gone.
- **D13** Scene = unique name (1–50, any case) + at most one action per light (on/off, optional colour, optional brightness).
- **D14** Scenes are global, in PostgreSQL with Alembic.
- **D15** `/scene list|add|edit|delete|run` (no bare `/scene`).
- **D16** Add/edit open an in-memory, owner-only scene builder; 14.5-min timeout; Save needs ≥ 1 action.
- **D17** Running skips (and lists) disallowed/missing lights; partial failures listed, others still change.
- **D18** `/settings` holds bot-wide settings in the DB: the reset scene and the daytime confirmation.
- **D19** `/reset` runs the reset scene; deleting it asks with an extra line and clears the setting.
- **D20** `ALLOWED_USER_IDS` gates every light, scene and settings command; `/ping` is open.
- **D21** Daytime confirmation for every command that switches an **off** light on (fresh bridge read),
  when the setting is on (D25).
- **D22** Light changes reply publicly and short; everything else ephemeral; no pings.
- **D23** `/lights` (allowed lights + state) and `python main.py lights` (every light, UUID, support, allowed).
- **D24** No `/on` exception light any more.

From `daytime-confirm-setting`:

- **D25** The daytime confirmation is a setting (`bot_settings.daytime_confirm`), **off by default**;
  off = never ask.
- **D26** `/settings daytime-confirm:on|off`; can be combined with `reset-scene`; `/settings` shows both.
- **D27** The sun check, `astral` and `LATITUDE`/`LONGITUDE` stay (needed when D25 is on).

From `light-command-tweaks`:

- **D28** `/color` and `/brightness` never switch a light on: lights that are on change now; off
  lights queue the change (D35). Replaces D8.
- **D29** Replaced by D35 (all off → queued, normal public reply).
- **D30** So `/color` and `/brightness` never ask the daytime confirmation; D21 covers `/on`,
  `/scene run` and `/reset`.
- **D31** Setting `bot_settings.on_exclude` (light UUIDs): lights `/on` **without** `lights` leaves
  alone. Named `/on` and every other command ignore it.
- **D32** `/settings on-exclude:<names>` replaces the list (D6 autocomplete); `none` clears; a bad
  name changes no setting.
- **D33** A bare `/on` doesn't mention excluded lights; all lights excluded → ephemeral error.
- **D34** Only allowed lights are saved; IDs that become disallowed or leave the bridge are ignored
  by `/on` and counted, not named, by `/settings` ("+N not controllable").
- **D35** `/color`/`/brightness` on an off light queue the change in memory, 30 min from the latest
  change to that light; lost on restart. Reply: "Queued until switched on (30 min): …".
- **D36** Applied only when the bot switches the light on (`/on`, `/scene run`, `/reset`), in the
  same PUT; not when it's switched on outside the bot.
- **D37** Per field, newer queued values replace older ones; the switch-on request's own colour and
  brightness win (scene wins), the queue fills the gaps.
- **D38** Used once; dropped after a successful switch-on or a direct change while the light is on;
  `/off` and a failed PUT keep it.

---

## 7. Checks and testing

- `ruff check .` and `ruff format --check .`
- `pytest tests/unit`
- Integration tests need the test Postgres:
  `docker compose -f compose.test.yaml up -d`, then
  `TEST_DATABASE_URL=postgresql+asyncpg://aurorahue:aurorahue@localhost:55433/aurorahue_test pytest`.
  Without the variable they skip with a message. If Docker isn't available, say so; never fake it.
- After model changes: `alembic check`.
- Local dev: `.venv` with Python 3.12 (`py -3.12 -m venv .venv`, `pip install -r requirements-dev.txt`,
  `pip install --no-deps -e .`). Running the bot locally needs `DATABASE_URL` set; it must be reachable
  (e.g. the test Postgres) unless `RUN_MIGRATIONS=false`, since the engine connects lazily.
- Requirements: `bash scripts/compile-requirements.sh` (pip-compile in a `python:3.12-slim`
  container, so pins match the image). Then `pip install -r requirements-dev.txt` in `.venv`.
- Don't build the Docker image to "verify" (Tim's rule). Claude can't use Discord or reach the Hue
  bridge: every segment that touches either ends with a **manual test checklist** for Tim.

## 8. Operating the bot

- Secrets and settings: `.env` (template `.env.example`), also read by the `db` service
  (`POSTGRES_*`; the password is only used when the `aurorahue-db-data` volume is first created).
- Light access: `configs/lights.json` (git-ignored; template `configs/lights.example.json`), mounted
  read-only (`./configs:/app/configs:ro`). No file = every light, with a warning; a broken file =
  the bot refuses to start and logs each bad field. Startup log: "Light access: whitelist, 6 lights".
- Which UUID is which light: `docker compose run --rm bot python main.py lights` (needs only the
  `HUE_*` settings; also lists file IDs that aren't on the bridge).
- Deploy: `bash update.sh` (`--skip-db` skips the backup). Backups land in
  `backups/backup-<time>.sql.gz` (newest 14 kept); a failed backup aborts the update.
- Migrations run on bot start (`RUN_MIGRATIONS=true`).
- After editing `configs/lights.json`: `docker compose restart bot`.
