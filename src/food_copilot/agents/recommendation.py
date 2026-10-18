"""Recommendation agent. Eligible restaurants come from tools, then Python checks them again."""

import json
import re

from food_copilot.data.repository import get_default_repository
from food_copilot.retrieval.constraints import apply_constraints, parse_constraints
from food_copilot.services.discovery import build_answer, candidate_from_record

_ID = re.compile(r"MY-OSM-[A-Za-z0-9-]+")
_ALLOWED = {"discover_restaurants", "get_restaurant_details", "get_restaurant_evidence"}
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "discover_restaurants",
            "description": "Find restaurants that already pass region, budget, and evidence filters.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_restaurant_details",
            "description": "Read one stored restaurant by exact id.",
            "parameters": {
                "type": "object",
                "properties": {"restaurant_id": {"type": "string"}},
                "required": ["restaurant_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_restaurant_evidence",
            "description": "Read stored address, price, and halal evidence for one id.",
            "parameters": {
                "type": "object",
                "properties": {"restaurant_id": {"type": "string"}},
                "required": ["restaurant_id"],
            },
        },
    },
]


def _checked(discovery: dict, query: str, repository) -> dict:
    constraints = parse_constraints(query)
    records = []
    for restaurant_id in discovery.get("eligible_restaurant_ids") or []:
        row = repository.get_by_id(restaurant_id) if repository is not None else None
        if row is not None:
            records.append(row)
    buckets = apply_constraints(records, constraints)
    cards = [candidate_from_record(row, constraints) for row in buckets.matching]
    counts = dict(discovery.get("exclusion_counts") or {})
    for code, count in buckets.exclusion_counts.items():
        counts[code] = counts.get(code, 0) + count
    answer = build_answer(constraints, buckets, cards)
    if not discovery.get("ok", True):
        answer = "The restaurant tool failed. No restaurants were recommended."
        cards = []
    return {
        "answer": answer,
        "constraints": constraints.model_dump(),
        "results": [card.model_dump() for card in cards],
            "eligible_restaurant_ids": [card.restaurant_id for card in cards],
        "exclusion_counts": counts,
        "needs_clarification": bool(discovery.get("needs_clarification")),
        "sources_note": discovery.get("sources_note") or "Shown facts come from stored records. Unverified fields stay unverified.",
        "language": discovery.get("language") or "",
        "retriever": discovery.get("retriever") or "baseline",
    }


def _provider_tool_call(call: dict) -> dict:
    return {
        "id": call.get("id") or call.get("name") or "tool",
        "type": "function",
        "function": {
            "name": call.get("name") or "",
            "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
        },
    }


def recommend(query: str, model, call_tool, repository=None, history: list | None = None) -> dict:
    repository = repository if repository is not None else get_default_repository()
    messages = [
        {
            "role": "system",
            "content": (
                "Recommend only restaurants returned by tools. "
                "Do not invent restaurants, prices, addresses, or halal evidence. "
                "If no restaurant qualifies, explain the evidence gap from the tool result. "
                "Do not mention internal filenames, filesystem paths, or dataset file names."
            ),
        },
    ]
    for item in (history or [])[-6:]:
        role = item.get("role") if isinstance(item, dict) else None
        content = str(item.get("content") or "")[:500] if isinstance(item, dict) else ""
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": query})
    discovery = None
    called: list[str] = []
    reply = {"content": "", "tool_calls": []}
    for _ in range(4):
        reply = model.complete(messages, _TOOLS)
        if not reply.get("tool_calls"):
            break
        messages.append({
            "role": "assistant",
            "content": reply.get("content") or "",
            "tool_calls": [_provider_tool_call(call) for call in reply["tool_calls"]],
        })
        for call in reply["tool_calls"]:
            name = call.get("name") or ""
            called.append(name)
            if name not in _ALLOWED:
                result = {"ok": False, "error": "tool_not_allowed"}
            else:
                try:
                    result = call_tool(name, call.get("arguments") or {})
                except Exception:
                    result = {
                        "ok": False,
                        "error": "tool_failed",
                        "answer": "The restaurant tool failed. No restaurants were recommended.",
                        "results": [],
                        "eligible_restaurant_ids": [],
                        "exclusion_counts": {},
                        "needs_clarification": False,
                    }
            if name == "discover_restaurants":
                discovery = result
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or name,
                "content": json.dumps(result, ensure_ascii=False),
            })
    if discovery is None:
        called.append("discover_restaurants")
        try:
            discovery = call_tool("discover_restaurants", {"query": query})
        except Exception:
            discovery = {
                "ok": False,
                "error": "tool_failed",
                "answer": "The restaurant tool failed. No restaurants were recommended.",
                "eligible_restaurant_ids": [],
                "exclusion_counts": {},
                "needs_clarification": False,
            }
    checked = _checked(discovery, query, repository)
    allowed = set(checked["eligible_restaurant_ids"])
    cited = set(_ID.findall(reply.get("content") or ""))
    if reply.get("content") and not (cited - allowed):
        checked["answer"] = reply["content"]
    if any(item.get("dataset_origin") == "demo" for item in checked["results"]):
        note = "Demonstration data: these prices and halal labels are examples, not verified restaurant facts."
        if note not in checked["answer"]:
            checked["answer"] = checked["answer"].rstrip() + "\n" + note
    checked["tools_called"] = called
    return checked
