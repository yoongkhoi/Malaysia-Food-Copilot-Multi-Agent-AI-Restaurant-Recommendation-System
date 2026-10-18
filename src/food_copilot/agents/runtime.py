"""Run the two agents in order. LangGraph is not this runtime."""

from food_copilot.agents.mcp_client import mcp_call
from food_copilot.agents.model import OpenAIChatModel
from food_copilot.agents.preference import review_preferences, with_saved_preferences
from food_copilot.agents.recommendation import recommend
from food_copilot.config.settings import feature_flags
from food_copilot.errors import FeatureDisabled


def answer_with_agents(
    query: str,
    user_id: str | None = None,
    session_id: str | None = None,
    model=None,
    call_tool=None,
    memory=None,
    repository=None,
) -> dict:
    if not feature_flags()["ENABLE_LLM_AGENT"]:
        raise FeatureDisabled("ENABLE_LLM_AGENT is false. The deterministic orchestrator was not replaced.")
    model = model or OpenAIChatModel()
    history = []
    stored = []
    configured = memory is not None and user_id and memory.status().get("postgres") and memory.status().get("redis")
    if configured:
        try:
            stored = memory.preferences(user_id)
        except Exception:
            stored = []
        if session_id:
            try:
                history = memory.recent_messages(session_id)
            except Exception:
                history = []
    preference = review_preferences(query, model, memory=memory, user_id=user_id, session_id=session_id)
    recommendation = recommend(
        with_saved_preferences(query, stored),
        model,
        call_tool or mcp_call,
        repository=repository,
        history=history,
    )
    recommendation["proposed_preferences"] = preference["proposed_preferences"]
    recommendation["saved_preferences"] = preference["saved_preferences"]
    recommendation["temporary_preferences"] = preference["temporary"]
    recommendation["agent_mode"] = "preference+recommendation"
    return recommendation
