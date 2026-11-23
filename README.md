# AuroraHue

A small Discord bot that controls the Philips Hue lights in one home through one Hue bridge.
Switch lights on and off, set a colour or brightness, and save **scenes** (a setting per light) you
can run with one command. Slash commands only; it runs in Docker Compose with PostgreSQL.

## Commands

Only users listed in `ALLOWED_USER_IDS` can use these (empty = everyone). `/ping` is open to all.

| Command | What it does |
|---|---|
| `/on [lights]` | Switch lights on; they keep their colour and brightness. |
| `/off [lights]` | Switch lights off. |
| `/color color [lights]` | Set a colour and switch the lights on. `color` is a hex colour (`#ff8800`, `f80`) or a white temperature (`2700K`, 2000–6500). |
| `/brightness percent [lights]` | Set brightness 0–100 and switch the lights on. 0 is the lowest glow, not off. |
| `/lights` | The lights the bot controls, with their state (only you see it). |
| `/scene list [scene]` | All scenes, or one scene's lights. The reset scene is marked ⟲. |
| `/scene add name` | Create a scene in the scene editor. |
| `/scene edit scene [new-name]` | Change (and optionally rename) a scene in the scene editor. |
| `/scene delete scene` | Delete a scene (asks first). |
| `/scene run scene` | Run a scene. |
| `/reset` | Run the reset scene. |
| `/settings [reset-scene]` | Show the settings, or pick the reset scene (`none` clears it). |

- **`lights`** is a comma-separated list of light names; autocomplete offers them one after another.
  Leave it empty for all lights.
- **Daytime check:** between sunrise and sunset (±30 minutes) the bot asks before switching on a
  light that is off right now.
- Light changes reply publicly ("Turned on 3 lights."); lists, the scene editor, settings and errors
  only show to you.

### The scene editor

`/scene add` and `/scene edit` open an editor only you can use:

- **Set lights…**: pick one or more lights, then fill in a form: on/off, colour (optional) and
  brightness (optional). Empty fields keep the light's current value when the scene runs.
- **Remove lights…**: take lights out of the scene.
- **Save** stores the scene; **Cancel** throws the changes away. The editor expires after
  14.5 minutes without saving.

Lights that aren't in a scene are left alone when it runs. A light the bot may no longer control is
skipped and mentioned in the reply.

## Setup

1. Copy `.env.example` to `.env` and fill it in:
   - `DISCORD_TOKEN`: the bot token.
   - `GUILD_IDS`: the server(s) to register the slash commands in.
   - `ALLOWED_USER_IDS`: who may control the lights (empty = everyone).
   - `HUE_BRIDGE_IP`, `HUE_APP_KEY`: the bridge's address and an application key.
   - `LATITUDE`, `LONGITUDE`: your location, for the daytime check.
   - `POSTGRES_*` and `DATABASE_URL`: the database (the password must match in both).
2. Choose which lights the bot may control (next section).
3. Start it: `docker compose up -d --build`.

### Which lights the bot may control

`configs/lights.json` (copy `configs/lights.example.json`):

```json
{
  "whitelist": true,
  "lights": ["8a94b76b-eb9f-42fb-8b58-8c8701a80283"]
}
```

- `"whitelist": true`: only the listed lights. `false`: every light **except** the listed ones.
- An empty (or missing) `lights` list allows every light.
- No file at all: every light is allowed (with a warning in the log). A broken file: the bot
  doesn't start and logs what's wrong.
- The file is read once at startup. After editing it: `docker compose restart bot`.

The file uses the lights' IDs. To see which ID is which light:

```bash
docker compose run --rm bot python main.py lights
```

This lists every light on the bridge with its ID, name, what it supports and whether the file
allows it.

## Updating

```bash
bash update.sh            # pull, back up the database, rebuild, restart
bash update.sh --skip-db  # same, without the backup
```

Backups go to `backups/` (the newest 14 are kept); if the backup fails, the update stops.
Database migrations run when the bot starts.

## AI Disclaimer

This bot is built using AI tools as an assist to development. Code either human written or human
checked.
