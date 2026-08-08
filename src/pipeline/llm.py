"""Provider-agnostic structured LLM call.

Both pipeline stages need the same operation: send messages plus a *forced*
tool schema and get the tool's arguments back as a plain dict. This module
hides whether that runs on Kimi (Moonshot, OpenAI-compatible) or Anthropic
behind the ``LLM_PROVIDER`` env var, so the pipeline files keep their own
retry / Pydantic-validation loops untouched.

Env vars:
  LLM_PROVIDER        "deepseek" (default) | "kimi" | "anthropic"
  DEEPSEEK_API_KEY    required when provider is deepseek (domestic OpenAI-compatible endpoint)
  DEEPSEEK_BASE_URL   optional; defaults to https://api.deepseek.com
  MOONSHOT_API_KEY    required when provider is kimi
  MOONSHOT_BASE_URL   kimi endpoint switch (.cn domestic default; .ai for international)
  ANTHROPIC_API_KEY   required when provider is anthropic
  LLM_MODEL_PER_ASSET / LLM_MODEL_SYNTHESIZE   optional per-stage model override
"""
import json
import os
import time

import httpx
from openai import APIConnectionError, APITimeoutError

PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek").lower()

# A long k3 synthesis (reasoning always on) can run long enough that an
# intermediate proxy drops the connection — either before the stream starts
# (openai APIConnectionError) or mid-stream ("incomplete chunked read",
# httpx.RemoteProtocolError). The OpenAI SDK only retries failures before the
# stream starts, so we retry the whole request ourselves on a transient drop.
_STREAM_ATTEMPTS = 3
_TRANSIENT = (httpx.HTTPError, APIConnectionError, APITimeoutError)

# Moonshot's base URL is region-dependent: .cn is the domestic (proxy-free)
# endpoint, .ai the international one (set MOONSHOT_BASE_URL to
# https://api.moonshot.ai/v1 — it needs a separate .ai key).
_MOONSHOT_CN = "https://api.moonshot.cn/v1"

# Per-stage model, per provider. Both stages use a forced tool_choice; per_asset
# is cheap extraction work, synthesize is the reasoning/quality lever.
_MODELS = {
    "kimi": {
        # Never upgrade per_asset to a reasoning model — thinking about a
        # single-ticker summary is pure waste.
        "per_asset":  "kimi-k2.6",
        # k2.6 (thinking off, forced tool) is fast + reliable and passed QC near-
        # perfectly. kimi-k3's always-on reasoning gives sharper transmission-chain
        # analysis but can't hit a <2min budget on large inputs (20 econ + 210
        # earnings blew past it), and it rejects a forced tool_choice — so it
        # routes through JSON mode (_call_kimi_json) and is opt-in only:
        # LLM_MODEL_SYNTHESIZE=kimi-k3 when you want max quality and can wait.
        "synthesize": "kimi-k2.6",
    },
    "anthropic": {
        "per_asset":  "claude-haiku-4-5-20251001",
        "synthesize": "claude-sonnet-4-6",
    },
    # DeepSeek V4 (OpenAI-compatible, domestic endpoint, cheap). Like kimi-k3 it
    # defaults to thinking mode which rejects a forced tool_choice, so we disable
    # thinking (see _call_deepseek) for the forced-tool path. flash = cheap
    # extraction, pro = quality lever.
    "deepseek": {
        "per_asset":  "deepseek-v4-flash",
        "synthesize": "deepseek-v4-pro",
    },
}


class NoToolCall(RuntimeError):
    """Model returned no usable tool call — the caller retries."""


class StreamDropped(NoToolCall):
    """Transport dropped the streamed request after all retries — distinct from a
    bad/empty payload, so callers can fall back rather than re-prompt for schema."""


def model_for(stage: str) -> str:
    """Resolve the model id for a pipeline stage under the active provider.

    An env override (LLM_MODEL_PER_ASSET / LLM_MODEL_SYNTHESIZE) wins if set.
    """
    override = os.environ.get(f"LLM_MODEL_{stage.upper()}")
    if override:
        return override
    return _MODELS[PROVIDER][stage]


def call_tool(model: str, messages: list, tool_schema: dict, max_tokens: int) -> dict:
    """Force `model` to call `tool_schema` and return its arguments as a dict.

    `tool_schema` is the Anthropic-style {name, description, input_schema}.
    Raises NoToolCall if the model produces no parseable tool call.
    """
    if PROVIDER == "anthropic":
        return _call_anthropic(model, messages, tool_schema, max_tokens)
    if PROVIDER == "deepseek":
        return _call_deepseek(model, messages, tool_schema, max_tokens)
    return _call_kimi(model, messages, tool_schema, max_tokens)


_anthropic_client = None


def _call_anthropic(model, messages, tool_schema, max_tokens) -> dict:
    global _anthropic_client
    import anthropic
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    # Stream for the same reason as the Kimi path: a long non-streaming synthesis
    # request can be dropped by an intermediate proxy while it sits idle.
    with _anthropic_client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=messages,
    ) as stream:
        resp = stream.get_final_message()
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        raise NoToolCall("No tool_use block in response")
    return block.input


_kimi_client = None


def _ensure_kimi_client():
    global _kimi_client
    from openai import OpenAI
    if _kimi_client is not None:
        return
    base_url = os.environ.get("MOONSHOT_BASE_URL", _MOONSHOT_CN)
    # Fail fast: a stalled stream errors in ~2 min instead of sitting for 10 (the
    # old 600s timeout × retries was what turned a flaky proxy into a 30-min hang).
    kwargs = dict(api_key=os.environ["MOONSHOT_API_KEY"], base_url=base_url, timeout=120.0)
    if "moonshot.cn" in base_url:
        # Domestic endpoint: connect directly, bypassing any overseas proxy set in
        # the shell env (HTTPS_PROXY). Routing a .cn request through an overseas
        # proxy reintroduces exactly the long-connection drops we're escaping.
        kwargs["http_client"] = httpx.Client(trust_env=False, timeout=120.0)
    _kimi_client = OpenAI(**kwargs)


def _call_kimi(model, messages, tool_schema, max_tokens) -> dict:
    _ensure_kimi_client()
    # kimi-k3 keeps reasoning permanently on and rejects a forced tool_choice, so
    # it can't use the tool path — route it through JSON mode instead (schema in
    # the prompt + response_format json_object, validated downstream as usual).
    if "k3" in model.lower():
        return _call_kimi_json(model, messages, tool_schema, max_tokens)
    # kimi needs thinking explicitly disabled to allow a forced tool_choice.
    return _call_forced(_kimi_client, model, messages, tool_schema, max_tokens,
                        extra_body={"thinking": {"type": "disabled"}})


_deepseek_client = None


def _ensure_deepseek_client():
    global _deepseek_client
    from openai import OpenAI
    if _deepseek_client is not None:
        return
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    # Domestic endpoint → connect directly, bypassing any overseas proxy in the env.
    _deepseek_client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"], base_url=base_url, timeout=120.0,
        http_client=httpx.Client(trust_env=False, timeout=120.0))


def _call_deepseek(model, messages, tool_schema, max_tokens) -> dict:
    _ensure_deepseek_client()
    # DeepSeek V4 defaults to thinking mode, which — like kimi-k3 — rejects a forced
    # tool_choice ("Thinking mode does not support this tool_choice"). Same fix: disable
    # thinking via extra_body. DeepSeek uses OpenAI's classic `max_tokens` field.
    return _call_forced(_deepseek_client, model, messages, tool_schema, max_tokens,
                        extra_body={"thinking": {"type": "disabled"}}, token_field="max_tokens")


def _call_forced(client, model, messages, tool_schema, max_tokens,
                 extra_body=None, token_field="max_completion_tokens") -> dict:
    """Generic OpenAI-compatible forced-tool path (streamed + retried). Shared by
    Kimi and DeepSeek; only the token-limit field name and any provider `extra_body`
    differ. Anthropic tool schema -> OpenAI function schema (input_schema = parameters)."""
    function = {
        "type": "function",
        "function": {
            "name": tool_schema["name"],
            "description": tool_schema.get("description", ""),
            "parameters": tool_schema["input_schema"],
        },
    }
    kwargs = {
        "model": model, "messages": messages, "tools": [function],
        "tool_choice": {"type": "function", "function": {"name": tool_schema["name"]}},
        token_field: max_tokens,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    raw_args = _stream_collect(client, kwargs, _pick_tool_args)
    if not raw_args:
        raise NoToolCall("No tool_call arguments in streamed response")
    try:
        return json.loads(raw_args)
    except json.JSONDecodeError as e:
        raise NoToolCall(f"Tool arguments were not valid JSON: {e}")


def _pick_tool_args(delta) -> str:
    if not getattr(delta, "tool_calls", None):
        return ""
    return "".join(tc.function.arguments for tc in delta.tool_calls
                   if tc.function and tc.function.arguments)


def _pick_content(delta) -> str:
    # content carries the answer; reasoning_content (k3 thinking) is skipped.
    return getattr(delta, "content", "") or ""


def _stream_collect(client, create_kwargs: dict, pick) -> str:
    """Stream a chat completion and reassemble a string via pick(delta).

    Retries the whole request on a transient transport drop — a long request can be
    cut mid-stream, which the OpenAI SDK does not retry once bytes have started flowing.
    """
    last_exc = None
    for attempt in range(_STREAM_ATTEMPTS):
        try:
            stream = client.chat.completions.create(stream=True, **create_kwargs)
            parts: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                s = pick(chunk.choices[0].delta)
                if s:
                    parts.append(s)
            return "".join(parts)
        except _TRANSIENT as e:
            last_exc = e
            if attempt < _STREAM_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3.0s backoff
    raise StreamDropped(f"stream dropped after {_STREAM_ATTEMPTS} attempts: {last_exc}")


def _strip_fences(text: str) -> str:
    """Drop a leading/trailing ```json ... ``` fence if the model wrapped its JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _call_kimi_json(model, messages, tool_schema, max_tokens) -> dict:
    """JSON-mode path for models that can't use a forced tool_choice (kimi-k3).

    The tool's JSON schema is put in the prompt and `response_format=json_object`
    guarantees parseable JSON; conformance is enforced downstream by the same
    Pydantic validation + retry loop as the tool path. Reasoning tokens (thinking
    is always on for k3) arrive as `reasoning_content` deltas, which we skip — only
    `content` carries the answer JSON.
    """
    schema_text = json.dumps(tool_schema["input_schema"], ensure_ascii=False)
    instruction = (
        "Respond with ONLY a single valid JSON object — no prose, no explanation, "
        "no markdown code fences — that conforms to this JSON schema:\n" + schema_text
    )
    msgs = list(messages) + [{"role": "user", "content": instruction}]
    try:
        raw = _strip_fences(_stream_collect(
            _kimi_client,
            dict(
                model=model,
                messages=msgs,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
            _pick_content,
        ))
    except StreamDropped as e:
        # The proxy kept cutting this long k3 request. Fall back to the cheaper
        # k2.x forced-tool path (much shorter request — thinking disabled — so it
        # survives a flaky proxy) so a brief is still produced this run.
        fallback = os.environ.get("KIMI_FALLBACK_MODEL", "kimi-k2.6")
        print(f"[llm] {model} synthesis stream unreachable ({e}); "
              f"falling back to {fallback}")
        return _call_forced(_kimi_client, fallback, messages, tool_schema, max_tokens,
                            extra_body={"thinking": {"type": "disabled"}})
    if not raw:
        raise NoToolCall("Empty content in streamed JSON-mode response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise NoToolCall(f"JSON-mode output was not valid JSON: {e}")
