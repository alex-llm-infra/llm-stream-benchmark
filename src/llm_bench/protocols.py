from dataclasses import dataclass
import json
from typing import Any, Dict, Optional, Tuple


@dataclass
class ParsedSSEFrame:
    is_done: bool = False
    has_content_token: bool = False
    has_reasoning_token: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


def build_request_spec(
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    base = base_url.rstrip("/")
    if protocol.lower() == "anthropic":
        url = f"{base}/messages" if not base.endswith("/messages") else base
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        return url, headers, payload

    # Default: OpenAI-compatible protocol
    url = f"{base}/chat/completions" if not base.endswith("/chat/completions") else base
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise systems engineering assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return url, headers, payload


def parse_sse_line(protocol: str, line: str) -> Optional[ParsedSSEFrame]:
    if not line or not line.startswith("data:"):
        return None

    data_str = line[5:].strip()
    if data_str == "[DONE]":
        return ParsedSSEFrame(is_done=True)

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError:
        return None

    frame = ParsedSSEFrame()

    if protocol.lower() == "anthropic":
        evt_type = payload.get("type", "")
        if evt_type == "message_stop":
            frame.is_done = True
        elif evt_type == "message_start":
            usage = payload.get("message", {}).get("usage", {})
            frame.input_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            frame.cached_tokens = usage.get("cache_read_input_tokens", 0)
        elif evt_type == "content_block_delta":
            delta = payload.get("delta", {})
            d_type = delta.get("type", "")
            if d_type == "thinking_delta" and delta.get("thinking"):
                frame.has_reasoning_token = True
            elif d_type in ("text_delta", "input_json_delta") and (delta.get("text") or delta.get("partial_json")):
                frame.has_content_token = True
        elif evt_type == "message_delta":
            usage = payload.get("usage", {})
            frame.output_tokens = usage.get("output_tokens", 0)
        return frame

    # OpenAI & DeepSeek / OpenRouter compatible schema
    choices = payload.get("choices", [])
    if choices:
        delta = choices[0].get("delta", {})
        if delta.get("reasoning_content") or delta.get("reasoning"):
            frame.has_reasoning_token = True
        if delta.get("content") or delta.get("tool_calls"):
            frame.has_content_token = True

    usage = payload.get("usage")
    if isinstance(usage, dict):
        frame.input_tokens = usage.get("prompt_tokens", 0)
        frame.output_tokens = usage.get("completion_tokens", 0)
        details = usage.get("prompt_tokens_details") or {}
        frame.cached_tokens = details.get("cached_tokens", 0) or usage.get("prompt_cache_hit_tokens", 0)

    return frame
