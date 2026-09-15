# 05 — Doc source: implementation and review record

- **Status:** done
- **Blocked by:** none (contract: ticket 04's decisions)
- **Assignee/lock:** agent (pi)
- **Need-review:** yes — carried out, two rounds, both recorded below
- **Need-test-cases:** none (the child repo has no runner; verification = run the generator + targeted module tests written to `/tmp`)

## What landed

`litellmgen.py` (+166 lines):

- `Pattern` and `Doc` — the config surface, both `extra='forbid'`, `bind: Literal['forward']|None`.
- `flatten`, `page_text` — a page body (Quill-delta JSON included) becomes one line of text.
- `nearest_listed`, `doc_facts`, `from_docs` — rule application, forward binding, min-on-conflict, per-rule
  counts, complaints; a bad rule, a dead rule or an unreachable page is reported and skipped, never fatal.
- `DERIVED_ONLY` (`max_tokens` cannot be prose-derived), `BOOL_FIELDS` (a rule without a `value` capture is
  only valid on a flag field).
- `build`: `guard`-isolated, inserted as the fourth source — priority is
  backup < catalog < endpoint < **docs** < user `models:`, so hand-written facts still win.

`lm.yml` (not versioned — it holds live keys): the `docs:` block for `volcengine`, six patterns, no vendor
knowledge in the script. The console URL is an SPA shell, so the block points at the JSON endpoint behind it
(`/api/doc/getDocDetail?DocumentID=1925114&lang=zh`).

## Evidence

| Command | Result |
| --- | --- |
| `python3 litellmgen.py` | `doc1 …: 10 models, hits [8, 8, 1, 1, 1, 5]`; `[volcengine] backup=12 catalog=12 endpoint=0 docs=10 user=12 -> 24 models`; 388 entries |
| output diff vs the pre-docs run | 80 entries changed, all volcengine (10 models × 4 keys × 2 aliases); key sets equal; every other group byte-identical |
| facts landed | `doubao-seed-evolving` 1000000/256000 · `minimax-m3` 1024000/128000/vision · `glm-5.3` 1000000/128000 · `glm-5.3-flash` 1000000/128000/vision · `deepseek-v4-flash`/`pro` 1000000/384000 · `kimi-k3` 1000000/128000/vision · `kimi-k2.7-code` 256000/32000/vision · `doubao-seed-2.1-turbo`/`2.0-lite` vision; `ark-code-latest`/`glm-latest` empty |
| `litellm --config ~/litellm.yml --port 4001` | ready; all six coding-plan models answer 200 (`ark-code-latest`, `glm-5.3`, `glm-5.3-flash`, `kimi-k3`, `doubao-seed-2.1-turbo`, `minimax-m3`) |
| over-large `max_tokens` (200000 vs the doc's 128000 output cap) | **400 from the provider**, not a silent cap — the behaviour ticket 04 chose |
| module tests (`/tmp/lg_test*.py`, `main()` stubbed) | forward-bind tie, undeclared unit, invalid regex, invalid `field`, `max_tokens` rule, dead-rule reporting, bad `text:` locator, `bind`/`window` key typos — all as specified |

## Review record (need-review)

- **Round 1** — fresh-context reviewer (`explore`, read-only), diff hash `941b5901a3db74fe: verdict **reject**,
  4 B + 3 C. B:`nearest_listed` tied at one index and bound `glm-5.3-flash` to `glm-5.3` (prefix
  shadowing); an undeclared unit silently multiplied by 1 and min-on-conflict kept the wrong value; one
  unknown `field` raised and discarded everything already mined; a failing first doc dropped the group's
  remaining docs. C: the dead-rule warning named only the field; `max_tokens` was excluded from doc patterns
  by config only, not by code; a `bind` typo degraded to "nothing matched".
- **Round 2** — fresh-context reviewer (`general-purpose`, executed the tests), diff hash
  `a1416b7195307f0c`: verdict **reject**; confirmed fixes 1-6 hold, then found the round-1 fixes incomplete:
  an invalid *regex* still killed the whole docs source (`re.error` escaped both the per-doc `try` and the
  `except ValueError`); a misspelled *key* (`bindd:`) was still silently dropped because `Pattern`/`Doc` were
  `extra='ignore'`; a rule with no `value` capture on a numeric field set `True`, which pydantic coerced to
  `1` and min-on-conflict then made sticky — a silent load-bearing `max_input_tokens: 1`. C: the per-doc
  error message conflated config with network failure; a rule whose matches all used an undeclared unit was
  also reported as "nothing matched".
- **All fixed and re-verified** (targeted tests above): patterns are compiled up front with `re.error`
  caught, `Pattern`/`Doc` are `extra='forbid'`, non-flag fields must capture a `value`, the locator failure
  is reported as such and the next doc still runs, and the dead-rule list excludes rules already reported
  for undeclared units. The regenerated config is byte-identical to the pre-fix output, so the fixes changed
  diagnostics only.
- Two consecutive rejections is the `R-TKT.2` parking threshold: no third round was run on the author's
  initiative — the escalation is with the user.

## Limitations, accepted

- Prose regexes rot when the vendor edits the page: mitigated by per-rule hit counts and complaints on every
  run, not prevented.
- A pathological pattern can backtrack and hang the run; declared patterns are trusted, unguarded.
- `ark-code-latest` and `glm-latest` are router aliases the page never describes, so they stay fact-less.
- No test runner in this repo; the module tests used to verify the fixes live under `/tmp` and are not
  committed. A `--selftest` or `tests/` is the obvious successor if these patterns keep growing.

## Comments

- start — agent (pi), 2026-09-15: split out of ticket 04 (which passed ~150 lines) as the implementation
  half; the design, prototype and decision record stay in 04.
- done — agent (pi), 2026-09-15: two review rounds, all findings fixed, gates re-run; config regenerated and
  live on port 4001.
