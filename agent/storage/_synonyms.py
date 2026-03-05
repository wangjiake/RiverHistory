"""Category and subject synonym groups for fuzzy matching."""

_CATEGORY_SYNONYM_GROUPS = [
    {"位置", "居住地", "居住城市", "地点", "住址", "居住", "所在地"},
    {"职业", "职位", "工作", "岗位"},
    {"教育", "教育背景", "学历"},
    {"家乡", "籍贯", "出生地", "老家"},
    {"兴趣", "爱好", "休闲活动", "休闲", "运动", "运动与锻炼"},
    {"感情", "恋爱", "情感", "婚恋"},
    {"出生年份", "年龄", "出生年"},
    {"专业", "学科", "主修"},
    {"娱乐", "游戏"},
    {"宠物", "养宠"},
    {"技能", "技术", "编程"},
    {"身份", "个人信息"},
    {"饮食", "饮食与美食", "美食"},
]

_CAT_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _CATEGORY_SYNONYM_GROUPS:
    for _name in _group:
        _CAT_SYNONYM_MAP[_name] = _group

_SUBJECT_SYNONYM_GROUPS = [
    {"居住地", "居住城市", "当前居住地", "所在城市"},
    {"职业", "当前职位", "工作", "职位", "岗位"},
    {"学校", "大学", "毕业学校"},
    {"专业", "主修", "学科"},
    {"家乡", "老家", "出生地"},
    {"运动", "体育", "锻炼"},
    {"游戏", "电子游戏"},
    {"出生年", "出生年份"},
    {"女朋友", "女友", "对象"},
    {"男朋友", "男友"},
]

_SUBJ_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SUBJECT_SYNONYM_GROUPS:
    for _name in _group:
        _SUBJ_SYNONYM_MAP[_name] = _group


def _get_category_synonyms(category: str) -> set[str]:
    return _CAT_SYNONYM_MAP.get(category, {category})


def _get_subject_synonyms(subject: str) -> set[str]:
    return _SUBJ_SYNONYM_MAP.get(subject, {subject})
