# Contributing

This is a small, closed utility: one script that generates a LiteLLM model configuration. Maintenance changes are welcome, especially when LiteLLM's config format or an upstream source changes.

## Ground rules

- Keep the change small and evidence-backed. Describe the upstream fact or the observed failure that motivated it.
- Preserve the core semantics: one flat `Facts` shape, per-field source priority, `None` as "no opinion", and no fabricated `false` values.
- Keep `litellmgen.py` a single implementation file unless there is a concrete need to split it.
- Do not add a stable CLI, a test runner, or portable config paths as incidental changes; those are deliberately out of scope.
- Never commit API keys, Copilot tokens, your config file, or generated configs containing credentials.

## Verifying

There is no test suite. Run the generator with your own local config, then inspect the generated YAML: per-source counts, roster membership, aliases, and the absence of invented fields. `python3 -m py_compile litellmgen.py` catches syntax errors but is not a behavioral test.

## Pull requests

Include:

- What changed and why.
- What you ran and what you inspected.
- Any source or format change that could make the result stale.
- Remaining limitations, if any.

Maintainers review and merge. If a change depends on a product decision (for example, which fields may reach `model_info`), open an issue first rather than deciding it inside a patch.
