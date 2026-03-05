"""Step 7: Trajectory summary generation."""

from datetime import datetime
from agent.utils.llm_client import call_llm
from agent.core.sleep_prompts import get_prompt, get_label
from agent.storage import load_observations, load_active_events, load_trajectory_summary
from ._parsing import _parse_json_object


def generate_trajectory_summary(current_profile: list[dict],
                                config: dict,
                                new_observations: list[dict] | None = None,
                                language: str = "zh") -> dict:
    """Step 7: 生成/更新人物轨迹总结（v14: 使用双层画像）。"""
    llm_config = config.get("llm", {})

    # 格式化画像（双层标签）
    profile_text = ""
    if current_profile:
        for p in current_profile:
            layer_tag = get_label("layer_confirmed", language) if p.get("layer") == "confirmed" else get_label("layer_suspected", language)
            profile_text += f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}\n"
    else:
        profile_text = get_label("no_profile", language)

    # 本次新观察（增量输入）
    new_obs_text = ""
    if new_observations:
        for o in new_observations:
            obs_type = o.get("type") or o.get("observation_type", "?")
            content = o.get("content", "")
            new_obs_text += f"  [{obs_type}] {content}\n"
    else:
        new_obs_text = "（本次无新观察）\n"

    # 历史观察（全量，帮助理解用户变化轨迹）
    historical_obs = load_observations(limit=80)
    hist_obs_text = ""
    if historical_obs:
        for o in historical_obs:
            time_str = o['created_at'].strftime('%Y-%m-%d') if o.get('created_at') else '?'
            hist_obs_text += f"  [{time_str}] [{o['observation_type']}] {o['content']}\n"
    else:
        hist_obs_text = "（暂无历史观察）\n"

    # 加载事件（保留，数量少）
    events = load_active_events(top_k=10)
    event_text = ""
    if events:
        for e in events:
            event_text += f"  [{e['category']}] {e['summary']}\n"
    else:
        event_text = "（暂无事件）\n"

    # 加载上一次轨迹
    prev_trajectory = load_trajectory_summary()
    prev_text = ""
    if prev_trajectory:
        prev_text = (
            f"上一次轨迹总结：\n"
            f"  阶段: {prev_trajectory['life_phase']}\n"
            f"  特征: {prev_trajectory['phase_characteristics']}\n"
            f"  方向: {prev_trajectory['trajectory_direction']}\n"
            f"  稳定性: {prev_trajectory['stability_assessment']}\n"
            f"  动向: {prev_trajectory.get('recent_momentum', '')}\n"
            f"  总结: {prev_trajectory.get('full_summary', '')}\n"
        )
    else:
        prev_text = "上一次轨迹总结：（首次生成）\n"

    user_content = (
        f"当前系统时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（今年是{datetime.now().year}年）\n\n"
        f"当前画像（活跃假设）：\n{profile_text}\n"
        f"本次新观察：\n{new_obs_text}\n"
        f"历史观察（完整时间线）：\n{hist_obs_text}\n"
        f"近期事件：\n{event_text}\n"
        f"{prev_text}"
    )
    messages = [
        {"role": "system", "content": get_prompt("trajectory_summary", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    return _parse_json_object(raw)
