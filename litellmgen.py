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
import re
from collections.abc import Awaitable, Iterable
from json import load, loads
from pathlib import Path
from typing import Any, Literal, TypeVar, get_args

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
    supports_adaptive_thinking: bool|None = None
    supports_legacy_thinking: bool|None = None
    supports_output_config: bool|None = None
    supports_computer_use: bool|None = None
    supports_pdf_input: bool|None = None
    supports_embedding_image_input: bool|None = None
    supports_native_structured_output: bool|None = None
    supports_tool_search: bool|None = None
    thinking_always_on: bool|None = None
    supported_endpoints: list[str]|None = None


# litellm rewrites a caller's `max_tokens` from this legacy cost-map field (token_counter.py), so it is
# never prose-derived: a misread page must not be able to silently cap a request.
DERIVED_ONLY = ('max_tokens',)

# Flag fields take `True` from a rule with no `value` capture; every other field must capture a number.
BOOL_FIELDS = frozenset(name for name, field in Facts.model_fields.items() if bool in get_args(field.annotation))


class Pattern(BaseModel):
    """One extraction rule: `field` gets the captured `value` (or True) for the names the rule captures.

    Strict, like `Doc`: a misspelled key is a config error rather than a silently ignored one, since a
    dropped `bind` would look exactly like a dead pattern.
    """

    model_config = ConfigDict(extra='forbid')

    field: str
    pattern: str
    bind: Literal['forward']|None = None    # bind to the nearest name the group lists when nothing is captured
    window: int = 400


class Doc(BaseModel):
    """A vendor doc page to mine facts from. Every rule lives here; nothing about the vendor lives in code."""

    model_config = ConfigDict(extra='forbid')

    url: str
    text: str = ''              # dotted path to the body inside a JSON response; '' = the response itself
    split: str = '、'
    units: dict[str, int] = Field(default_factory=dict)
    patterns: list[Pattern]


class Cfg(BaseModel):
    """One model group from lm.yml."""

    model_config = ConfigDict(extra='allow')

    openai: str|None = None
    style: str|None = None
    keys: list[str]
    models: dict[str, dict[str, object]] = Field(default_factory=dict)
    docs: list[Doc] = Field(default_factory=list)


F = TypeVar('F', bound=BaseModel)


def merge(primary: F, fallback: F) -> F:
    """Field-wise priority merge: `primary` wins where it has an opinion, `fallback` fills the rest."""
    values = {name: getattr(primary, name) for name in type(primary).model_fields}
    return type(primary)(**{
        name: value if value is not None else getattr(fallback, name)
        for name, value in values.items()
    })


def absorb(target: dict[str, F], source: Iterable[tuple[str, F]]) -> dict[str, F]:
    """Fold one source into `target`; the source wins per field where it has an opinion."""
    for model, found in source:
        target[model] = merge(found, target[model]) if model in target else found
    return target


def facts(raw: dict[str, object]) -> Facts:
    """Normalize one source entry to flat facts."""
    parsed = Facts.model_validate(raw)
    return parsed.model_copy(update={name: None for name in COST_FIELDS if getattr(parsed, name) == 0.0})


def keyed(entries: Iterable[tuple[str, dict[str, object]]]) -> dict[str, Facts]:
    """`<model> -> Facts`; entries collapsing onto one model name are merged, never last-wins."""
    return absorb({}, ((model, facts(entry)) for model, entry in entries))


async def get_json(sess: ClientSession, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = await sess.get(url, headers=headers, timeout=ClientTimeout(30))
    response.raise_for_status()
    return await response.json()


def from_backup(provider: str, cost_map: dict[str, dict[str, object]]) -> dict[str, Facts]:
    """litellm's shipped cost map: `litellm_provider` is the vendor tag, keys may carry the prefix."""
    return keyed((key.removeprefix(f'{provider}/'), entry) for key, entry in cost_map.items()
                 if entry.get('litellm_provider') == provider)


async def from_catalog(sess: ClientSession, provider: str) -> dict[str, Facts]:
    body = await get_json(sess, f'{CATALOG_URL}?provider={provider}')
    return keyed((str(entry['id']).removeprefix(f'{provider}/'), entry) for entry in body['data'])


async def from_endpoint(sess: ClientSession, cfg: Cfg) -> dict[str, Facts]:
    """The provider's own /models list: ids only, so the facts stay unset."""
    body = await get_json(sess, f'{cfg.openai}/models', {'Authorization': f'Bearer {cfg.keys[0]}'})
    return keyed((str(entry['id']), entry) for entry in body['data'])


def flatten(node: Any, out: list[str]) -> list[str]:
    """Every piece of text in a response body, including Quill-delta `insert` values."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        if isinstance(node.get('insert'), str):
            out.append(node['insert'])
        else:
            for value in node.values():
                flatten(value, out)
    elif isinstance(node, list):
        for value in node:
            flatten(value, out)
    return out


def page_text(body: Any, locator: str) -> str:
    """One line for the whole page: walk `locator`, parse an embedded body, flatten."""
    for step in locator.split('.') if locator else []:
        body = body[step]
    if isinstance(body, str):
        try:
            body = loads(body)
        except ValueError:
            return re.sub(r'\s+', ' ', body)
    return re.sub(r'\s+', ' ', ''.join(flatten(body, [])))


def nearest_listed(window: str, names: dict[str, str]) -> list[str]:
    r"""The nearest listed name after a match: a `[\w.-]+` capture would bind the page's component ids.

    Ties at one index break to the longest name, so `glm-5.3-flash` never resolves to `glm-5.3`.
    """
    low = window.lower()
    hits = [(low.find(name), -len(name), name) for name in names if low.find(name) >= 0]
    return [names[min(hits)[2]]] if hits else []


def doc_facts(doc: Doc, page: str, names: dict[str, str]
              ) -> tuple[dict[str, Facts], list[tuple[int, str, int, bool]], list[str]]:
    """Mine one page: facts, per-rule `(order, field, matches, skipped)` counts, and complaints.

    Only names the group lists are accepted. A bad rule is reported and skipped — it never discards what
    the other rules already mined.
    """
    found: dict[str, dict[str, object]] = {}
    counts: list[tuple[int, str, int, bool]] = []
    complaints: list[str] = []
    for order, rule in enumerate(doc.patterns, start=1):
        where = f'#{order} ({rule.field})'
        if rule.field not in Facts.model_fields:
            complaints.append(f'{where} is not a facts field, rule skipped')
            continue
        if rule.field in DERIVED_ONLY:
            complaints.append(f'{where} is derived by litellm, never prose-derived, rule skipped')
            continue
        try:
            pattern = re.compile(rule.pattern)
        except re.error as bad:
            complaints.append(f'{where} is not a valid regex, rule skipped: {bad}')
            continue
        if 'value' not in pattern.groupindex and rule.field not in BOOL_FIELDS:
            complaints.append(f'{where} captures no `value` and {rule.field} is not a flag, rule skipped')
            continue
        count = 0
        undeclared: set[str] = set()
        for match in pattern.finditer(page):
            groups = match.groupdict()
            captured = groups.get('models') or groups.get('model') or ''
            here = [name.strip() for name in captured.split(doc.split) if name.strip()]
            if not here and rule.bind == 'forward':
                here = nearest_listed(page[match.end():match.end() + rule.window], names)
            here = [name for name in here if name.lower() in names]
            if not here:
                continue
            value = groups.get('value')
            unit = (groups.get('unit') or '').lower()
            if unit and unit not in doc.units:
                undeclared.add(unit)      # an undeclared unit would silently scale the number by 1
                continue
            count += 1
            for model in here:
                facts = found.setdefault(names[model.lower()], {})
                if value is None:
                    facts[rule.field] = True          # the rule has no `value`, and the field is a flag
                    continue
                try:
                    number = int(float(value) * doc.units.get(unit, 1))
                except ValueError:
                    continue          # a capture that is not a number yields nothing
                previous = facts.get(rule.field)
                if isinstance(previous, int):
                    number = min(number, previous)     # never over-promise a window
                facts[rule.field] = number
        if undeclared:
            complaints.append(f'{where} uses units not declared in `units`: {sorted(undeclared)}')
        counts.append((order, rule.field, count, bool(undeclared)))
    return {model: Facts.model_validate(facts) for model, facts in found.items()}, counts, complaints


async def from_docs(sess: ClientSession, cfg: Cfg, names: dict[str, str]) -> dict[str, Facts]:
    """Mine every doc the group declares; a bad rule, a dead rule or an unreachable page is reported."""
    found: dict[str, Facts] = {}
    for index, doc in enumerate(cfg.docs, start=1):
        where = f'doc{index} {doc.url.split("?")[0]}'
        try:
            page = page_text(await get_json(sess, doc.url), doc.text)
        except Exception as unread:      # a broken page must not take the group's other docs down
            print(f'  !! {where} page or `text` locator failed: {unread!r}')
            continue
        facts, counts, found_complaints = doc_facts(doc, page, names)
        print(f'  {where}: {len(facts)} models, hits {[count for _, _, count, _ in counts]}')
        for complaint in found_complaints:
            print(f'  !! {where} {complaint}')
        dead = [f'#{order} {field}' for order, field, count, skipped in counts if not count and not skipped]
        if dead:
            print(f'  !! {where} nothing matched: {", ".join(dead)} — the page may have changed')
        absorb(found, facts.items())
    return found


async def guard(name: str, source: str, fetch: Awaitable[dict[str, Facts]]) -> dict[str, Facts]:
    """Report a failing source loudly and carry on with the others, never silently."""
    try:
        return await fetch
    except Exception as error:
        print(f'!! [{name}] {source} source unavailable: {type(error).__name__}: {error}')
        return {}


async def build(sess: ClientSession, name: str, cfg: Cfg,
                cost_map: dict[str, dict[str, object]]) -> tuple[str, Cfg, dict[str, Facts]]:
    offline = from_backup(name, cost_map)
    catalog = await guard(name, 'catalog', from_catalog(sess, name))
    probed = (await guard(name, 'endpoint', from_endpoint(sess, cfg))
              if not (offline or catalog) and cfg.openai and cfg.keys else {})
    names = {model.lower(): model for model in cfg.models}
    mined = await guard(name, 'docs', from_docs(sess, cfg, names))
    models: dict[str, Facts] = {}
    for source in (offline, catalog, probed, mined, keyed(cfg.models.items())):
        absorb(models, source.items())
    print(f'[{name}] backup={len(offline)} catalog={len(catalog)} endpoint={len(probed)} '
          f'docs={len(mined)} user={len(cfg.models)} -> {len(models)} models')
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
    for name, cfg in groups.items():
        if cfg.model_extra:
            print(f'[{name}] lm.yml keys not implemented, ignored: {sorted(cfg.model_extra)}')
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
