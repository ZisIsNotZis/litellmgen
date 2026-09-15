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
| output key census | only flat keys: `mode` 214, `max_input_tokens` 212, `max_tokens` 180, `max_output_tokens` 166, `supports_*` …, `tiered_pricing` 32; `features`/`modalities`/`task_type`/`token_limits` **absent**; 0 empty-dict values |
| fabricated-`false` check | `siemens` = 25 entries, `model_info` `{}` in all of them, 0 with `supports_vision` (was `false` in 25) |
| `litellm --config ~/litellm.yml --port 4001` | ready in 9s, `GET /health/readiness` 200 |
| hello per group | `deepseek/deepseek-chat` 200 · `zai/glm-5` 200 · `volcengine/ark-code-latest` 200 · `volcengine/doubao-seed-2-0-pro-260215` 200 · `siemens/bge-m3` embeddings 200 (dim 1024) · `github_copilot` 400, pre-existing → ticket 02 |

Residual: the port-4000 proxy still holds the pre-change config in memory; it picks the new one up
on restart. Proxy on 4001 (`pid 834918`, log `/tmp/litellm4001.log`) left running for the user's own
poking.

## Comments

- start — agent (pi), 2026-09-15: ticket opened; nested-shape parsing needed only for sources that
  speak it, none does today, so adapters are flat in / flat out.
- done — agent (pi), 2026-09-15: rewrite landed; source 1 resurrected (`litellm_provider`), nested
  schema + `insertLimits` deleted, unknown `cfg` keys now warn (they surfaced ticket 02).
