"""睡觉脚本 — 离线批量处理当天的对话（v15 — 矛盾处理重构）。

v15 核心变化（相对 v14）：
  - Step 4c 不再用 LLM 当场判断矛盾，只做基本过滤后直接创建 dispute pair
  - 真正的判断交给 dispute resolution（Step 5.1），它能看到跨会话积累的证据
  - dispute resolution 给 LLM 精确的时间线：矛盾创建时间 + 之前的观察 + 之后的观察
  - 时间趋势比提及次数更重要

工作流程：
  0. 预加载：画像、轨迹（贯穿全流程的全局上下文）
  1. 读取未处理对话
  Per-session:
    2. 提取观察 + 标签（合并，1次LLM）→ observations + session_tags
    3. 提取事件 → event_log
  Global:
    3.5 行为模式分析（跨观察聚合推理）
    4. 画像更新 + 策略生成（合并，带时间标记 + 轨迹）→ user_profile + strategies
      4c: 矛盾标记（基本过滤后直接创建 dispute pair，不用 LLM）
    5. 交叉验证（suspected facts with corroborating evidence → confirmed）
    5.1 矛盾争议解决（精确时间线 + LLM 判断）
    5.5 过期处理（过期事实 → close_time_period）
    5.7 成熟度演进
    6. 分析用户模型 → user_model
    7. 更新轨迹总结（条件触发）
    8. 标记已处理

可手动调用：python3 -m agent.sleep
"""

import logging
from datetime import datetime, timedelta
from agent.config import load_config
from agent.storage import (
    get_db_connection,
    save_event, save_session_tag,
    save_observation, update_observation_classification,
    load_full_current_profile, load_timeline,
    save_profile_fact, close_time_period, confirm_profile_fact,
    add_evidence, find_current_fact,
    load_suspected_profile,
    load_trajectory_summary,
    get_expired_facts, update_fact_decay,
    load_disputed_facts, resolve_dispute,
    upsert_user_model, load_user_model,
    save_strategy,
    save_trajectory_summary,
    load_active_events,
    save_or_update_relationship, load_relationships,
    save_memory_snapshot,
    delete_fact_edges_for,
)
from agent.utils.profile_filter import prepare_profile, format_profile_text
from .extractors import (
    extract_observations_and_tags, extract_events,
    classify_observations, create_new_facts,
)
from .analysis import (
    generate_strategies, analyze_user_model,
    analyze_behavioral_patterns, cross_verify_suspected_facts,
)
from .disputes import resolve_disputes_with_llm
from .trajectory import generate_trajectory_summary
from ._data_access import get_unprocessed_conversations, mark_processed, _consolidate_profile
from ._maturity import _calculate_maturity_decay

logger = logging.getLogger(__name__)


def run(fallback_time=None):
    config = load_config()
    language = config.get("language", "en")

    print("  [sleep] start")

    # Step 1: 读取未处理的对话
    session_convs = get_unprocessed_conversations()
    if not session_convs:
        print("  [sleep] no new conversations, skip")
        return

    total_msgs = sum(len(msgs) for msgs in session_convs.values())
    print(f"  [sleep] {total_msgs} conversations, {len(session_convs)} sessions")

    _pipeline_errors = 0
    all_msg_ids = []
    all_convs = []
    all_observations = []

    # 预加载已有画像（v14: user_profile）
    existing_profile = load_full_current_profile(exclude_superseded=True)

    # Step 0: 预加载轨迹
    trajectory = load_trajectory_summary()
    if trajectory and trajectory.get("life_phase"):
        print(f"  [sleep] trajectory loaded")
    else:
        print("  [sleep] no trajectory yet")
        trajectory = None

    total_session_count = len(session_convs)
    for session_idx, (session_id, convs) in enumerate(session_convs.items(), 1):
        print(f"  [sleep] session {session_idx}/{total_session_count}")
        msg_ids = [c["id"] for c in convs]
        all_msg_ids.extend(msg_ids)
        all_convs.extend(convs)

        # Step 2: 提取观察 + 标签 + 人际关系
        result = extract_observations_and_tags(convs, config,
                                               existing_profile=existing_profile,
                                               language=language)
        observations_raw = result.get("observations", [])
        tags = result.get("tags", [])
        relationships = result.get("relationships", [])

        # 按 about 字段分流：user 观察 vs 第三方观察
        observations = []      # 用户本人的观察 → 进入假设管道
        third_party_obs = []   # 第三方观察 → 仅记录，不进假设管道
        for o in observations_raw:
            about = o.get("about", "user")
            if about == "user" or about == "" or about is None or about == "null":
                observations.append(o)
            else:
                third_party_obs.append(o)

        # 给每条用户观察打上会话时间戳
        conv_times = [c["user_input_at"] for c in convs if c.get("user_input_at")]
        session_time = min(conv_times) if conv_times else None
        for o in observations:
            o["_session_order"] = session_idx
            o["_session_total"] = total_session_count
            o["_conv_time"] = session_time

        user_count = len(observations)
        tp_count = len(third_party_obs)
        print(f"  [sleep] extracted {user_count + tp_count} observations, {len(tags)} tags")

        # 保存用户观察
        for o in observations:
            obs_id = save_observation(
                session_id=session_id,
                observation_type=o["type"],
                content=o["content"],
                subject=o.get("subject"),
                context=o.get("context"),
                reference_time=session_time,
            )
            o["_db_id"] = obs_id

        # 保存第三方观察（仍然存 observations 表，但不进入假设管道）
        for o in third_party_obs:
            obs_id = save_observation(
                session_id=session_id,
                observation_type=o["type"],
                content=o["content"],
                subject=o.get("subject"),
                context=f"about:{o.get('about', '?')}",
                reference_time=session_time,
            )
            o["_db_id"] = obs_id

        # 只有用户观察进入后续假设管道
        all_observations.extend(observations)

        # 保存人际关系
        for r in relationships:
            name = r.get("name")
            relation = r.get("relation", "")
            details = r.get("details", {})
            if relation:
                save_or_update_relationship(name, relation, details,
                                            reference_time=session_time)

        for t in tags:
            save_session_tag(session_id, t["tag"], t.get("summary", ""),
                           reference_time=session_time)

        # Step 3: 提取事件 → event_log
        events = extract_events(convs, config, language=language)
        print(f"  [sleep] extracted {len(events)} events")
        for e in events:
            decay_days = e.get("decay_days")
            importance = e.get("importance")
            save_event(e["category"], e["summary"], session_id,
                       importance=importance, decay_days=decay_days,
                       reference_time=session_time)

    # Step 3.5: 行为模式分析
    behavioral_signals = []
    if all_observations and len(all_observations) >= 1:
        print("  [sleep] analyzing behavioral patterns...")
        current_profile = load_full_current_profile(exclude_superseded=True)
        behavioral_signals = analyze_behavioral_patterns(
            all_observations, current_profile, trajectory, config,
            language=language
        )
        if behavioral_signals:
            # 计算最早的会话时间（用于 start_time）
            _obs_times = [o.get("_conv_time") for o in all_observations if o.get("_conv_time")]
            _earliest_time = min(_obs_times) if _obs_times else None

            for bs in behavioral_signals:
                pattern_type = bs.get('pattern_type', '?')
                cat = bs.get('category', '')
                subj = bs.get('subject', '')
                inferred = bs.get('inferred_value', '')
                conf = bs.get('confidence', 0)
                ev_count = bs.get("evidence_count", 0)

                # 行为模式直接创建 suspected 画像事实（inferred 来源）
                # 只要检测到模式就创建，裁决交给后续 Step 5/5.1
                if cat and subj and inferred:
                    # 检查是否已有同 category+subject 的事实（避免重复创建）
                    existing = find_current_fact(cat, subj)
                    if existing and existing.get("value", "").strip().lower() == inferred.strip().lower():
                        pass
                    else:
                        fact_id = save_profile_fact(
                            category=cat,
                            subject=subj,
                            value=inferred,
                            source_type="inferred",
                            start_time=_earliest_time,
                        )

                # 证据足够时额外生成 clarify 策略
                if ev_count >= 3:
                    try:
                        save_strategy(
                            hypothesis_category=cat,
                            hypothesis_subject=subj,
                            strategy_type="clarify",
                            description=f"行为模式暗示{subj}可能是{inferred}",
                            trigger_condition=f"用户提到{subj}相关话题时",
                            approach=f"自然地确认：你是不是{inferred}？",
                            reference_time=_earliest_time,
                        )
                    except Exception:
                        _pipeline_errors += 1
                        logger.error("Save clarify strategy failed", exc_info=True)

    # ═══ Step 4: 分步画像更新（v14 拆分版）═══
    print("  [sleep] classifying observations...")
    current_profile = load_full_current_profile(exclude_superseded=True)
    timeline = load_timeline()

    # 辅助：按 fact_id 查找画像
    def _find_fact(fid) -> dict | None:
        if not fid:
            return None
        for p in current_profile:
            if p.get("id") == fid:
                return p
        return None

    # 计算最晚对话时间（用于非观察直接关联的操作，如争议解决、过期处理）
    _all_conv_times = [o["_conv_time"] for o in all_observations if o.get("_conv_time")]
    latest_conv_time = max(_all_conv_times) if _all_conv_times else fallback_time

    # 预计算 obs_query 供各步骤使用
    obs_query = " ".join(o.get("subject", "") for o in all_observations if o.get("subject"))

    # 初始化变更计数（在 if 块外，供后续使用）
    changed_items = []
    new_fact_count = 0
    contradict_count = 0
    affected_fact_ids = set()  # 增量 cross_verify / resolve_disputes 用

    if all_observations:
        # Step 4a: 动态范围选择 classify_observations 的 profile
        obs_subjects = set(o.get("subject", "") for o in all_observations if o.get("subject"))
        has_contradictions = any(o.get("type") == "contradiction" for o in all_observations)

        if has_contradictions:
            # 有直接矛盾 → 全量
            classify_profile = current_profile
        elif len(obs_subjects) <= 3:
            # 窄话题 → 相关 category + 最近 3 个月
            three_months_ago = datetime.now() - timedelta(days=90)
            obs_categories = set()
            for o in all_observations:
                if o.get("subject"):
                    obs_categories.add(o.get("subject", ""))
            classify_profile = [
                p for p in current_profile
                if p.get("subject") in obs_subjects
                or p.get("category") in obs_categories
                or (p.get("updated_at") and p["updated_at"].replace(tzinfo=None) >= three_months_ago)
            ]
            if not classify_profile:
                classify_profile = current_profile
        else:
            # 宽话题 → fallback 排序 top 80
            classify_profile, _ = prepare_profile(
                current_profile, query_text=obs_query, max_entries=80, language=language
            )

        classifications = classify_observations(
            all_observations, classify_profile, config, timeline,
            trajectory=trajectory, language=language
        )

        # 校验：检查是否所有观察都被分类
        classified_indices = {c.get("obs_index") for c in classifications if c.get("obs_index") is not None}
        all_indices = set(range(len(all_observations)))
        missing_indices = all_indices - classified_indices
        if missing_indices:
            print(f"  [sleep] warning: {len(missing_indices)} unclassified observations")
            # 漏掉的 statement/contradiction 自动补为 new，其他补为 irrelevant
            for idx in missing_indices:
                obs = all_observations[idx]
                if obs.get("type") in ("statement", "contradiction"):
                    classifications.append({"obs_index": idx, "action": "new",
                                            "reason": "4a漏分类，自动补为new"})
                else:
                    pass

        # 按 action 分组
        supports = [c for c in classifications if c.get("action") == "support"]
        contradictions = [c for c in classifications if c.get("action") == "contradict"]
        evidence_against_list = [c for c in classifications if c.get("action") == "evidence_against"]
        new_obs_cls = [c for c in classifications if c.get("action") == "new"]
        irrelevant_cls = [c for c in classifications if c.get("action") == "irrelevant"]

        # 回写分类结果到 observations 表
        for c in classifications:
            obs_idx = c.get("obs_index")
            action = c.get("action", "")
            if isinstance(obs_idx, int) and 0 <= obs_idx < len(all_observations):
                db_id = all_observations[obs_idx].get("_db_id")
                if db_id:
                    update_observation_classification(db_id, action)

        print(f"  [sleep] classified: {len(supports)} support, {len(contradictions)} contradict, {len(new_obs_cls)} new")

        # 收集本轮受影响的 fact_id（供增量 cross_verify / resolve_disputes）
        for s in supports:
            fid = s.get("fact_id")
            if fid:
                affected_fact_ids.add(fid)
        for c in contradictions:
            fid = c.get("fact_id")
            if fid:
                affected_fact_ids.add(fid)
        for ea in evidence_against_list:
            fid = ea.get("fact_id")
            if fid:
                affected_fact_ids.add(fid)

        # 处理 support → 追加证据 + mention_count
        for s in supports:
            fact = _find_fact(s.get("fact_id"))
            if fact:
                # v20: 先计算 obs_time，传给 add_evidence 和 save_profile_fact
                _obs_idx = s.get("obs_index")
                _obs_time = all_observations[_obs_idx].get("_conv_time") if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else latest_conv_time
                add_evidence(fact["id"], {"reason": s.get("reason", "")},
                             reference_time=_obs_time)
                # 同值重复提及走 save_profile_fact 触发 mention_count++
                save_profile_fact(
                    category=fact["category"],
                    subject=fact["subject"],
                    value=fact["value"],
                    source_type=fact.get("source_type", "stated"),
                    decay_days=fact.get("decay_days"),
                    start_time=_obs_time,
                )
                pass

        # 处理 evidence_against → 追加反面证据
        for ea in evidence_against_list:
            fact = _find_fact(ea.get("fact_id"))
            if fact:
                _ea_idx = ea.get("obs_index")
                _ea_time = all_observations[_ea_idx].get("_conv_time") if isinstance(_ea_idx, int) and 0 <= _ea_idx < len(all_observations) else latest_conv_time
                add_evidence(fact["id"], {"reason": f"[反面] {ea.get('reason', '')}"},
                             reference_time=_ea_time)
                pass

        # Step 4b: 创建新画像（只处理 "new" 类观察）
        if new_obs_cls:
            print(f"  [sleep] creating {len(new_obs_cls)} new facts...")
            new_obs_data = []
            for c in new_obs_cls:
                idx = c.get("obs_index")
                if isinstance(idx, int) and 0 <= idx < len(all_observations):
                    new_obs_data.append(all_observations[idx])

            if new_obs_data:
                _new_obs_times = [o.get("_conv_time") for o in new_obs_data if o.get("_conv_time")]
                _new_batch_time = max(_new_obs_times) if _new_obs_times else None
                _create_profile, _ = prepare_profile(current_profile, query_text=obs_query, max_entries=15, language=language)
                new_facts = create_new_facts(
                    new_obs_data, _create_profile, config, behavioral_signals,
                    trajectory=trajectory, language=language
                )
                for nf in new_facts:
                    # 兼容旧 LLM 输出：claim → value
                    value = nf.get("value") or nf.get("claim")
                    if not nf.get("category") or not nf.get("subject") or not value:
                        continue
                    if value.startswith("用户") or len(value) > 80:
                        continue
                    decay = nf.get("decay_days")
                    # 找到来源 observation 原文，存入 evidence
                    _src_obs = ""
                    for _o in new_obs_data:
                        _cnt = _o.get("content") or ""
                        if _cnt and (value in _cnt or _cnt in value):
                            _src_obs = _cnt
                            break
                    _evidence = [{"observation": _src_obs}] if _src_obs else None
                    fact_id = save_profile_fact(
                        category=nf["category"],
                        subject=nf["subject"],
                        value=value,
                        source_type=nf.get("source_type", "stated"),
                        decay_days=decay,
                        evidence=_evidence,
                        start_time=_new_batch_time,
                    )
                    new_fact_count += 1
                    if fact_id:
                        affected_fact_ids.add(fact_id)
                    changed_items.append({
                        "change_type": "new",
                        "category": nf["category"],
                        "subject": nf["subject"],
                        "claim": value,
                        "source_type": nf.get("source_type", "stated"),
                    })

        # Step 4c: 标记矛盾（不再当场判断，交给 dispute resolution）
        contradict_count = 0
        if contradictions:
            print(f"  [sleep] processing {len(contradictions)} contradictions...")
            for c in contradictions:
                fid = c.get("fact_id")
                fact = _find_fact(fid)
                new_val = c.get("new_value")
                if not fact or not new_val:
                    continue
                # v20: 先计算 obs_time
                _obs_idx = c.get("obs_index")
                _obs_time = all_observations[_obs_idx].get("_conv_time") if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else latest_conv_time
                # 同值过滤
                if new_val.strip().lower() == (fact.get("value") or "").strip().lower():
                    add_evidence(fact["id"], {"reason": c.get("reason", "再次提及")},
                                 reference_time=_obs_time)
                    continue
                # 脏值过滤
                if new_val.startswith("用户") or len(new_val) > 40:
                    continue
                # 直接创建 dispute pair，不用 LLM 判断
                # 保存触发矛盾的原始对话，供 Step 5.1 判断
                _obs = all_observations[_obs_idx] if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else {}
                _evidence_entry = {"reason": c.get("reason", "")}
                if _obs.get("content"):
                    _evidence_entry["observation"] = _obs["content"]
                new_id = save_profile_fact(
                    category=fact["category"],
                    subject=fact["subject"],
                    value=new_val,
                    source_type="stated",
                    decay_days=fact.get("decay_days"),
                    evidence=[_evidence_entry],
                    start_time=_obs_time,
                )
                contradict_count += 1
                if new_id:
                    affected_fact_ids.add(new_id)
                changed_items.append({
                    "change_type": "contradict",
                    "category": fact["category"],
                    "subject": fact["subject"],
                    "claim": f"{fact['value']}→{new_val}",
                })

        # Step 4d: 策略生成（只对新建/矛盾的画像）
        strategy_count = 0
        if changed_items:
            print(f"  [sleep] generating strategies for {len(changed_items)} changes...")
            strategies = generate_strategies(changed_items, config,
                                            current_profile=current_profile,
                                            trajectory=trajectory,
                                            language=language)
            for s in strategies:
                cat = s.get("category")
                subj = s.get("subject")
                if not cat or not subj:
                    continue
                try:
                    save_strategy(
                        hypothesis_category=cat,
                        hypothesis_subject=subj,
                        strategy_type=s.get("type", "probe"),
                        description=s.get("description", ""),
                        trigger_condition=s.get("trigger", ""),
                        approach=s.get("approach", ""),
                        reference_time=latest_conv_time,
                    )
                    strategy_count += 1
                except Exception as e:
                    _pipeline_errors += 1
                    logger.error("Save strategy failed: %s", e)

        print(f"  [sleep] step4 done: {len(supports)} support, {new_fact_count} new, {contradict_count} contradict, {strategy_count} strategies")

        # Step 4.5: 观察兜底 — 已移除（v15）
        # 原因：与 4a+4b 完全重复，且是重复记录循环的直接触发点
    else:
        print("  [sleep] no new observations, skip")

    # Step 5: 交叉验证（v14: suspected → confirmed）
    suspected_facts = load_suspected_profile()
    print(f"  [sleep] cross-verifying {len(suspected_facts)} suspected facts...")
    confirmed_count = 0

    if suspected_facts:
        judgments = cross_verify_suspected_facts(suspected_facts, config, trajectory=trajectory, language=language)
        judgment_map = {j["fact_id"]: j for j in judgments}

        for f in suspected_facts:
            j = judgment_map.get(f["id"])
            if not j:
                continue

            action = j["action"]
            reason = j.get("reason", "")

            if action == "confirm":
                confirm_profile_fact(f["id"], reference_time=latest_conv_time)
                confirmed_count += 1
            else:
                pass

    print(f"  [sleep] {confirmed_count} confirmed, {len(suspected_facts) - confirmed_count} still suspected")

    # Step 5.1: 矛盾争议解决
    disputed_pairs = load_disputed_facts()
    print(f"  [sleep] resolving {len(disputed_pairs)} disputes...")
    dispute_resolved = 0
    if disputed_pairs:
        judgments = resolve_disputes_with_llm(disputed_pairs, config, trajectory=trajectory, language=language)
        for j in judgments:
            old_fid = j["old_fact_id"]
            new_fid = j["new_fact_id"]
            action = j["action"]
            reason = j.get("reason", "")

            if action == "accept_new":
                resolve_dispute(old_fid, new_fid, accept_new=True, resolution_time=latest_conv_time)
                delete_fact_edges_for(old_fid)
                dispute_resolved += 1
            elif action == "reject_new":
                resolve_dispute(old_fid, new_fid, accept_new=False, resolution_time=latest_conv_time)
                delete_fact_edges_for(new_fid)
                dispute_resolved += 1
            else:
                pass

        print(f"  [sleep] {dispute_resolved} disputes resolved")
    else:
        pass

    # Step 5.5: 过期处理（v14: 过期事实 → close_time_period）
    print("  [sleep] checking expired facts...")
    expired_facts = get_expired_facts(reference_time=latest_conv_time)
    stale_count = 0
    if expired_facts:
        for f in expired_facts:
            fact_id = f["id"]
            cat = f["category"]
            subj = f["subject"]

            if f.get("superseded_by") or f.get("supersedes"):
                continue

            close_time_period(fact_id, end_time=latest_conv_time)
            try:
                delete_fact_edges_for(fact_id)
            except Exception:
                logger.error("Delete edges for expired fact %s failed", fact_id, exc_info=True)
            try:
                save_strategy(
                    hypothesis_category=cat,
                    hypothesis_subject=subj,
                    strategy_type="verify",
                    description=f"{subj}信息长期未提及，已过期关闭",
                    trigger_condition=f"用户提到{subj}相关话题时",
                    approach=f"自然地确认用户的{subj}是否有变化",
                    reference_time=latest_conv_time,
                )
            except Exception:
                _pipeline_errors += 1
                logger.error("Save expired-fact strategy failed", exc_info=True)
            stale_count += 1

        print(f"  [sleep] {stale_count} expired")
    else:
        pass

    # Step 5.7: 兴趣成熟度演进（纯代码，不调 LLM）
    print("  [sleep] maturity evolution...")
    key_anchors = []
    if trajectory and trajectory.get("key_anchors"):
        key_anchors = [str(a).lower() for a in trajectory["key_anchors"]]

    # v14: 从 user_profile 查询
    all_living = load_full_current_profile()

    maturity_count = 0
    for f in all_living:
        start = f.get("start_time")
        updated = f.get("updated_at")
        if not start or not updated:
            continue
        # 统一时区
        f_naive = start.replace(tzinfo=None) if hasattr(start, 'tzinfo') and start.tzinfo else start
        l_naive = updated.replace(tzinfo=None) if hasattr(updated, 'tzinfo') and updated.tzinfo else updated
        span_days = (l_naive - f_naive).days
        ev = f.get("evidence", [])
        evidence_count = len(ev) if isinstance(ev, list) else 0
        current_decay = f.get("decay_days") or 90

        subj_lower = (f.get("subject") or "").lower()
        value_lower = (f.get("value") or "").lower()
        in_anchors = any(subj_lower in a or value_lower in a or a in subj_lower or a in value_lower
                         for a in key_anchors)

        new_decay = _calculate_maturity_decay(span_days, evidence_count, current_decay, in_anchors)
        if new_decay > current_decay:
            update_fact_decay(f["id"], new_decay, reference_time=latest_conv_time)
            maturity_count += 1

    print(f"  [sleep] {maturity_count} upgraded")

    # Step 6: 分析用户模型 → user_model
    print("  [sleep] analyzing user model...")
    if all_convs:
        current_profile_for_model = load_full_current_profile(exclude_superseded=True)
        model_convs = all_convs[-50:] if len(all_convs) > 50 else all_convs
        model_results = analyze_user_model(model_convs, config,
                                           current_profile=current_profile_for_model,
                                           language=language)
        print(f"  [sleep] {len(model_results)} dimensions analyzed")
        for m in model_results:
            upsert_user_model(
                dimension=m["dimension"],
                assessment=m["assessment"],
                evidence_summary=m.get("evidence", ""),
            )
    else:
        pass

    # Step 7: 条件更新轨迹总结
    print("  [sleep] checking trajectory update...")
    should_update_trajectory = False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT session_id) FROM raw_conversations WHERE processed = TRUE")
            total_sessions = cur.fetchone()[0] + len(session_convs)
    finally:
        conn.close()

    prev_session_count = trajectory.get("session_count", 0) if trajectory else 0
    sessions_since_update = total_sessions - prev_session_count

    has_significant_change = (
        confirmed_count > 0
        or dispute_resolved > 0
        or contradict_count > 0
        or any(
            item.get("category", "").lower() in ("职业", "career", "家庭", "family", "居住", "住所",
                                                   "education", "教育", "健康", "health", "location")
            for item in changed_items
        )
    )

    if has_significant_change and sessions_since_update >= 2:
        should_update_trajectory = True
    elif sessions_since_update >= 10:
        # 兜底：太久没更新也触发
        should_update_trajectory = True

    if not trajectory:
        current_profile = load_full_current_profile(exclude_superseded=True)
        if current_profile:
            should_update_trajectory = True

    if should_update_trajectory:
        current_profile = load_full_current_profile(exclude_superseded=True)
        if current_profile:
            trajectory_result = generate_trajectory_summary(
                current_profile, config, new_observations=all_observations,
                language=language
            )
            if trajectory_result and trajectory_result.get("life_phase"):
                try:
                    save_trajectory_summary(trajectory_result, session_count=total_sessions,
                                            reference_time=latest_conv_time)
                    print(f"  [sleep] trajectory updated: {trajectory_result.get('life_phase', '?')}")
                except Exception as e:
                    _pipeline_errors += 1
                    logger.error("trajectory save failed: %s", e)
            else:
                print("  [sleep] trajectory generation failed")
        else:
            pass
    else:
        pass

    # Step 7.5: Profile 去重合并（只在有新 fact 或矛盾解决时）
    if new_fact_count > 0 or dispute_resolved > 0:
        print("  [sleep] consolidating profile...")
        _consolidate_profile(language=language)

    # Step 7.6: 预编译 memory_snapshot
    print("  [sleep] generating memory snapshot...")
    try:
        final_profile = load_full_current_profile(exclude_superseded=True)
        snapshot_text = format_profile_text(
            final_profile, max_entries=40, detail="full", language=language
        )

        user_model_data = load_user_model()
        if user_model_data:
            model_lines = [f"  {m['dimension']}: {m['assessment']}" for m in user_model_data]
            snapshot_text += "\n\n用户特征：\n" + "\n".join(model_lines)

        events_data = load_active_events(top_k=5)
        if events_data:
            event_lines = [f"  [{e['category']}] {e['summary']}" for e in events_data]
            snapshot_text += "\n\n近期事件：\n" + "\n".join(event_lines)

        relationships_data = load_relationships()
        if relationships_data:
            rel_lines = [f"  {r['relation']}: {r.get('name', '?')}" for r in relationships_data[:10]]
            snapshot_text += "\n\n人际关系：\n" + "\n".join(rel_lines)

        save_memory_snapshot(snapshot_text, profile_count=len(final_profile))
        print("  [sleep] snapshot saved")
    except Exception as e:
        _pipeline_errors += 1
        logger.error("snapshot failed: %s", e)

    # Step 8: 标记已处理
    mark_processed(all_msg_ids)
    print(f"  [sleep] processed {len(all_msg_ids)} conversations")

    if _pipeline_errors:
        logger.warning("Sleep pipeline completed with %d error(s)", _pipeline_errors)

    print("  [sleep] done")
