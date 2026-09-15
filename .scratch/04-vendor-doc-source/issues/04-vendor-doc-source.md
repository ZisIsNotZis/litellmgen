# 04 — Fifth source: facts from a vendor doc page

- **Status:** ready-for-human
- **Blocked by:** none
- **Assignee/lock:** unclaimed
- **Need-review:** yes if implemented (new config surface + a new source in the merge)
- **Need-test-cases:** none (verification = the throwaway prototype's yield, below)

## Why

No automated source knows the volcengine **coding-plan** model names (`ark-code-latest`, `glm-5.3`,
`glm-latest`, `kimi-k3`, …). litellm's catalog and the shipped cost map cover `doubao-seed-*` only, and
the provider's own `/models` is reported by the user as both incomplete (missing the intended names) and
wrong (e.g. `glm-5.3` context, `glm-5.3-flash` multimodality). The doc page is the only authority.

## Feasibility (probed, not assumed)

| Fetch | Result |
| --- | --- |
| `console.volcengine.com/ark/region:cn-beijing/docs/82379/1925114?lang=zh` | 44 KB SPA shell, **no doc content** (`window.__PRELOAD_DATA__` is `{}`) |
| `www.volcengine.com/docs/82379/1925114` | 11 KB SPA shell, no content |
| `arkbff-cn-beijing.console.volcengine.com/api/...` | **401** — needs a console session, out |
| `www.volcengine.com/api/doc/getDocDetail?DocumentID=1925114&lang=zh` | **200, 79 KB JSON, no auth** ← the doc body |

`Result.Content` is Quill-delta JSON: `{"version":…, "data": {"<section>": {"ops": [{"insert": "…"}]}}}`,
82 sections, 457 string inserts + 33 embedded objects. The tables are **cell-id references**
(`{"insert": {"id": "c1oz…"}, "attributes": {"colWidth": "100", "mergeCellID": …}}`) pointing into a card
store this endpoint does not return — so there is no table to parse, and no HTML either. The facts sit in
prose:

- `doubao-seed-evolving、glm-5.3、glm-5.3-flash、kimi-k3、deepseek-v4-flash、deepseek-v4-pro 支持 1M 上下文窗口`
- `Doubao-Seed-Evolving 长度限制如下： 上下文窗口：1024k 最大输出：256k`
- `MiniMax-M3 长度限制如下： 上下文窗口：1024k 最大输出长度：128k`
- `支持多模态视觉理解。256k 上下文窗口，64k 输出` (belongs to the *following* card, not the preceding text)

So "generic HTML" is dead; a **generic doc source** (URL → text → declared patterns) is viable.

## Prototype (`/tmp/docproto/{source.yml,engine.py}`, throwaway, nothing in the repo)

Four patterns, all declared in YAML, zero provider knowledge in the code: a name-list + shared value rule, a
labelled-limits rule for input and one for output, and a multimodality rule.

| | |
| --- | --- |
| covered (8/12) | `doubao-seed-evolving` 1024k/256k · `minimax-m3` 1024k/128k · `glm-5.3` 1024k/128k · `glm-5.3-flash` 1024k/128k · `deepseek-v4-flash` 1024k/384k · `deepseek-v4-pro` 1024k/384k · `kimi-k3` 1024k/128k · `kimi-k2.7-code` 256k |
| uncovered (4) | `ark-code-latest`, `doubao-seed-2.1-turbo`, `doubao-seed-2.0-lite`, `glm-latest` |
| extraction noise | none — every extracted name matched a name the group already lists |

Findings from building it: units must match case-insensitively (`1024k`, not `1024K`) and include the
Chinese 万 (`100 万 token` = 1000000); two patterns give `doubao-seed-evolving` 1000000 and 1024000
respectively, so **pattern precedence must be declared**; and the prose that precedes a card
(`支持多模态视觉理解`) cannot be bound by position in the flattened text — component-id blobs sit between
claim and name.

## Modality, and the forward-bind rule (round 2)

Modality is stated in three shapes:

- `glm-5.3-flash 为原生多模态模型，支持图片输入` — name inside the sentence, plain regex.
- `支持多模态视觉理解。256k 上下文窗口，64k 输出… *Doubao-Seed-2.1-turbo` — claim first, name after.
- `原生支持视觉理解，并拥有 100 万 token 上下文窗口… *说明 *Kimi-K3 长度限制如下` — claim first, name ~400 chars later.

One rule covers the last two: **bind forward to the nearest name that the group's own model list contains**
(not "nearest name-like token" — the flattened text is full of component ids like
`xr1231e1v2uqf6yifrtlwk1eoi11sysj4zfxc1jh7oi9gvbqrj1b00k3mfqchsjjdootegZ`, which a naive `[\w.-]+` would
bind to). Same list-based guard as everywhere else in this generator.

Six patterns, all in YAML, zero provider knowledge in the code:

| Hits | Field | Shape |
| ---: | --- | --- |
| 8 | `max_input_tokens` | `(?P<model>[\w.\-]+)\s*长度限制如下…上下文窗口[：:]\s*(?P<value>\d+…)\s*(?P<unit>[KkMm万])` |
| 8 | `max_output_tokens` | same, `最大输出(长度)?(（…）)?[：:]` |
| 1 | `max_input_tokens` | `(?P<models>[\w.\-]+(?:、[\w.\-]+)*)\s*支持\s*(?P<value>…)\s*(?P<unit>…)\s*(?:超长)?上下文` |
| 1 | `max_input_tokens` | `并拥有\s*(?P<value>…)\s*(?P<unit>…)\s*token\s*上下文窗口` + forward bind |
| 1 | `supports_vision` | `(?P<model>[\w.\-]+)\s*为原生多模态模型` |
| 5 | `supports_vision` | `支持多模态视觉理解\|原生支持视觉理解` + forward bind |

| | |
| --- | --- |
| covered (**10/12**) | `doubao-seed-evolving` 1024000/256000 · `minimax-m3` 1024000/128000/vision · `glm-5.3` 1024000/128000 · `glm-5.3-flash` 1024000/128000/vision · `deepseek-v4-flash` 1024000/384000 · `deepseek-v4-pro` 1024000/384000 · `kimi-k3` 1000000/128000/vision · `kimi-k2.7-code` 256000/32000/vision · `doubao-seed-2.1-turbo` vision · `doubao-seed-2.0-lite` vision |
| uncovered (2) | `ark-code-latest`, `glm-latest` — router aliases the doc never describes; nothing to extract |
| noise | none — the group-list guard refused every component id and stray word |

Matches the facts the user asserted by hand: `glm-5.3` ≈1M context, `glm-5.3-flash` multimodal.

## Decisions needed

1. Implement `docs:` as a fifth source in `litellmgen.py`? Shape:

   ```yaml
   volcengine:
     docs:
       - url: https://www.volcengine.com/api/doc/getDocDetail?DocumentID=1925114&lang=zh
         text: Result.Content
         split: "、"
         units: {k: 1000, m: 1000000}
         patterns:
           - {field: max_input_tokens, pattern: '…'}
   ```

   The URL in `lm.yml` has to be the JSON API one — the console URL cannot be resolved to it generically,
   and the user's constraint is that nothing provider-specific lives in the script.
2. Precedence: first match wins, or last (i.e. patterns ordered as a priority list like the sources)?
   Author's lean: **first match wins**, patterns ordered most-specific-first — the same "declared order is
   the priority" idiom the four existing sources already use. This decides `doubao-seed-evolving`
   (1024000 from the per-model rule vs 1000000 from the name-list rule).
3. Positional prose (shape C): **answered — keep it.** The user requires modality, and the forward-bind rule
   (nearest name from the group's own list, within a declared window) covers it in one rule.
4. Missing 2/12: acceptable — both are router aliases the doc does not describe. Treat the doc source as
   the *lowest* priority source, under the user's own `models:`, so hand-written facts still win.

Honest cost: prose regexes rot silently when the vendor edits the page. Mitigation to build in: print each
pattern's hit count per run, like the per-source counts that exposed the dead `provider`/`litellm_provider`
filter — plus refuse names the group does not list, which is what kept the prototype noise-free.

## Comments

- ready-for-human — agent (pi), 2026-09-15: endpoint found and prototype run; implementation waits on the
  four decisions above. `lm.yml` deliberately untouched for this.
- round 2 — agent (pi), 2026-09-15: modality added at the user's request; forward-bind rule designed and
  measured (10/12). Prototype at `/tmp/docproto/{source.yml,engine.py}` — still throwaway, nothing landed.
  Waiting on the go for decision 1 before touching `litellmgen.py`.
