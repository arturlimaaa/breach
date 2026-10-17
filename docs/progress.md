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
| M4 Mineflayer adapter + server setup | `al/m4-adapter` | running | `node --test` with a fake bot; live T1 waits on the EULA |
| M3 baseline B (rmalde architecture, grid) | `al/m3-baseline-b` | merged 1048e7b; follow-up (shared verifier classes, log-convention tests) merged cc9a544, 62 tests | B finishes vanilla T1; re-crafts under a count change; stalls under a precondition change |
| M3 evaluator + proof script | `al/m3-proof` | merged 78fc94e | proof.json and results table from a run directory |
| M3 matrix runner (B and D × every change × seeds, HS episodes) | `al/m3-proof` | running | `python3 -m breach.matrix runs/<name> --seeds 1 2 --systems B D` prints the table |
| M3 change-class follow-up (goal choice mid-plan, oak_wood barrier override, change.json) | `al/m3-changes` | running | tests per item; datapack for the oak_wood swap carries the override |
| M2 Nemotron client + inducer + test ordering | `al/m2-llm` | running | fake-transport tests; schema gate; model_calls.jsonl |
| M3 ring-sample look for H2 | `al/m3-look` | running | H2 succeeds on seeds 1 to 5 within budget |
| M7 site + OBS banner | `al/m7-site` | running | `node site/check.mjs` against fixtures |

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
