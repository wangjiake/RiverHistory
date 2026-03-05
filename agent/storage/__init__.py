"""Storage layer — re-exports from submodules."""

from ._db import configure_db, get_db_connection, _as_dict, _as_dicts
from ._synonyms import _get_category_synonyms, _get_subject_synonyms

from .conversation import (
    save_raw_conversation, save_conversation_turn,
    save_session_tag, load_existing_tags, search_sessions_by_tag,
)
from .events import save_event, load_active_events
from .observations import (
    save_observation, update_observation_classification,
    load_observations, load_observations_by_time_range,
)
from .hypotheses import (
    save_hypothesis, update_hypothesis_evidence,
    load_active_hypotheses, get_expired_hypotheses,
    get_hypothesis_by_subject,
    enter_suspicion_mode, update_suspected_evidence, resolve_suspicion,
    upgrade_hypothesis_decay, set_hypothesis_status,
)
from .profile import (
    upsert_profile, load_current_profile, remove_profile,
    upsert_user_model, load_user_model,
    save_trajectory_summary, load_trajectory_summary,
    save_or_update_relationship, load_relationships,
    save_profile_fact, close_time_period, confirm_profile_fact,
    add_evidence, find_current_fact,
    load_suspected_profile, load_confirmed_profile,
    load_full_current_profile, load_timeline,
    get_expired_facts, load_disputed_facts, resolve_dispute,
    update_fact_decay, delete_fact_edges_for,
)
from .strategies import save_strategy
from .memory import (
    load_conversation_summaries_around,
    load_summaries_by_observation_subject,
    save_memory_snapshot, load_memory_snapshot,
)
from .parsing import parse_turns
