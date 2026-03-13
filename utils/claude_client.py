import copy
import anthropic
from utils.env import settings
import yaml

# Configure global Anthropic client
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Load model assignments from config file
with open("config/models.yaml") as f:
    MODELS = yaml.safe_load(f)

# Tool definitions for API (e.g. web_search)
TOOL_WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search"}


def get_response_text(response) -> str:
    """Extract final text from a Messages API response (handles tool use: last text block)."""
    content = getattr(response, "content", None) or []
    text = None
    for block in content:
        if getattr(block, "type", None) == "text" and hasattr(block, "text"):
            text = block.text
    return text if text else str(response)


def _content_has_text_block(content) -> bool:
    """True if content has at least one text block."""
    for block in content or []:
        if getattr(block, "type", None) == "text":
            return True
    return False


def _build_tool_result_blocks(content) -> list:
    """Build user-message tool_result blocks from response content (server-side tool results)."""
    results = []
    for block in content or []:
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result" and hasattr(block, "tool_use_id"):
            # API expects tool_result with content as string
            raw = getattr(block, "content", None)
            if isinstance(raw, list):
                parts = []
                for item in raw:
                    if hasattr(item, "model_dump"):
                        parts.append(str(item.model_dump()))
                    elif isinstance(item, dict):
                        parts.append(str(item))
                    else:
                        parts.append(str(item))
                content_str = "\n".join(parts) if parts else ""
            else:
                content_str = str(raw) if raw is not None else ""
            results.append({
                "type": "tool_result",
                "tool_use_id": getattr(block, "tool_use_id", ""),
                "content": content_str,
            })
    return results


def _content_to_message_param(content) -> list:
    """Convert response content blocks to message param format (list of dicts)."""
    out = []
    for block in content or []:
        if hasattr(block, "model_dump"):
            out.append(block.model_dump(exclude_none=True))
        else:
            out.append(dict(block) if hasattr(block, "keys") else {"type": "text", "text": str(block)})
    return out


def _sanitize_schema(schema_payload: dict) -> None:
    """Strip schema keywords not supported by Messages API; set additionalProperties on objects."""
    if not isinstance(schema_payload, dict):
        return
    if schema_payload.get("type") == "object" and "additionalProperties" not in schema_payload:
        schema_payload["additionalProperties"] = False
    if schema_payload.get("type") in ("integer", "number"):
        schema_payload.pop("minimum", None)
        schema_payload.pop("maximum", None)
    for k in ["minItems", "maxItems", "pattern", "format"]:
        schema_payload.pop(k, None)
    for v in schema_payload.values():
        if isinstance(v, dict):
            _sanitize_schema(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _sanitize_schema(item)


def _build_agent_params(agent_name: str, system_prompt: str, user_message: str,
                        schema: dict = None, tools: list = None) -> dict:
    """Build params dict for messages.create (sync or async)."""
    model = MODELS.get(agent_name, "claude-sonnet-4-6")
    params = {
        "model": model,
        "max_tokens": 4096,
        "system": [
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [{"role": "user", "content": user_message}],
    }
    if tools:
        params["tools"] = [
            TOOL_WEB_SEARCH if t == "web_search" else t for t in tools
        ]
    if schema:
        schema_payload = copy.deepcopy(schema)
        _sanitize_schema(schema_payload)
        if schema_payload.get("type") == "object" and "additionalProperties" not in schema_payload:
            schema_payload["additionalProperties"] = False
        params["output_config"] = {
            "format": {"type": "json_schema", "schema": schema_payload},
        }
    return params


_MAX_TOOL_LOOP_ROUNDS = 5


def _run_tool_loop_sync(params: dict):
    """Run messages.create in a loop until we get a text block or no more tool use."""
    cl = client
    messages = list(params["messages"])
    for _ in range(_MAX_TOOL_LOOP_ROUNDS):
        create_params = {**params, "messages": messages}
        response = cl.messages.create(**create_params)
        content = getattr(response, "content", None) or []
        if _content_has_text_block(content):
            return response
        tool_results = _build_tool_result_blocks(content)
        if not tool_results:
            return response
        messages.append({"role": "assistant", "content": _content_to_message_param(content)})
        messages.append({"role": "user", "content": tool_results})
    return response


async def _run_tool_loop_async(params: dict):
    """Async: run messages.create in a loop until we get a text block or no more tool use."""
    from utils.async_claude import async_claude
    cl = async_claude
    messages = list(params["messages"])
    response = None
    for _ in range(_MAX_TOOL_LOOP_ROUNDS):
        create_params = {**params, "messages": messages}
        response = await cl.messages.create(**create_params)
        content = getattr(response, "content", None) or []
        if _content_has_text_block(content):
            return response
        tool_results = _build_tool_result_blocks(content)
        if not tool_results:
            return response
        messages.append({"role": "assistant", "content": _content_to_message_param(content)})
        messages.append({"role": "user", "content": tool_results})
    return response


def call_agent(agent_name: str, system_prompt: str, user_message: str,
               schema: dict = None, effort: str = None, tools: list = None):
    """Central function for all agent calls (sync).

    Automatically applies prompt caching on the system prompt.
    Uses structured outputs when schema is provided.
    Optionally enables tools (e.g. web_search). When tools are used, runs a tool loop
    until the model returns a text block (so we never return raw tool_use response).
    """
    params = _build_agent_params(agent_name, system_prompt, user_message, schema=schema, tools=tools)
    if tools:
        return _run_tool_loop_sync(params)
    return client.messages.create(**params)


async def async_call_agent(agent_name: str, system_prompt: str, user_message: str,
                           schema: dict = None, tools: list = None):
    """Async version of call_agent for parallel execution (e.g. Phase 2 planning).
    When tools are used, runs a tool loop until the model returns a text block.
    """
    from utils.async_claude import async_claude
    params = _build_agent_params(agent_name, system_prompt, user_message, schema=schema, tools=tools)
    if tools:
        return await _run_tool_loop_async(params)
    return await async_claude.messages.create(**params)
