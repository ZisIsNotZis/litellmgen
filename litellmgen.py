#!/bin/env python3
"""Generate ~/litellm.yml from provider facts gathered from several sources.

Sources, lowest priority first:
  1. litellm's shipped model_prices_and_context_window_backup.json (offline baseline)
  2. https://api.litellm.ai/model_catalog (live, richer)
  3. the provider's own /models endpoint (discovery only, when 1 and 2 know nothing)
  4. ~/my/misc/lm.yml `models:` (user assertions, highest priority)

Every source is normalized to `Facts` — one flat leaf per fact — before merging, so priority
is decided per field and never per object. `None` means "no source had an opinion": it never
overwrites a value, and `exclude_none` keeps it out of the output.
"""

from asyncio import gather, new_event_loop
from json import load
from pathlib import Path
from typing import TypeVar

from aiohttp import ClientSession, ClientTimeout
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from yaml import safe_dump, safe_load

CATALOG_URL = 'https://api.litellm.ai/model_catalog'
BACKUP_PATH = Path('/home/z/.venv/lib/python3.12/site-packages/litellm/model_prices_and_context_window_backup.json')
CONFIG_PATH = Path('/home/z/my/misc/lm.yml')
OUTPUT_PATH = Path('/home/z/litellm.yml')

# Per-token costs litellm reads; a 0.0 in these sources means "price unknown", not "free".
COST_FIELDS = (
    'input_cost_per_token',
    'output_cost_per_token',
    'input_cost_per_audio_token',
    'output_cost_per_reasoning_token',
    'cache_read_input_token_cost',
    'cache_creation_input_token_cost',
)


class Facts(BaseModel):
    """One model's flat facts. Declared fields are exactly what reaches `model_info`."""

    model_config = ConfigDict(extra='ignore')

    mode: str|None = None
    max_tokens: int|None = None
    max_input_tokens: int|None = None
    max_output_tokens: int|None = None
    output_vector_size: int|None = None
    input_cost_per_token: float|None = None
    output_cost_per_token: float|None = None
    input_cost_per_audio_token: float|None = None
    output_cost_per_reasoning_token: float|None = None
    cache_read_input_token_cost: float|None = None
    cache_creation_input_token_cost: float|None = None
    tiered_pricing: list[dict[str, object]]|None = None
    supports_vision: bool|None = None
    supports_audio_input: bool|None = None
    supports_audio_output: bool|None = None
    supports_reasoning: bool|None = None
    supports_response_schema: bool|None = None
    supports_function_calling: bool|None = None
    supports_parallel_function_calling: bool|None = None
    supports_tool_choice: bool|None = None
    supports_prompt_caching: bool|None = None
    supports_system_messages: bool|None = None
    supports_assistant_prefill: bool|None = None
    supports_native_streaming: bool|None = None
    supports_web_search: bool|None = None


class Cfg(BaseModel):
    """One model group from lm.yml."""

    model_config = ConfigDict(extra='allow')

    openai: str|None = None
    style: str|None = None
    keys: list[str]
    models: dict[str, Facts] = Field(default_factory=dict)


F = TypeVar('F', bound=BaseModel)


def merge(primary: F, fallback: F) -> F:
    """Field-wise priority merge: `primary` wins where it has an opinion, `fallback` fills the rest."""
    values = {name: getattr(primary, name) for name in type(primary).model_fields}
    return type(primary)(**{
        name: value if value is not None else getattr(fallback, name)
        for name, value in values.items()
    })


def facts(raw: dict[str, object]) -> Facts:
    """Normalize one source entry to flat facts."""
    parsed = Facts.model_validate(raw)
    return parsed.model_copy(update={name: None for name in COST_FIELDS if getattr(parsed, name) == 0.0})


def from_backup(provider: str, cost_map: dict[str, dict[str, object]]) -> dict[str, Facts]:
    """litellm's shipped cost map: `litellm_provider` is the vendor tag, keys may carry the prefix."""
    return {
        key.removeprefix(f'{provider}/'): facts(entry)
        for key, entry in cost_map.items()
        if entry.get('litellm_provider') == provider
    }


async def from_catalog(sess: ClientSession, provider: str) -> dict[str, Facts]:
    body = await (await sess.get(f'{CATALOG_URL}?provider={provider}')).json()
    return {str(entry['id']).removeprefix(f'{provider}/'): facts(entry) for entry in body['data']}


async def from_endpoint(sess: ClientSession, cfg: Cfg) -> dict[str, Facts]:
    """The provider's own /models list: ids only, so the facts stay unset."""
    body = await (await sess.get(f'{cfg.openai}/models',
                                 headers={'Authorization': f'Bearer {cfg.keys[0]}'},
                                 timeout=ClientTimeout(10))).json()
    return {str(entry['id']): Facts() for entry in body['data']}


async def build(sess: ClientSession, name: str, cfg: Cfg,
                cost_map: dict[str, dict[str, object]]) -> tuple[str, Cfg, dict[str, Facts]]:
    offline = from_backup(name, cost_map)
    catalog = await from_catalog(sess, name)
    listed = await from_endpoint(sess, cfg) if not (offline or catalog) and cfg.openai and cfg.keys else {}
    models: dict[str, Facts] = {}
    for source in (offline, catalog, listed, cfg.models):
        for model, found in source.items():
            models[model] = merge(found, models[model]) if model in models else found
    print(f'[{name}] backup={len(offline)} catalog={len(catalog)} endpoint={len(listed)} '
          f'user={len(cfg.models)} -> {len(models)} models')
    return name, cfg, models


def entries(name: str, cfg: Cfg, models: dict[str, Facts]) -> list[dict[str, object]]:
    backend = cfg.style or name
    return [
        {
            'model_name': alias,
            'litellm_params': {
                'api_base': cfg.openai,
                'api_key': key,
                'drop_params': True,
                'model': f'{backend}/{model}',
            },
            'model_info': found.model_dump(exclude_none=True),
        }
        for model, found in models.items()
        for key in cfg.keys or [None]
        for alias in (name, f'{name}/{model}')
    ]


async def main() -> None:
    with BACKUP_PATH.open() as handle:
        cost_map: dict[str, dict[str, object]] = load(handle)
    with CONFIG_PATH.open() as handle:
        groups = TypeAdapter(dict[str, Cfg]).validate_python(safe_load(handle))
    async with ClientSession() as sess:
        built = await gather(*(build(sess, name, cfg, cost_map) for name, cfg in groups.items()))
    model_list = [entry for name, cfg, models in built for entry in entries(name, cfg, models)]
    if not model_list:
        raise SystemExit('refusing to write an empty model_list')
    with OUTPUT_PATH.open('w') as handle:
        safe_dump({'model_list': model_list,
                   'router_settings': {'routing_strategy': 'simple-shuffle'}}, handle)
    print(f'wrote {OUTPUT_PATH} with {len(model_list)} entries')


new_event_loop().run_until_complete(main())
