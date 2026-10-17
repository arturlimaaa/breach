# Progress

## Checkpoints

Orchestrator: the main session. Builders: Opus agents, one per lane, each in
its own git worktree and branch. A lane is done when its gate command passed
and the orchestrator read the output, then the branch is merged into
`al/integrate` (checked out at /Users/artur/breach; lanes live in /Users/artur/breach-wt/<lane>).

| Lane | Branch | Status | Gate |
|---|---|---|---|
| M0 core | `al/m0-core` | done, 9f73c73 | 17 tests green |
| M1 verifier + certifier + demotion | `al/m1-verify` | merged fcae9e7, 29 tests | synthetic-log tests; vanilla T1 plans after a server demotion |
| M3 change-class generator + datapacks | `al/m3-changes` | merged 2a72002, 49 tests; 20 of 30 changes benchmarkable | 30 changes enumerated, rulesets and datapacks written, impossible goals excluded |
| M4 Mineflayer adapter + server setup | `al/m4-adapter` | merged 3a78b9a; `npm ci` in adapter/ then `node --test`, 21 pass | two contract gaps remain before a live T1: no `place` action, and shaped recipes need `grid` as rows (follow-up lane) |
| M3 baseline B (rmalde architecture, grid) | `al/m3-baseline-b` | merged 1048e7b; follow-up (shared verifier classes, log-convention tests) merged cc9a544, 62 tests | B finishes vanilla T1; re-crafts under a count change; stalls under a precondition change |
| M3 evaluator + proof script | `al/m3-proof` | merged 78fc94e | proof.json and results table from a run directory |
| M3 matrix runner (B and D × every change × seeds, HS episodes) | `al/m3-proof` | merged 7d5435a, 92 tests | seeds 1 2, 20 changes: B HC 60% success, D HC 0% (18 of 40 mis-scored by the loop's contradiction path, routed to m2-recover), D HS 0 contradictions and 0 model calls but no plan until recovery lands |
| M3 change-class follow-up (goal choice mid-plan, oak_wood barrier override, change.json) | `al/m3-changes` | merged 7d5435a | 8 of 20 changes hit the changed rule mid-plan; the other 12 end on the changed craft; change.json round-trips |
| M2 Nemotron client + inducer + test ordering | `al/m2-llm` | merged 7d5435a | fake-transport tests pin provider-shaped requests (NVIDIA, Crusoe, Ollama); schema gate; model_calls.jsonl |
| M3 proof follow-up (worst_case and aggregate keyed by system; manifest records the world's outcome; a lying manifest is refused; repeats skip move and look) | `al/m3-proof` | merged 54f1222, 96 tests | seeds 1 2: B HC 65%, D HC 20% (the terminal count changes) before recovery |
| M3 matrix wiring for A (`--systems A B D`, `--llm`, offline replanner logs calls as `vanilla-replanner`) | `al/m3-proof` | merged f88b581, 117 tests | seed 1 offline: A 45% HC and HS at 5 calls per episode; D HS 0 calls |
| M3 recovery latency measured across episodes on a server; C wiring | `al/m3-proof` | running | the 9 same-step changes get a latency from their HS use |
| M3 ring-sample look for H2 | `al/m3-look` | merged 903f260, 65 tests | H2 seeds 1 to 5 finish in 74 to 187 actions (blind spiral: never within 300); T1 to T3 and H1 unchanged |
| M7 site + OBS banner | `al/m7-site` | merged 071d77f, 661ac1c, 09e8fba (per-system worst-case lines, real fixture); `node site/check.mjs` 9 pass | status.json and proof.json contracts in site/README.md; banner follows a rewrite within 600 ms |
| M4 adapter follow-up (`place` action, vanilla shape table by multiset) | `al/m4-adapter` | merged 2539e1e, 24 Node tests | `place` picks a free cardinal neighbour at foot level; a count map with a vanilla multiset takes its shape |
| M4 live smoke (T1's steps by curl against the running server) | `al/m4-adapter` | passed; fixes merged fd6b1b8 | T1 completes live in 12 hand-driven adapter steps, every delta exact; border is set by the adapter on each reset from the spawn packet; `place` reports the inventory delta |
| M4 adapter viewer (prismarine-viewer 1.32.0 behind VIEWER_PORT) and three live fixes (drop walk, high-log reach, path stop) | `al/m4-adapter` | merged e1411d7, 28 Node tests | T1 live again in 12 steps; a log 5 blocks up is mined; viewer follows the bot after its first move |
| M4 adapter: accept steps after success until the budget | `al/m4-adapter` | merged 8e8a719, 29 Node tests | the running adapter predates it; restart after look merges |
| M4 adapter: real `look` (corridor scan over columns, air-adjacent blocks only) | `al/m4-adapter` | merged 971f57d, 32 Node tests; adapter restarted on merged code | same output shape as the grid's look |
| M4 count-datapack gate live (`/reload`, craft stick returns 2, disable, returns 4) | `al/m4-adapter` | passed 15:09 | pack folder `world/datapacks/stick-count-2` stays in place, disabled; `datapack disable "file/<id>"` reloads by itself; the flag reaches level.dat on save |
| M7 watch page (viewer frame + status panel + live step log) | `al/m7-site` | merged fd75715, 12 site checks | `site/watch.html?run=<run>&episode=<id>`; fixture preview with `?run=../site/fixtures` |
| M4 live travel semantics (`paths` capability, toward-moves, action fields for D, B, and A; spiral bounded only after a null look) | `al/m4-live-travel` | merged e77ad31, 042ea0c, e25cbd2; 132 tests | D over the fake adapter: T1 in 12 actions with one toward-move per mine; H2 over the fake 10 of 10 seeds; 52 grid logs byte-identical; T3 over the fake fails 4 of 10 on remembered out-of-view stone (station-placement lane) |
| M3 proof: immediate repeat = next non-move, non-look step reusing the refuted rule_id | `al/m3-proof` | merged 37982ba, 131 tests | a revision id or test step never counts; A 60% and B 20% unchanged |
| M4 adapter: per-step JSON log line, `setup/reset-world.sh` with `world.pristine` | `al/m4-adapter` | merged e8bf3fa, 33 Node tests; the lane is regenerating the pristine world and then reruns the core's live T1 | the mine after a successful toward-move is explained by the adapter's log |
| M4 adapter `executed` flag on every /step reply | `al/m4-adapter` | merged 5b940f6, 37 Node tests | false only when the action was refused before touching the world |
| M8 NeMo Gym wrapper, verifiable-reward export, tier ablation runner | `al/m8-nemo` | running | export loads in a smoke test; ablation row per model |
| M6 HR arm: reload-before-first-use world wrapper, grid tests, live datapack reload through the console | `al/m6-reload` | merged 2666a66, 180 tests | grid, seed 1, perfect inducer, all 20 changes: contradiction at the reload step, 0 actions after it reuse the rule, every HR recovers, HS 0 inducer calls; live apply waits on `datapack list enabled` and re-enables the pack after `reload` |
| M4 fourth core-driven live T1 (`runs/live-t1-4`, with placement) | integrate | mined, crafted planks and a table, then the second toward-move failed "no path toward log" for a log diagonally adjacent one block up, and the run ended "no reachable log" at 5 actions | the adapter's toward-move used a stricter goal than its mine (adapter lane aligning them); the executor will attempt the mine after a failed toward-move (recovery lane) |
| M3 live.py `--llm`, status and store files, `--store`, `--prior`, `--keep-pack` | `al/m3-proof` | queued behind the Nano failure analysis | live HR then HS on the server with Nemotron becomes one command each |
| M4 fifth core-driven live T1 (`runs/live-t1-5`, reach fix) | integrate | mined, crafted planks and a table; a mine after a successful toward-move answered "no log in sight" (now tolerant, no contradiction); then 140 of 150 actions went to cardinal `move east` steps that all failed "no path east" while look reported logs at distance 1 on four headings | root cause: observe, toward-move and mine use a line-of-sight-to-centre test while look uses air-adjacency, so trunks under leaves are invisible to the core; the adapter unifies on the air-adjacent rule and adds a pathing heading move; the executor explores with heading moves on pathing worlds |
| M5 rmalde's harness as live B: pinned clone script, model wiring, events converter | `al/m5-rmalde` | running; Jev key is an operator item | proof runs on a converted events.jsonl |
| M4 second core-driven live T1 (`runs/live-t1-2`, with the real look) | integrate | ran: 4 actions, look, move north, toward-move ok, then mine ok=false, "contradiction at mine:log"; by hand from the bot's spot the adapter says "no log in sight" (the bot had wandered onto depleted ground) | needs the per-step log and a world reset |
| M4 first core-driven live T1 (`runs/live-t1-1`) | integrate | ran: 16 actions, mined a log, crafted planks and a table, then a mine returned ok=false with an empty delta under server lag and was scored "contradiction at mine:log" | finding: a mine whose block was not removed is an execution failure, not evidence against the rule; score it tolerant (adapter output `block_removed`), exact only once the block is gone. Goes to the station-placement lane with the executor's `place` step. Exploration used the blind spiral because the adapter's look is not in yet. |
| M3 proof: recovery tests are not repeats; probes do not count as inventory | `al/m3-proof` | merged 55774a0, 120 tests | D's drop-change test mine scores 0 repeats |
| M2 recovery loop + system C + status.json | `al/m2-recover` | merged e3f6227, 158 tests, site check 12 | seed 1, perfect inducer, HC then HS: all 20 changes recover, 0 inducer calls in HS, every revision certified after HS, proof repeat 0 on all 20, latency 3 to 60; the refuting step is the first test when it succeeded, so count changes recover with 0 probes |
| M3 matrix wiring for C, D's real inducer (`--llm`), `--inducer perfect`, status.json and store.json per D job, runs/latest | `al/m3-proof` | merged 629aae9, 163 tests (the lane's merge was red on the status argument; fixed on integrate) | offline, seeds 1 2, perfect inducer: D 100% HC and HS, 0 repeats, recovery worst 60; A 45% with 60% repeats, B 65% with 20%, C 45% with 151 actions after contradiction and 40% repeats. Dashboard `runs/latest` shows this run. |
| M3 Crusoe request shape (no `reasoning_budget` there; thinking through `chat_template_kwargs`) | `al/m3-proof` | merged 27a7e5d, 164 tests | one real induction call on Nano 30B: HTTP 200 with the JSON schema, 400 tokens in, 2392 out, 18.3 s, 7.8k characters of reasoning, one candidate kept and it was the true revised stick rule |
| M3 first real Nemotron run (D over 20 changes, seed 1, Nano 30B, `runs/nemotron-nano-s1` on the dashboard) | `al/m3-proof` | done, before chained logs | 13 of 20 contradictions recovered (mean 12.5 actions, worst 52), 7 never (torch and crafting_table changes exhausted two rounds); HC success 45%, HS 40% with 0 model calls and 0 contradictions on all 20 HS; 24 induction calls, 0 failed, median 748 tokens in and 4016 out, median 26 s, max 72 s; schema gate kept 32 of 70 candidates, rejected 0 (the rest duplicates or past k). Failure analysis assigned. |
| M3 chained transition logs (`TransitionLog(path, prior=...)`, run_jobs passes a chain's earlier logs, live `--prior`) and the matrix `--sets HC HR HS` (HR chains under D/<change>-s<seed>-hr) | `al/m3-proof` | merged 0a52484, 193 tests | HC then HS and HR then HS leave the revision certified in store.json |
| M5 rmalde's harness as live B: pinned clone script, model relay (planner to Nemotron, Jev to OpenRouter), events converter | `al/m5-rmalde` | merged bdc8b4a; setup run (his npm postinstall scripts) and the Jev key wait on the operator | converted events pass the proof; waits are not actions |
| M4 adapter reach: eight columns around the block within 4.5, toward-move and mine share one approach over the three nearest visible blocks | `al/m4-adapter` | merged 0a52484, 41 Node tests; adapter restarted on it | the diagonal case from live run 4 returns ok with no pathfinder call |
| M4 adapter heading move (`move {"heading": H, "blocks": n}` paths n blocks along a look heading, falls back to n/2 then n/4 from the start point, 20 s per attempt) | `al/m4-adapter` | merged fb64170, 46 Node tests, 201 core tests; adapter restarted on it | cardinal and toward forms unchanged; the executor's heading exploration on pathing worlds is on the recovery lane |
| M4 adapter visibility unified on look's air-adjacent rule (observe `visible`, toward-move and mine candidates are the non-air blocks within 8 that touch `air`, nearest first; a toward-move's block leads the next mine's candidates) | `al/m4-adapter` | merged d79fcaa, 48 Node tests, 201 core tests; adapter restarted on it after a world reset | a trunk under leaves is in the observation and minable; `visible` now lists every exposed block within 8 and parse() keeps one block per column |
| M4 sixth core-driven live T1 (`runs/live-t1-6`, pristine world, watchdog off) | integrate | passed 16:19: wooden pickaxe in 13 actions, 13 of 13 verdicts match, 0 contradictions, 0 model calls; `python3 -m breach.proof runs/live-t1-6` reads 100% | M4 gate met (core completes T1 in the real world, zero exact mismatches); three toward-move, mine, planks triples, then table, sticks, place, pickaxe; the second live gate (count datapack) passed at 15:09 |
| M4 adapter mine tool from the game's harvest data (equips the fastest held harvester, refuses stone with no pickaxe held, executed false, reports the tool) | `al/m4-adapter` | merged 9e90b30, 51 Node tests, 201 core tests | before it a bare-handed stone dig removed the block with no drop, a false drop contradiction; the adapter restarts on it with the next merge |
| M6 first live HR (`runs/live-hr-1`, stick-count-2, Nemotron Nano 30B, `--keep-pack --llm`) | integrate | the pack loaded by reload at step 4 (listing seen), then the stick craft answered "output slot empty" (observed {}); two induction rounds gave candidates with empty deltas and `near` values "planks", "stick", '{"crafting_table":1}'; the executor placed planks for one; "unrecoverable craft:stick" after 6 actions, 2 calls, 8643 tokens | the HR reload path works live; cause confirmed: the bot held spruce planks (`/data get entity breach Inventory`) and the pack's recipe takes `minecraft:oak_planks` only; the adapter lane switches pack ingredients to the planks and logs tags and writes a log loot table per wood; the proof lane adds the inducer gate (a craft candidate produces its target, `near` is null or a station block, `tool` is a known tool) |
| M3 live `--hs <change>` (HS episode on a server that already has the change loaded, no pack; with `--store`, `--prior`, `--llm`) | `al/m3-proof` | merged 4360713, 202 tests | over the fake adapter an HR with keep_pack then HS leaves the revision certified from both logs |
| M3 Nano failure analysis (12 failing changes of `runs/nemotron-nano-s1`) | `al/m3-proof` | report delivered | only 8 of the 13 "recoveries" are genuine: 8 changes adopted a revision that produces nothing, confirmed by a probe's empty slot, and all 5 HS failures after a recovered HC come from them; the true rule appeared for 1 of 12; neither k=5 nor a third round would cover any; the prompt lacks the change class, the item list, and that a craft must produce its target; Super 120B still answers 429. Decided: no proof guard, the schema gate makes such a rule impossible; the grid's refusal message stays out of the prompt because the live adapter gives none |
| M2 exploration on pathing worlds (one heading move per look, a turn after a failed move; a failed toward-move no longer ends travel, the mine is attempted) | `al/m2-recover` | merged 4360713, 206 tests | D 10 of 10 on T1 to H2 over the fake and the grid; H2 over the fake 19 to 59 actions (was 48 to 167); log target "E8"; open on the lane: the remembered-block walk is still cardinal, a refused dig is still exact |
| M4 adapter `look` with a block-type target and `move {"to": {x,y,z}}` (reach goal, 20 s bound) | `al/m4-adapter` | merged 9401298, 58 Node tests | stone masked by logs is found; a return to a remembered table is one action; the core side goes to the recovery lane |
| M3 inducer schema gate (a craft candidate consumes something, produces its target, `near` null or a station, the prompt states it) | `al/m3-proof` | merged c9ff0b0, 209 tests | the four live-HR candidates are refused; the Nano matrix rerun with the gate has not happened; craft candidates should also require `tool` null (crafting never needs a held tool), one line, not done |
| Wrap-up 2026-10-17 16:35 | integrate | c9ff0b0 pushed, 209 core, 58 Node, 12 site | not done: a live HR/HS success (datapack wood tags in progress on the adapter lane), the Nano rerun, live T2/H1/H2, live B (user items), recordings; lanes told to stop after their current commit |
| M4 third core-driven live T1 (`runs/live-t1-3`, pristine world) | integrate | every mine and 2x2 craft matched; failed at the 3x3 craft: the executor never places the table ("no crafting table within 16 blocks") and scored the refused craft as a contradiction | both faults are on the recovery lane: `place` step, and an `executed` flag on StepResult so a refused action is tolerant |
| M4 station placement (grid `place`, near = station block in reach, planner skip, B menu), mine ok=false is tolerant, remembered blocks out of view | `al/m2-recover` | merged d06b7cb, 173 tests | D over the fake adapter and the grid: T1 to H2 all 10 of 10 on seeds 1 to 10 (T3 was 6); B unchanged except H2; grid T1 is 20 actions (one place step) |
| M4 executor reads the adapter's `executed` flag (StepResult.executed; refused actions log tolerant; refused probes are never evidence) | `al/m2-recover` | merged 7e594bc, 201 tests | a refused craft without a station is tolerant; a refused recipe with a station stays exact; next on the lane: a mine that left its block is tolerant, and heading-move exploration on pathing worlds |
| M3 live.py run wiring (`--llm`, status and store files, `--store`, `--prior`, `--keep-pack`) | `al/m3-proof` | merged 7e594bc | next on the lane: `--hs <change>`, then the Nano failure analysis |
| M3 system A (Nemotron plan per task, no memory) | `al/m3-system-a` | merged 8a8e520, 114 tests | scripted-`complete` tests; one call per task minimum; re-asks on failure up to 8 calls; matrix wiring assigned to the proof lane |
| M4 HttpWorld glue + live CLI | `al/m4-httpworld` | merged 00f13ca, 107 tests | Executor and B over a fake HTTP adapter reproduce the grid T1 and H2 logs; `python3 -m breach.live runs/<name> --task T1` |
| M4 live travel semantics (action fields, `move toward` on pathing worlds, fake adapter contract) | `al/m4-live-travel` | running | T1 over the fake adapter with one move per travel; grid logs unchanged |
| M4 station placement (grid `place`, executor near-check, planner rule for a placed table, B menu) | after recovery lands | queued | live T1 reaches the 3x3 craft |

Follow-ups not yet assigned: B explores with the blind spiral, so B fails H2 on
the grid while rmalde's real harness has ring samples; give B the `look`
before the H2 row is compared. The look reports the nearest block of any type
per heading; a logs-only look reached the first log in 39 to 58 actions
against 44 to 149 (measured by the look lane, not committed). Wire systems A
and C into `evaluate.run_jobs` after their lanes merge. Executor-side
placement of the crafting table (grid `place` action, executor near-check, B
menu option) is a lane after recovery lands.

Library behaviour found live (adapter lane): mineflayer-pathfinder keeps
walking a partial route after a step reports "no path" unless the goal is
cleared, and its reach check refuses blocks 3 or more above the feet;
prismarine-viewer 1.33.0 fails to import on Node 24 (undeclared native
`canvas`), 1.32.0 works; console commands piped before the world loads have
no world, so `worldborder` fails while `gamerule` works; a detached screen
session needs `-p 0` for `stuff` to reach the console.

Tooling: the Playwright MCP browser is shared between every agent in the
session and can only write under /Users/artur/schema-voyager; agents take
screenshots with a headless Chrome and a throwaway profile in their scratchpad.

Nemotron: the Crusoe key in ~/.config/breach/env (mode 600, outside every
repo) answers HTTP 200 for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and, as
of 2026-10-17 15:16, HTTP 429 "max_requests_limit (orchestrator)" for the
Super 120B model; the env file points at Nano 30B until Super answers. No
Ollama fallback is used.

Client: Prism Launcher 11.1.1 is installed with two 1.16.5 instances
(`breach-me` for the operator, `breach-agent` for the spectator or second
client), both auto-joining localhost:25565; the Microsoft sign-in is the
operator's step before any launch. The bot viewer runs at
http://127.0.0.1:3007 while the adapter is started with VIEWER_PORT=3007.

Crash on 2026-10-17 14:50: the server's watchdog killed it after a 60 s tick
under CPU starvation (load 232 on 8 cores: a Prism game client, the WebGL
viewer tab, and parallel lane test runs). Restarted from the saved world.
Keep one viewer tab open and no game client while lanes run their suites.
Second crash 16:10, the same watchdog at load 213, one minute after a world
reset. `max-tick-time=-1` is now set in the live server.properties and in
`setup/download-server.sh` (bdfefe8), so a stalled tick lags instead of
killing the server. The adapter exits when the server kicks the bot and is
restarted by hand after a reset.

World facts (seed 12345, read offline from `world.pristine` by the adapter
lane): the bot spawns at (58,69,-112) with logs on all eight headings at 1 to
3 blocks; no exposed stone within 32 blocks, the nearest at (48,72,-81), 33
blocks south-southwest, 12 within 48; the nearest exposed coal 76 blocks away.
Logs mask stone in an unfiltered look until about 25 blocks south. So T2, H1,
T3 and the stone-drop changes need a look filtered by block type and a move to
a remembered position (adapter lane), and the table placed at the point of use
or a return to the placed one (executor).

Server: the vanilla 1.16.5 server runs from `adapter/server/` (seed 12345,
offline mode, port 25565, `eula=true` set on 2026-10-17) inside the detached
screen session `mc`; console commands via `screen -S mc -X stuff 'cmd\n'`.

## 2026-10-17, session 1

Shipped (M0, branch `al/m0-core`): typed rules with scope and status
(`rules.py`), store with server-scope shadowing (`store.py`), grid world with
seeded layouts, rulesets, and the probe action (`world.py`), minimum-action
planner over certified rules only (`planner.py`), transition log with exact
and tolerant verdicts (`log.py`), executor that aborts a plan at the first
exact mismatch (`loop.py`). 17 tests pass:
`python3 -m unittest discover -s tests -t .`

Gate M0: empty store issues zero crafts; a stick-count ruleset aborts at the
craft step with zero actions after; the same seed loads identically.

Dead ends: the planner's cost recursion returned a (cost, rule) tuple where a
number was expected; the executor reused a stale map after mining and mined
the same cell twice. Both fixed, both covered by the loop tests.

Not done: H2 exploration. The blind spiral is O(r²) and cannot reach logs 33
blocks away within 300 actions; the grid needs the ring-sample `look` (M3).
Persistence paths of the store and log are written but not exercised by tests.

Next session, first: M1 (verifier whitelist by action and block, `quarantined`
verdict, certifier by replay with the three conditions, server-scoped
demotion), tests first.

Operator queue: repo name and remote (nothing is pushed yet), Crusoe org and
credit form, build.nvidia.com key, Jev key for B, Minecraft EULA.
