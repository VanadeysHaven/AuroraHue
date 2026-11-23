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
main.py                     logging + Config.from_env() + bot.run
aurorahue/config.py         frozen dataclass Config, from .env (python-dotenv)
aurorahue/bot.py            AuroraHue(commands.Bot): loads cogs, syncs commands (GUILD_IDS or global)
aurorahue/cogs/general.py   /ping
aurorahue/cogs/light_toggle.py  /on /minimum /soft /off, is_allowed() check, daytime ConfirmView
aurorahue/hue/hue_client.py HueClient (httpx2, CLIP v2, verify=False); hard-coded LIGHT_IDS,
                            ON_EXCLUDED_LIGHT_IDS, ON_STATE preset
aurorahue/helpers/sun_finder.py  astral sunrise/sunset; is_daytime() (±30 min)
```
No database, no tests yet.

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
- Integration tests need the test Postgres *(after segment 1 of lights-and-scenes)*:
  `docker compose -f compose.test.yaml up -d`, then
  `TEST_DATABASE_URL=postgresql+asyncpg://aurorahue:aurorahue@localhost:55433/aurorahue_test pytest`.
  Without the variable they skip with a message. If Docker isn't available, say so; never fake it.
- After model changes: `alembic check`.
- Local dev: `.venv` with Python 3.12 (`py -3.12 -m venv .venv`, `pip install -r requirements-dev.txt`,
  `pip install --no-deps -e .`).
- Don't build the Docker image to "verify" (Tim's rule). Claude can't use Discord or reach the Hue
  bridge: every segment that touches either ends with a **manual test checklist** for Tim.

## 8. Operating the bot

- Secrets and settings: `.env` (template `.env.example`). Light access: `configs/lights.json`
  (template `configs/lights.example.json`), mounted read-only into the container.
- Deploy: `bash update.sh` (`--skip-db` skips the backup). Backups land in `backups/`.
- After editing `configs/lights.json`: `docker compose restart bot`.
