# Site

Static demo pages. No build step and no dependencies: serve the repo root and open a page.

```bash
python3 -m http.server   # from the repo root
open "http://localhost:8000/site/?run=<run>"
```

- `index.html`: the dashboard. Results table from `proof.json`, the plan diff with the rule under revision, and every stored rule grouped by status.
- `banner.html`: the OBS overlay. Add a Browser source at `http://localhost:8000/site/banner.html?run=<run>`, 1920×1080. The page background is transparent. It polls `status.json` every 250 ms and keeps the last frame when a read fails.

Both pages read `runs/<run>/`. `?run=` defaults to `latest`: the runner keeps `runs/latest` as a symlink to the newest run.

A run name is a path under `runs/`, so `?run=../site/fixtures` previews the fixtures. The banner has three more states: `?run=../site/fixtures/certified`, `../site/fixtures/demoted` and `../site/fixtures/revising`. `demoted` also carries a `store.json` for its before and after card.

Gate: `node site/check.mjs` (Node 24) runs both pages against the fixtures in a vm, with no browser and no network.

## Data contract

The pages read three files from `runs/<run>/` and ignore keys they do not know. A missing or unparsable file is reported in place of its section.

### status.json

The executor rewrites it after every step and on every rule status change. Write a temporary file and rename it over `status.json`, so a poll never reads half a file.

| Key | Type | Meaning |
|---|---|---|
| `episode` | string | Episode id. |
| `server` | string | Server id: the scope of a demotion. |
| `goal` | string | Goal item. |
| `step` | int | Actions spent: the `step` of the last transition. |
| `budget` | int | Action budget. |
| `started` | ISO 8601 | Run start. The banner clock shows `updated` minus `started`. |
| `updated` | ISO 8601 | Time of this write. |
| `plan` | list | `{rule_id, action, target, status}`, with `status` one of `done`, `current`, `pending`, `aborted`. After a contradiction, keep the done steps, mark the rest of the old plan `aborted`, then append the new plan. |
| `last` | object | The last transition: `{action, target, rule_id, predicted, observed, verdict}` as in the transition log. |
| `rule` | object | The rule in focus: `{rule_id, status, evidence, note}`. `status` is `certified`, `hypothesis`, `demoted`, `revising` or `recertified` (certified with `revision_of` set). `evidence` is the length of the rule's evidence list. `note` is one line of free text. |
| `model` | object | `{calls, last_latency_ms}`: text-model calls this episode, and the latency of the last finished call or `null`. |

While a rule is `demoted`, `revising` or `recertified`, `rule.rule_id` names the server-scoped record that `certify.demote` creates, such as `craft:stick@grid/stick-count-2`. The dashboard finds the rule it replaces through that record's `revision_of`. The banner's demoted line compares `last.predicted` with `last.observed`, so `last` is the contradicting step at that moment.

### proof.json

Written by `python3 -m breach.proof runs/<run>`. Top-level keys:

- `system`: the system label.
- `episodes`: one object per episode with `id`, `task`, `seed`, `success`, `actions`, `contradictions`, `actions_after_contradiction`, `immediate_repeat`, `recovery_latency`, `text_model_calls`, `tokens`.
- `aggregate`: `holdout_success`, `actions_per_success`, `actions_after_contradiction`, `immediate_repeat_rate`, `recovery_latency_mean`, `recovery_latency_worst`, `text_model_calls_per_episode`.
- `worst_case`: `{episode, recovery_latency}`. The episode whose `id` matches is the first row.

Rates are fractions in [0, 1]. A `null` metric shows as a dash. A failed episode with a contradiction and a `null` recovery latency shows `never`.

### store.json

The rule store file as `RuleStore` writes it: a JSON list of `Rule.to_dict()`. The pages read `rule_id`, `status`, `delta`, `scope`, `evidence`, `tool`, `near`, `source` and `revision_of`.

## Fixtures

A stone pickaxe episode on a server where a stick craft yields 2, not 4. Step numbers, plans and evidence lists come from the grid executor on seed 1, with training on T1 to T3 over seeds 1 and 2. The recovery is hand-written: the probe step, the revised rule's `source` and evidence, the Nemotron latency and token counts, and every `proof.json` number past the first contradiction.
