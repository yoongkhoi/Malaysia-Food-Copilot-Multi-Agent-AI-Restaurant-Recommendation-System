"""Multi-agent workflow with a scripted model and an in-memory MCP session."""

import json

from food_copilot.agents.mcp_host import MemoryMcp
from food_copilot.agents.workflow import run_agent_workflow
from food_copilot.mcp.server import build_mcp_server
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _records():
    return [
        restaurant("korean-1", name="Sae Ma Eul", cuisine=["korean"], latitude=3.10, longitude=101.66),
        restaurant("other-1", name="How Ye Kee", cuisine=["chinese"], latitude=3.07, longitude=101.64),
    ]


class ScriptedModel:
    model_name = "scripted"

    def complete(self, messages, tools=None, timeout=8, max_tokens=180, temperature=None, role=None):
        if role == "intent":
            return {
                "content": json.dumps({
                    "task": "restaurant_search",
                    "region": None,
                    "cuisines": ["korean"],
                    "exclude_cuisines": [],
                    "exclude_brands": [],
                    "budget_mode": "none",
                    "needs_reviews": False,
                    "needs_web": False,
                }),
                "tool_calls": [],
            }
        if role == "tools":
            if any(item.get("role") == "tool" for item in messages):
                return {"content": "", "tool_calls": []}
            return {
                "content": "",
                "tool_calls": [{"id": "s1", "name": "search_restaurants", "arguments": {"query": "korean restaurant"}}],
            }
        if role == "rank":
            return {"content": json.dumps({"order": ["korean-1"], "notes": ["Korean cuisine matches the request."]}), "tool_calls": []}
        return {
            "content": json.dumps({
                "message": "Sae Ma Eul is the Korean option in Old Klang Road. The street address and price are not verified.",
                "restaurant_ids": ["korean-1", "made-up-id"],
            }),
            "tool_calls": [],
        }


def test_workflow_uses_mcp_search_and_model_synthesis():
    service = DiscoveryService(records=_records())
    mcp = MemoryMcp(build_mcp_server(service=service, repository=service.repository))
    assert "search_restaurants" in mcp.tool_names
    assert "get_restaurant_reviews" in mcp.tool_names
    result = run_agent_workflow("korean restaurant", repository=service.repository, model=ScriptedModel(), mcp=mcp, search=lambda query: {"ok": True, "results": []})
    assert result["trace"]["synthesis"] == "written"
    assert result["trace"]["llm_called"] is True
    assert "intent_agent" in result["trace"]["nodes"]
    assert "synthesis_agent" in result["trace"]["nodes"]
    assert [item["name"] for item in result["results"]] == ["Sae Ma Eul"]
    assert "made-up-id" not in json.dumps(result["results"])
    assert "Sae Ma Eul is the Korean option" in result["answer"]
    assert any(item.startswith("mcp:") for item in result["tools_called"])
    assert result["constraints"]["region"] == "old_klang_road"


def test_missing_model_is_labeled_as_a_stored_list(monkeypatch):
    monkeypatch.setattr("food_copilot.agents.workflow._model", lambda: (None, {"configured": False, "model": ""}))
    service = DiscoveryService(records=_records())
    mcp = MemoryMcp(build_mcp_server(service=service, repository=service.repository))
    result = run_agent_workflow("korean restaurant", repository=service.repository, model=None, mcp=mcp, search=lambda query: {"ok": True, "results": []})
    assert result["trace"]["synthesis"] == "fallback"
    assert result["llm_called"] is False
    assert "not a written recommendation" in result["answer"].lower() or "not configured" in result["answer"].lower()
    assert result["results"]


class DeadMcp:
    status = "disconnected"
    error = "startup_timeout"
    tool_names: list[str] = []

    def call(self, name, arguments):
        return {"ok": False, "error": "mcp_disconnected", "tool": name}


def test_disconnected_mcp_is_reported_and_local_search_still_runs():
    service = DiscoveryService(records=_records())
    result = run_agent_workflow(
        "korean restaurant",
        repository=service.repository,
        model=ScriptedModel(),
        mcp=DeadMcp(),
        search=lambda query: {"ok": True, "results": []},
    )
    assert result["trace"]["mcp_status"] == "disconnected"
    assert any(item.startswith("local:") for item in result["tools_called"])
    assert [item["name"] for item in result["results"]] == ["Sae Ma Eul"]
