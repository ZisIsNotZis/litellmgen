# 01 — Per-field merge of flat model facts

- **Status:** done
- **Blocked by:** none
- **Assignee/lock:** agent (pi)
- **Need-review:** yes (behavior change: rewrites the generator and the generated `~/litellm.yml`)
- **Need-test-cases:** none (single-script generator; verification = regenerated config inspected + proxy hello check per vendor group)

## Issue

`litellmgen.py` merged its four sources with `models |= {...}`, i.e. whole-object replacement
after pydantic validation. Because absent fields validate to `None`, a higher-priority source
does not add to a lower one, it erases it. Measured on the previous output (388 entries):

- source 1 (`model_prices_and_context_window_backup.json`) contributed **0 models, always** —
  the file keys entries by `litellm_provider`, the filter read `provider` (0/3917 matches).
- A `cfg.models` entry of `{}` (volcengine's 12 models) clobbered nothing today only because
  the catalog ids differ; on collision it would have wiped the catalog's limits.
- 4/4 nested `model_info` keys were schema defaults in 388/388 entries — no source ever
  populates `features`, `modalities`, `task_type` or `token_limits`.
- `insertLimits` fabricated values: siemens's `/models` returns only `{id, type, display_name,
  created_at}`, and the nested defaults turned that into `supports_vision: false`,
  `supports_audio_input: false` and `task_type: [TextGeneration]` for 25 models.
- `insertLimits` also had four copy-paste assignment bugs (`supports_json_schema` guarded by
  `supports_audio_input`; `supports_audio_output` assigning `supports_audio_input`; both
  `supports_parallel_function_calling` branches assigning `supports_function_calling`).

PO direction (user, this round): nested shapes are needed only for *parsing*; everything is flat
afterwards. Never fabricate `false`; fabricating `None` is fine, `exclude_none` drops it.

## Acceptance criteria

- [x] Every source is normalized to one flat `Facts` model before merging; priority is per field.
- [x] `None` means "no source had an opinion" and never overwrites a non-`None` value.
- [x] No fabricated non-`None` values: empty container → unset, and unused sources stay unset.
- [x] Nested `Features`/`Modalities`/`Limits`/`insertLimits` deleted (no source speaks that shape).
- [x] `exclude_none=True` emission; no dict-level merging anywhere (typed merge only).
- [x] Source 1 resurrected by filtering on `litellm_provider`.
- [x] Per-source counts printed per group, so a dead source is visible at a glance.
- [x] Generated `~/litellm.yml` inspected: no nested keys, siemens carries no fabricated `false`.
- [x] One chat hello per vendor group against a local proxy on port 4001.
- [x] `github_copilot` failure filed as ticket 02 (pre-existing, out of this slice).

## Decisions (PO, this round)

- **Costs kept** (flat, litellm reads them: `utils.py` `_get_model_info_helper`). A `0.0`
  per-token cost in these sources means "price unknown", not "free" (volcengine), so `0.0`
  is normalized to unset; `tiered_pricing` carries the real volcengine numbers.
- **`model_info.id` dropped.** litellm assigns a per-deployment id when absent
  (`router.py:3764`); passing the catalog's upstream model name would make both aliases of a
  model share one id, and one failure would mark both unhealthy.
- **Endpoint source stays a discovery fallback** (`no offline and no catalog data`): its payload
  is an id list, not a description, so it can only add keys.
- **Unknown `cfg` keys warn instead of being ignored silently.** `lm.yml` uses `anthropic:`
  (siemens, volcengine) and `mode: responses` (github_copilot); none is implemented, all were
  dropped without a word. Implementing them is out of this slice.
- **Branchless, one commit**: the repo has no history to branch from, and this is one file /
  one concern. The pre-change file was never committed and its bytes are gone, so there is no
  baseline commit — the old behavior is recorded in the Issue section instead.

## Evidence

Gate = the script runs and its output is inspected; the module has no test runner.

| Command | Result |
| --- | --- |
| `python3 litellmgen.py` | exit 0; `[volcengine] backup=12 catalog=12 endpoint=0 user=12 -> 24`, `[github_copilot] 33/33/0/16 -> 47`, `[deepseek] 10/10/0/0 -> 10`, `[siemens] 0/0/25/0 -> 25`, `[zai] 16/16/0/0 -> 16`; 388 entries (was 388), 269,706 → 145,616 bytes |
| output key census | only flat keys: `mode` 214, `max_input_tokens` 212, `max_tokens` 180, `max_output_tokens` 166, `supports_*` …, `tiered_pricing` 32; `features`/`modalities`/`task_type`/`token_limits` **absent** |
| fabricated-`false` check | `siemens` = 25 entries, `model_info` `{}` in all of them, 0 with `supports_vision` (was `false` in 25). 174/388 entries carry `model_info: {}` — models whose names appear in no fact source (siemens's 25, volcengine's 12 and github_copilot's 16 user-listed names × their keys × 2 aliases) |
| drift check: litellm-declared `model_info` fields present in the sources but not declared | `[]` — all 35 declared fields cover them (round 2 had left `supports_output_config` out; now emitted on 2 entries) |
| `python3 litellmgen.py` with the catalog host pointed at a dead port (`/tmp/litellmgen.degraded.py`) | every group printed `!! [name] catalog source unavailable: ClientConnectorError`, then `backup=… catalog=0 …`; still wrote 388 entries, `deepseek/deepseek-chat` kept its limits from source 1 |
| user `cfg.models` `0.0` cost + explicit override (`/tmp/lm.test.yml`) | `deepseek-chat: {input_cost_per_token: 0.0}` → emitted `2.8e-07` (catalog kept); `deepseek-reasoner: {max_input_tokens: 999, supports_vision: false}` → `999` / `False` (user wins) |
| `litellm --config ~/litellm.yml --port 4001` | ready in 1s, `GET /health/readiness` 200, 0 error lines in `/tmp/litellm4001.log` |
| hello per group | `deepseek/deepseek-chat` 200 · `zai/glm-5` 200 · `volcengine/ark-code-latest` 200 · `volcengine/doubao-seed-2-0-pro-260215` 200 · `siemens/bge-m3` embeddings 200 (dim 1024) · `github_copilot` 400, pre-existing → ticket 02 |

Residuals: the port-4000 proxy still holds the pre-change config in memory and picks the new one up on
restart; the proxy on 4001 (`pid 839737`, log `/tmp/litellm4001.log`) is left running for the user's own
poking.

## Review record (need-review)

- Reviewer 1 (fresh context, adversarial code review; change = commit `2210d37`, diff hash
  `e1464026741f3ef2`): verdict **reject** — 8 findings, 3 at B. Real: unknown `cfg` keys were never
  warned about although this ticket decides they must be (grep for `warn` returned 0 hits); the user
  source bypassed the `0.0`-cost normalization, so a user `0.0` could override a catalog price and
  mark a paid model free; prefix-stripping collapsed the backup map's duplicate keys last-wins (6
  pairs for `deepseek`, byte-identical today, order-dependent otherwise). Also: no `raise_for_status`,
  no per-source isolation, 3 litellm-read fields missing from the declared set.
- Reviewer 2 (fresh context, fix verification; change = working-tree diff `57af2e46029d6074`): verdict
  **reject** — the `0.0`-cost and duplicate-key fixes verified FIXED; the status check was added but
  turned one vendor's catalog failure into an all-or-nothing abort; the declared set was still missing
  litellm-declared fields (`supports_output_config` present in the sources); the unknown-key warning
  was placed after the network work, so a failed build suppressed it.
- All findings fixed: fixes 1-3 in commit 1, the rest in the follow-up commit (per-source `guard()`,
  warning moved before the network work, 7 more declared fields + the drift check above).
- Two consecutive rejections is the parking threshold (`R-TKT.2`); no third round was run. The residual
  judgement call — hand-picked whitelist versus deriving it from litellm's own `ModelInfo` schema — is
  escalated to the user and tracked in ticket 03, not decided here.

## Comments

- start — agent (pi), 2026-09-15: ticket opened; nested-shape parsing needed only for sources that
  speak it, none does today, so adapters are flat in / flat out.
- done — agent (pi), 2026-09-15: rewrite landed; source 1 resurrected (`litellm_provider`), nested
  schema + `insertLimits` deleted, unknown `cfg` keys now warn (they surfaced ticket 02).
