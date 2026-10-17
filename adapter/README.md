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

`start.sh` pipes `gamerule doDaylightCycle false`, `gamerule keepInventory true`, and `difficulty peaceful` to the
server console. The console reads them before the world loads, and a command read then has no world to act on, so
`worldborder` fails there. The adapter sets the border on each reset instead. The terminal stays attached to the
console for further commands.

`setup/reset-world.sh` resets the world between runs. It sends `stop` to the screen session `mc` and waits for the
server to exit. It then replaces `server/world` with `server/world.pristine` and starts `start.sh` in a new detached
screen session `mc`, returning once the server logs `Done`. It leaves the world alone unless the pristine copy exists
and the server has exited. It finds the server by its command line, `jar server.jar nogui`, so it assumes one server on
the machine. The adapter exits when its bot is dropped, so start the adapter again afterwards.

`server/world.pristine` is a world generated from seed 12345 that no player has entered, with an empty `datapacks`
folder. To make a new one: stop the server, move `server/world` aside, start the server so it generates a world, stop
it, and copy `server/world` to `server/world.pristine`.

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
| `VIEWER_PORT` | unset | When set, serves a third-person 3D view of the bot in the browser at `http://127.0.0.1:<port>`. It listens on all interfaces; prismarine-viewer has no host option. |

Each `/reset` and `/step` prints one JSON line to stdout, so a run the core drives can be read from the adapter's
output: `time`, `action`, `target`, `grid` (crafts and probes), `ok`, `message`, `output`, `events` (when any), and
`at`, the bot's position afterwards.

The adapter exits when the bot leaves the server. The viewer is prismarine-viewer 1.32.0: 1.33.0 loads the native
`canvas` package at runtime without declaring it, so it fails to import. The viewer's camera follows the bot only
once the bot first moves.

`POST /reset` centers a 256-block world border on the world spawn, clears the inventory with `/clear`, then fills it
with one `/give` per task item. Its response is the observation plus `message`, the commands it issued
(`"/worldborder center 8 -24; /worldborder set 256; /clear; /give @s oak_planks 4"`), so a run manifest can record the
start state. Blocks are not restored.

Steps over Minecraft:

- `move`: `target` is `north`, `south`, `east`, `west` (one block), or `{"toward": "log"}`, which paths until the
  nearest visible block of that type is horizontally within 1 block and within 4.5 blocks of reach. Paths never dig or
  place blocks, so moving leaves the inventory alone. A failed path stops the bot where it stands. Bounded at 20 s.
- `look`: changes nothing. `output` maps each heading `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW` to the nearest `log`,
  `stone`, `coal_ore`, or `crafting_table` as `{"block", "distance"}`, and leaves out headings that show none. It
  searches like the grid's look, over the loaded chunks: a corridor 7 wide and 48 long, step by step, center lane
  first. Each corridor cell is a column searched within 16 blocks of the feet, nearest height first. A block counts
  only when it touches air; worldgen fills caves with `cave_air`, so buried stone and cave walls stay out. A look that
  finds nothing reads about 280,000 blocks in about 0.15 s.
- Every observation lists the non-air blocks within 8 blocks that have a clear line from the bot's eyes, nearest first.
- `mine`: `target` is a block name. Walks within reach of the nearest visible one (20 s) and digs it with the fastest
  held tool. It waits 1 s for the drop. When the drop has rolled out of pickup range, it walks onto it (3 s) and
  waits 1 s more. `output` is `{block_removed, collected}`. `block_removed` is read after those waits, so a dig the
  server refused shows as `false`. `collected` is the inventory delta. `ok` equals `block_removed`.
- `place`: `target` is a held block, such as `crafting_table`. Places it on the first horizontally adjacent cell at
  foot level that is free, has a solid block below, and does not overlap the bot. `ok` is true once the server shows
  the block there, and the message gives its position. `output` is the inventory delta, as for `craft`:
  `{"crafting_table": -1}`. With no such cell, or when the server refuses, `ok` is false with a message.
- `craft`, `probe`: `grid` is a count map `{"planks": 2}` or rows `[["planks"], ["planks"]]` with `null` for an empty
  cell. A count map whose ingredient multiset matches a vanilla shape in `craft.mjs` takes that shape: planks, stick,
  crafting table, torch, wooden and stone pickaxe, furnace, ladder. Any other count map fills one item per cell, left
  to right and top to bottom. Rows set the shape outright. A grid that fits 2x2 uses the inventory grid. A larger one
  uses the nearest crafting table within 4 blocks, walking to one within 16. Crafting never places a table; `place`
  one first. `craft` takes the result once and reports the observed inventory delta, consumption negative:
  `{"planks": -2, "stick": 4}`. It returns `ok: false` and `"output slot empty"` when the server computed no result.
  `probe` reports the result slot, `{}` when empty, and puts everything back.
- `events` lists `death`, `damage` (the bot was hurt), and `kicked` seen during the step.
- Every step is bounded at 60 s. A timeout or an error inside the step is `ok: false` with a message.
- Steps go on after the goal is reached, so recovery can still act; `done` and `success` report as before. Only a
  spent budget refuses a step, with `ok: false` and `"episode is over"`, without counting it.

The shape table is shape knowledge only, so that two planks go one above the other and do not craft a pressure plate.
It says nothing about what a grid produces: the server decides that. The change datapacks are shapeless, so any
layout of their ingredients matches them.

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

Where each ingredient goes comes from `slotsFor` in `craft.mjs`, which reads only the request and the shape table.
The result is read from `window.slots[0]`, which holds what the server sent for the result slot after the last
confirmed click. `craft` then clears the consumed grid slots locally with `window.updateSlot`, because 1.16.5 servers
do not resend them. The delta comes from `bot.inventory.items()`. The code never calls `bot.recipesFor`,
`bot.recipesAll`, `bot.craft`, or `registry.recipes`. The test `the adapter never reads recipe data` fails if any
adapter module mentions them.
