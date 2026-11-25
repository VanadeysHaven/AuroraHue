# Brief — Light command tweaks

**Status:** done
**Slug:** `light-command-tweaks` · **Migration:** `0004` (`bot_settings.on_exclude`, Segment 2)
Written by Claude (Opus 5.5), 2026-11-25.

**Goal:** two changes Tim asked for.
1. `/color` and `/brightness` no longer switch lights on. They change only lights that are on now.
2. A setting with lights that `/on` **without** a `lights` option leaves alone.

**Read first:** `CLAUDE.md`, then §1–§3 below, then the segment.

| Seg | Title | Branch | Status |
|---|---|---|---|
| 1 | `/color` and `/brightness` stop switching lights on | `claude/light-command-tweaks-s1-s2` | ✅ done |
| 2 | `/on` exclusion setting, migration `0004` | `claude/light-command-tweaks-s1-s2` | ✅ done |
| 3 | Queue changes for off lights (D35–D38) | `claude/light-command-tweaks-s1-s2` | ✅ done |

Legend: ⬜ todo · 🔨 in progress · ✅ done · ✅ done.

---

## 1. Decisions

| ID | Decision | Source |
|---|---|---|
| D28 | `/color` and `/brightness` never switch a light on. Lights that are on (fresh bridge read) change; lights that are off are skipped and listed in the public reply: `Skipped (off): Desk, Hallway.` **Replaces D8.** | Tim (no auto-on; skip and list) |
| D29 | If every targeted light is off, nothing changes and the reply is an **ephemeral error** (no public message): `That light is off; nothing changed. Use /on first.` (one light) / `All of those lights are off; nothing changed. Use /on first.` (several). | Tim |
| D30 | Since `/color` and `/brightness` never switch a light on, they never ask the daytime confirmation (D21). | Claude (follows from D28) |
| D31 | Bot-wide setting `on_exclude` in `bot_settings` (D18): lights that `/on` **without** `lights` leaves alone. Stored as light UUIDs (D4). `/on Desk` still switches Desk on. No other command looks at it (`/off`, `/color`, `/brightness`, scenes, `/reset`). | Tim (setting, bare `/on` only), Claude (scope) |
| D32 | `/settings on-exclude:<names>`: comma-separated light names with the D6 autocomplete; **replaces** the whole list; `none` (any case) clears it. A bad name is an error and nothing changes (D6). Can be combined with the other `/settings` options. | Tim (one option, replaces list) |
| D33 | A bare `/on` doesn't mention excluded lights in its reply. If every allowed light is excluded: ephemeral error `Every light is excluded from /on without lights; name the lights to switch on.` | Tim (say nothing), Claude (all-excluded case) |
| D34 | Only lights allowed **at save time** go into `on_exclude` (`resolve` already ensures that). IDs that later become disallowed or leave the bridge are ignored by `/on`; `/settings` doesn't name them (D4) but adds `(+N not controllable)`. | Claude (same rule as D13/D17) |
| D35 | `/color` and `/brightness` on an **off** light queue the change in memory instead of skipping it. Kept 30 minutes from the latest change to that light; lost on restart. Public reply: `Queued until switched on (30 min): Desk.` Replaces the skip in D28 and all of D29. | Tim |
| D36 | The queued change is applied only when the **bot** switches the light on (`/on`, `/scene run`, `/reset`), in the same PUT. Switching on with the Hue app or a wall switch doesn't apply it. | Tim (Claude's recommendation) |
| D37 | Queued colour and brightness combine per light; a newer value replaces the older one per field. On switch-on, the request's own colour/brightness win (a scene action wins), the queue fills the gaps. | Tim (scene wins), Claude (per field) |
| D38 | A queued change is used once: dropped after a successful switch-on, or when the light gets a direct change while it's on (the queue is stale then). `/off` and a failed PUT keep it. | Claude |

D8 is superseded by D28. Segment 3 replaces the skip half of D28 and all of D29 with D35. D21 still holds; after Segment 1 it applies to `/on`, `/scene run` and
`/reset` only.

---

## 2. Design

### Segment 1 — `/color`, `/brightness`

**`LightState` (`hue/hue_client.py`).** `on: bool | None`; `to_payload()` leaves `on` out when
it's `None`. So if a light is switched off between the check and the PUT, the colour command
doesn't switch it back on (the bridge just answers "soft off").

**`LightRequest` (`services/lights.py`).** `on: bool | None`. `None` = "keep on/off; only for a
light that is on" (D28). Validation adds: `on is None` needs a colour or a brightness.

**`Outcome.OFF = "off"`** — skipped because the light is off and the request has `on=None`. Not
counted in `ApplyReport.changed`.

**`LightService.apply`.** For `wanted.on is None` and `not light.on` → `Outcome.OFF`, no PUT.
`_state_for` passes `on=None` through to `LightState`. Scenes are untouched: their actions always
say on or off.

**`LightService.lit(targets) -> list[str]`** (new). Fresh bridge read (`allowed(fresh=True)`,
which also refreshes the cache that `apply` then uses). Returns the target IDs that are on now.
None on → raises `InvalidInput` with the D29 message (singular when `len(targets) == 1`).

**Cogs (`cogs/lights.py`).** `/color` and `/brightness`:
1. Parse, `resolve(lights)` (as today).
2. `async with asyncio.timeout(FRESH_READ_TIMEOUT): await service.lit(ids)`; `TimeoutError` →
   `BridgeUnavailable` (same as `confirm_if_daytime`). This runs **before** answering, so the D29
   error is still ephemeral via the tree handler.
3. `await interaction.response.defer()` (public) — no `confirm_if_daytime` (D30).
4. `apply(ids, LightRequest(on=None, color=…))` / `(on=None, brightness=…)` with **all** `ids`,
   so off lights come back as `OFF` and are listed. Reply via `report_text` + `followup`.
- Descriptions: `/color` "Set the colour of lights that are on." · `/brightness` "Set the
  brightness of lights that are on."

**`report_text` (`cogs/common.py`).** After the colour-skipped line: `Skipped (off): A, B.`

### Segment 2 — `/on` exclusion

**Schema (migration `0004_on_exclude.py`).** `bot_settings.on_exclude` =
`postgresql.ARRAY(sa.Uuid(as_uuid=False))`, `NOT NULL`, `server_default '{}'`. Downgrade drops it.
Model: `on_exclude: Mapped[list[str]]`.

**`SettingsService`.** `SettingsView.on_exclude: tuple[str, ...] = ()`. New
`set_on_exclude(ids: Sequence[str]) -> SettingsView` via the existing `_upsert` (deduplicated,
sorted), commit, return `get_settings()`.

**`services/lights.py`: `on_targets(lights: Sequence[BridgeLight], excluded: Collection[str])
-> list[str]`** (pure). IDs of `lights` not in `excluded`; empty → `InvalidInput` (D33 message).

**`/on` (`cogs/lights.py`).** Bare = `lights` is `None` or only spaces/commas. Bare →
`on_targets(await service.resolve(None), settings.on_exclude)`; otherwise as today. The daytime
confirmation gets the filtered IDs. The reply is the normal `report_text` (excluded lights simply
aren't targets, D33).

**`/settings on-exclude` (`cogs/settings.py`).**
- Option `on_exclude: str | None`, renamed `on-exclude`, description "Lights /on without lights
  leaves alone (comma-separated, or none)", autocomplete = the D6 lights autocomplete.
- `none` (stripped, any case) → `set_on_exclude([])`. Otherwise `resolve(text)` → IDs →
  `set_on_exclude(ids)`. Resolve before writing anything, so a bad name changes no setting. Empty
  after stripping counts as "not given".
- Sentences: set → `/on without lights now leaves out: Desk, Hallway.`; cleared →
  `/on without lights switches every light on.`
- `settings_text` gets a third line: `Excluded from /on: Desk, Hallway` / `Excluded from /on: none`,
  names from `LightService.allowed()` (cached), escaped, in name order; IDs not among them add
  ` (+N not controllable)` (D34). Bridge down → `Excluded from /on: N lights (bridge unreachable)`.

---

## 3. Tests

**Segment 1, unit** (`tests/unit/test_light_service.py`, `test_replies.py`, hue client tests):
| Case | Expect |
|---|---|
| `LightRequest(on=None)` with neither colour nor brightness | `ValueError` |
| `LightState(on=None, brightness=50).to_payload()` | no `on` key |
| `apply` `on=None` colour, light on | one PUT, no `on` in it, `OK` |
| `apply` `on=None` colour, light off | no PUT, `OFF` |
| `apply` `on=None`, one on + one off | one PUT; `OK` + `OFF`; `changed == 1` |
| `apply` `on=None` hex on a temperature-only light that is on | `COLOR_SKIPPED` (D11 still holds) |
| `lit` with two on, one off | the two IDs |
| `lit` all off, one target / two targets | `InvalidInput`, singular / plural message |
| `report_text` with `OFF` results | `Skipped (off): A, B.` |
| `apply(on=True)` (scenes, `/on`) | unchanged behaviour (existing tests stay green) |

**Segment 2, unit:** `on_targets` — none excluded → all; some excluded → the rest; all excluded →
`InvalidInput`; excluded ID not among the lights → ignored. `settings_text` with exclusions, none,
and with a not-controllable ID.

**Segment 2, integration** (`tests/integration/test_settings.py`, add):
| Case | Expect |
|---|---|
| fresh migration, `get_settings()` | `on_exclude == ()` |
| `set_on_exclude([b, a, a])` | `(a, b)` |
| set, then `set_on_exclude([])` | `()` |
| reset scene + daytime confirm set, then `set_on_exclude` | all three kept |

Migration (`tests/integration/test_migration_0004.py`, like `0003`): up → down → up; the existing
row has `on_exclude = '{}'` after up.

---

## Segment 1 — `/color` and `/brightness` stop switching lights on

**Branch:** `claude/light-command-tweaks-s1-s2` (both segments, Tim's call) · **Status:** ✅ done

1. [x] `LightState.on` optional, payload leaves it out (main session).
2. [x] `LightRequest.on` optional, `Outcome.OFF`, `apply` skip, `lit()` (main session).
3. [x] `/color` and `/brightness`: `lit` before answering, public defer, no daytime check (D28–D30).
4. [x] `report_text`: `Skipped (off): …`.
5. [x] Tests from §3, Segment 1 (main session; see Handoff).
6. [x] Docs: `CLAUDE.md` (§4 command table, D8 replaced by D28, D21 note, D28–D30 added),
       `README.md` (`/color`, `/brightness` rows).
7. [x] Checks (§7 of `CLAUDE.md`).

**Manual test checklist (Tim, after deploy):**
- [x] One light on, one off: `/color #ff0000` → only the on light turns red; reply lists the other
      under `Skipped (off)`; the off light stays off.
- [x] Same with `/brightness 30`.
- [x] `/color 2700K Desk` with Desk off → private error, Desk stays off.
- [x] `/on` afterwards: the light comes on with its old colour (not the skipped one).
- [x] Daytime confirmation on, daylight: `/color` never asks.

Checked by Tim on 2026-11-25 against Segment 3 behaviour: the "Skipped (off)" reply and the
all-off private error above were replaced by the queue (D35).

**Handoff** (2026-11-25, built together with Segment 2):
- Built: `LightState.on` and `LightRequest.on` take `None` (keep on/off; `on` left out of the PUT);
  `Outcome.OFF`; `LightService.lit()` (fresh read, D29 errors); `/color` and `/brightness` call it
  under the 2 s limit before a public defer, then `apply(on=None)`; `report_text` adds
  `Skipped (off): …`. Command descriptions now say "of lights that are on".
- Deviations:
  - `apply` skips the PUT when an `on=None` request leaves nothing to send (e.g. `/color` on a
    plain white light): outcome `COLOR_SKIPPED`, no empty PUT to the bridge.
  - `lit([])` returns `[]` instead of raising, so "no allowed lights at all" still answers
    "No lights changed." as before.
  - Tests written in the main session, not by Haiku (short cases; reviewing a subagent diff would
    have cost more).
- Open questions: none.

---

## Segment 2 — `/on` exclusion setting

**Branch:** `claude/light-command-tweaks-s1-s2` · **Status:** ✅ done

1. [x] Model column + migration `0004_on_exclude.py`; `alembic check` (main session).
2. [x] `SettingsService`: `on_exclude` in the view, `set_on_exclude` (main session).
3. [x] `on_targets` in `services/lights.py`; bare `/on` uses it (D31, D33).
4. [x] `/settings on-exclude` option, autocomplete, sentences, third settings line (D32, D34).
5. [x] Tests from §3, Segment 2 (main session; see Handoff).
6. [x] Docs: `CLAUDE.md` (architecture: migration `0004`; §4 `/on` and `/settings` rows; D31–D34),
       `README.md` (`/on`, `/settings` rows).
7. [x] Checks (§7 of `CLAUDE.md`), including integration tests if Docker is available.

**Manual test checklist (Tim, after deploy):**
- [x] `/settings on-exclude:Desk` → reply names Desk; `/settings` shows `Excluded from /on: Desk`.
- [x] Everything off, `/on` → every light except Desk comes on; reply doesn't mention Desk.
- [x] `/on Desk` → Desk comes on.
- [x] `/settings on-exclude:nosuchlight` → error, setting unchanged.
- [x] Exclude every light, `/on` → private error.
- [x] `/settings on-exclude:none` → `/on` switches every light on again.

**Handoff** (2026-11-25):
- Built: `BotSettings.on_exclude` + migration `0004_on_exclude.py`; `SettingsView.on_exclude`,
  `set_on_exclude()` (deduplicated, sorted); `on_targets()` in `services/lights.py`; bare `/on`
  (`is_bare()` in `cogs/lights.py`) filters through it before the daytime check;
  `/settings on-exclude` with "none" + D6 autocomplete, resolved before any setting is written;
  `settings_text(view, light_names)` has a third line, built by `excluded_text()`.
- Checks: `ruff check`/`format --check` clean; `pytest tests/unit` 180 passed; full `pytest` with
  the test Postgres 245 passed; `alembic check`: no new operations.
- Deviations:
  - `on_exclude` is `ARRAY(Text)`, not `ARRAY(Uuid)`: light IDs are `Text` everywhere else
    (`scene_actions.light_id`), and `str` in the code.
  - An `on-exclude` value of only spaces/commas counts as "not given" (resolve would read it as
    "every light").
  - Only hidden IDs left → `Excluded from /on: none (+1 not controllable)`.
  - `/settings` now also reads the (cached) light list to name excluded lights; bridge down →
    `N lights (bridge unreachable)` instead of failing.
  - Both segments on one branch and the brief carried uncommitted onto it (Tim's call).
- Open questions: none.

---

## Segment 3 — Queue changes for off lights

**Branch:** `claude/light-command-tweaks-s1-s2` (on top of Segments 1 and 2, Tim's call) ·
**Status:** ✅ done

Tim's follow-up (2026-11-25): instead of skipping an off light, queue the colour change in memory
for 30 minutes; it doesn't need to survive a restart. Decisions D35–D38 (§1). Replaces the "skip"
half of D28 and all of D29: `LightService.lit()` and the 2 s pre-check are gone.

1. [x] `services/pending.py`: `PendingChanges` (queue/peek/take/drop, 30 min TTL on the `Clock`).
2. [x] `LightService.apply`: off + `on=None` → queue what the light can show, `Outcome.QUEUED`;
       `on=True` → request values over queued ones; drop after success or a direct change;
       `fresh=` parameter. `lit()` removed.
3. [x] `/color`, `/brightness`: public defer, `apply(…, fresh=True)`.
4. [x] `report_text`: `Queued until switched on (30 min): …`; no "No lights changed." when all queued.
5. [x] Tests: queue, merge, expiry, used once, `/off` keeps, change-while-on drops, failed PUT keeps.
6. [x] Docs: `CLAUDE.md` (architecture, §4, D28/D29 amended, D35–D38), `README.md`.
7. [x] Checks.

**Manual test checklist (Tim, after deploy):**
- [x] Desk off: `/color #ff0000 Desk` → public "Queued until switched on (30 min): Desk."; Desk
      stays off.
- [x] `/brightness 20 Desk`, then `/on Desk` → Desk comes on red at 20 %.
- [x] `/on Desk` again later → no colour change (used once).
- [x] Queue a colour, wait 30 min, `/on` → old colour.
- [x] Queue `#0000ff` for a light, run a scene that sets that light to a colour → the scene's colour.
- [x] Queue a colour, restart the bot, `/on` → old colour (nothing survives a restart).

**Handoff** (2026-11-25):
- Built: `PendingChanges` in `services/pending.py`, owned by `LightService` (no change to
  `bot.py`). `apply` queues what the light can show (colour dropped when it can't show it;
  nothing at all → `COLOR_SKIPPED`), merges the queue into `on=True` requests and drops it after a
  successful PUT. `/color` and `/brightness` defer publicly first, then read the bridge fresh, so
  there's no 3 s limit any more.
- Checks: `ruff check`/`format --check` clean; full `pytest` with the test Postgres 254 passed.
- Deviations: built straight away on Tim's "change it", as a third segment of this brief rather
  than a new brief.
- Open questions: none.
