# 02 — `github_copilot` group answers no request

- **Status:** needs-triage
- **Blocked by:** none
- **Assignee/lock:** unclaimed
- **Need-review:** unknown until triaged
- **Need-test-cases:** none yet

## Issue

Found while hello-checking the regenerated `~/litellm.yml` (ticket 01). Every request to the
`github_copilot` model group fails with 400; the other four groups pass. Pre-existing: the old
generator emitted the same group from the same sources, and it also ignored `lm.yml`'s
`mode: responses`.

Observed on port 4001, `~/litellm.yml` from ticket 01:

| Request | Result |
| --- | --- |
| `POST /v1/chat/completions` `github_copilot/gpt-5.6-sol` (user cfg model, facts all unset) | 400 `model "gpt-5.6-sol" is not accessible via the /chat/completions endpoint` |
| `POST /v1/responses` `github_copilot/gpt-5.6-sol` | 400, same message — litellm routed it to `/chat/completions` anyway, so the deployment's mode is `chat` |
| `POST /v1/chat/completions` `github_copilot/claude-sonnet-4` (from litellm's cost map) | 400 `The requested model is not supported.` |

Two candidate causes, not yet separated:

1. **Mode.** `lm.yml` asks for `mode: responses`; `Cfg` never read it and the ticket-01 generator
   only warns about it, so no `model_info.mode` is emitted and every deployment defaults to chat.
   litellm's own cost map has `mode: responses` for 2 of its 33 `github_copilot` entries, so the
   mechanism exists — those 16 user models are private names litellm cannot know about.
2. **Credential/entitlement.** No copilot token appears in the proxy process environment, and the
   upstream rejects even cost-map-known models.

## Acceptance criteria (to settle at triage)

- [ ] Cause 1 vs 2 decided with evidence, not inference.
- [ ] If mode: `Cfg` gains the field it declares in `lm.yml`, emitted into `model_info`.
- [ ] If credentials: how the group is meant to authenticate is written down in `WORKSPACE.md`.
- [ ] One passing hello against the group, or the group removed from `lm.yml` as `wontfix`.

## Comments

- needs-triage — agent (pi), 2026-09-15: filed from a hello check; no investigation beyond the
  three requests above.
