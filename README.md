<p align="center">
  <a href="README.md"><strong>English</strong></a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="assets/logo.svg" alt="litellmgen logo" width="132">
</p>

<h1 align="center">litellmgen</h1>

<p align="center">
  <strong>Build one LiteLLM config from five model sources, with every field resolved by source priority.</strong>
</p>

litellmgen reads LiteLLM's shipped cost map, the live LiteLLM catalog, provider `/models` endpoints, GitHub Copilot's account catalog, and vendor documentation, then writes a single `litellm.yml`. Model facts are normalized to one flat shape and merged field by field, so a higher-priority source only replaces the fields it actually states.

## Quick start

Requires Python 3.12+.

```bash
git clone https://github.com/ZisIsNotZis/litellmgen.git
cd litellmgen
python3 -m pip install aiohttp pydantic PyYAML
```

Open `litellmgen.py` and set `BACKUP_PATH`, `CONFIG_PATH`, and `OUTPUT_PATH` near the top to paths on your machine. `BACKUP_PATH` should point at the `model_prices_and_context_window_backup.json` shipped with your installed LiteLLM, and `CONFIG_PATH` at your own `lm.yml` (see [the shape below](#configuration-shape)). Then run:

```bash
python3 litellmgen.py
```

The generated router config is written to `OUTPUT_PATH`; the repository ships the author's own machine-local `/home/z/litellm.yml`, so replace it. If no models are produced, the script exits instead of writing an empty `model_list`.

## What it can do now

- **Five fact sources** — LiteLLM's shipped backup, the LiteLLM catalog, a provider's `/models`, GitHub Copilot's account catalog, and declarative vendor-doc extraction.
- **Per-field merging** — `None` means "this source has no opinion", so a higher-priority source cannot erase a lower-priority value just by omitting it.
- **Honest absence** — missing capabilities stay unset instead of becoming fabricated `false` values; `exclude_none` keeps them out of the output.
- **Roster-based membership** — a group's `roster:` decides which names can enter the config. Other sources only annotate those names, so a platform-wide model dump cannot leak models your subscription cannot use.
- **One alias per model per key** — every model is exported as `<group>/<model>`, repeated once for each key in the group.
- **Config passthrough** — arbitrary flat keys under `models:` become assertions and win over every fetched source.
- **Visible failures** — a dead catalog, endpoint, doc page, or Copilot token exchange is reported and skipped; the other sources still run.
- **Per-source counts** — every group prints how many models each source contributed, so a silently dead source is obvious.

### Sources and priority

| Priority | Source | Contributes |
| --- | --- | --- |
| Lowest | LiteLLM shipped backup | prices, context limits, capability flags |
| | LiteLLM catalog | the same facts, fetched live |
| | Provider `/models` | discovery and whatever metadata the endpoint states |
| | GitHub Copilot catalog | account-scoped capabilities and limits |
| | Vendor docs | facts extracted by rules declared in your config |
| Highest | `models:` in your config | hand-written overrides and extra names |

The provider endpoint is used when `roster:` asks for it, or as a fallback when both LiteLLM sources are empty. The Copilot channel is used only when a group's roster includes `copilot`.

### Configuration shape

`CONFIG_PATH` is a YAML mapping of provider groups. Each group can declare:

- `openai` — the provider's API base.
- `style` — the LiteLLM provider prefix used in `litellm_params.model`; defaults to the group name.
- `keys` — a mapping of key labels to API keys.
- `roster` — the channels allowed to decide membership, such as `[backup, catalog]`, `[docs]`, or `[copilot]`.
- `models` — extra model names and per-model assertions.
- `docs` — vendor pages with `roster`, `inline_code`, and `patterns` rules for mining model facts.

A group in full, as a shape rather than a real provider:

```yaml
# lm.yml — one key per provider group. It holds credentials, so it is not versioned.
myprovider:                              # the group name is the alias prefix: myprovider/<model>
  openai: https://api.example.com/v1      # the provider's API base
  style: openai                           # prefix for litellm_params.model; defaults to the group name
  keys:
    main: <your-api-key>                  # omit for keyless endpoints
  roster: [backup, catalog]               # only these channels may decide membership
  models:
    some-model: {max_output_tokens: 128000}   # extra name and/or assertions; wins over every source
  docs:
    - url: https://docs.example.com/models
      roster: ['(?P<name>model-[\d.]+)']   # names the page declares for itself
      inline_code: ['model-[\d.]+']        # fullmatch on spans the page marks as literal ids
      units: {'k': 1000}                   # multipliers for a rule's `unit` group
      patterns:
        - {field: max_input_tokens, pattern: '(?P<value>\d+)\s*context'}   # `value` is the fact
```

Unknown keys inside a group are printed and ignored; a misspelled key inside `docs` or `patterns` is a config error. Keep credentials in `CONFIG_PATH` outside the repository; it is deliberately not versioned.

## Architecture

```text
LiteLLM backup ─┐
LiteLLM catalog ─┤
provider /models ─┼─→ Facts (flat, typed) ─→ field-wise merge ─→ roster filter ─→ entries ─→ litellm.yml
Copilot catalog ─┤
vendor docs ─────┤
your models: ────┘
```

- `Facts` declares exactly the flat fields that may reach `model_info`; undeclared fields are ignored.
- `merge()` keeps the primary value where present and fills gaps from the fallback.
- `absorb()` folds sources in priority order, one model at a time.
- `build()` gathers channels under `guard()`, applies roster membership, and handles doc-derived names.
- `entries()` exports one router entry per model and key, with `drop_params: true`.

## How to develop

There is no build step and no package to install. The project is one script.

```bash
python3 -m py_compile litellmgen.py   # syntax check
python3 litellmgen.py                 # requires local paths and network access
```

- `litellmgen.py` is the only implementation file; keep it that way unless there is a concrete need to split it.
- A stable CLI and an automated test suite are intentionally out of scope. Verification is a real run plus inspection of the generated YAML.
- The config and backup paths are machine-local. Do not hard-code a contributor's home directory into a committed example.
- Never commit API keys, Copilot tokens, or generated configs containing secrets.

See [`docs/project-status.md`](docs/project-status.md) for the project's classification and deferred work.

## How to contribute

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: keep the change small and evidence-backed, preserve per-field priority and the "no fabricated facts" rule, and report what you ran and what you inspected.

## Roadmap

### Implemented

- Five prioritized fact sources, including account-scoped Copilot and declarative vendor-doc extraction.
- Per-field merge with `None` as "no opinion" and no fabricated `false` values.
- Roster-driven membership and `<group>/<model>` aliases.
- Cost normalization where `0.0` means "unknown", not "free".
- Per-source failure isolation, per-rule doc hit counts, and unknown-config-key warnings.

### Planned

The project is closed as a milestone: no new features are planned unless LiteLLM's config format or its upstream sources change. Deliberately deferred:

- A stable command-line interface.
- Automated tests.
- Portable, non-machine-local configuration paths.

### Future vision

Adding a provider or a model should stay a small YAML edit, not a hunt through five dashboards and a spreadsheet. If the upstream ecosystem settles on a machine-readable source of truth, litellmgen should be able to consume it as one more channel without changing how facts are merged, prioritized, or exported.

## License

[AGPL-3.0](LICENSE.md) © 2026 ZisIsNotZis.
