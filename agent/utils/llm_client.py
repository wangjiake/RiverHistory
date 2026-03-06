"""LLM client."""

import requests


def is_llm_error(text: str) -> bool:
    """Check if text is an LLM error message."""
    return bool(text) and text.startswith("[LLM ")


def call_llm(messages: list[dict], config: dict) -> str:
    api_base = config.get("api_base", "https://api.openai.com")
    model = config.get("model", "gpt-4o-mini")
    api_key = config.get("api_key", "")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 2048)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # gpt-5/o1/o3 系列：max_completion_tokens + 不支持自定义 temperature
    is_new_model = any(k in model for k in ("gpt-5", "o1", "o3"))
    if is_new_model:
        token_param = {"max_completion_tokens": max_tokens}
    else:
        token_param = {"max_tokens": max_tokens, "temperature": temperature}

    try:
        resp = requests.post(
            f"{api_base}/v1/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                **token_param,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices")
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"[LLM error: {e}]"
