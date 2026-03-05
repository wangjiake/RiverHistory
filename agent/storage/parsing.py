"""History data parsing: Claude, ChatGPT, Gemini, Demo formats."""

import json
from datetime import datetime


def parse_turns(row: dict) -> list[dict]:
    source = row["source"]
    content = row["content"]
    conversation_time = row["conversation_time"]

    if isinstance(content, str):
        content = json.loads(content)

    if source == "claude":
        return _parse_claude(content, conversation_time)
    elif source == "chatgpt":
        return _parse_chatgpt(content, conversation_time)
    elif source == "gemini":
        return _parse_gemini(content, conversation_time)
    elif source == "demo":
        return _parse_demo(content, conversation_time)
    else:
        return []


def _parse_claude(content: dict, conversation_time) -> list[dict]:
    messages = content.get("chat_messages", [])
    turns = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("sender") == "human":
            user_text = ""
            for part in msg.get("content", []):
                if isinstance(part, dict) and part.get("type") == "text":
                    user_text += part.get("text", "")
                elif isinstance(part, str):
                    user_text += part

            assistant_text = ""
            if i + 1 < len(messages) and messages[i + 1].get("sender") == "assistant":
                for part in messages[i + 1].get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        assistant_text += part.get("text", "")
                    elif isinstance(part, str):
                        assistant_text += part
                i += 2
            else:
                i += 1

            if user_text.strip():
                turns.append({
                    "user_input": user_text.strip(),
                    "assistant_reply": assistant_text.strip(),
                    "timestamp": conversation_time,
                })
        else:
            i += 1
    return turns


def _parse_chatgpt(content: dict, conversation_time) -> list[dict]:
    mapping = content.get("mapping", {})

    msgs = []
    for node_id, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        author = msg.get("author", {}).get("role", "")
        parts = msg.get("content", {}).get("parts", [])
        text = ""
        for p in parts:
            if isinstance(p, str):
                text += p
        create_time = msg.get("create_time")
        if text.strip() and author in ("user", "assistant"):
            msgs.append({
                "role": author,
                "text": text.strip(),
                "create_time": create_time,
            })

    msgs.sort(key=lambda m: m["create_time"] or 0)

    turns = []
    i = 0
    while i < len(msgs):
        if msgs[i]["role"] == "user":
            user_text = msgs[i]["text"]
            ts = msgs[i]["create_time"]
            from datetime import timezone
            if ts:
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            else:
                timestamp = conversation_time

            assistant_text = ""
            if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                assistant_text = msgs[i + 1]["text"]
                i += 2
            else:
                i += 1

            turns.append({
                "user_input": user_text,
                "assistant_reply": assistant_text,
                "timestamp": timestamp,
            })
        else:
            i += 1
    return turns


def _parse_gemini(content: dict, conversation_time) -> list[dict]:
    prompt = content.get("prompt", "")
    response = content.get("response", "")

    if not prompt or not isinstance(prompt, str):
        return []

    return [{
        "user_input": prompt.strip(),
        "assistant_reply": (response or "").strip(),
        "timestamp": conversation_time,
    }]


def _parse_demo(content: dict, conversation_time) -> list[dict]:
    messages = content.get("messages", [])
    turns = []
    for msg in messages:
        if isinstance(msg, dict):
            user = msg.get("user", "").strip()
            assistant = msg.get("assistant", "").strip()
            if user:
                turns.append({
                    "user_input": user,
                    "assistant_reply": assistant,
                    "timestamp": conversation_time,
                })
    return turns
