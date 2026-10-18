"""Deterministic tool routing. Optional model and LangGraph paths stay off."""

from food_copilot.config.settings import feature_flags
from food_copilot.data.repository import evidence_for, get_default_repository
from food_copilot.errors import FeatureDisabled, ToolError
from food_copilot.retrieval.constraints import QueryConstraints
from food_copilot.services.discovery import DeterministicIntentParser, DiscoveryService


def get_restaurant_details(restaurant_id: str, repository=None) -> dict:
    if not isinstance(restaurant_id, str) or not restaurant_id.strip():
        raise ToolError("restaurant_id must be a non-empty string")
    repository = repository or get_default_repository()
    row = repository.get_by_id(restaurant_id.strip())
    if row is None:
        return {"ok": False, "error": "not_found", "restaurant_id": restaurant_id}
    return {"ok": True, "restaurant": row, "evidence": [item.model_dump() for item in evidence_for(row)]}


def handle_message(query: str, service: DiscoveryService | None = None) -> dict:
    service = service or DiscoveryService()
    request = DeterministicIntentParser().parse(query)
    tools: list[dict] = []
    if request.clarification:
        outcome = service.from_text(query)
        tools.append({"tool": "explain_constraints", "detail": "clarification"})
    else:
        if not isinstance(request.constraints, QueryConstraints):
            raise ToolError("discover_restaurants requires a validated QueryConstraints object")
        tools.append({
            "tool": "discover_restaurants",
            "detail": request.constraints.region or request.constraints.city or "constraints",
        })
        outcome = service.from_constraints(request.constraints, query_text=query, request=request)
        tools.append({"tool": "explain_constraints", "detail": "results"})
        outcome["language"] = request.language
    outcome["tools_called"] = [item["tool"] for item in tools]
    outcome["audit"] = tools
    return outcome


def run_llm_agent(query: str) -> dict:
    if not feature_flags()["ENABLE_LLM_AGENT"]:
        raise FeatureDisabled("ENABLE_LLM_AGENT is false. The deterministic orchestrator was not replaced.")
    from food_copilot.agents.runtime import answer_with_agents

    return answer_with_agents(query)


def build_optional_graph():
    if not feature_flags()["ENABLE_LANGGRAPH"]:
        raise FeatureDisabled("ENABLE_LANGGRAPH is false. Use food_copilot.agents.orchestrator.handle_message.")
    try:
        from food_copilot.agents.graph import build_chat_graph
        from food_copilot.agents.mcp_client import mcp_call
        from food_copilot.agents.model import OpenAIChatModel
        from food_copilot.memory.store import MemoryStore
    except ImportError as exc:
        raise FeatureDisabled("langgraph is not installed. The deterministic orchestrator still runs.") from exc
    return build_chat_graph(OpenAIChatModel(), mcp_call, memory=MemoryStore(), repository=get_default_repository())
