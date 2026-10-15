# litellmgen

> **Status: closed (milestone).** A complete local utility; no further development
> is planned unless the LiteLLM configuration format or its sources change.

A Python utility that builds a LiteLLM model configuration from multiple sources: LiteLLM's local model-price backup, the LiteLLM model catalog, provider `/models` endpoints, the GitHub Copilot account catalog, vendor documentation pages, and local assertions. It normalizes model facts and merges them field-by-field according to source priority.

## Sources and membership

Facts are gathered from every source, lowest priority first: LiteLLM's shipped backup, the LiteLLM catalog, a provider `/models` endpoint, the Copilot account catalog, vendor doc pages, then `models:` in the input configuration. Priority is decided per field, so a higher source fills only the fields it actually states.

Which *names* reach the output is separate. A provider's `roster:` names the channels that decide membership (for example `[docs]` for a coding-plan provider whose `/models` lists the whole platform, or `[copilot]` for GitHub Copilot), and every other source only annotates a member. When `roster:` is omitted, any source may introduce a model, preserving the permissive default. A doc page contributes to a `docs` roster through `roster:`/`inline_code:` name rules, and `models:` remains an optional place for extra names and per-model assertions.

## Output

Every model is exported under exactly one alias, `<group>/<model>`, once per key declared in that group; a group's bare name is not an alias.

## Requirements

Python 3.12+ and the packages `aiohttp`, `pydantic`, and `PyYAML`.

## Important configuration

Before running, review the constants near the top of [`litellmgen.py`](litellmgen.py). In particular, backup, input-configuration, and output paths are currently local absolute paths and must be changed for your environment. Provider endpoints can be queried over the network; only use configuration and credentials you trust. The `copilot` channel reads the GitHub-to-Copilot token that LiteLLM caches locally, and refreshes it from the cached GitHub access token when it has expired.

This repository contains the finished generator script; a stable command-line interface and test suite are intentionally out of scope. See [`docs/project-status.md`](docs/project-status.md).