# 03 — `Facts` whitelist can drift from litellm's `model_info` schema

- **Status:** ready-for-human
- **Blocked by:** none
- **Assignee/lock:** unclaimed
- **Need-review:** no (no code change yet — this ticket asks for a decision)
- **Need-test-cases:** none yet

## Issue

`Facts` declares 35 flat fields and `extra='ignore'`; the declared set *is* the output whitelist, so a
field litellm reads but `Facts` does not declare is dropped silently. Two review rounds found this
class twice: round 1 named `supported_endpoints`, `supports_adaptive_thinking`,
`supports_legacy_thinking`; round 2 named `supports_output_config` (present in the sources on
`github_copilot/claude-opus-4.5`) plus six litellm-declared fields that no current source populates.

The list is currently hand-picked from litellm's own reads, which is why it drifts. The drift check
below returns `[]` as of the follow-up commit, but nothing enforces it on the next litellm upgrade.

## Question for the user

Hand-pick and re-check on upgrade, or derive the field set from litellm mechanically?

| Option | Cost | Consequence |
| --- | --- | --- |
| A: keep the hand-picked set (status quo) | none | silent drop whenever litellm adds a model_info field; the check below must be re-run by hand |
| B: derive the names from litellm's `ModelInfoBase` + `ProviderSpecificModelInfo` + `ModelInfo` at run time | ~10 lines; output schema follows the installed litellm | the emitted whitelist changes under our feet on a litellm upgrade — but that is the drift, made visible |
| C: keep the set, print the dropped-but-litellm-declared keys each run | ~10 lines | no schema coupling; the drift is reported instead of prevented |

Author's lean: **C** — it reports the drift without making the output depend on litellm's internals.

## Drift check (run after any litellm upgrade)

```bash
cd /home/z/vibe/litellmgen && python3 - <<'EOF'
import json, re
src = open('litellmgen.py').read()
declared = set(re.findall(r'^\s{4}([a-z_0-9]+):', re.search(r'class Facts.*?(?=\nclass )', src, re.S).group(0), re.M))
t = open('/home/z/.venv/lib/python3.12/site-packages/litellm/types/utils.py').read()
names = set()
for cls in ('ModelInfoBase', 'ProviderSpecificModelInfo', 'ModelInfo'):
    m = re.search(rf'^class {cls}\b.*?(?=^class )', t, re.S | re.M)
    if m:
        names |= set(re.findall(r'^\s{4}([a-z_0-9]+):', m.group(0), re.M))
bk = json.load(open('/home/z/.venv/lib/python3.12/site-packages/litellm/model_prices_and_context_window_backup.json'))
present = set()
for v in bk.values():
    if v.get('litellm_provider') in ('deepseek', 'zai', 'volcengine', 'github_copilot', 'siemens'):
        present |= set(v)
print(sorted((present & names) - declared - {'litellm_provider'}))
EOF
```

## Comments

- ready-for-human — agent (pi), 2026-09-15: split out of ticket 01 after two review rounds; the
  decision is a product call (which fields the yml may carry), so it is not taken in-slice.
