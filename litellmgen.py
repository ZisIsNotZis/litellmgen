#!/bin/env python3
"""Generate ~/litellm.yml from provider facts gathered from several sources.

Lowest priority first: litellm's shipped model_prices_and_context_window_backup.json, the live
https://api.litellm.ai/model_catalog, the provider's own /models endpoint, the account-scoped
https://api.githubcopilot.com/models, vendor doc pages (`roster` names the page declares, `patterns`
the facts it states), and ~/my/misc/lm.yml `models:` (extras and assertions).

A provider's `roster:` decides which names are members; every other source only annotates a member,
so a platform-wide `/models` dump cannot ship models a subscription cannot use; with no `roster:`,
any source may introduce one. Every source is normalized to `Facts` — one flat leaf per fact — so
priority is decided per field and never per object. `None` means "no source had an opinion": it
never overwrites a value, and `exclude_none` keeps it out of the output. Each model is exported once
per key, as `<group>/<model>`.
"""

from asyncio import gather, new_event_loop
import os
import re
from collections.abc import Awaitable, Iterable
from json import dumps, load, loads
from pathlib import Path
from time import time
from typing import Any, Literal, TypeVar, get_args

from aiohttp import ClientSession, ClientTimeout
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from yaml import safe_dump, safe_load

CATALOG_URL = 'https://api.litellm.ai/model_catalog'
BACKUP_PATH = Path('/home/z/.venv/lib/python3.14/site-packages/litellm/model_prices_and_context_window_backup.json')
CONFIG_PATH = Path('/home/z/my/misc/lm.yml')
OUTPUT_PATH = Path('/home/z/litellm.yml')

# github_copilot has no plain /models; litellm caches the GitHub->Copilot exchange here.
COPILOT_DIR = Path(os.getenv('GITHUB_COPILOT_TOKEN_DIR', '~/.config/litellm/github_copilot')).expanduser()
COPILOT_TOKEN_URL = 'https://api.github.com/copilot_internal/v2/token'
COPILOT_API_BASE = 'https://api.githubcopilot.com'
# Copilot's catalog speaks its own endpoint names; litellm's cost map spells them /v1/...
ENDPOINT_ALIASES = {'/chat/completions': '/v1/chat/completions', '/responses': '/v1/responses'}

# Per-token costs litellm reads; a 0.0 in these sources means "price unknown", not "free".
COST_FIELDS = ('input_cost_per_token', 'output_cost_per_token', 'input_cost_per_audio_token',
               'output_cost_per_reasoning_token', 'cache_read_input_token_cost',
               'cache_creation_input_token_cost')


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


# litellm rewrites a caller's `max_tokens` from this legacy cost-map field (token_counter.py), so it
# is never prose-derived: a misread page must not be able to silently cap a request.
DERIVED_ONLY = ('max_tokens',)

# Flag fields take `True` from a rule with no `value` capture; every other field must capture a number.
BOOL_FIELDS = frozenset(name for name, field in Facts.model_fields.items() if bool in get_args(field.annotation))


class Pattern(BaseModel):
    """One extraction rule: `field` gets the captured `value` (or True, for a flag) for its names.

    Strict, like `Doc`: a misspelled key is a config error, not a silently ignored one.
    """

    model_config = ConfigDict(extra='forbid')

    field: str
    pattern: str
    bind: Literal['forward']|None = None    # bind to the nearest listed name when nothing is captured
    window: int = 400


class Doc(BaseModel):
    """A vendor doc page to mine. Every rule lives here; nothing about the vendor lives in code."""

    model_config = ConfigDict(extra='forbid')

    url: str
    text: str = ''              # dotted path to the body inside a JSON response; '' = the response itself
    split: str = '、'
    units: dict[str, int] = Field(default_factory=dict)
    # A page that names its own models feeds the roster: `roster` regexes search the flattened page
    # text, while `inline_code` regexes fullmatch the spans the page marked as literal ids. Both yield
    # lowercase ids, the form a vendor's API accepts (`GLM-5.3` on the page, `glm-5.3` for us).
    roster: list[str] = Field(default_factory=list)
    inline_code: list[str] = Field(default_factory=list)
    patterns: list[Pattern]


Channel = Literal['backup', 'catalog', 'endpoint', 'copilot', 'docs']


class Cfg(BaseModel):
    """One model group from lm.yml."""

    model_config = ConfigDict(extra='allow')

    openai: str|None = None
    style: str|None = None
    keys: dict[str, str] = Field(default_factory=dict)
    roster: list[Channel]|None = None     # who decides membership; None = any source may add a model
    models: dict[str, dict[str, object]] = Field(default_factory=dict)   # extras + assertions
    docs: list[Doc] = Field(default_factory=list)


F = TypeVar('F', bound=BaseModel)


def merge(primary: F, fallback: F) -> F:
    """Field-wise priority merge: `primary` wins where it has an opinion, `fallback` fills the rest."""
    values = {name: getattr(primary, name) for name in type(primary).model_fields}
    return type(primary)(**{
        name: value if value is not None else getattr(fallback, name) for name, value in values.items()
    })


def absorb(target: dict[str, F], source: Iterable[tuple[str, F]]) -> dict[str, F]:
    """Fold one source into `target`; the source wins per field where it has an opinion."""
    for model, found in source:
        target[model] = merge(found, target[model]) if model in target else found
    return target


def keyed(entries: Iterable[tuple[str, dict[str, object]]]) -> dict[str, Facts]:
    """One source's `<model> -> Facts`, normalizing cost fields and merging same-name entries."""
    def facts(raw: dict[str, object]) -> Facts:
        """0.0 in a cost field means "price unknown", not "free"."""
        parsed = Facts.model_validate(raw)
        return parsed.model_copy(update={name: None for name in COST_FIELDS if getattr(parsed, name) == 0.0})

    return absorb({}, ((model, facts(entry)) for model, entry in entries))


async def get_json(sess: ClientSession, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = await sess.get(url, headers=headers, timeout=ClientTimeout(30))
    response.raise_for_status()
    return await response.json()


async def guard(name: str, source: str, fetch: Awaitable[dict[str, Facts]]) -> dict[str, Facts]:
    """Report a failing source loudly and carry on with the others, never silently."""
    try:
        return await fetch
    except Exception as error:
        print(f'!! [{name}] {source} source unavailable: {type(error).__name__}: {error}')
        return {}


def from_backup(provider: str, cost_map: dict[str, dict[str, object]]) -> dict[str, Facts]:
    """litellm's shipped cost map: `litellm_provider` is the vendor tag, keys may carry the prefix."""
    return keyed((key.removeprefix(f'{provider}/'), entry) for key, entry in cost_map.items()
                 if entry.get('litellm_provider') == provider)


async def from_catalog(sess: ClientSession, provider: str) -> dict[str, Facts]:
    body = await get_json(sess, f'{CATALOG_URL}?provider={provider}')
    return keyed((str(entry['id']).removeprefix(f'{provider}/'), entry) for entry in body['data'])


async def from_endpoint(sess: ClientSession, cfg: Cfg) -> dict[str, Facts]:
    """The provider's own /models list: ids only, so the facts stay unset."""
    auth = {'Authorization': f'Bearer {next(iter(cfg.keys.values()))}'}
    body = await get_json(sess, f'{cfg.openai}/models', auth)
    return keyed((str(entry['id']), entry) for entry in body['data'])


async def copilot_token(sess: ClientSession) -> tuple[str, str]:
    """The cached Copilot bearer and API base, refreshed from the cached GitHub access token if stale.

    litellm performs the GitHub -> Copilot exchange at runtime and caches it, so reusing that cache
    keeps this generator from needing a github_copilot key of its own.
    """
    cached: dict[str, Any] = loads((COPILOT_DIR / 'api-key.json').read_text())
    if not cached.get('expires_at', 0) > time():
        access = (COPILOT_DIR / 'access-token').read_text().strip()
        cached = await get_json(sess, COPILOT_TOKEN_URL,
                                {'authorization': f'token {access}', 'accept': 'application/json'})
        (COPILOT_DIR / 'api-key.json').write_text(dumps(cached))
    endpoints = cached.get('endpoints') or {}
    return str(cached['token']), str(endpoints.get('api') or COPILOT_API_BASE)


def copilot_facts(entry: dict[str, Any]) -> Facts:
    """One `api.githubcopilot.com/models` entry -> flat facts. An account-scoped catalog, so it wins."""
    def flag(value: Any) -> bool|None:
        """A capability is an opinion only when the catalog states it; absent stays unknown."""
        return None if value is None else bool(value)

    capabilities = entry.get('capabilities') or {}
    limits = capabilities.get('limits') or {}
    supports = capabilities.get('supports') or {}
    endpoints = [ENDPOINT_ALIASES.get(endpoint, endpoint)
                 for endpoint in entry.get('supported_endpoints') or []
                 if isinstance(endpoint, str) and endpoint.startswith('/')]
    responses_only = any('responses' in e for e in endpoints) and not any('chat' in e for e in endpoints)
    kind = capabilities.get('type')
    return Facts(
        mode=('embedding' if kind == 'embeddings' else
              'completion' if kind == 'completion' else
              'responses' if responses_only else 'chat'),
        max_input_tokens=limits.get('max_prompt_tokens') or limits.get('max_context_window_tokens'),
        max_output_tokens=limits.get('max_output_tokens'),
        supports_vision=flag(supports.get('vision')),
        supports_function_calling=flag(supports.get('tool_calls')),
        supports_parallel_function_calling=flag(supports.get('parallel_tool_calls')),
        supports_native_streaming=flag(supports.get('streaming')),
        supports_response_schema=flag(supports.get('structured_outputs')),
        supports_reasoning=flag(supports.get('reasoning_effort')),
        supported_endpoints=endpoints or None,
    )


async def from_copilot(sess: ClientSession) -> dict[str, Facts]:
    """github_copilot has no plain /models: read the account's own catalog through the token exchange."""
    token, api_base = await copilot_token(sess)
    body = await get_json(sess, f'{api_base}/models', {
        'Authorization': f'Bearer {token}',
        'copilot-integration-id': 'vscode-chat',
        'editor-version': 'vscode/1.95.0',
        'editor-plugin-version': 'copilot-chat/0.26.7',
        'user-agent': 'GitHubCopilotChat/0.26.7',
        'openai-intent': 'conversation-panel',
        'x-github-api-version': '2025-04-01',
    })
    return absorb({}, ((str(entry['id']), copilot_facts(entry)) for entry in body['data']))


def walk(node: Any, text: list[str], spans: list[str]) -> None:
    """Collect a response body's text, including Quill-delta `insert` values and inline-code spans."""
    if isinstance(node, str):
        text.append(node)
    elif isinstance(node, dict):
        insert = node.get('insert')
        if isinstance(insert, str):
            if (node.get('attributes') or {}).get('inlineCode'):
                spans.append(insert)
            text.append(insert)
        else:
            for value in node.values():
                walk(value, text, spans)
    elif isinstance(node, list):
        for value in node:
            walk(value, text, spans)


def page_parts(body: Any, locator: str) -> tuple[str, list[str]]:
    """One flat line of the whole page, and the spans it marked as literal code, in order.

    `locator` walks into the body first, parsing an embedded JSON string once.
    """
    for step in locator.split('.') if locator else []:
        body = body[step]
    if isinstance(body, str):
        try:
            body = loads(body)
        except ValueError:
            pass
    text: list[str] = []
    spans: list[str] = []
    walk(body, text, spans)
    return re.sub(r'\s+', ' ', ''.join(text)), spans


def nearest_listed(window: str, names: dict[str, str]) -> list[str]:
    r"""The nearest listed name after a match: a `[\w.-]+` capture would bind the page's own ids.

    Ties at one index break to the longest name, so `glm-5.3-flash` never resolves to `glm-5.3`.
    """
    low = window.lower()
    hits = [(low.find(name), -len(name), name) for name in names if low.find(name) >= 0]
    return [names[min(hits)[2]]] if hits else []


def doc_facts(doc: Doc, page: str, names: dict[str, str], where: str) -> dict[str, Facts]:
    """Mine one page for the names the group lists, printing what matched.

    Only listed names are accepted; a bad rule is reported and skipped, never discarding what the
    other rules already mined.
    """
    found: dict[str, dict[str, object]] = {}
    counts: list[tuple[int, str, int, bool]] = []
    complaints: list[str] = []
    for order, rule in enumerate(doc.patterns, start=1):
        spot = f'#{order} ({rule.field})'
        if rule.field not in Facts.model_fields or rule.field in DERIVED_ONLY:
            complaints.append(f'{spot} is not a prose-minable facts field, rule skipped')
            continue
        try:
            pattern = re.compile(rule.pattern)
        except re.error as bad:
            complaints.append(f'{spot} is not a valid regex, rule skipped: {bad}')
            continue
        if 'value' not in pattern.groupindex and rule.field not in BOOL_FIELDS:
            complaints.append(f'{spot} captures no `value` and {rule.field} is not a flag, rule skipped')
            continue
        count = 0
        undeclared: set[str] = set()
        for match in pattern.finditer(page):
            groups = match.groupdict()
            listed = (groups.get('models') or groups.get('model') or '').split(doc.split)
            here = [name.strip() for name in listed if name.strip()] or (
                nearest_listed(page[match.end():match.end() + rule.window], names)
                if rule.bind == 'forward' else [])
            here = [name for name in here if name.lower() in names]
            if not here:
                continue
            value, unit = groups.get('value'), (groups.get('unit') or '').lower()
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
            complaints.append(f'{spot} uses units not declared in `units`: {sorted(undeclared)}')
        counts.append((order, rule.field, count, bool(undeclared)))
    print(f'  {where}: {len(found)} models, hits {[count for _, _, count, _ in counts]}')
    for complaint in complaints:
        print(f'  !! {where} {complaint}')
    dead = [f'#{order} {field}' for order, field, count, skipped in counts if not count and not skipped]
    if dead:
        print(f'  !! {where} nothing matched: {", ".join(dead)} — the page may have changed')
    return {model: Facts.model_validate(raw) for model, raw in found.items()}


def doc_roster(doc: Doc, page: str, spans: list[str]) -> list[str]:
    """The names one page declares for itself: `roster` regexes over the text, `inline_code` over spans."""
    named = [match.group('name') for rule in doc.roster for match in re.finditer(rule, page)]
    coded = [span for rule in doc.inline_code for span in spans if re.fullmatch(rule, span)]
    return [name.lower() for name in (*named, *coded)]


async def from_docs(sess: ClientSession,
                    cfg: Cfg, known: Iterable[str]) -> tuple[dict[str, Facts], list[str]]:
    """Mine every doc the group declares: the facts, and the roster the pages name for themselves.

    Pages are fetched once so that a roster in any one page can name models for the rules in every
    page. A broken page or a bad rule is reported and never takes the group's other docs down.
    """
    pages: list[tuple[int, Doc, str, list[str]]] = []
    for index, doc in enumerate(cfg.docs, start=1):
        try:
            page, spans = page_parts(await get_json(sess, doc.url), doc.text)
            pages.append((index, doc, page, spans))
        except Exception as unread:      # a broken page must not take the group's other docs down
            print(f'  !! doc{index} {doc.url.split("?")[0]} page or `text` locator failed: {unread!r}')
    roster = [name for _, doc, page, spans in pages for name in doc_roster(doc, page, spans)]
    names = {name.lower(): name for name in (*known, *roster)}
    found: dict[str, Facts] = {}
    for index, doc, page, _ in pages:
        absorb(found, doc_facts(doc, page, names, f'doc{index} {doc.url.split("?")[0]}').items())
    return found, roster


async def build(sess: ClientSession, name: str, cfg: Cfg,
                cost_map: dict[str, dict[str, object]]) -> tuple[str, Cfg, dict[str, Facts]]:
    """Gather every source, then keep only the names the group's `roster:` admits (all, when unset)."""
    roster = cfg.roster or ['backup', 'catalog', 'endpoint']
    channels: dict[str, dict[str, Facts]] = {'backup': from_backup(name, cost_map)}
    channels['catalog'] = await guard(name, 'catalog', from_catalog(sess, name))
    channels['endpoint'] = (          # `cfg.roster`, not `roster`: the default never asks for /models
        await guard(name, 'endpoint', from_endpoint(sess, cfg))
        if ('endpoint' in (cfg.roster or []) or not (channels['backup'] or channels['catalog']))
        and cfg.openai and cfg.keys else {})
    channels['copilot'] = (await guard(name, 'copilot', from_copilot(sess))
                           if 'copilot' in roster else {})
    extras = list(cfg.models)
    known = [*extras, *(model for channel in roster if channel != 'docs' for model in channels[channel])]
    mined: dict[str, Facts] = {}
    named: list[str] = []
    if cfg.docs:
        try:
            mined, named = await from_docs(sess, cfg, known)
        except Exception as error:       # a dead doc source must not take the group down
            print(f'!! [{name}] docs source unavailable: {type(error).__name__}: {error}')
    if cfg.roster is None:               # no roster declared: any source may introduce a model
        members = [model for source in (*channels.values(), mined) for model in source] + named
    else:
        members = [model for channel in roster if channel != 'docs' for model in channels[channel]]
        members += named if 'docs' in roster else []
    spelling: dict[str, str] = {}        # lowercase -> the spelling that reaches the output
    for model in (*members, *extras):
        spelling.setdefault(model.lower(), model)

    models: dict[str, Facts] = {}
    for source in (*channels.values(), mined, keyed(cfg.models.items())):
        for model, found in source.items():
            if model.lower() in spelling:
                key = spelling[model.lower()]
                models[key] = merge(found, models[key]) if key in models else found
    for key in spelling.values():        # a roster name no source states facts for is still a member
        models.setdefault(key, Facts())
    counts = ' '.join(f'{channel}={len(found)}' for channel, found in channels.items())
    print(f'[{name}] roster="{" ".join(roster)}" {counts} docs={len(mined)} extra={len(extras)} '
          f'-> {len(models)} models')
    return name, cfg, models


def entries(name: str, cfg: Cfg, models: dict[str, Facts]) -> list[dict[str, object]]:
    """One router entry per model and key, exported as `<group>/<model>` and nothing else."""
    return [
        {
            'model_name': f'{name}/{model}',
            'litellm_params': {
                'api_base': cfg.openai,
                'api_key': key,
                'drop_params': True,
                'model': f'{cfg.style or name}/{model}',
            },
            'model_info': found.model_dump(exclude_none=True),
        }
        for model, found in models.items()
        for key in cfg.keys.values() or [None]
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


if __name__ == '__main__':
    new_event_loop().run_until_complete(main())
