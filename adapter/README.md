# Adapter

Mineflayer bot behind the local HTTP contract in [docs/design.md](../docs/design.md#adapter-contract-node-over-local-http).
Minecraft Java 1.16.5, Node 24.2 or later.

## Tests

```bash
npm install
npm test
```

The tests need no Minecraft server. `server.test.mjs` drives the HTTP contract over `fake.mjs`, an in-memory world.
`world.test.mjs` runs the Mineflayer world over a hand-made bot object. `protocol.test.mjs` connects a real Mineflayer
bot to a minecraft-protocol server that answers 2x2 grid clicks the way vanilla 1.16.5 does: the result slot arrives
before the click's confirmation, the server does not resend consumed grid slots, and it rejects a click whose claimed
item differs from the slot. It runs `/clear` and `/give` a few ticks late. That encodes a reading of the vanilla
source, not a live check. Mineflayer's `once` leaves
a 20 s timer running, so that file holds its process about 20 s after its tests pass.

## Minecraft server

```bash
MC_SEED=12345 setup/download-server.sh
```

The script fetches the official 1.16.5 `server.jar` into `server/` and checks its SHA-1. It skips the download when the
jar already matches. It writes `server.properties` (peaceful, spawn protection 0, view distance 10, offline mode, port
25565, `level-seed` from `MC_SEED`), an `ops.json` that gives the bot op level 2, and `start.sh`.

Two steps belong to the operator: install a JDK (`brew install openjdk@17`, then put it on `PATH`) and accept the
EULA by putting `eula=true` in `server/eula.txt`. Then:

```bash
server/start.sh
```

`start.sh` pipes these commands to the server console, which runs them once the world has loaded:
`gamerule doDaylightCycle false`, `gamerule keepInventory true`, `worldborder center ~ ~` (the world spawn),
`worldborder set 256`, `difficulty peaceful`. The terminal stays attached to the console for further commands.

To reset to a saved world: `stop`, replace `server/world` with the saved copy, start the server and the adapter again.

## Adapter

```bash
npm start
```

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `3100` | HTTP port on 127.0.0.1 |
| `MC_HOST`, `MC_PORT` | `127.0.0.1`, `25565` | Minecraft server |
| `MC_USERNAME` | `breach` | Bot name. `ops.json` is written for this name. |
| `MC_WORLD` | `world` | World name in the `server` field, `mc/<host>:<port>/<world>`. Set it per change world so server-scoped rules stay apart. |

The adapter exits when the bot leaves the server.

Steps over Minecraft:

- `move`: `target` is `north`, `south`, `east`, `west` (one block), or `{"toward": "log"}`, which paths until the
  nearest visible block of that type is horizontally within 1 block and in line of sight. Paths never dig or place
  blocks, so moving leaves the inventory alone. Bounded at 20 s.
- `look`: changes nothing. Every observation lists the non-air blocks within 8 blocks that have a clear line from the
  bot's eyes, nearest first.
- `mine`: `target` is a block name. Walks to the nearest visible one (20 s), digs it with the fastest held tool, then
  waits up to 3 s for the drop. `output` is `{block_removed, collected}`. `block_removed` is read after that wait, so
  a dig the server refused shows as `false`. `collected` is the inventory delta. `ok` equals `block_removed`.
- `craft`, `probe`: `grid` is a count map `{"planks": 4}` or rows `[["planks"], ["planks"]]` with `null` for an empty
  cell. A count map fills one item per cell, left to right and top to bottom. That only crafts shapeless and
  full-square recipes. Stick, torch, the pickaxes, furnace, and ladder are shaped in 1.16.5 and need rows. Two planks
  side by side craft a pressure plate. A grid that fits 2x2 uses the inventory grid. A larger one uses the nearest
  crafting table within 4 blocks, walking to one within 16. `craft` takes the result once and reports the observed
  inventory delta, consumption negative: `{"planks": -2, "stick": 4}`. It returns `ok: false` and `"output slot
  empty"` when the server computed no result. `probe` reports the result slot, `{}` when empty, and puts everything
  back.
- `events` lists `death`, `damage` (the bot was hurt), and `kicked` seen during the step.
- Every step is bounded at 60 s. A timeout or an error inside the step is `ok: false` with a message.

There is no `place` action. A 3x3 craft needs a crafting table already standing within 16 blocks.

## Datapacks and `/reload`

Copy a generated pack to `server/world/datapacks/<id>/` (`pack.mcmeta` with `pack_format` 6, then
`data/minecraft/recipes/` or `data/minecraft/loot_tables/`). Type `reload` in the `start.sh` terminal. The bot can
also chat `/reload`, since it has op level 2. In 1.16.5 a reload enables every pack in that folder that was not
explicitly disabled, so the change applies at once. `datapack list enabled` shows it as `file/<id>`. To remove it,
run `datapack disable "file/<id>"`, or delete the folder and `reload`.

## Crafting calls

Crafting never reads recipe data. These are the only Mineflayer calls on the crafting path:

| Call | Use |
|---|---|
| `bot.findBlock({matching, maxDistance: 16})` | Find a crafting table block |
| `bot.pathfinder.goto(goal)` | Walk to a table farther than 4 blocks |
| `bot.openBlock(table)` | Open the table's 3x3 window |
| `bot.closeWindow(window)` | Close a stray window before a 2x2 craft; close the table afterwards |
| `bot.clickWindow(slot, 0, 0)` | Pick up an ingredient stack, swapping it with the cursor |
| `bot.clickWindow(slot, 1, 0)` | Right-click one item into a grid slot |
| `bot.putSelectedItemRange(start, end, window, null)` | Return the cursor stack to the inventory |
| `bot.putAway(0)` | `craft` only: take the result once and store it |
| `bot.putAway(slot)` | Move grid leftovers back |

The result is read from `window.slots[0]`, which holds what the server sent for the result slot after the last
confirmed click. `craft` then clears the consumed grid slots locally with `window.updateSlot`, because 1.16.5 servers
do not resend them. The delta comes from `bot.inventory.items()`. The code never calls `bot.recipesFor`,
`bot.recipesAll`, `bot.craft`, or `registry.recipes`. The test `the adapter never reads recipe data` fails if any
adapter module mentions them.
