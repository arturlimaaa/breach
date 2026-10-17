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
| M3 ring-sample look for H2 | `al/m3-look` | merged 903f260, 65 tests | H2 seeds 1 to 5 finish in 74 to 187 actions (blind spiral: never within 300); T1 to T3 and H1 unchanged |
| M7 site + OBS banner | `al/m7-site` | merged 071d77f, then 661ac1c (multi-system proof.json); `node site/check.mjs` 8 pass | status.json and proof.json contracts in site/README.md; banner follows a rewrite within 600 ms |
| M4 adapter follow-up (`place` action, vanilla shape table by multiset) | `al/m4-adapter` | merged 2539e1e, 24 Node tests | `place` picks a free cardinal neighbour at foot level; a count map with a vanilla multiset takes its shape |
| M4 live smoke (T1's steps by curl against the running server) | `al/m4-adapter` | passed; fixes merged fd6b1b8 | T1 completes live in 12 hand-driven adapter steps, every delta exact; border is set by the adapter on each reset from the spawn packet; `place` reports the inventory delta |
| M4 adapter viewer (prismarine-viewer behind VIEWER_PORT) and real `look` | `al/m4-adapter` | running | http://127.0.0.1:3007 shows the bot; look reports per-heading nearest blocks |
| M2 recovery loop + system C | `al/m2-recover` | running | scripted-inducer tests; every benchmark change recovers on seed 1 and its HS episode makes zero inducer calls |
| M3 system A (Nemotron plan per task, no memory) | `al/m3-system-a` | running | scripted-`complete` tests; at least one call per task |
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

Tooling: the Playwright MCP browser is shared between every agent in the
session and can only write under /Users/artur/schema-voyager; agents take
screenshots with a headless Chrome and a throwaway profile in their scratchpad.

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
