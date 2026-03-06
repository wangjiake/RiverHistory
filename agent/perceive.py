"""Perception module."""

from datetime import datetime
from agent.utils.llm_client import call_llm

_PROMPTS = {
    "zh": (
        "你是一个输入分析器。分析用户的输入，输出以下5行信息。\n\n"
        "严格按以下格式，每行一个：\n"
        "纠错：如果用户输入有明显的错别字或同音字错误，输出修正后的完整句子；如果没有错误，原样输出用户的话。注意：专业术语、外语词汇、你不认识的词不要改。\n"
        "分类：knowledge 或 chat 或 personal\n"
        "意图：一句话描述用户想要什么（基于纠错后的内容）\n"
        "AI摘要：忠实复述用户纠错后的问题，只补充上下文中已有的信息使句子完整，禁止添加用户没说的内容\n"
        "话题关键词：从用户的话中提取2-5个关键词，用逗号分隔\n\n"
        "分类说明：\n"
        "- knowledge：纯知识问答，和用户个人无关（如'Python怎么读文件''片栗粉是什么'）\n"
        "- chat：闲聊寒暄，不涉及用户个人信息（如'今天好冷''你觉得呢'）\n"
        "- personal：涉及用户个人信息的任何内容\n\n"
        "personal 判断标准（宁可多判不可漏判）：\n"
        "只要句子里有'我''我们''公司''我家'等第一人称，或者提到用户自己的任何事情，就是 personal。\n"
        "拿不准的时候，选 personal。"
    ),
    "en": (
        "You are an input analyzer. Analyze the user's input and output the following 5 lines of information.\n\n"
        "Strictly follow this format, one per line:\n"
        "Correction: If the user's input contains obvious typos or homophones errors, output the corrected full sentence; if there are no errors, output the user's message as-is. Note: Do not alter technical terms, foreign words, or words you don't recognize.\n"
        "Category: knowledge or chat or personal\n"
        "Intent: A one-sentence description of what the user wants (based on the corrected content)\n"
        "AI Summary: Faithfully restate the user's corrected question, only adding context already present to make the sentence complete — do not add anything the user did not say\n"
        "Topic Keywords: Extract 2-5 keywords from the user's message, separated by commas\n\n"
        "Category definitions:\n"
        "- knowledge: Pure factual Q&A, unrelated to the user personally (e.g., 'How to read files in Python', 'What is cornstarch')\n"
        "- chat: Casual small talk, no personal information involved (e.g., 'It's so cold today', 'What do you think')\n"
        "- personal: Any content involving the user's personal information\n\n"
        "Criteria for personal (err on the side of over-classification):\n"
        "As long as the sentence contains 'I', 'we', 'my company', 'my family', or any first-person reference, or mentions anything about the user themselves, it is personal.\n"
        "When in doubt, choose personal."
    ),
    "ja": (
        "あなたは入力分析器です。ユーザーの入力を分析し、以下の5行の情報を出力してください。\n\n"
        "厳密に以下の形式で、1行ずつ出力してください：\n"
        "修正：ユーザーの入力に明らかな誤字や変換ミスがある場合、修正後の完全な文を出力してください。誤りがなければ、ユーザーの発言をそのまま出力してください。注意：専門用語、外来語、認識できない語句は変更しないでください。\n"
        "分類：knowledge または chat または personal\n"
        "意図：ユーザーが何を求めているかを一文で記述（修正後の内容に基づく）\n"
        "AI要約：修正後のユーザーの質問を忠実に復唱し、文脈にある情報のみで文を補完してください。ユーザーが述べていない内容の追加は禁止です。\n"
        "トピックキーワード：ユーザーの発言から2〜5個のキーワードを抽出し、カンマで区切って出力\n\n"
        "分類の説明：\n"
        "- knowledge：純粋な知識に関する質問で、ユーザー個人とは無関係（例：「Pythonでファイルを読むには」「片栗粉とは何か」）\n"
        "- chat：雑談・挨拶で、ユーザーの個人情報を含まない（例：「今日は寒いね」「どう思う？」）\n"
        "- personal：ユーザーの個人情報に関わるあらゆる内容\n\n"
        "personal の判断基準（見逃すよりも多めに判定すること）：\n"
        "文中に「私」「私たち」「うちの会社」「うちの家」などの一人称があるか、ユーザー自身に関することが含まれていれば personal です。\n"
        "迷った場合は personal を選んでください。"
    ),
}

_LABELS = {
    "zh": {
        "correction": ["纠错：", "纠错:"],
        "category": ["分类：", "分类:"],
        "intent": ["意图：", "意图:"],
        "summary": ["AI摘要：", "AI摘要:"],
        "keywords": ["话题关键词：", "话题关键词:"],
        "user_prefix": "用户说：",
    },
    "en": {
        "correction": ["Correction:", "Correction："],
        "category": ["Category:", "Category："],
        "intent": ["Intent:", "Intent："],
        "summary": ["AI Summary:", "AI Summary："],
        "keywords": ["Topic Keywords:", "Topic Keywords："],
        "user_prefix": "User said: ",
    },
    "ja": {
        "correction": ["修正：", "修正:"],
        "category": ["分類：", "分類:"],
        "intent": ["意図：", "意図:"],
        "summary": ["AI要約：", "AI要約:"],
        "keywords": ["トピックキーワード：", "トピックキーワード:"],
        "user_prefix": "ユーザーの発言：",
    },
}


def perceive(user_input: str, llm_config: dict, language: str = "en") -> dict:
    prompt = _PROMPTS.get(language, _PROMPTS["en"])
    labels = _LABELS.get(language, _LABELS["en"])

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"{labels['user_prefix']}{user_input}"},
    ]

    raw = call_llm(messages, llm_config).strip()
    perception_at = datetime.now()
    result = _parse_output(raw, user_input, language)
    result["perception_at"] = perception_at
    return result


def _parse_output(raw: str, user_input: str, language: str = "en") -> dict:
    labels = _LABELS.get(language, _LABELS["en"])
    result = {
        "intent": user_input,
        "category": "chat",
        "need_memory": False,
        "memory_type": "无",
        "ai_summary": user_input,
        "topic_keywords": [],
    }
    def _extract_value(line: str) -> str:
        if "：" in line:
            return line.split("：", 1)[1].strip()
        return line.split(":", 1)[1].strip() if ":" in line else line.strip()

    for line in raw.split("\n"):
        line = line.strip()
        if any(line.startswith(p) for p in labels["correction"]):
            val = _extract_value(line)
            if val:
                result["corrected_input"] = val
        elif any(line.startswith(p) for p in labels["category"]):
            val = _extract_value(line).lower()
            if val in ("knowledge", "chat", "personal"):
                result["category"] = val
        elif any(line.startswith(p) for p in labels["intent"]):
            result["intent"] = _extract_value(line)
        elif any(line.startswith(p) for p in labels["summary"]):
            result["ai_summary"] = _extract_value(line)
        elif any(line.startswith(p) for p in labels["keywords"]):
            kw_str = _extract_value(line)
            result["topic_keywords"] = [k.strip() for k in kw_str.split(",") if k.strip()]

    result["need_memory"] = result["category"] in ("chat", "personal")
    result["memory_type"] = "personal" if result["category"] == "personal" else "无"
    return result
