"""Category and subject synonym groups for fuzzy matching."""

_CATEGORY_SYNONYM_GROUPS = [
    {"位置", "居住地", "居住城市", "地点", "住址", "居住", "所在地",
     "location", "residence",
     "場所", "住所", "所在地"},
    {"职业", "职位", "工作", "岗位",
     "career", "work", "job", "occupation", "profession",
     "仕事", "職業", "職位", "キャリア"},
    {"教育", "教育背景", "学历",
     "education", "academic background",
     "教育背景", "学歴"},
    {"家乡", "籍贯", "出生地", "老家",
     "hometown", "birthplace", "home town",
     "故郷", "出身地", "地元"},
    {"兴趣", "爱好", "休闲活动", "休闲", "运动", "运动与锻炼",
     "hobby", "interest", "sports", "hobbies", "interests",
     "趣味", "興味", "スポーツ"},
    {"感情", "恋爱", "情感", "婚恋",
     "relationship", "romance", "love",
     "恋愛", "感情", "恋愛関係"},
    {"出生年份", "年龄", "出生年",
     "age", "birth_year", "birth year",
     "年齢", "生まれ年", "誕生年"},
    {"专业", "学科", "主修",
     "major", "subject", "field of study",
     "専攻", "学科", "専門"},
    {"娱乐", "游戏",
     "entertainment", "gaming", "games",
     "娯楽", "ゲーム", "エンタメ"},
    {"宠物", "养宠",
     "pet", "pets",
     "ペット", "飼育"},
    {"技能", "技术", "编程",
     "skills", "tech", "programming", "technology",
     "スキル", "技術", "プログラミング"},
    {"身份", "个人信息",
     "identity", "personal_info", "personal info",
     "身元", "個人情報", "アイデンティティ"},
    {"饮食", "饮食与美食", "美食",
     "diet", "food", "cuisine",
     "食事", "食べ物", "グルメ", "料理"},
    {"家庭", "家人",
     "family",
     "家族", "家庭"},
    {"健康",
     "health",
     "健康状態"},
    {"健身",
     "fitness",
     "フィットネス", "筋トレ"},
    {"旅行", "出行",
     "travel", "traveling",
     "旅行", "旅"},
]

_CAT_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _CATEGORY_SYNONYM_GROUPS:
    for _name in _group:
        _CAT_SYNONYM_MAP[_name] = _group

_SUBJECT_SYNONYM_GROUPS = [
    {"居住地", "居住城市", "当前居住地", "所在城市",
     "residence", "current city", "city of residence", "living city",
     "居住都市", "現在の居住地", "住んでいる都市"},
    {"职业", "当前职位", "工作", "职位", "岗位",
     "career", "current position", "job", "occupation", "work",
     "職業", "現在の職位", "仕事", "職位"},
    {"学校", "大学", "毕业学校",
     "school", "university", "college", "alma mater",
     "学校", "大学", "卒業校"},
    {"专业", "主修", "学科",
     "major", "field of study", "subject",
     "専攻", "専門", "学科"},
    {"家乡", "老家", "出生地",
     "hometown", "birthplace", "home town",
     "故郷", "実家", "出身地"},
    {"运动", "体育", "锻炼",
     "sports", "exercise", "workout", "athletics",
     "スポーツ", "運動", "エクササイズ"},
    {"游戏", "电子游戏",
     "games", "video games", "gaming",
     "ゲーム", "ビデオゲーム", "テレビゲーム"},
    {"出生年", "出生年份",
     "birth year", "year of birth", "birth_year",
     "生まれ年", "誕生年"},
    {"女朋友", "女友", "对象",
     "girlfriend", "partner", "significant other",
     "彼女", "恋人", "パートナー"},
    {"男朋友", "男友",
     "boyfriend",
     "彼氏"},
]

_SUBJ_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SUBJECT_SYNONYM_GROUPS:
    for _name in _group:
        _SUBJ_SYNONYM_MAP[_name] = _group


def _get_category_synonyms(category: str) -> set[str]:
    return _CAT_SYNONYM_MAP.get(category, {category})


def _get_subject_synonyms(subject: str) -> set[str]:
    return _SUBJ_SYNONYM_MAP.get(subject, {subject})
