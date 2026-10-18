"""LangGraph workflow. It calls the existing agents and then checks their restaurant IDs."""

import re
from typing import TypedDict

from food_copilot.agents.preference import review_preferences, with_saved_preferences
from food_copilot.agents.recommendation import recommend
from food_copilot.data.repository import get_default_repository
from food_copilot.retrieval.constraints import apply_constraints, parse_constraints
from food_copilot.services.discovery import build_answer, candidate_from_record

_ID = re.compile(r"MY-OSM-[A-Za-z0-9-]+")


class ChatGraphState(TypedDict, total=False):
    query: str
    user_id: str | None
    session_id: str | None
    recent_messages: list
    loaded_preferences: list
    temporary_preferences: list
    proposed_preferences: list
    saved_preferences: list
    recommendation: dict
    memory_saved: bool
    memory_note: str


def build_chat_graph(model, call_tool, memory=None, repository=None):
    from langgraph.graph import END, StateGraph

    repository = repository if repository is not None else get_default_repository()

    def load_memory(state: ChatGraphState) -> dict:
        messages: list = []
        preferences: list = []
        configured = (
            memory is not None
            and state.get("user_id")
            and memory.status().get("postgres")
            and memory.status().get("redis")
        )
        if configured:
            try:
                preferences = memory.preferences(state["user_id"])
            except Exception:
                preferences = []
            if state.get("session_id"):
                try:
                    messages = memory.recent_messages(state["session_id"])
                except Exception:
                    messages = []
        return {"recent_messages": messages, "loaded_preferences": preferences}

    def preference(state: ChatGraphState) -> dict:
        result = review_preferences(
            state["query"],
            model,
            memory=memory,
            user_id=state.get("user_id"),
            session_id=state.get("session_id"),
        )
        return {
            "temporary_preferences": result["temporary"],
            "proposed_preferences": result["proposed_preferences"],
            "saved_preferences": result["saved_preferences"],
        }

    def recommendation(state: ChatGraphState) -> dict:
        query = with_saved_preferences(state["query"], state.get("loaded_preferences") or [])
        return {
            "recommendation": recommend(
                query,
                model,
                call_tool,
                repository=repository,
                history=state.get("recent_messages") or [],
            )
        }

    def validate(state: ChatGraphState) -> dict:
        current = dict(state.get("recommendation") or {})
        constraints = parse_constraints(state["query"])
        records = []
        for item in current.get("results") or []:
            row = repository.get_by_id(item["restaurant_id"])
            if row is not None:
                records.append(row)
        buckets = apply_constraints(records, constraints)
        cards = [candidate_from_record(row, constraints) for row in buckets.matching]
        allowed = {card.restaurant_id for card in cards}
        answer = current.get("answer") or ""
        if set(_ID.findall(answer)) - allowed:
            answer = build_answer(constraints, buckets, cards)
        counts = dict(buckets.exclusion_counts)
        if not records and current.get("exclusion_counts"):
            counts = dict(current["exclusion_counts"])
        current["answer"] = answer
        current["results"] = [card.model_dump() for card in cards]
        current["exclusion_counts"] = counts
        current["constraints"] = constraints.model_dump()
        return {"recommendation": current}

    def persist(state: ChatGraphState) -> dict:
        user_id = state.get("user_id")
        session_id = state.get("session_id")
        if bool(user_id) != bool(session_id):
            return {
                "memory_saved": False,
                "memory_note": "Both user_id and session_id are required before a conversation can be saved.",
            }
        if not user_id or not session_id or memory is None:
            return {"memory_saved": False, "memory_note": ""}
        answer = (state.get("recommendation") or {}).get("answer") or ""
        try:
            memory.append_message(user_id, session_id, "user", state["query"])
            memory.append_message(user_id, session_id, "assistant", answer[:4000])
        except Exception:
            return {
                "memory_saved": False,
                "memory_note": "The answer was produced, but the conversation was not saved.",
            }
        return {"memory_saved": True, "memory_note": ""}

    graph = StateGraph(ChatGraphState)
    graph.add_node("load_memory", load_memory)
    graph.add_node("preference", preference)
    graph.add_node("recommendation", recommendation)
    graph.add_node("validate", validate)
    graph.add_node("persist", persist)
    graph.set_entry_point("load_memory")
    graph.add_edge("load_memory", "preference")
    graph.add_edge("preference", "recommendation")
    graph.add_edge("recommendation", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def run_chat_graph(
    query: str,
    user_id: str | None = None,
    session_id: str | None = None,
    model=None,
    call_tool=None,
    memory=None,
    repository=None,
) -> dict:
    from food_copilot.agents.mcp_client import mcp_call
    from food_copilot.agents.model import OpenAIChatModel

    app = build_chat_graph(
        model or OpenAIChatModel(),
        call_tool or mcp_call,
        memory=memory,
        repository=repository,
    )
    final = app.invoke({"query": query, "user_id": user_id, "session_id": session_id})
    recommendation = dict(final.get("recommendation") or {})
    recommendation["proposed_preferences"] = final.get("proposed_preferences") or []
    recommendation["saved_preferences"] = final.get("saved_preferences") or []
    recommendation["temporary_preferences"] = final.get("temporary_preferences") or []
    recommendation["agent_mode"] = "langgraph"
    recommendation["memory_saved"] = bool(final.get("memory_saved"))
    recommendation["memory_note"] = final.get("memory_note") or ""
    recommendation.setdefault("sources_note", "Shown facts come from stored records. Unverified fields stay unverified.")
    recommendation.setdefault("tools_called", [])
    recommendation.setdefault("language", "")
    recommendation.setdefault("retriever", "baseline")
    recommendation.setdefault("needs_clarification", False)
    return recommendation
