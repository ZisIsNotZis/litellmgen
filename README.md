# litellmgen

A Python utility that builds a LiteLLM model configuration from multiple sources: LiteLLM's local model-price backup, the LiteLLM model catalog, provider `/models` endpoints, and local user assertions. It normalizes model facts and merges them field-by-field according to source priority.

## Requirements

Python 3.12+ and the packages `aiohttp`, `pydantic`, and `PyYAML`.

## Important configuration

Before running, review the constants near the top of [`litellmgen.py`](litellmgen.py). In particular, backup, input-configuration, and output paths are currently local absolute paths and must be changed for your environment. Provider endpoints can be queried over the network; only use configuration and credentials you trust.

This repository currently contains the generator script; no stable command-line interface or test suite is declared.