# AuroraHue — what Claude Code needs to know

> Written by Claude (Opus 5.5), 2026-11-23. Read this file, then **only** the brief (and the segment)
> you're working on. Sections marked *(after lights-and-scenes)* describe where the code is going;
> until that brief is done, the code may not match them yet.

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
aurorahue/bot.py            AuroraHue(commands.Bot): DB engine + sessionmaker, HueClient +
                            LightService (setup_hook; closed in close()), warns about unknown access
                            IDs at startup, SystemClock, loads cogs, syncs commands
aurorahue/core/clock.py     Clock protocol, SystemClock (tests: tests/support/clock.py FixedClock)
aurorahue/core/errors.py    AuroraHueError(.message) + NotFound, NameTaken, InvalidInput, NotAllowed,
                            BridgeUnavailable
aurorahue/core/access.py    LightAccess (pydantic, strict): allows(), unknown(), describe()
aurorahue/core/color.py     Hex, Kelvin, Color, parse_color (InvalidColor), hex_to_xy, xy_to_hex,
                            kelvin_to_mirek, mirek_to_kelvin, parse_brightness
aurorahue/services/lights.py  LightService: 60 s light cache, allowed(), resolve(), apply() ->
                            ApplyReport; LightRequest (on, colour, brightness %); every write checks
                            LightAccess again
aurorahue/services/scenes.py  SceneService (sessions, LightService, clock): list/get/get_by_id/
                            create/update/delete/actions_for_run/run; validates on save (D13)
aurorahue/services/settings.py  SettingsService: get_settings(), set_reset_scene() (D18, D19)
aurorahue/services/model.py StrictModel (frozen, strict pydantic), SessionFactory
aurorahue/db/               base.py (Base, naming convention, TIMESTAMPTZ), session.py, migrate.py,
                            url.py (DATABASE_URL only, for Alembic), models.py (Scene, SceneAction,
                            BotSettings)
migrations/                 Alembic (async env.py); revisions named 0001_initial.py, 0002_…
aurorahue/cogs/general.py   /ping
aurorahue/cogs/common.py    is_allowed(), ConfirmView, confirm_if_daytime (D21), lights option +
                            autocomplete (D6), report_text (D22), the tree error handler
aurorahue/cogs/lights.py    /on /off /color /brightness [lights], /lights
aurorahue/hue/hue_client.py HueClient (httpx2, CLIP v2, verify=False): list_lights() -> BridgeLight,
                            apply(id, LightState) (one PUT); HTTP errors -> BridgeUnavailable
aurorahue/helpers/sun_finder.py  astral sunrise/sunset; is_daytime() (±30 min)
```
Tables (migration `0002`): `scenes`, `scene_actions`, `bot_settings` (one row, id 1); the scene
services aren't wired into the bot yet (segment 5). Tests: `tests/unit` (layering, access file,
light service with a fake client), `tests/integration` (migrations, scenes and settings services;
fixtures in `conftest.py`, fake bridge in `tests/support/`). New code in `core`/`services`/`hue` uses absolute imports (the layering test only
sees those).

### Target *(after lights-and-scenes)*
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

## 4. Domain rules *(after lights-and-scenes)*

Filled in from the brief's decisions when its segments are done. Until then, the brief is the
source of truth.

**Light commands** (segment 3 done; all gated by `ALLOWED_USER_IDS`):
| Command | Does |
|---|---|
| `/on [lights]` | switch on, keeping colour and brightness (D7) |
| `/off [lights]` | switch off; never asks (D7) |
| `/color color [lights]` | hex (`#ff8800`, `f80`) or temperature (`2700K`, 2000–6500), switches on (D8, D9) |
| `/brightness percent [lights]` | 0–100, 0 = lowest glow, not off; switches on (D8, D10) |
| `/lights` | allowed lights with on/off, brightness, colour; ephemeral (D23) |

- `lights`: comma-separated names, autocomplete per D6; empty = all allowed lights.
- Daytime confirmation (D21) only when a targeted light is off right now (fresh bridge read,
  2 s limit so Discord's 3 s answer window holds). `confirm_if_daytime` answers the interaction;
  callers reply with `interaction.followup`.
- Light changes reply publicly via `report_text` (D22); errors and `/lights` are ephemeral.
- Errors: one `tree.error` handler (`cogs/common.on_app_command_error`); `AuroraHueError`
  messages are markdown/mention-escaped as a whole, so they must not rely on markdown.

---

## 5. Code conventions

- Python 3.12, full type hints, ruff lint + format, line length 100 (`pyproject.toml`).
- Logging via `logging`, never `print`.
- Bot replies set `allowed_mentions=discord.AllowedMentions.none()`; user text (scene names, light
  names) is escaped.
- Errors meant for users are `AuroraHueError` subclasses with a user-safe `.message`; commands raise,
  one error handler shows them ephemerally and logs the rest *(after lights-and-scenes)*.
- Database code follows Sidequest: SQLAlchemy 2 async + asyncpg, `Base` with a naming convention,
  `expire_on_commit=False`, relationships `lazy="raise"`, services commit their own work.
- Code comments cite decisions (`D<n>`) from the brief, not segment numbers.

---

## 6. Decisions still in force

None recorded yet. Each finished brief adds its decisions here (ID + one line).

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
