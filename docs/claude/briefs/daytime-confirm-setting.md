# Brief — Daytime confirmation as a setting

**Status:** ready
**Slug:** `daytime-confirm-setting` · **Migration:** `0003` (`bot_settings.daytime_confirm`)
Written by Claude (Opus 5.5), 2026-11-24.

**Goal:** the daytime confirmation (D21) no longer asks by default. Tim can switch it back on with
`/settings daytime-confirm:on`. With it off, `/on`, `/color`, `/brightness`, `/scene run` and
`/reset` just do it, day or night.

**Read first:** `CLAUDE.md`, then §1–§3 below, then the segment.

| Seg | Title | Branch | Status |
|---|---|---|---|
| 1 | Setting, migration, `/settings` option, docs | `claude/daytime-confirm-setting-s1` | ⬜ todo |

Legend: ⬜ todo · 🔨 in progress · 👀 waiting for review · ✅ done.

---

## 1. Decisions

| ID | Decision | Source |
|---|---|---|
| D25 | The daytime confirmation (D21) is a bot-wide setting, `daytime_confirm`, stored in `bot_settings` (D18). **Default off.** Off = no question at any time of day; the command goes straight to the public defer. On = D21 exactly as today. | Tim (setting in `/settings`), Claude (default off, since the request was to stop the prompts) |
| D26 | `/settings` gets a second optional option `daytime-confirm` with choices **on** / **off**. Both options may be given in one call; each is applied, then the reply shows all settings. `/settings` with no options shows both lines: `Reset scene: …` and `Daytime confirmation: on/off`. | Claude |
| D27 | The sun check, `astral`, `LATITUDE`/`LONGITUDE` and `helpers/sun_finder.py` stay: they are needed when the setting is on. | Claude (follows from D25) |

D21 is amended, not removed: "when `daytime_confirm` is on (D25)".

---

## 2. Design

**Schema (migration `0003_daytime_confirm.py`).** `bot_settings.daytime_confirm BOOLEAN NOT NULL
DEFAULT false` (`server_default=sa.false()`). Downgrade drops the column. Model:
`daytime_confirm: Mapped[bool] = mapped_column(Boolean, server_default=false())` on `BotSettings`.

**Service (`services/settings.py`).**
- `SettingsView` gains `daytime_confirm: bool = False`.
- `get_settings()` today **inner**-joins `Scene`, so with no reset scene it returns an empty view.
  It becomes a select from `BotSettings` with an **outer** join to `Scene`, returning
  `reset_scene_id`, `reset_scene_name` and `daytime_confirm`. No row → `SettingsView()` (defaults).
- New `set_daytime_confirm(enabled: bool) -> SettingsView`: the same upsert pattern as
  `set_reset_scene` (`on_conflict_do_update` on `id`, only `daytime_confirm` in `set_`), commit,
  return `get_settings()`.

**`confirm_if_daytime` (`cogs/common.py`).** Order of checks, cheapest first, so the common case
does no bridge read:
1. `switching_on` empty → defer (as today).
2. `settings_service(interaction).get_settings()`; `daytime_confirm` false → defer.
3. `sun_finder.is_daytime` false → defer.
4. Fresh bridge read and question, exactly as today.

The DB read sits before the interaction is answered, like the bridge read; it's one small query,
well inside Discord's 3 s. It is **not** under `FRESH_READ_TIMEOUT` (that limit is for the bridge).
Update the docstring and the D21 comment to cite D25.

**`/settings` (`cogs/settings.py`).**
- Option `daytime_confirm: app_commands.Choice[str] | None`, renamed `daytime-confirm`, choices
  `on` / `off`, description "Ask before switching lights on in daytime".
- Apply `reset-scene` first (as today), then `daytime-confirm`. Reply (ephemeral, no mentions):
  the confirmation sentence(s) for what changed, then the current settings. Exact wording:
  - shown/after change: `Reset scene: **<name>**` or `Reset scene: none`, and
    `Daytime confirmation: on` / `Daytime confirmation: off`.
  - set on: `Daytime confirmation on; switching an off light on in daytime asks first.`
  - set off: `Daytime confirmation off; light commands never ask.`
  - Keep the existing reset-scene sentences.
- Keep files small: if the render grows, a `settings_text(view: SettingsView) -> str` helper in
  `cogs/settings.py`, unit-tested in `tests/unit/test_replies.py`.

---

## 3. Tests

Integration (`tests/integration/test_settings.py`, add):
| Case | Expect |
|---|---|
| fresh migration, `get_settings()` | `daytime_confirm is False`, reset scene None |
| `set_daytime_confirm(True)` then `get_settings()` | True; reset scene untouched |
| set True, then False | False |
| reset scene set, then `set_daytime_confirm(True)` | both kept |
| `set_daytime_confirm(True)` after deleting row 1 | row recreated, True, reset scene None |
| no reset scene, `daytime_confirm` True | `get_settings()` still returns True (outer-join regression) |

Migration (`tests/integration/test_migration_0003.py`, like `test_migration_0002.py`): up → down →
up; after up, the existing row has `daytime_confirm = false`.

Unit: `settings_text` for the four on/off × scene/none combinations, if the helper exists.

---

## Segment 1 — Setting, migration, `/settings` option, docs

**Branch:** `claude/daytime-confirm-setting-s1` · **Status:** ⬜ todo

1. [ ] Model column + migration `0003_daytime_confirm.py` (main session); `alembic check`.
2. [ ] `SettingsService`: outer join, `daytime_confirm` in the view, `set_daytime_confirm` (main session).
3. [ ] `confirm_if_daytime` checks the setting first (D25) (main session).
4. [ ] `/settings daytime-confirm` option and reply text (D26) (main session).
5. [ ] Tests from §3 (Haiku from the case tables, reviewed).
6. [ ] Docs: `CLAUDE.md` (architecture: migration `0003`, `/settings` row, D21 amended, D25–D27
       added), `README.md` (`/settings` row, the "Daytime check" bullet says it's off by default).
7. [ ] Checks (§7 of `CLAUDE.md`), including integration tests if Docker is available.

**Manual test checklist (Tim, after deploy):**
- [ ] `/settings` shows `Daytime confirmation: off`.
- [ ] In daylight, `/on` on an off light: no question, lights go on, public reply.
- [ ] `/settings daytime-confirm:on`, then `/on` in daylight on an off light: the question appears.
- [ ] `/settings daytime-confirm:off reset-scene:<scene>`: both change in one reply.
- [ ] `/reset` and `/scene run` in daylight with the setting off: no question.

**Handoff:** —
