"""LLM client."""

import requests


def call_llm(messages: list[dict], config: dict) -> str:
    api_base = config.get("api_base", "https://api.openai.com")
    model = config.get("model", "gpt-4o-mini")
    api_key = config.get("api_key", "")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 2048)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(
            f"{api_base}/v1/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM error: {e}]"
