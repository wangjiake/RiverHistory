"""
Multilingual prompts for sleep.py (zh / en / ja).
Each prompt is a dict keyed by language code.
"""


def get_prompt(name: str, language: str = "zh") -> str:
    """Get prompt by name and language, fallback to zh."""
    prompts = ALL_PROMPTS.get(name)
    if not prompts:
        raise KeyError(f"Unknown prompt: {name}")
    return prompts.get(language, prompts["zh"])


def get_label(name: str, language: str = "zh") -> str:
    """Get UI/format label by name and language."""
    labels = FORMAT_LABELS.get(name)
    if not labels:
        return name
    return labels.get(language, labels["zh"])


# ══════════════════════════════════════════════════════════════
# Format labels (used in _format_profile_for_llm, _format_trajectory_block, etc.)
# ══════════════════════════════════════════════════════════════

FORMAT_LABELS = {
    "no_profile": {
        "zh": "（暂无画像）\n",
        "en": "(No profile yet)\n",
        "ja": "（プロフィールなし）\n",
    },
    "no_trajectory": {
        "zh": "\n人物轨迹总结：（暂无，首次分析）\n",
        "en": "\nTrajectory summary: (None yet, first analysis)\n",
        "ja": "\n人物軌跡要約：（なし、初回分析）\n",
    },
    "trajectory_header": {
        "zh": "\n人物轨迹总结：\n",
        "en": "\nTrajectory summary:\n",
        "ja": "\n人物軌跡要約：\n",
    },
    "phase": {"zh": "  阶段: ", "en": "  Phase: ", "ja": "  段階: "},
    "characteristics": {"zh": "  特征: ", "en": "  Characteristics: ", "ja": "  特徴: "},
    "direction": {"zh": "  方向: ", "en": "  Direction: ", "ja": "  方向: "},
    "stability": {"zh": "  稳定性: ", "en": "  Stability: ", "ja": "  安定性: "},
    "anchors": {"zh": "  锚点: ", "en": "  Anchors: ", "ja": "  アンカー: "},
    "volatile": {"zh": "  易变区域: ", "en": "  Volatile areas: ", "ja": "  変動領域: "},
    "momentum": {"zh": "  近期动向: ", "en": "  Recent momentum: ", "ja": "  最近の動向: "},
    "summary": {"zh": "  总结: ", "en": "  Summary: ", "ja": "  要約: "},
    "layer_conflict": {"zh": "[矛盾中]", "en": "[Disputed]", "ja": "[矛盾中]"},
    "layer_confirmed": {"zh": "[核心]", "en": "[Confirmed]", "ja": "[確定]"},
    "layer_suspected": {"zh": "[怀疑]", "en": "[Suspected]", "ja": "[疑い]"},
    "mention_fmt": {
        "zh": "(提及{mc}次, source={src}, 开始={start}, 更新={updated}, 证据{ev}条",
        "en": "(mentioned {mc}x, source={src}, start={start}, updated={updated}, {ev} evidence",
        "ja": "(言及{mc}回, source={src}, 開始={start}, 更新={updated}, 証拠{ev}件",
    },
    "challenged_by": {
        "zh": ", 被#{sid}挑战",
        "en": ", challenged by #{sid}",
        "ja": ", #{sid}に挑戦されている",
    },
    "challenges": {
        "zh": ", 挑战#{sid}",
        "en": ", challenges #{sid}",
        "ja": ", #{sid}に挑戦中",
    },
    "closed_periods_header": {
        "zh": "\n已关闭的时间段（历史）：\n",
        "en": "\nClosed time periods (history):\n",
        "ja": "\n終了した期間（履歴）：\n",
    },
    "existing_model_header": {
        "zh": "当前已有的用户模型：\n",
        "en": "Current user model:\n",
        "ja": "現在のユーザーモデル：\n",
    },
    "no_existing_model": {
        "zh": "当前已有的用户模型：（暂无，这是首次分析）",
        "en": "Current user model: (None yet, this is the first analysis)",
        "ja": "現在のユーザーモデル：（なし、初回分析です）",
    },
    "profile_overview_header": {
        "zh": "\n用户画像（参考，帮助理解用户背景）：\n",
        "en": "\nUser profile (reference, to help understand user background):\n",
        "ja": "\nユーザープロフィール（参考、ユーザー背景の理解用）：\n",
    },
}


# ══════════════════════════════════════════════════════════════
# Prompts
# ══════════════════════════════════════════════════════════════

ALL_PROMPTS = {

# ── Step 2: Extract observations + tags ──

"extract_observations_and_tags": {

"zh": """从对话中提取所有值得记录的观察，并为对话打上检索标签。

一、观察提取
观察类型：
- statement: 用户直接陈述的事实（"我叫小明""我搬到大阪了""我辞职了"）
- question: 用户问了什么话题（反映关注点）
- reaction: 用户对某事的反应（赞同/反对/回避）
- behavior: 用户的行为模式（连续问某类问题）
- contradiction: 与已知信息明确矛盾的内容（对比下方已知信息判断）

提取原则（重要！）：
- 对话中包含用户消息和助手回复，助手回复仅作为上下文参考（帮你理解对话语境），但只提取用户本人表达的信息
- 用户提问不算 statement，只算 question
- 反问/确认句式（"我是不是...""是不是我..."）→ question，不是 statement。结合助手回复判断：如果助手否定了，说明这不是事实
- 每条用户消息可能包含多个独立事实 → 每个事实单独提取为一条观察
  例："回到北京了 重新入职出版社" → 2条观察（居住地+职业）
- 重大生活变化必须提取：搬家/换城市、换工作/辞职、分手/恋爱、养宠物
- ★ 身份信息必须提取：用户说出自己的名字（"我叫XX""我是XX""Hey I'm XX"）→ 必须提取为 statement，subject="姓名"
- 隐含的地理信号也要提取：用户问某城市的地铁/租房/水电/台风等生活问题，暗示用户可能在该城市生活 → 提取为 statement（如"用户在杭州租房"）
- 与已知信息矛盾时用 contradiction 类型；不确定是否矛盾时仍然用 statement 提取事实本身
- ★ 每条 [msg-N] 用户消息必须至少产生一条观察，不允许跳过任何一条用户消息

subject 命名规则：
- subject 必须优先复用已知画像中已有的 category 名称（如"居住城市""职位""兴趣爱好"等）
- 只有确实是全新维度时才创建新 subject 名
- 已有 category 列表：{category_list}

about 字段（最重要！区分用户本人 vs 第三方）：
- about="user" — 关于用户本人的信息（默认）
- about="他人名字或称呼" — 关于别人的信息
- 判断标准：
  "我在上海" → about="user"（用户自己）
  "同学老张在北京做室内设计" → about="老张"（同学的城市和职业，不是用户的）
  "室友去了杭州做景观设计" → about="室友"（室友的，不是用户的）
  "赵一然是景观设计师 川美毕业的" → about="赵一然"（女朋友的职业和学校）
  "她养了只金毛叫花生" → about="赵一然"（女朋友的宠物）
  "和赵一然在一起了" → about="user"（用户自己的感情状态）
  "爸妈觉得年轻多闯闯" → about="user"（内容是关于用户的决定）
- 关键：别人在哪里工作/住哪/学什么 ≠ 用户在哪里工作/住哪/学什么

{known_info_block}

二、会话标签
- 每个标签是简短的主题描述（如"React表单组件""搬家计划"）
- 纯闲聊不需要标签，最多 3 个标签
- 已有标签：{existing_tags}
- 如果是已有标签的延续，复用已有标签名

三、人际关系提取
从对话中提取用户提到的人物关系。只提取明确提到的人物，不要推测。
- name: 人物名字（没有名字写 null）
- relation: 与用户的关系（同学、室友、同事、女朋友、男朋友、父母、朋友等）
- details: 关于此人的具体信息（键值对）

输出格式：
{
  "observations": [
    {"type":"statement", "content":"用户说回到北京了", "subject":"居住地", "about":"user"},
    {"type":"statement", "content":"同学老张在北京做室内设计", "subject":"他人信息", "about":"老张"},
    {"type":"statement", "content":"和赵一然在一起了", "subject":"感情", "about":"user"}
  ],
  "tags": [{"tag": "标签名", "summary": "一句话摘要"}],
  "relationships": [
    {"name":"老张", "relation":"同学", "details":{"城市":"北京", "职业":"室内设计"}},
    {"name":"赵一然", "relation":"女朋友", "details":{"职业":"景观设计师", "学校":"川美"}}
  ]
}
没有内容返回 {"observations": [], "tags": [], "relationships": []}""",

"en": """Extract all noteworthy observations from the conversation, and generate retrieval tags.

I. Observation Extraction
Observation types:
- statement: Facts directly stated by the user ("I'm Jake" "I moved to Austin" "I quit my job")
- question: Topics the user asked about (reflects interests)
- reaction: User's reaction to something (agreement/disagreement/avoidance)
- behavior: User's behavioral patterns (repeatedly asking about certain topics)
- contradiction: Content that clearly contradicts known information (compare with known info below)

Extraction principles (important!):
- The conversation includes user messages and assistant replies. Assistant replies are only for context — only extract information expressed by the user themselves
- User questions are NOT statements, classify them as question
- Rhetorical/confirmation questions ("Am I...?" "Is it true that I...?") → question, not statement. Check assistant reply: if assistant denied it, it's not a fact
- Each user message may contain multiple independent facts → extract each as a separate observation
  Example: "Moved back to NYC and rejoined the publisher" → 2 observations (location + job)
- Major life changes MUST be extracted: moving cities, changing jobs/quitting, breakup/new relationship, getting a pet
- ★ Identity info MUST be extracted: user states their name ("I'm Jake" "My name is X" "Hey I'm X") → MUST extract as statement, subject="name"
- Implicit geographic signals should be extracted: user asking about subway/rent/utilities in a city suggests they may live there → extract as statement
- Use contradiction type when it contradicts known info; when uncertain, use statement
- ★ Every [msg-N] user message must produce at least one observation, do not skip any

subject naming rules:
- subject must reuse existing category names from the known profile (e.g. "city" "job_title" "hobby")
- Only create new subject names for genuinely new dimensions
- Existing category list: {category_list}

about field (most important! distinguish user vs third party):
- about="user" — information about the user themselves (default)
- about="person's name or title" — information about someone else
- Judgment criteria:
  "I live in SF" → about="user"
  "My buddy Mike works at Google" → about="Mike" (friend's job, not user's)
  "My roommate moved to Seattle" → about="roommate" (roommate's info, not user's)
  "Sophie is a graphic designer from RISD" → about="Sophie" (girlfriend's career and school)
  "She has a golden retriever named Peanut" → about="Sophie" (girlfriend's pet)
  "Sophie and I started dating" → about="user" (user's own relationship status)
  "My parents think I should explore more" → about="user" (about user's decision)
- Key: where others work/live/study ≠ where the user works/lives/studies

{known_info_block}

II. Session Tags
- Each tag is a brief topic description (e.g. "React form components" "moving plans")
- Pure small talk doesn't need tags, max 3 tags
- Existing tags: {existing_tags}
- If continuing an existing topic, reuse the existing tag name

III. Relationship Extraction
Extract people mentioned by the user. Only extract explicitly mentioned people, don't speculate.
- name: Person's name (write null if no name)
- relation: Relationship to user (classmate, roommate, colleague, girlfriend, boyfriend, parents, friend, etc.)
- details: Specific info about this person (key-value pairs)

Output format:
{
  "observations": [
    {"type":"statement", "content":"User moved back to NYC", "subject":"city", "about":"user"},
    {"type":"statement", "content":"Buddy Mike works at Google in Oakland", "subject":"third_party_info", "about":"Mike"},
    {"type":"statement", "content":"Started dating Sophie", "subject":"relationship", "about":"user"}
  ],
  "tags": [{"tag": "tag_name", "summary": "one-line summary"}],
  "relationships": [
    {"name":"Mike", "relation":"college friend", "details":{"city":"Oakland", "company":"Google"}},
    {"name":"Sophie", "relation":"girlfriend", "details":{"job":"graphic designer", "school":"RISD"}}
  ]
}
Return {"observations": [], "tags": [], "relationships": []} if nothing to extract""",

"ja": """会話からすべての記録すべき観察を抽出し、検索タグを付けてください。

一、観察抽出
観察タイプ：
- statement: ユーザーが直接述べた事実（「私は太郎です」「大阪に引っ越しました」「退職しました」）
- question: ユーザーが質問したトピック（関心を反映）
- reaction: 何かに対するユーザーの反応（賛同/反対/回避）
- behavior: ユーザーの行動パターン（特定の質問を繰り返す）
- contradiction: 既知情報と明確に矛盾する内容（下記の既知情報と比較して判断）

抽出原則（重要！）：
- 会話にはユーザーメッセージとアシスタントの返答が含まれます。アシスタントの返答はコンテキスト参考のみ — ユーザー本人が表現した情報のみ抽出
- ユーザーの質問は statement ではなく question
- 反語/確認形式（「私って...？」「...ですよね？」）→ question、statement ではない。アシスタントが否定した場合、事実ではない
- 各ユーザーメッセージには複数の独立した事実が含まれる場合がある → 各事実を個別の観察として抽出
  例：「東京に戻って出版社に復帰した」→ 2つの観察（居住地+職業）
- 重大なライフイベントは必ず抽出：引越し/転居、転職/退職、別れ/恋愛、ペットを飼う
- ★ 身元情報は必ず抽出：ユーザーが名前を言った（「私はXXです」「XXと申します」）→ 必ず statement として抽出、subject="名前"
- 暗黙の地理的シグナルも抽出：特定の都市の地下鉄/家賃/光熱費について質問 → その都市に住んでいる可能性を示唆
- 既知情報と矛盾する場合は contradiction タイプ；不確かな場合は statement で事実を抽出
- ★ すべての [msg-N] ユーザーメッセージは少なくとも1つの観察を生成する必要があり、スキップは不可

subject 命名規則：
- subject は既知プロフィールの既存 category 名を優先的に再利用（「居住都市」「職位」「趣味」など）
- 本当に新しい次元の場合のみ新しい subject 名を作成
- 既存 category リスト：{category_list}

about フィールド（最重要！ユーザー本人 vs 第三者を区別）：
- about="user" — ユーザー本人に関する情報（デフォルト）
- about="人物名や呼称" — 他人に関する情報
- 判断基準：
  「東京に住んでいます」→ about="user"
  「同級生の田中は大阪でデザイナーをしている」→ about="田中"（同級生の情報）
  「ルームメイトが福岡に行った」→ about="ルームメイト"
  「彼女のさくらはデザイナーで武蔵美卒」→ about="さくら"
  「さくらと付き合い始めた」→ about="user"（ユーザー自身の恋愛状態）
- キー：他人の仕事/住所/学歴 ≠ ユーザーの仕事/住所/学歴

{known_info_block}

二、セッションタグ
- 各タグは簡潔なトピック説明（例：「Reactコンポーネント」「引越し計画」）
- 雑談にはタグ不要、最大3個
- 既存タグ：{existing_tags}
- 既存トピックの続きなら既存タグ名を再利用

三、人間関係抽出
ユーザーが言及した人物関係を抽出。明確に言及された人物のみ、推測しない。
- name: 人物名（名前がなければ null）
- relation: ユーザーとの関係（同級生、ルームメイト、同僚、彼女、彼氏、両親、友人など）
- details: この人物の具体的情報（キーバリューペア）

出力形式：
{
  "observations": [
    {"type":"statement", "content":"ユーザーは東京に戻った", "subject":"居住地", "about":"user"},
    {"type":"statement", "content":"同級生の田中は大阪でデザイナー", "subject":"他者情報", "about":"田中"},
    {"type":"statement", "content":"さくらと付き合い始めた", "subject":"恋愛", "about":"user"}
  ],
  "tags": [{"tag": "タグ名", "summary": "一行要約"}],
  "relationships": [
    {"name":"田中", "relation":"同級生", "details":{"都市":"大阪", "職業":"デザイナー"}},
    {"name":"さくら", "relation":"彼女", "details":{"職業":"デザイナー", "学校":"武蔵美"}}
  ]
}
抽出するものがなければ {"observations": [], "tags": [], "relationships": []} を返す""",
},


# ── Step 3: Extract events ──

"extract_event": {

"zh": """从这段对话中提取值得记录的时间性事件。
格式：[{"category": "分类标签", "summary": "一句话摘要", "importance": 重要性, "decay_days": 过期天数, "status": "状态"}]
没有值得记录的事件返回 []

- category: 你来决定分类名（简短中文标签，如"健康""工作""出行""学习"等）
- importance: 0.0-1.0，你根据这件事对用户生活的影响程度判断
- decay_days: 你根据事件的时效性判断，这个信息多久后不再重要
- status（可选）：planning（打算做）、done（已完成）

注意：兴趣、偏好、关系人等信息不要在这里提取（由假设系统处理）。
只提取有实际意义的事件，日常闲聊和纯知识问答不需要提取。""",

"en": """Extract noteworthy time-based events from this conversation.
Format: [{"category": "category_label", "summary": "one-line summary", "importance": importance, "decay_days": expiry_days, "status": "status"}]
Return [] if no events worth recording

- category: You decide the category name (short English label, e.g. "health" "work" "travel" "study")
- importance: 0.0-1.0, judge based on impact on user's life
- decay_days: Judge based on how long the information remains relevant
- status (optional): planning (intending to do) or done (completed)

Note: Interests, preferences, and relationships should NOT be extracted here (handled by the profile system).
Only extract events with real significance. Casual chat and knowledge Q&A don't need extraction.""",

"ja": """この会話から記録すべき時間性イベントを抽出してください。
形式：[{"category": "カテゴリ", "summary": "一行要約", "importance": 重要度, "decay_days": 有効日数, "status": "状態"}]
記録すべきイベントがなければ [] を返す

- category: カテゴリ名を決定（簡潔な日本語、例：「健康」「仕事」「旅行」「学習」）
- importance: 0.0-1.0、ユーザーの生活への影響度で判断
- decay_days: 情報の時効性で判断
- status（任意）：planning（計画中）、done（完了）

注意：趣味、好み、人間関係はここで抽出しない（プロフィールシステムが処理）。
実質的な意味のあるイベントのみ抽出。雑談や知識Q&Aは不要。""",
},


# ── Step 4a: Classify observations ──

"classify_observations": {

"zh": """你会收到本次新观察和当前画像（双层：怀疑画像 + 核心画像）。
任务：对每条观察逐一分类。

分类类型：
- support: 支持某个已有画像事实（内容一致或补充说明）→ 给出 fact_id 和 reason
- contradict: 与某个已有画像事实明确矛盾（值不同）→ 给出 fact_id、new_value 和 reason
- evidence_against: 暗示某画像事实可能不再成立（如"好久没XX了"）→ 给出 fact_id 和 reason
- new: 全新的用户个人信息，没有对应画像 → 给出 reason
- irrelevant: 不包含用户个人信息（闲聊/知识问答/别人的信息）

判断规则：
- 旅行/出差去某地 ≠ 住在某地，不算矛盾居住地
- 怀旧/回忆 ≠ 当前状态（"好久没追剧了"是 evidence_against，不是 support）
- 别人的信息（闺蜜/同事/朋友的工作/城市）→ irrelevant，不要归到用户的画像上
- "好久没XX了""不XX了" → evidence_against（对应的兴趣画像）
- 用户说"搬到XX""到XX入职""回到XX了" → contradict（对应居住地/职业画像）
- 用户说"辞职了""换工作了" → contradict（对应职业画像）
- 用户说"分手了" → evidence_against（对应感情画像）
- 计划/愿望（"想去""打算学"）→ irrelevant，不创建画像
- new_value 必须是简短属性值（城市名/职位名），不是句子

出生地 vs 居住城市（重要！这是两个不同 category，不能混淆）：
- category="出生地"（"XX人""老家XX""家乡XX"）是永久锚点，搬家/换城市绝不算 contradict 出生地
- category="居住城市"（"搬到XX""在XX租房""到XX入职"）→ 如果画像有 category="居住城市" 则 contradict；如果没有则归为 new，绝不 contradict 出生地
- "职位"只存岗位名称（如"助理建筑师""设计管理"），不要存城市名

注意时间顺序：观察按会话时间排序，越新越代表当前状态。

重要：每条观察都必须输出分类结果（包括 irrelevant），不允许跳过任何一条。
输出数组长度必须等于输入观察数量。

输出JSON数组：
[
  {"obs_index": 0, "action": "support", "fact_id": 129, "reason": "再次提到北京生活"},
  {"obs_index": 1, "action": "contradict", "fact_id": 129, "new_value": "上海", "reason": "用户说到上海入职"},
  {"obs_index": 2, "action": "new", "reason": "用户提到新的兴趣跑步"},
  {"obs_index": 3, "action": "evidence_against", "fact_id": 135, "reason": "用户说好久没追剧了"},
  {"obs_index": 4, "action": "irrelevant", "reason": "闲聊内容，不含个人信息"}
]""",

"en": """You will receive new observations and the current profile (two layers: suspected + confirmed).
Task: Classify each observation one by one.

Classification types:
- support: Supports an existing profile fact (consistent or supplementary) → provide fact_id and reason
- contradict: Clearly contradicts an existing profile fact (different value) → provide fact_id, new_value, and reason
- evidence_against: Suggests a profile fact may no longer hold (e.g. "haven't done X in ages") → provide fact_id and reason
- new: Entirely new personal information with no matching profile → provide reason
- irrelevant: Contains no personal user information (small talk/knowledge Q&A/others' info)

Judgment rules:
- Traveling/business trip to a place ≠ living there, not a contradiction of residence
- Nostalgia/memories ≠ current state ("Haven't watched shows in forever" is evidence_against, not support)
- Others' info (friend/colleague's job/city) → irrelevant, do not attribute to user's profile
- "Haven't done X in ages" "Stopped doing X" → evidence_against (corresponding hobby profile)
- User says "moved to X" "started work at X" "back in X" → contradict (residence/job profile)
- User says "quit my job" "changed jobs" → contradict (job profile)
- User says "broke up" → evidence_against (relationship profile)
- Plans/wishes ("want to go" "planning to learn") → irrelevant, don't create profile
- new_value must be a brief attribute value (city name/job title), not a sentence

Hometown vs current city (important! These are two different categories, don't confuse):
- category="hometown" ("from X" "grew up in X") is a permanent anchor, moving cities NEVER contradicts hometown
- category="city" ("moved to X" "renting in X" "started work in X") → if profile has category="city" then contradict; if not then new, NEVER contradict hometown
- "job_title" only stores the role name (e.g. "software engineer" "design manager"), not city names

Note time order: Observations are sorted by session time, newer = more representative of current state.

Important: Every observation must have a classification result (including irrelevant), do not skip any.
Output array length must equal input observation count.

Output JSON array:
[
  {"obs_index": 0, "action": "support", "fact_id": 129, "reason": "Mentioned living in NYC again"},
  {"obs_index": 1, "action": "contradict", "fact_id": 129, "new_value": "Austin", "reason": "User said they moved to Austin"},
  {"obs_index": 2, "action": "new", "reason": "User mentioned new hobby: rock climbing"},
  {"obs_index": 3, "action": "evidence_against", "fact_id": 135, "reason": "User said haven't played guitar in months"},
  {"obs_index": 4, "action": "irrelevant", "reason": "Small talk, no personal info"}
]""",

"ja": """新しい観察と現在のプロフィール（二層：疑いプロフィール + 確定プロフィール）を受け取ります。
タスク：各観察を一つずつ分類してください。

分類タイプ：
- support: 既存プロフィール事実を支持（内容が一致または補足）→ fact_id と reason を提供
- contradict: 既存プロフィール事実と明確に矛盾（値が異なる）→ fact_id、new_value、reason を提供
- evidence_against: プロフィール事実がもう成立しない可能性を示唆（「最近XXしていない」）→ fact_id と reason
- new: 完全に新しい個人情報、対応するプロフィールなし → reason を提供
- irrelevant: 個人情報を含まない（雑談/知識Q&A/他人の情報）

判断ルール：
- 旅行/出張で訪問 ≠ 居住、居住地の矛盾ではない
- 懐かしい/思い出 ≠ 現在の状態（「最近ドラマ見てない」は evidence_against）
- 他人の情報（友人/同僚の仕事/都市）→ irrelevant
- 「最近XXしてない」「XXやめた」→ evidence_against
- 「XXに引っ越した」「XXで入社」→ contradict（居住地/職業）
- 「退職した」「転職した」→ contradict（職業）
- 「別れた」→ evidence_against（恋愛）
- 計画/願望（「行きたい」「学びたい」）→ irrelevant
- new_value は簡潔な属性値（都市名/職位名）、文ではない

出身地 vs 居住都市（重要！別の category）：
- category="出身地"（「XX出身」「実家はXX」）は永久アンカー、引越しは出身地の矛盾ではない
- category="居住都市"（「XXに引っ越した」「XXで賃貸」）→ 居住都市の画像があれば contradict
- 「職位」は役職名のみ（「ソフトウェアエンジニア」等）、都市名は不可

時間順序に注意：観察はセッション時間順、新しいほど現在の状態を代表。

重要：すべての観察に分類結果を出力（irrelevant 含む）、スキップ不可。
出力配列の長さ = 入力観察数。

出力JSON配列：
[
  {"obs_index": 0, "action": "support", "fact_id": 129, "reason": "再び東京の生活に言及"},
  {"obs_index": 1, "action": "contradict", "fact_id": 129, "new_value": "大阪", "reason": "大阪に引っ越したと述べた"},
  {"obs_index": 2, "action": "new", "reason": "新しい趣味のランニングに言及"},
  {"obs_index": 3, "action": "evidence_against", "fact_id": 135, "reason": "最近ドラマを見ていないと述べた"},
  {"obs_index": 4, "action": "irrelevant", "reason": "雑談、個人情報なし"}
]""",
},


# ── Step 4b: Create new hypotheses ──

"create_hypotheses": {

"zh": """你会收到一批新观察，为每条创建画像事实。

═══ 标准 category: subject 命名 ═══
{existing_categories}

{categorization_history}

═══ 规则 ═══
- value 写简短属性值（城市名/职位名/校名），不写句子
- 别人的信息不创建，计划/愿望不创建
- 年龄换算：用户说"今年22" → value="约{birth_year}年出生"
- 兴趣类：一个爱好一条记录
- decay_days：3650=身份/背景（姓名、性别、出生年、家乡、学校、专业）, 540=居住地/职业/长期爱好/宠物, 365=感情关系, 120-180=中期兴趣, 60=短期状态, 14-30=临时行为

═══ 示例 ═══
观察："北外毕业的 英语翻译专业 今年24 青岛人"
输出：
[{"category":"教育背景", "subject":"毕业院校", "value":"北京外国语大学", "source_type":"stated", "decay_days": 3650},
 {"category":"教育背景", "subject":"专业", "value":"英语翻译", "source_type":"stated", "decay_days": 3650},
 {"category":"出生年", "subject":"出生年份", "value":"约2002年出生", "source_type":"inferred", "decay_days": 3650},
 {"category":"出生地", "subject":"家乡城市", "value":"青岛", "source_type":"stated", "decay_days": 3650}]

观察："搬到杭州了 在一家外贸公司做英语翻译"
输出：
[{"category":"居住城市", "subject":"居住城市", "value":"杭州", "source_type":"stated", "decay_days": 540},
 {"category":"职业", "subject":"职位", "value":"英语翻译", "source_type":"stated", "decay_days": 540}]

没有需要创建的返回 []""",

"en": """You will receive a batch of new observations. Create a profile fact for each one.

═══ Standard category: subject naming ═══
{existing_categories}

{categorization_history}

═══ Rules ═══
- value should be a brief attribute value (city name/job title/school name), not a sentence
- Do not create facts for others' info or plans/wishes
- Age conversion: user says "I'm 22" → value="born around {birth_year}"
- Hobbies: one record per hobby
- decay_days: 3650=identity/background (name, gender, birth year, hometown, school, major), 540=residence/career/long-term hobbies/pets, 365=relationships, 120-180=medium-term interests, 60=short-term states, 14-30=temporary behaviors

═══ Examples ═══
Observation: "Went to UC Berkeley for computer science, 28 years old, from Portland"
Output:
[{"category":"education", "subject":"university", "value":"UC Berkeley", "source_type":"stated", "decay_days": 3650},
 {"category":"education", "subject":"major", "value":"computer science", "source_type":"stated", "decay_days": 3650},
 {"category":"birth_year", "subject":"birth_year", "value":"born around {birth_year}", "source_type":"inferred", "decay_days": 3650},
 {"category":"hometown", "subject":"hometown", "value":"Portland", "source_type":"stated", "decay_days": 3650}]

Observation: "Moved to Austin, working as a senior backend engineer at a SaaS company"
Output:
[{"category":"city", "subject":"city", "value":"Austin", "source_type":"stated", "decay_days": 540},
 {"category":"career", "subject":"job_title", "value":"senior backend engineer", "source_type":"stated", "decay_days": 540}]

Return [] if nothing to create""",

"ja": """新しい観察のバッチを受け取ります。各観察に対してプロフィール事実を作成してください。

═══ 標準 category: subject 命名 ═══
{existing_categories}

{categorization_history}

═══ ルール ═══
- value は簡潔な属性値（都市名/職位名/学校名）、文ではない
- 他人の情報や計画/願望は作成しない
- 年齢変換：ユーザーが「今年22歳」→ value="約{birth_year}年生まれ"
- 趣味：1つの趣味につき1レコード
- decay_days：3650=アイデンティティ/背景（名前、性別、生年、出身地、学校、専攻）、540=居住地/職業/長期趣味/ペット、365=恋愛関係、120-180=中期的趣味、60=短期状態、14-30=一時的行動

═══ 例 ═══
観察：「東大の建築学科卒業 今年25歳 京都出身」
出力：
[{"category":"学歴", "subject":"大学", "value":"東京大学", "source_type":"stated", "decay_days": 3650},
 {"category":"学歴", "subject":"専攻", "value":"建築学", "source_type":"stated", "decay_days": 3650},
 {"category":"生年", "subject":"生年", "value":"約{birth_year}年生まれ", "source_type":"inferred", "decay_days": 3650},
 {"category":"出身地", "subject":"出身都市", "value":"京都", "source_type":"stated", "decay_days": 3650}]

作成するものがなければ [] を返す""",
},


# ── Step 4c: Cross-validate contradictions ──

"cross_validate": {

"zh": """你会收到矛盾信息，包含：
1. 老值及其时间区间（从什么时候开始、到什么时候被矛盾、期间被提及多少次）
2. 新述说及其开始时间
3. 该 subject 的历史时间线（如果有）
4. 该 subject 的相关历史观察（带时间戳）

任务：基于完整时间线，判断这个矛盾是真实变化还是误判。

判断标准：
- 用户直接陈述变化（"我搬到XX了""到XX入职""辞职了"）→ 真实变化，confirm_change
- 历史观察中有多条支持新值的时间线证据 → 真实变化
- 老值持续时间长、提及次数多，新值只出现一次且无佐证 → 需要谨慎
- 只是旅行/出差提到某地 → 不是变化，reject
- 怀旧/回忆提到旧事 → 不是变化，reject
- 第三方信息混淆（说的是别人）→ 不是变化，reject

交叉验证（重要）：
- 看历史观察的时间线，新值附近是否有佐证（如提到当地天气/地标/同事）
- 老值的时间区间内是否一直稳定
- 如果有历史变迁记录，是否符合变化趋势

new_value 必须是简短属性值（城市名/职位名），不是句子。

输出JSON数组：
[{"obs_index": 0, "action": "confirm_change", "fact_id": 129, "new_value": "上海", "reason": "用户明确说搬到上海，且近期多次提到上海地标"}]
判断为假矛盾的：
[{"obs_index": 1, "action": "reject", "fact_id": 129, "reason": "只是出差提到成都，老值北京持续3个月且多次确认"}]
没有需要处理的返回 []""",

"en": """You will receive contradiction information containing:
1. Old value and its time range (when it started, when contradicted, how many times mentioned)
2. New claim and its start time
3. Timeline history for this subject (if any)
4. Related historical observations for this subject (with timestamps)

Task: Based on the complete timeline, judge whether this contradiction is a real change or a false alarm.

Judgment criteria:
- User directly states a change ("I moved to X" "started work at X" "quit") → real change, confirm_change
- Multiple timeline evidence in historical observations supports new value → real change
- Old value lasted long with many mentions, new value appeared once with no corroboration → be cautious
- Just traveling/business trip mentioning a place → not a change, reject
- Nostalgia/memories mentioning old things → not a change, reject
- Third-party info confusion (talking about someone else) → not a change, reject

Cross-validation (important):
- Check historical observation timeline: is there corroboration near the new value (e.g. mentioning local weather/landmarks/colleagues)?
- Was the old value stable throughout its time range?
- If there's a history of changes, does it fit the trend?

new_value must be a brief attribute value (city name/job title), not a sentence.

Output JSON array:
[{"obs_index": 0, "action": "confirm_change", "fact_id": 129, "new_value": "Austin", "reason": "User explicitly said moved to Austin, multiple recent mentions of Austin landmarks"}]
For false contradictions:
[{"obs_index": 1, "action": "reject", "fact_id": 129, "reason": "Just a business trip to Denver, old value SF confirmed over 3 months"}]
Return [] if nothing to process""",

"ja": """矛盾情報を受け取ります：
1. 旧値とその期間（いつから、いつ矛盾が発生、何回言及されたか）
2. 新しい主張とその開始時間
3. この subject の履歴タイムライン（ある場合）
4. この subject の関連する過去の観察（タイムスタンプ付き）

タスク：完全なタイムラインに基づき、この矛盾が本当の変化か誤判断かを判断。

判断基準：
- ユーザーが直接変化を述べた（「XXに引っ越した」「XXで入社」「退職した」）→ 本当の変化、confirm_change
- 複数のタイムライン証拠が新値を支持 → 本当の変化
- 旧値が長期間安定、新値が1回だけ → 慎重に
- 旅行/出張で言及しただけ → 変化ではない、reject
- 懐かしい思い出 → 変化ではない、reject
- 第三者情報の混同 → 変化ではない、reject

new_value は簡潔な属性値（都市名/職位名）。

出力JSON配列：
[{"obs_index": 0, "action": "confirm_change", "fact_id": 129, "new_value": "大阪", "reason": "大阪に引っ越したと明言、最近大阪の地名を複数回言及"}]
偽の矛盾：
[{"obs_index": 1, "action": "reject", "fact_id": 129, "reason": "出張で名古屋に言及しただけ"}]
処理するものがなければ [] を返す""",
},


# ── Step 4d: Generate strategies ──

"generate_strategies": {

"zh": """你会收到本轮新建或发生变更的假设。
任务：为需要验证的假设设计自然的验证策略。

策略类型：
- verify: 直接确认 — 仅在用户主动提起相关话题时
- probe: 投石问路 — 间接试探
- clarify: 澄清细节
- deepen: 深入了解

策略原则：极其自然，不能让用户感觉被试探。

只为以下情况生成策略：
- 推测得来的新假设（需要二次确认）
- 发生矛盾的假设（需要验证变化）
不需要策略的：用户直接明确陈述的事实（source_type=stated）

输出JSON数组：
[{"category": "位置", "subject": "居住地", "type": "probe", "description": "确认居住城市", "trigger": "当聊到生活或城市话题时", "approach": "可以问最近生活怎么样"}]
没有需要策略的返回 []""",

"en": """You will receive newly created or changed hypotheses this round.
Task: Design natural verification strategies for hypotheses that need validation.

Strategy types:
- verify: Direct confirmation — only when user brings up the topic
- probe: Indirect exploration — subtle probing
- clarify: Clarify details
- deepen: Learn more

Strategy principle: Must feel completely natural, user should not feel interrogated.

Only generate strategies for:
- Inferred new hypotheses (need secondary confirmation)
- Contradicted hypotheses (need to verify the change)
No strategy needed for: Facts directly stated by user (source_type=stated)

Output JSON array:
[{"category": "location", "subject": "city", "type": "probe", "description": "Confirm current city", "trigger": "When chatting about lifestyle or city topics", "approach": "Ask how life has been lately"}]
Return [] if no strategies needed""",

"ja": """今回新規作成または変更された仮説を受け取ります。
タスク：検証が必要な仮説に対して自然な検証戦略を設計。

戦略タイプ：
- verify: 直接確認 — ユーザーが関連トピックを持ち出した時のみ
- probe: 間接的探索 — さりげない確認
- clarify: 詳細の明確化
- deepen: より深く理解

戦略原則：完全に自然でなければならない。ユーザーに探られていると感じさせない。

戦略を生成するのは：
- 推測による新仮説（二次確認が必要）
- 矛盾が発生した仮説（変化の検証が必要）
戦略不要：ユーザーが直接明言した事実（source_type=stated）

出力JSON配列：
[{"category": "位置", "subject": "居住地", "type": "probe", "description": "現在の居住都市を確認", "trigger": "生活や都市の話題になった時", "approach": "最近の生活について聞く"}]
戦略不要なら [] を返す""",
},


# ── Step 5: Cross-verify suspected facts ──

"cross_verify_suspected": {

"zh": """你会收到一批处于怀疑层（suspected）的画像事实，每个事实包含证据。
任务：判断哪些怀疑画像有足够的交叉证据，可以晋升为核心画像（confirmed）。

═══ 判断标准 ═══
1. confirm — 有足够交叉证据，可以确认
2. keep — 暂无足够证据，保持怀疑状态

确认条件（confirm）：
- 用户在多个会话中重复提及同一事实（mention_count >= 2）
- 有佐证观察支持（如提到当地天气/地标/同事验证了居住地）
- 用户直接明确陈述且无矛盾（source_type=stated 且 mention_count >= 2）
- 该 subject 的旧时间段存在（说明是变化后的新值），且用户直接陈述了变化

保持怀疑（keep）：
- 只提及过1次，无佐证
- 来自推理（inferred），尚未被用户确认

重要：
- 怀疑画像默认是相信的，只是未验证
- 不需要很高的门槛，2次提及或1次明确陈述+1条佐证就够了
- 不要驳回——怀疑画像只会被矛盾关闭，不会被驳回

输出：
[{"fact_id": 123, "action": "confirm", "reason": "用户在两次对话中都提到在北京生活，且提到北京地铁"}]
没有需要处理的返回 []""",

"en": """You will receive a batch of suspected profile facts, each with evidence.
Task: Judge which suspected facts have enough cross-evidence to be promoted to confirmed.

═══ Judgment criteria ═══
1. confirm — Enough cross-evidence, can be confirmed
2. keep — Not enough evidence yet, keep as suspected

Confirmation conditions (confirm):
- User mentioned the same fact in multiple sessions (mention_count >= 2)
- Corroborating observations support it (e.g. mentioning local weather/landmarks verifies residence)
- User directly stated it clearly with no contradiction (source_type=stated and mention_count >= 2)
- An old time period exists for this subject (indicates it's a new value after a change), and user stated the change

Keep as suspected (keep):
- Only mentioned once, no corroboration
- From inference (inferred), not yet confirmed by user

Important:
- Suspected facts are trusted by default, just unverified
- The bar is not high: 2 mentions or 1 clear statement + 1 corroboration is enough
- Do not reject — suspected facts can only be closed by contradictions, not rejected

Output:
[{"fact_id": 123, "action": "confirm", "reason": "User mentioned living in Austin in two conversations, plus mentioned Austin BBQ and local climbing gym"}]
Return [] if nothing to process""",

"ja": """疑いレイヤー（suspected）のプロフィール事実のバッチを受け取ります。各事実には証拠が含まれます。
タスク：十分な交差証拠がある疑い事実を確定（confirmed）に昇格させるか判断。

═══ 判断基準 ═══
1. confirm — 十分な交差証拠あり、確定可能
2. keep — まだ証拠不足、疑い状態を維持

確定条件（confirm）：
- 複数のセッションで同じ事実に言及（mention_count >= 2）
- 裏付け観察あり（地元の天気/ランドマークへの言及で居住地を検証）
- ユーザーが直接明言し矛盾なし（source_type=stated かつ mention_count >= 2）

疑い維持（keep）：
- 1回だけの言及、裏付けなし
- 推論由来（inferred）、未確認

重要：
- 疑い事実はデフォルトで信頼される、未検証なだけ
- 高い基準は不要、2回言及または1回明言+1裏付けで十分
- 却下しない — 疑い事実は矛盾でのみ閉じられる

出力：
[{"fact_id": 123, "action": "confirm", "reason": "2回の会話で東京在住に言及、東京の地下鉄にも言及"}]
処理するものがなければ [] を返す""",
},


# ── Step 5.1: Resolve disputes ──

"resolve_dispute": {

"zh": """你会收到一批矛盾争议，每对包含：
- 旧值：当前画像中已有的值（可能是核心画像或怀疑画像）
- 新值：新观察到的矛盾值（怀疑画像）
- 触发矛盾的原文：导致产生新值的那条原始观察内容（最关键的判断依据！）
- 对话摘要：矛盾之前和之后的所有对话记录摘要（不是按关键词过滤的，是完整的对话流）
- 轨迹参考：人物轨迹中的锚点和易变区域

任务：判断每对矛盾中哪个值是正确的当前状态。

═══ 首先看触发原文 ═══
- 触发原文是产生新值的直接来源，必须最先阅读
- 如果原文说的是别人的信息（"我妹叫XX""室友在XX工作"）→ 这不是用户本人的变化，应该 reject_new
- 如果原文是关系升级而非换人（"求婚了""结婚了"）→ 不是交往对象变更，应该 reject_new
- 如果原文确实表明用户本人状态变化（"我搬到XX了""我辞职了"）→ 结合后续对话判断

═══ 判断标准 ═══
1. accept_new — 接受新值，关闭旧值
2. reject_new — 驳回新值，保留旧值
3. keep — 暂无足够证据判断，继续等待

═══ 核心原则：从完整生活场景交叉判断 ═══
- 重点看「矛盾之后的对话摘要」：不只看直接提到新旧值的对话，而是看用户整体生活场景在哪里
- 用户的工作、居住、社交、日常消费如果全在新地方 → 即使旧值提及次数多也应该 accept_new
- 旧值在矛盾之后只以回忆/怀念语境出现（"老家的桂花""想念以前"）≠ 当前状态
- 不要因为旧值是核心画像（confirmed）就偏向保留 — 人生会变化，搬家换工作很正常

接受新值（accept_new）：
- 用户直接陈述了变化（"我搬到XX了""到XX入职""辞职了"）→ 最强证据
- 矛盾之后的对话摘要显示用户生活重心已转移（工作/租房/社交/日常都在新地方）
- 该 subject 在 volatile_areas（易变区域）中

驳回新值（reject_new）：
- 触发原文说的是别人（家人/朋友/同事）的信息，被误标为用户本人的
- 触发原文是关系状态升级（交往→已婚），不是换了交往对象
- 新值来自旅行/出差提及，不是居住地变化
- 矛盾之后的对话摘要显示用户生活重心仍在旧值

继续等待（keep）：
- 矛盾之后暂无新的对话，无法判断生活场景趋势
- 但不要无限 keep —— 如果用户直接说了变化且后续生活场景吻合，应该 accept_new

输出：
[{"old_fact_id": 1, "new_fact_id": 2, "action": "accept_new", "reason": "用户明确说搬到深圳，且之后3个会话都在深圳的日常生活"}]
没有需要处理的返回 []""",

"en": """You will receive a batch of contradiction disputes, each pair contains:
- Old value: Existing value in the profile (may be confirmed or suspected)
- New value: Newly observed contradicting value (suspected)
- Trigger text: The original observation that produced the new value (most critical evidence!)
- Conversation summaries: All conversation summaries before and after the contradiction (complete conversation flow, not keyword-filtered)
- Trajectory reference: Anchors and volatile areas from the person's trajectory

Task: For each contradiction pair, judge which value is the correct current state.

═══ First read the trigger text ═══
- The trigger text is the direct source of the new value, must be read first
- If it's about someone else ("my sister is named X" "roommate works at X") → not user's change, reject_new
- If it's a relationship upgrade not a change ("got engaged" "got married") → not a partner change, reject_new
- If it genuinely shows the user's own state change ("I moved to X" "I quit") → combine with subsequent conversations

═══ Judgment criteria ═══
1. accept_new — Accept new value, close old value
2. reject_new — Reject new value, keep old value
3. keep — Not enough evidence to judge, keep waiting

═══ Core principle: Cross-judge from complete life context ═══
- Focus on "conversation summaries after the contradiction": not just mentions of old/new values, but where the user's overall life is happening
- If user's work, housing, social life, daily activities are all in the new place → accept_new even if old value was mentioned more
- Old value appearing only in nostalgia context after contradiction ("miss my old neighborhood") ≠ current state
- Don't be biased toward keeping old value just because it's confirmed — life changes, moving and job changes are normal

Accept new (accept_new):
- User directly stated the change ("I moved to X" "started at X" "quit") → strongest evidence
- Post-contradiction summaries show user's life center has shifted
- The subject is in volatile_areas

Reject new (reject_new):
- Trigger text was about others' info, mislabeled as user's
- Trigger was a relationship status upgrade, not a partner change
- New value from travel/trip mention, not residence change
- Post-contradiction summaries show user's life center remains at old value

Keep waiting (keep):
- No new conversations after the contradiction, can't judge life trend
- But don't keep forever — if user stated the change and subsequent life fits, accept_new

Output:
[{"old_fact_id": 1, "new_fact_id": 2, "action": "accept_new", "reason": "User explicitly said moved to Austin, next 3 sessions all about Austin daily life"}]
Return [] if nothing to process""",

"ja": """矛盾争議のバッチを受け取ります。各ペアには：
- 旧値：プロフィールの既存値（確定または疑い）
- 新値：新たに観察された矛盾値（疑い）
- トリガーテキスト：新値を生成した元の観察内容（最重要な判断根拠！）
- 会話要約：矛盾前後のすべての会話記録要約（完全な会話フロー）
- 軌跡参考：人物軌跡のアンカーと変動領域

タスク：各矛盾ペアで、どちらが正しい現在の状態かを判断。

═══ まずトリガーテキストを確認 ═══
- 他人の情報（「妹はXX」「ルームメイトがXXで働いている」）→ ユーザーの変化ではない、reject_new
- 関係のアップグレード（「婚約した」「結婚した」）→ 相手の変更ではない、reject_new
- ユーザー本人の状態変化（「XXに引っ越した」「退職した」）→ 後続の会話と合わせて判断

═══ 判断基準 ═══
1. accept_new — 新値を受け入れ、旧値を閉じる
2. reject_new — 新値を却下、旧値を保持
3. keep — 判断材料不足、待機継続

出力：
[{"old_fact_id": 1, "new_fact_id": 2, "action": "accept_new", "reason": "大阪に引っ越したと明言、以降3セッションすべて大阪の日常生活"}]
処理するものがなければ [] を返す""",
},


# ── Step 7: Trajectory summary ──

"trajectory_summary": {

"zh": """你是一个人物分析专家。根据用户的全部假设画像、历史观察和事件记录，
生成一份人物轨迹总结，描述这个人当前处于什么人生阶段、在经历什么、往哪个方向走。

你会收到：
1. 当前画像（所有活跃假设）
2. 所有历史观察（时间线排列）
3. 重大事件记录
4. 上一次的轨迹总结（如果有）

你的任务：理解这个人，不是理解一个个孤立的属性。

输出：
{
  "life_phase": "阶段名（如'职业探索期''创业期''成家立业期''育儿期'等）",
  "phase_characteristics": "这个阶段的特征（100字内）",
  "trajectory_direction": "这个人目前在往哪个方向走",
  "stability_assessment": "整体稳定性评估（爱好、居住地、工作、感情各自多稳定）",
  "key_anchors": ["锚点1", "锚点2"],
  "volatile_areas": ["易变区域1", "易变区域2"],
  "recent_momentum": "近期动向和势头",
  "predicted_shifts": "基于当前轨迹，预测可能发生的变化",
  "full_summary": "200字以内的完整人物轨迹总结，像写一个人物小传一样"
}

重要：
- 基于事实和观察写，不要编造
- 关注变化趋势，不只是罗列属性
- stability_assessment 要具体到每个维度（工作、居住、爱好、感情）
- key_anchors 是不太可能变的东西（家乡、学校、核心身份）
- volatile_areas 是正在变或即将变的（新爱好、新城市、新关系）
- 如果上一次有轨迹总结，在此基础上更新，不要完全重写""",

"en": """You are a character analysis expert. Based on the user's full profile, historical observations, and event records,
generate a trajectory summary describing what life phase this person is in, what they're experiencing, and where they're heading.

You will receive:
1. Current profile (all active facts)
2. All historical observations (in timeline order)
3. Major event records
4. Previous trajectory summary (if any)

Your task: Understand this person as a whole, not just isolated attributes.

Output:
{
  "life_phase": "Phase name (e.g. 'career exploration' 'startup phase' 'settling down' 'parenthood')",
  "phase_characteristics": "Characteristics of this phase (under 100 words)",
  "trajectory_direction": "Where this person is currently heading",
  "stability_assessment": "Overall stability assessment (hobbies, residence, work, relationship — how stable each is)",
  "key_anchors": ["anchor1", "anchor2"],
  "volatile_areas": ["volatile_area1", "volatile_area2"],
  "recent_momentum": "Recent developments and momentum",
  "predicted_shifts": "Based on current trajectory, predict likely changes",
  "full_summary": "Complete trajectory summary under 200 words, like writing a character sketch"
}

Important:
- Write based on facts and observations, don't fabricate
- Focus on change trends, not just listing attributes
- stability_assessment should be specific to each dimension (work, residence, hobbies, relationship)
- key_anchors are things unlikely to change (hometown, school, core identity)
- volatile_areas are things currently changing or about to change (new hobbies, new city, new relationship)
- If there's a previous trajectory summary, update it, don't rewrite from scratch""",

"ja": """あなたは人物分析の専門家です。ユーザーの全プロフィール、過去の観察、イベント記録に基づき、
この人物が現在どのライフステージにいるか、何を経験しているか、どの方向に向かっているかを要約してください。

受け取るもの：
1. 現在のプロフィール（すべてのアクティブな事実）
2. すべての過去の観察（タイムライン順）
3. 重要イベント記録
4. 前回の軌跡要約（ある場合）

タスク：個々の属性ではなく、この人物を全体として理解する。

出力：
{
  "life_phase": "段階名（例：「キャリア探索期」「起業期」「定住期」「育児期」）",
  "phase_characteristics": "この段階の特徴（100字以内）",
  "trajectory_direction": "この人物が現在向かっている方向",
  "stability_assessment": "全体的な安定性評価（趣味、居住地、仕事、恋愛それぞれ）",
  "key_anchors": ["アンカー1", "アンカー2"],
  "volatile_areas": ["変動領域1", "変動領域2"],
  "recent_momentum": "最近の動向と勢い",
  "predicted_shifts": "現在の軌跡に基づく、予測される変化",
  "full_summary": "200字以内の完全な人物軌跡要約、人物スケッチのように"
}

重要：
- 事実と観察に基づいて書く、捏造しない
- 変化のトレンドに注目、属性の羅列ではない
- key_anchors は変わりにくいもの（出身地、学校、コアアイデンティティ）
- volatile_areas は変化中または変化しそうなもの
- 前回の軌跡要約がある場合、それを更新する""",
},


# ── Step 6: Analyze user communication model ──

"analyze_user_model": {

"zh": """根据对话历史，分析用户的沟通特征。

你还会收到当前已有的用户模型（如果有的话），请在已有基础上更新，不要完全覆盖。
新的对话只是补充证据，不应该让一两次对话就推翻长期积累的判断。

维度（不限于此）：
- communication_style: 直接/委婉/幽默/正式
- knowledge_areas: 用户最擅长/最常讨论的领域
- sensitivity: 哪些话题敏感
- trust_level: 对AI的信任程度
- personality_hints: 性格线索

重要：
- knowledge_areas 应该反映用户最频繁讨论的领域，不是最近一次聊的话题
- 只输出有明确证据支持的维度

{existing_model_block}

输出：[{"dimension": "...", "assessment": "...", "evidence": "..."}]
没有可分析的返回 []""",

"en": """Based on conversation history, analyze the user's communication characteristics.

You will also receive the current user model (if any). Update it based on existing data, don't completely overwrite.
New conversations are supplementary evidence; one or two conversations should not overturn long-accumulated judgments.

Dimensions (not limited to these):
- communication_style: direct/indirect/humorous/formal
- knowledge_areas: Topics the user is most knowledgeable about or discusses most frequently
- sensitivity: Which topics are sensitive
- trust_level: Level of trust in AI
- personality_hints: Personality clues

Important:
- knowledge_areas should reflect the user's most frequently discussed areas, not just the latest conversation topic
- Only output dimensions with clear evidence

{existing_model_block}

Output: [{"dimension": "...", "assessment": "...", "evidence": "..."}]
Return [] if nothing to analyze""",

"ja": """会話履歴に基づき、ユーザーのコミュニケーション特性を分析してください。

現在のユーザーモデル（ある場合）も受け取ります。既存データに基づいて更新し、完全に上書きしないでください。
新しい会話は補足証拠であり、1-2回の会話で長期的な判断を覆すべきではありません。

次元（これに限定されない）：
- communication_style: 直接的/間接的/ユーモラス/フォーマル
- knowledge_areas: ユーザーが最も得意/最も頻繁に議論する分野
- sensitivity: どのトピックがセンシティブか
- trust_level: AIへの信頼度
- personality_hints: 性格の手がかり

重要：
- knowledge_areas はユーザーが最も頻繁に議論する分野を反映すべき
- 明確な証拠がある次元のみ出力

{existing_model_block}

出力：[{"dimension": "...", "assessment": "...", "evidence": "..."}]
分析するものがなければ [] を返す""",
},


# ── Step 3.5: Behavioral pattern analysis ──

"behavioral_pattern": {

"zh": """你会收到近期观察记录和用户当前画像（活跃假设）。
任务：发现跨观察的隐含行为模式。不是分析单条观察，而是看多条观察组合在一起暗示了什么。

重点关注这些模式：
1. 地理集中：多条观察涉及同一城市的地标/天气/交通/生活/水电 → 可能搬迁
   例：问了B城水电气 + 在B商场吃饭 + B的地铁好挤 → 可能住在B
2. 兴趣萌芽：连续多次提到某个新活动且有参与行为 → 可能是新爱好
   例：报了冲浪课 + 周末去冲浪 + 被浪拍 → 冲浪是新爱好
3. 关系信号：反复提到同一人 + 正面情感/亲密行为 → 可能是新感情关系
   例：和XX一起去看电影 + XX来我家 + XX教我做饭 → XX可能是对象
4. 职业转变：工作内容/环境/同事描述系统性变化 → 可能换工作
   例：节奏比以前快 + 协调甲方和设计院 + 做高端住宅 → 工作内容变了

规则：
- 只输出与当前画像矛盾或补充画像空白的模式，画像已有且一致的不输出
- 至少3条观察指向同一推论才算模式，单条不算
- evidence_count 填写支持该推论的观察条数

输出：
[{"pattern_type": "地理集中", "category": "位置", "subject": "居住地", "inferred_value": "深圳", "evidence_count": 3, "evidence_summary": "近3个会话提到深圳的西涌、南山、大梅沙"}]
没有发现模式返回 []""",

"en": """You will receive recent observation records and the user's current profile (active facts).
Task: Discover implicit behavioral patterns across observations. Don't analyze individual observations — look at what multiple observations together imply.

Focus on these patterns:
1. Geographic concentration: Multiple observations involving the same city's landmarks/weather/transit/daily life → possible relocation
   Example: Asked about Austin utilities + ate at Austin restaurant + Austin traffic → possibly living in Austin
2. Interest emergence: Repeatedly mentioning a new activity with participation → possible new hobby
   Example: Signed up for surfing lessons + went surfing on weekend + got wiped out → surfing is a new hobby
3. Relationship signals: Repeatedly mentioning the same person + positive emotions/intimate behavior → possible new relationship
   Example: Went climbing with Sophie + Sophie came over + Sophie taught me to cook → Sophie might be partner
4. Career shift: Systematic changes in work content/environment/colleagues → possible job change
   Example: Faster pace than before + coordinating with clients and firms + luxury residential projects → work content changed

Rules:
- Only output patterns that contradict or fill gaps in current profile; skip if profile already covers it consistently
- At least 3 observations pointing to the same inference counts as a pattern; single observations don't count
- evidence_count = number of observations supporting the inference

Output:
[{"pattern_type": "geographic_concentration", "category": "location", "subject": "city", "inferred_value": "Austin", "evidence_count": 3, "evidence_summary": "Last 3 sessions mentioned Austin BBQ, East Austin, and Austin Bouldering Project"}]
Return [] if no patterns found""",

"ja": """最近の観察記録とユーザーの現在のプロフィール（アクティブな事実）を受け取ります。
タスク：観察を横断する暗黙の行動パターンを発見。個々の観察ではなく、複数の観察が組み合わさって何を示唆するかを見る。

注目パターン：
1. 地理的集中：複数の観察が同じ都市のランドマーク/天気/交通/生活に関連 → 転居の可能性
2. 趣味の萌芽：新しい活動に繰り返し言及＋参加行動 → 新しい趣味の可能性
3. 関係シグナル：同じ人物に繰り返し言及＋ポジティブな感情/親密な行動 → 新しい恋愛関係の可能性
4. キャリア転換：仕事内容/環境/同僚の体系的変化 → 転職の可能性

ルール：
- 現在のプロフィールと矛盾または空白を補完するパターンのみ出力
- 少なくとも3つの観察が同じ推論を指す場合のみパターン
- evidence_count = 推論を支持する観察数

出力：
[{"pattern_type": "地理的集中", "category": "位置", "subject": "居住地", "inferred_value": "大阪", "evidence_count": 3, "evidence_summary": "最近3セッションで大阪の地名を言及"}]
パターンが見つからなければ [] を返す""",
},


# ── Step 4.5: Sweep uncovered observations ──

"sweep_uncovered": {

"zh": """你会收到：
1. 一批 statement/contradiction 类观察（用户亲口说的事实或与已知信息矛盾的内容）
2. 当前所有画像事实（含 ID、category、subject、value、layer）

═══ value 值格式（最重要！必须遵守！）═══
value 必须是简短的属性值，不是观察描述句子。
✅ 正确：value="深圳", value="助理建筑师", value="同济大学", value="苏州"
❌ 错误：value="用户搬到了深圳", value="用户叫赵一鸣", value="在设计院做助理建筑师"

═══ category + subject 命名规则（重要！）═══
- 必须复用已有画像中的 category 和 subject 名称
- 已有画像列表中标注了 [id=X] [category] subject，请严格使用这些名称
- 如果是全新维度（没有已有画像匹配），使用简短中文名（2-4个字）

任务：找出哪些观察没有被任何画像覆盖，为它们创建画像。

判断"已覆盖"的标准（宽泛匹配！）：
- 已有画像的 subject 语义上对应到该观察（"居住城市"覆盖"用户搬到杭州"） → 已覆盖
- 但如果已有画像 value 和观察内容矛盾（画像是深圳，观察说杭州）→ 需要更新！
  此时不创建新画像，而是输出 contradictions 格式：{"fact_id": X, "new_value": "杭州", "reason": "..."}
- 没有任何画像对应 → 未覆盖，创建新画像

区分用户本人 vs 第三方（重要！）：
- 只为用户本人的信息创建画像
- 朋友/同事/家人/伴侣的信息不创建画像
- 感情对象本身作为画像（category="感情", subject="女朋友", value="名字"）

注意：
- 旅行/出差 ≠ 居住地
- 计划/愿望 ≠ 事实，不要为计划创建画像
- 用户亲口说的 source_type="stated"，推理的用 "inferred"
- 年龄不要存静态数字：用户说"今年22" → subject="出生年", value="约XXXX年出生"

decay_days（过期天数，必填）：
- 3650：核心身份（姓名、性别、出生年、生日）和背景（家乡、学校、专业）
- 540：生活状态（居住地、职业、公司）和长期爱好/宠物
- 365：感情关系（男女朋友、婚姻状态）
- 120-180：中期爱好/兴趣
- 60：短期状态
- 14-30：临时行为/一次性活动

输出格式：
{
  "new_facts": [{"category":"感情", "subject":"女朋友", "value":"林小晴", "source_type":"stated", "decay_days": 365}],
  "contradictions": [{"fact_id": 129, "category": "居住地", "subject": "居住城市", "new_value": "杭州", "reason": "用户明确说搬到杭州了"}]
}
如果没有未覆盖的，返回 {"new_facts": [], "contradictions": []}""",

"en": """You will receive:
1. A batch of statement/contradiction observations (facts stated by the user or content contradicting known info)
2. All current profile facts (with ID, category, subject, value, layer)

═══ value format (most important! must follow!) ═══
value must be a brief attribute value, not a descriptive sentence.
✅ Correct: value="Austin", value="software engineer", value="UC Berkeley", value="Portland"
❌ Wrong: value="User moved to Austin", value="User's name is Jake", value="Works as a software engineer at a startup"

═══ category + subject naming rules (important!) ═══
- Must reuse category and subject names from existing profile
- Existing profile entries are marked with [id=X] [category] subject — use these names strictly
- For genuinely new dimensions (no existing match), use short English names (1-3 words)

Task: Find which observations are not covered by any profile fact, and create profiles for them.

"Already covered" criteria (broad matching!):
- Existing profile's subject semantically matches the observation ("city" covers "user moved to Austin") → covered
- But if existing profile value contradicts observation (profile says SF, observation says Austin) → needs update!
  Don't create new profile, output as contradiction: {"fact_id": X, "new_value": "Austin", "reason": "..."}
- No profile matches → uncovered, create new profile

Distinguish user vs third party (important!):
- Only create profiles for user's own information
- Friends/colleagues/family/partner's info should not become profiles
- Romantic partner themselves as profile (category="relationship", subject="girlfriend", value="name")

Notes:
- Travel/business trip ≠ residence
- Plans/wishes ≠ facts, don't create profiles for plans
- User's own words → source_type="stated", inferred → "inferred"
- Don't store age as static number: user says "I'm 22" → subject="birth_year", value="born around XXXX"

decay_days (expiry days, required):
- 3650: Core identity (name, gender, birth year, birthday) and background (hometown, school, major)
- 540: Life status (residence, career, company) and long-term hobbies/pets
- 365: Relationships (partner, marital status)
- 120-180: Medium-term hobbies/interests
- 60: Short-term states
- 14-30: Temporary behaviors/one-time activities

Output format:
{
  "new_facts": [{"category":"relationship", "subject":"girlfriend", "value":"Sophie", "source_type":"stated", "decay_days": 365}],
  "contradictions": [{"fact_id": 129, "category": "location", "subject": "city", "new_value": "Austin", "reason": "User explicitly said moved to Austin"}]
}
Return {"new_facts": [], "contradictions": []} if nothing uncovered""",

"ja": """受け取るもの：
1. statement/contradiction タイプの観察バッチ（ユーザーが直接述べた事実または既知情報との矛盾）
2. 現在のすべてのプロフィール事実（ID、category、subject、value、layer 付き）

═══ value 形式（最重要！必ず守る！）═══
value は簡潔な属性値、説明文ではない。
✅ 正：value="大阪", value="ソフトウェアエンジニア", value="東京大学", value="京都"
❌ 誤：value="ユーザーは大阪に引っ越した", value="設計事務所でアシスタント"

═══ category + subject 命名規則（重要！）═══
- 既存プロフィールの category と subject 名を再利用すること
- 新次元の場合、簡潔な日本語名（2-4文字）

タスク：どの観察がプロフィールでカバーされていないか見つけ、新規作成。

「カバー済み」の判断（広いマッチング）：
- 既存プロフィールの subject が観察に意味的に対応 → カバー済み
- 但し value が矛盾する場合 → 更新必要、contradictions で出力
- 対応するプロフィールなし → 未カバー、新規作成

ユーザー本人 vs 第三者の区別（重要！）：
- ユーザー本人の情報のみプロフィール作成
- 友人/同僚/家族の情報は作成しない

decay_days（有効日数、必須）：
- 3650：コアアイデンティティと背景
- 540：生活状態と長期趣味/ペット
- 365：恋愛関係
- 120-180：中期的趣味
- 60：短期状態
- 14-30：一時的行動

出力形式：
{
  "new_facts": [{"category":"恋愛", "subject":"彼女", "value":"さくら", "source_type":"stated", "decay_days": 365}],
  "contradictions": [{"fact_id": 129, "category": "位置", "subject": "居住都市", "new_value": "大阪", "reason": "大阪に引っ越したと明言"}]
}
未カバーがなければ {"new_facts": [], "contradictions": []} を返す""",
},

}  # end ALL_PROMPTS
