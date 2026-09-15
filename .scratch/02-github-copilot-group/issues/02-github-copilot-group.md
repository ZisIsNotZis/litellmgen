# 02 — `github_copilot` needs per-model `mode`, not a group-level one

- **Status:** ready-for-human
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

## Fix (no code change needed)

Per-model, in `lm.yml` — the rewritten generator passes arbitrary flat keys through `Facts`:

```yaml
github_copilot:
  keys: []
  models:
    gpt-5.6-sol: {mode: responses, supported_endpoints: [/v1/responses]}
```

Verified emission: `{"mode": "responses", "supported_endpoints": ["/v1/responses"]}` in
`model_info`, and the probe above answers 200 through a proxy started on that config.

## Question for the user

- Drop the 2 not-served names, or keep them as intent-to-use-when-available? They currently make the
  group fail random requests under `simple-shuffle`.
- Is a group-level `mode` worth implementing in `Cfg` (3 lines), or is per-model the right shape?
  Author's lean: per-model only — this group mixes responses-only, chat-only and one embedding model,
  so a group-level switch would misroute whichever half it is not set to.
- Worth a probe helper that classifies a name list through the error wording above, so the split is
  re-derivable instead of hand-maintained?

## Comments

- needs-triage — agent (pi), 2026-09-15: filed from a hello check; three requests only.
- ready-for-human — agent (pi), 2026-09-15: causes separated with the probes above. `mode` is the
  fix, credentials were never the problem; the residue is a product call about the model list.
- Correction to what ticket 01's first report said: it claimed cause 2 was likely because no copilot
  token appeared in the proxy *environment*. The token is on disk, not in the environment, so that
  observation was worthless.
