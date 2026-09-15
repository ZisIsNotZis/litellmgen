# 02 — `github_copilot` needs per-model `mode`, not a group-level one

- **Status:** done
- **Blocked by:** none
- **Assignee/lock:** unclaimed
- **Need-review:** no (no code change needed for the fix — `lm.yml` carries it)
- **Need-test-cases:** none (verification was the probes below)

## Issue

Found while hello-checking the regenerated `~/litellm.yml` (ticket 01). Every request to the
`github_copilot` group failed with 400 while the other four groups passed. Two candidate causes were
filed: (1) `lm.yml` asks for `mode: responses`, the generator never read it; (2) credentials.

**Both settled. Cause 1 confirmed, cause 2 disproven.**

- Credentials exist and work: `~/.config/litellm/github_copilot/{access-token,api-key.json}` are
  present (litellm's `llms/github_copilot/authenticator.py:32-39` reads that dir), and
  `POST /v1/responses github_copilot/gpt-5.3-codex` → **200**.
- `mode` is the routing switch: `gpt-5.6-sol` on `/v1/chat/completions` → 400, and with
  `models: {gpt-5.6-sol: {mode: responses}}` on `/v1/responses` → **200** (probe proxy on 4002,
  config `/tmp/litellm.mode.yml`).
- litellm's shipped map marks only 2 of its 33 `github_copilot` entries `mode: responses` —
  `gpt-5.1-codex-max`, `gpt-5.3-codex` — both with `supported_endpoints: ["/v1/responses"]`.
  Everything else it knows (claude-\*, gemini-\*, grok-\*, gpt-\*) is `mode: chat`.
- The user's 16 hand-listed names are in **no** litellm map (nothing matches `gpt-5.5`/`gpt-5.6`),
  so litellm cannot know their mode and defaults to chat.

### The upstream error wording is the classifier

`github_copilot` has no `/models`-style discovery and its errors come from the Copilot API verbatim
(neither string exists in litellm's source), so they can be read directly:

| Upstream message | Meaning |
| --- | --- |
| `model "X" is not accessible via the /chat/completions endpoint` | exists, needs `mode: responses` |
| `The requested model is not supported.` (`code: model_not_supported`) | not served to this account |

### Classification of `lm.yml`'s 16 names (4001, `github_copilot/<name>` on `/chat/completions`)

| Needs `mode: responses` (8) | Chat already works (4) | Not served (2) | Unclear (2) |
| --- | --- | --- | --- |
| `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-6-astra`, `gpt-5.5`, `gpt-5.4-mini`, `grok-4.5`, `gpt-5.3-codex` | `gpt-5.4`, `gpt-5-mini`, `gemini-3.8-flash`, `gemini-3.5-flash` | `auto`, `hydrafusion` | `gemini-3.7-flash`, `gemini-3.6-flash` — `Invalid request format: litellm.InternalServerError` |

## Fix (applied, no code change needed)

Per-model, in `lm.yml` — the rewritten generator passes arbitrary flat keys through `Facts`. Applied
2026-09-15 (file kept out of the repo: it holds live API keys, core I7):

```yaml
github_copilot:
  models:
    gpt-5.6-sol: {mode: responses, supported_endpoints: [/v1/responses]}   # + 6 more responses-only names
    gpt-5.4: {}                                                          # chat, left unset
  keys: []
```

The group-level `mode: responses` was deleted: it was never read, and is the wrong shape for a mixed group.
Verified emission: `{"mode": "responses", "supported_endpoints": ["/v1/responses"]}`.

## Verification (proxy on 4001, `lm.yml` regenerated into `~/litellm.yml`)

| Endpoint | Result |
| --- | --- |
| `/v1/responses` — the 8 responses-only names | **8/8 → 200** (`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-6-astra`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.3-codex`, `grok-4.5`) |
| `/v1/chat/completions` — the chat names | **6/6 → 200** (`gpt-5.4`, `gpt-5-mini`, `gemini-3.8/3.7/3.6/3.5-flash`) |
| `auto`, `hydrafusion` | 400 `model_not_supported` — **expected**: the user confirmed these are blocked for the account |

Two corrections to this ticket's earlier reporting: the gemini-3.7/3.6-flash 400s filed as "unclear" were a
transient `InternalServerError` and both answer 200; and the earlier method (asking `/chat/completions` about
a `mode: responses` deployment) is itself invalid — litellm correctly refuses to bridge chat → responses, so
those models are reachable on `/v1/responses` only.

## Answered

- Keep the blocked names: yes, they are blocked for the account and that is fine.
- Group-level `mode` in `Cfg`: not wanted — per-model is the right shape.

## Question for the user

Whether to keep the 2 blocked names as intent, and whether a probe helper is worth having. Both are
optional; nothing depends on them. Ticket 04 covers the doc-source idea for the facts litellm cannot know.

## Comments

- needs-triage — agent (pi), 2026-09-15: filed from a hello check; three requests only.
- ready-for-human — agent (pi), 2026-09-15: causes separated with the probes above. `mode` is the
  fix, credentials were never the problem; the residue is a product call about the model list.
- Correction to what ticket 01's first report said: it claimed cause 2 was likely because no copilot
  token appeared in the proxy *environment*. The token is on disk, not in the environment, so that
  observation was worthless.
- done — agent (pi), 2026-09-15: `lm.yml` updated and verified; the account-blocked names are confirmed
  fine. Facts beyond what litellm's own sources carry are ticket 04's concern.
