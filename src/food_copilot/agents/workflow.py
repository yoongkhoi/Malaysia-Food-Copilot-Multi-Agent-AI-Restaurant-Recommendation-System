"""Multi-agent restaurant workflow.

Intent, tool choice, ranking, and the final recommendation each have their own step.
Restaurant ids come from retrieval. The final model writes the reply and cannot add candidates.
"""

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from food_copilot.agents.context import apply_history, present_results
from food_copilot.agents.intent_router import NO_SESSION_FOLLOWUP, classify_intent
from food_copilot.config.regions import PROJECT_REGION
from food_copilot.retrieval.constraints import QueryConstraints, parse_constraints
from food_copilot.services.discovery import reply_language

logger = logging.getLogger("food_copilot.workflow")
_ENV_MODEL = object()

_INTENT_SYSTEM = (
    "You convert a restaurant request into one JSON object and nothing else. "
    "Keys: task, region, city, cuisines, exclude_cuisines, name_contains, exclude_brands, "
    "max_budget_myr, budget_mode, occasion, ambience, diet, require_halal_verified, "
    "needs_reviews, needs_web, uncertainty. "
    "task is one of restaurant_search, restaurant_followup, review_recommendation, restaurant_info, general_qa. "
    "region is old_klang_road, kuala_lumpur, or null. "
    "Use null for region when the user does not name a place. Do not invent a budget number. "
    "needs_reviews is true only when the user asks about reviews or what people say. "
    "needs_web is true only when the user asks for something the stored records are unlikely to have, "
    "such as a recent opening or a specific atmosphere."
)

_TOOL_SYSTEM = (
    "You choose restaurant tools. Call search_restaurants before you recommend anything. "
    "Call get_restaurant_reviews only when reviews were requested or would distinguish the options. "
    "Call web_search only when stored records are not enough. "
    "Do not invent restaurant ids. After the tools return, reply with an empty message if you need no further tool."
)

_RANK_SYSTEM = (
    "Order the provided restaurant ids for this request. Return JSON with keys order and notes. "
    "order is a list of ids copied from the input. Do not add ids. "
    "notes is a short list of comparison points that use only the supplied fields."
)

_SYNTH_SYSTEM = (
    "Write a warm, specific restaurant recommendation as JSON with keys message and restaurant_ids. "
    "restaurant_ids must be copied from the supplied candidates. Do not add restaurants, prices, "
    "addresses, ratings, opening hours, review quotations, or URLs that are not in the facts. "
    "Say what is unknown instead of guessing. Explain why the options differ. "
    "message is plain text in the requested language."
)


class IntentPlan(BaseModel):
    task: str = "restaurant_search"
    region: str | None = None
    city: str | None = None
    cuisines: list[str] = Field(default_factory=list)
    exclude_cuisines: list[str] = Field(default_factory=list)
    name_contains: str | None = None
    exclude_brands: list[str] = Field(default_factory=list)
    max_budget_myr: float | None = None
    budget_mode: str = "none"
    occasion: str | None = None
    ambience: str | None = None
    diet: str | None = None
    require_halal_verified: bool = False
    needs_reviews: bool = False
    needs_web: bool = False
    uncertainty: str | None = None


def _model():
    from food_copilot.agents.model import OpenAIChatModel, openai_status

    status = openai_status()
    if not status["configured"]:
        return None, status
    return OpenAIChatModel(), status


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no json object")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json was not an object")
    return parsed


def _lock_hard_constraints(plan: IntentPlan, parsed: QueryConstraints) -> IntentPlan:
    data = plan.model_dump()
    if parsed.region:
        data["region"] = parsed.region
    if parsed.city:
        data["city"] = parsed.city
    if parsed.max_budget_myr is not None:
        data["max_budget_myr"] = parsed.max_budget_myr
        data["budget_mode"] = parsed.budget_mode
    if parsed.require_halal_verified:
        data["require_halal_verified"] = True
    if parsed.exclude_cuisines:
        data["exclude_cuisines"] = list(dict.fromkeys([*data["exclude_cuisines"], *parsed.exclude_cuisines]))
    if parsed.exclude_brands:
        data["exclude_brands"] = list(dict.fromkeys([*data["exclude_brands"], *parsed.exclude_brands]))
    if parsed.cuisine and parsed.cuisine not in data["cuisines"]:
        data["cuisines"] = [parsed.cuisine, *data["cuisines"]]
    if parsed.name_contains:
        data["name_contains"] = parsed.name_contains
    if data["region"] not in {"old_klang_road", "kuala_lumpur"}:
        data["region"] = None
    if data["task"] not in {
        "restaurant_search",
        "restaurant_followup",
        "review_recommendation",
        "restaurant_info",
        "general_qa",
    }:
        data["task"] = "restaurant_search"
    if data["task"] != "general_qa" and data["region"] is None and data["city"] is None:
        data["region"] = PROJECT_REGION
        data["uncertainty"] = data.get("uncertainty") or "No area was named, so Old Klang Road is used."
    return IntentPlan.model_validate(data)


def _coerce_plan(data: dict) -> IntentPlan:
    task = str(data.get("task") or "restaurant_search")
    if task not in {
        "restaurant_search",
        "restaurant_followup",
        "review_recommendation",
        "restaurant_info",
        "general_qa",
    }:
        task = "restaurant_search"
    region = data.get("region")
    if region not in {"old_klang_road", "kuala_lumpur"}:
        region = None
    def as_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []
    budget = data.get("max_budget_myr")
    try:
        budget = None if budget in (None, "", "null") else float(budget)
    except (TypeError, ValueError):
        budget = None
    mode = data.get("budget_mode") if data.get("budget_mode") in {"hard", "flexible", "none"} else "none"
    flag = data.get("require_halal_verified")
    reviews = data.get("needs_reviews")
    web = data.get("needs_web")
    return IntentPlan(
        task=task,
        region=region,
        city=str(data["city"]) if data.get("city") else None,
        cuisines=as_list(data.get("cuisines")),
        exclude_cuisines=as_list(data.get("exclude_cuisines")),
        name_contains=str(data["name_contains"]) if data.get("name_contains") else None,
        exclude_brands=as_list(data.get("exclude_brands")),
        max_budget_myr=budget,
        budget_mode=mode,
        occasion=str(data["occasion"]) if data.get("occasion") else None,
        ambience=str(data["ambience"]) if data.get("ambience") else None,
        diet=str(data["diet"]) if data.get("diet") else None,
        require_halal_verified=flag is True or str(flag).lower() == "true",
        needs_reviews=reviews is True or str(reviews).lower() == "true",
        needs_web=web is True or str(web).lower() == "true",
        uncertainty=str(data["uncertainty"]) if data.get("uncertainty") else None,
    )


def _plan_from_parser(text: str) -> IntentPlan:
    parsed = parse_constraints(text)
    task = "restaurant_search"
    if parsed.ambience == "date":
        task = "restaurant_search"
    return _lock_hard_constraints(
        IntentPlan(
            task=task,
            region=parsed.region,
            city=parsed.city,
            cuisines=list(parsed.cuisines or []),
            exclude_cuisines=list(parsed.exclude_cuisines or []),
            name_contains=parsed.name_contains,
            exclude_brands=list(parsed.exclude_brands or []),
            max_budget_myr=parsed.max_budget_myr,
            budget_mode=parsed.budget_mode,
            ambience=parsed.ambience,
            diet=parsed.diet,
            require_halal_verified=parsed.require_halal_verified,
        ),
        parsed,
    )


def _intent_from_model(model, text: str, history: list, context: dict) -> tuple[IntentPlan, str, bool]:
    parsed = parse_constraints(text)
    messages = [
        {"role": "system", "content": _INTENT_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "message": text,
                    "saved_context": {key: context.get(key) for key in ("region", "cuisine", "cuisines", "name_contains") if context.get(key)},
                    "recent_user_turns": [str(item.get("content") or "")[:200] for item in (history or []) if item.get("role") == "user"][-3:],
                },
                ensure_ascii=False,
            ),
        },
    ]
    started = time.perf_counter()
    reply = model.complete(messages, role="intent", max_tokens=400, timeout=12)
    logger.info("agent=intent latency_ms=%s", round((time.perf_counter() - started) * 1000))
    try:
        plan = _lock_hard_constraints(_coerce_plan(_parse_json(reply.get("content") or "")), parsed)
        return plan, "intent model", True
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("intent json failed: %s", exc.__class__.__name__)
        return _plan_from_parser(text), f"intent model returned unusable JSON ({exc.__class__.__name__}); parsed constraints were kept", False


def _tool_schemas(names: set[str], web: bool) -> list[dict]:
    schemas = []
    if "search_restaurants" in names:
        schemas.append({
            "type": "function",
            "function": {
                "name": "search_restaurants",
                "description": "Search the canonical restaurant dataset.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "region": {"type": "string"},
                        "cuisine": {"type": "string"},
                        "max_budget_myr": {"type": "number"},
                        "name_contains": {"type": "string"},
                        "exclude_ids": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        })
    if "get_restaurant_reviews" in names:
        schemas.append({
            "type": "function",
            "function": {
                "name": "get_restaurant_reviews",
                "description": "Read confirmed review excerpts for one restaurant.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "restaurant_id": {"type": "string"},
                        "name": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        })
    if "get_restaurant_details" in names:
        schemas.append({
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
        })
    if web:
        schemas.append({
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search public web pages. Results are sources, not canonical restaurants.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        })
    return schemas


def _search_args(plan: IntentPlan, text: str, exclude_ids: list[str]) -> dict:
    return {
        "query": text,
        "region": plan.region or "",
        "cuisine": plan.cuisines[0] if plan.cuisines else "",
        "max_budget_myr": plan.max_budget_myr or 0,
        "name_contains": plan.name_contains or "",
        "exclude_ids": ",".join(exclude_ids),
    }


def _run_search(mcp, repository, arguments: dict) -> dict:
    if mcp is not None and "search_restaurants" in getattr(mcp, "tool_names", []):
        result = mcp.call("search_restaurants", arguments)
        result["via"] = "mcp"
        return result
    from food_copilot.mcp.tools import search_restaurants
    from food_copilot.services.discovery import DiscoveryService

    result = search_restaurants(
        arguments.get("query") or "",
        region=arguments.get("region") or "",
        cuisine=arguments.get("cuisine") or "",
        max_budget_myr=float(arguments.get("max_budget_myr") or 0),
        name_contains=arguments.get("name_contains") or "",
        service=DiscoveryService(repository=repository) if repository is not None else None,
        exclude_ids=[item for item in str(arguments.get("exclude_ids") or "").split(",") if item],
    )
    result["via"] = "local"
    result["mcp_error"] = getattr(mcp, "error", "") if mcp is not None else "not_connected"
    return result


def _tool_loop(model, mcp, plan: IntentPlan, text: str, exclude_ids: list[str], repository, search, web_enabled: bool) -> dict:
    discovered = set(getattr(mcp, "tool_names", []) or [])
    schemas = _tool_schemas(discovered, web_enabled or search is not None)
    bag: dict[str, Any] = {"results": [], "reviews": [], "web": [], "calls": [], "constraints": {}, "retriever": "bm25"}
    if model is None or not schemas:
        found = _run_search(mcp, repository, _search_args(plan, text, exclude_ids))
        bag["results"] = found.get("results") or []
        bag["constraints"] = found.get("constraints") or {}
        bag["retriever"] = found.get("retriever") or bag["retriever"]
        bag["calls"].append({"tool": "search_restaurants", "via": found.get("via"), "ok": found.get("ok", True)})
        if plan.needs_reviews and bag["results"]:
            _attach_reviews(mcp, bag)
        if plan.needs_web and search is not None:
            _attach_web(search, text, bag)
        return bag
    messages: list[dict] = [
        {"role": "system", "content": _TOOL_SYSTEM},
        {"role": "user", "content": json.dumps({"request": text, "plan": plan.model_dump()}, ensure_ascii=False)[:4000]},
    ]
    for _round in range(3):
        started = time.perf_counter()
        reply = model.complete(messages, tools=schemas, role="tools", max_tokens=300, timeout=15)
        logger.info("agent=tools latency_ms=%s", round((time.perf_counter() - started) * 1000))
        calls = reply.get("tool_calls") or []
        if not calls:
            break
        messages.append({
            "role": "assistant",
            "content": reply.get("content") or "",
            "tool_calls": [
                {
                    "id": call.get("id") or f"call-{index}",
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments") or {})},
                }
                for index, call in enumerate(calls)
            ],
        })
        for call in calls:
            name = call.get("name")
            arguments = dict(call.get("arguments") or {})
            if name == "search_restaurants":
                forced = _search_args(plan, arguments.get("query") or text, exclude_ids)
                forced.update({key: value for key, value in arguments.items() if value not in (None, "")})
                forced["exclude_ids"] = ",".join(exclude_ids)
                outcome = _run_search(mcp, repository, forced)
                bag["results"] = outcome.get("results") or bag["results"]
                bag["constraints"] = outcome.get("constraints") or bag["constraints"]
                bag["retriever"] = outcome.get("retriever") or bag["retriever"]
                public = {"ok": outcome.get("ok", True), "ids": outcome.get("eligible_restaurant_ids") or [], "via": outcome.get("via")}
            elif name == "web_search":
                public = _attach_web(search, arguments.get("query") or text, bag)
            elif name == "get_restaurant_reviews":
                public = _review_call(mcp, arguments, bag)
            elif mcp is not None and name in discovered:
                public = mcp.call(name, arguments)
            else:
                public = {"ok": False, "error": "tool_not_discovered", "tool": name}
            bag["calls"].append({
                "tool": name,
                "ok": public.get("ok", True),
                "via": public.get("via") or ("local" if name == "web_search" else "mcp"),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or f"call-{name}",
                "content": json.dumps(public, ensure_ascii=False)[:3000],
            })
    if not bag["results"]:
        found = _run_search(mcp, repository, _search_args(plan, text, exclude_ids))
        bag["results"] = found.get("results") or []
        bag["constraints"] = found.get("constraints") or bag["constraints"]
        bag["retriever"] = found.get("retriever") or bag["retriever"]
        bag["calls"].append({"tool": "search_restaurants", "via": found.get("via"), "ok": found.get("ok", True), "reason": "model_skipped_search"})
    return bag


def _review_call(mcp, arguments: dict, bag: dict) -> dict:
    if mcp is not None and "get_restaurant_reviews" in getattr(mcp, "tool_names", []):
        public = mcp.call("get_restaurant_reviews", arguments)
    else:
        from food_copilot.mcp.tools import get_restaurant_reviews

        public = get_restaurant_reviews(
            restaurant_id=arguments.get("restaurant_id") or "",
            name=arguments.get("name") or "",
            limit=int(arguments.get("limit") or 3),
        )
        public["via"] = "local"
    for item in public.get("reviews") or []:
        bag["reviews"].append(item)
    return {"ok": public.get("ok", True), "count": len(public.get("reviews") or []), "note": public.get("note")}


def _attach_reviews(mcp, bag: dict) -> None:
    for card in (bag.get("results") or [])[:3]:
        _review_call(mcp, {"restaurant_id": card.get("restaurant_id") or "", "name": card.get("name") or "", "limit": 2}, bag)


def _attach_web(search, query: str, bag: dict) -> dict:
    if search is None:
        return {"ok": False, "error": "web_search_unavailable"}
    try:
        found = search(query)
    except Exception as exc:
        logger.exception("web search failed")
        found = {"ok": False, "error": exc.__class__.__name__, "results": []}
    from food_copilot.retrieval.web_search import source_is_restaurant

    pages = []
    for item in (found.get("results") or [])[:4]:
        pages.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("snippet"),
            "restaurant_page": bool(source_is_restaurant(item)),
        })
    bag["web"].extend(pages)
    return {"ok": bool(found.get("ok")), "error": found.get("error"), "results": pages}


def _facts(cards: list[dict], reviews: list[dict], web: list[dict]) -> dict:
    slim = []
    gaps = []
    for card in cards:
        address = card.get("stored_address") or None
        price = card.get("price_status") or card.get("price_max_myr")
        slim.append({
            "restaurant_id": card.get("restaurant_id"),
            "name": card.get("name"),
            "cuisine": card.get("cuisine_label"),
            "address": address,
            "address_verified": bool(card.get("location_verified")),
            "price_status": card.get("price_status") or "not_verified",
            "halal_status": card.get("halal_status") or "not_verified",
            "match_reason": card.get("match_reason"),
        })
        if not address:
            gaps.append(f"{card.get('name')}: street address is not on file")
        if not card.get("location_verified"):
            gaps.append(f"{card.get('name')}: location is not verified")
    if not reviews:
        gaps.append("No confirmed review excerpt was attached.")
    return {"candidates": slim, "reviews": reviews[:6], "web": web[:4], "gaps": gaps[:12]}


def _rank(model, query: str, cards: list[dict], packet: dict) -> tuple[list[dict], str]:
    if model is None or len(cards) < 2:
        return cards, ""
    known = {card.get("restaurant_id"): card for card in cards if card.get("restaurant_id")}
    started = time.perf_counter()
    try:
        reply = model.complete(
            [
                {"role": "system", "content": _RANK_SYSTEM},
                {"role": "user", "content": json.dumps({"request": query, "facts": packet}, ensure_ascii=False)[:5000]},
            ],
            role="rank",
            max_tokens=300,
            timeout=12,
        )
        body = _parse_json(reply.get("content") or "")
    except Exception as exc:
        logger.warning("rank model failed: %s", exc.__class__.__name__)
        return cards, f"Ranking model failed ({exc.__class__.__name__}). Stored retrieval order was kept."
    logger.info("agent=rank latency_ms=%s", round((time.perf_counter() - started) * 1000))
    ordered = []
    seen = set()
    for restaurant_id in body.get("order") or []:
        if restaurant_id in known and restaurant_id not in seen:
            ordered.append(known[restaurant_id])
            seen.add(restaurant_id)
    for card in cards:
        if card.get("restaurant_id") not in seen:
            ordered.append(card)
    notes = body.get("notes") if isinstance(body.get("notes"), list) else []
    return ordered, "; ".join(str(item) for item in notes[:4])


def _synthesize(model, query: str, plan: IntentPlan, cards: list[dict], packet: dict, language: str) -> tuple[str | None, str]:
    if model is None:
        return None, "The recommendation model is not configured, so this is the stored list and not a written recommendation."
    started = time.perf_counter()
    try:
        reply = model.complete(
            [
                {"role": "system", "content": _SYNTH_SYSTEM + f" Reply language: {language}."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"request": query, "plan": plan.model_dump(), "facts": packet},
                        ensure_ascii=False,
                    )[:7000],
                },
            ],
            role="synthesis",
            max_tokens=700,
            timeout=20,
        )
        body = _parse_json(reply.get("content") or "")
    except Exception as exc:
        logger.warning("synthesis failed: %s", exc.__class__.__name__)
        return None, f"The recommendation model failed ({exc.__class__.__name__}). The stored list is shown instead."
    logger.info("agent=synthesis latency_ms=%s", round((time.perf_counter() - started) * 1000))
    message = str(body.get("message") or "").strip()
    known = {card.get("restaurant_id") for card in cards}
    extra = [item for item in (body.get("restaurant_ids") or []) if item not in known]
    if extra:
        logger.warning("synthesis dropped unknown ids")
    if not message:
        return None, "The recommendation model returned an empty message. The stored list is shown instead."
    return message, "Final recommendation written by the model from retrieved restaurants."


def _fallback_answer(constraints: dict, cards: list[dict], note: str) -> str:
    listed = present_results(constraints, cards, total=len(cards))
    return f"{note}\n\n{listed}" if note else listed


def _constraints_dict(plan: IntentPlan, found: dict) -> dict:
    raw = dict(found.get("constraints") or {})
    raw.setdefault("region", plan.region)
    raw.setdefault("city", plan.city)
    raw.setdefault("cuisine", plan.cuisines[0] if len(plan.cuisines) == 1 else None)
    raw.setdefault("cuisines", plan.cuisines)
    raw.setdefault("name_contains", plan.name_contains)
    raw.setdefault("max_budget_myr", plan.max_budget_myr)
    raw.setdefault("budget_mode", plan.budget_mode)
    raw.setdefault("ambience", plan.ambience)
    return raw


def run_agent_workflow(
    query: str,
    repository=None,
    search=None,
    history: list | None = None,
    context: dict | None = None,
    model=_ENV_MODEL,
    mcp=None,
) -> dict:
    started = time.perf_counter()
    history = history or []
    context = context or {}
    agents = []
    if model is _ENV_MODEL:
        model, status = _model()
        model_name = status.get("model") or ""
    elif model is None:
        model_name = ""
    else:
        model_name = getattr(model, "model_name", "scripted")
    text, skipped_names = apply_history(query, history, context)
    decision = classify_intent(query, history, context)
    if decision.intent == "clarify":
        payload = _base(decision.clarification or NO_SESSION_FOLLOWUP, {}, [])
        payload.update({
            "needs_clarification": True,
            "intent": "clarify",
            "agent_mode": "multi_agent",
            "model_name": model_name,
            "model_note": "Follow-up had no saved restaurant context. No search was run.",
            "llm_called": False,
        })
        return _finish(payload, started, ["intent_agent"], agents, mcp)
    language = reply_language(query, history)
    intent_started = time.perf_counter()
    if decision.intent == "general_qa":
        plan = IntentPlan(task="general_qa")
        intent_note = "general question"
        intent_ok = True
    elif model is None:
        plan = _plan_from_parser(text)
        intent_note = "OPENAI_API_KEY is not set. Intent used the constraint parser, not a model."
        intent_ok = False
    else:
        plan, intent_note, intent_ok = _intent_from_model(model, text, history, context)
    agents.append({"name": "intent", "ok": intent_ok, "latency_ms": round((time.perf_counter() - intent_started) * 1000)})
    if plan.task == "general_qa" or decision.intent == "general_qa":
        from food_copilot.agents.discovery_graph import _answer_general

        answer, used_model, note, called, latency = _answer_general(query, language)
        agents.append({"name": "general", "ok": called, "latency_ms": latency})
        payload = _base(answer, {}, [])
        payload.update({
            "intent": "general_qa",
            "agent_mode": "multi_agent",
            "model_name": used_model or model_name,
            "model_note": note,
            "llm_called": called,
            "retriever": "none",
        })
        return _finish(payload, started, ["intent_agent", "general_agent"], agents, mcp)
    from food_copilot.config.settings import web_search_enabled

    web_on = web_search_enabled() or search is not None
    if search is None and web_search_enabled():
        from food_copilot.agents.discovery_graph import _live_search

        search = _live_search
    exclude_ids = [str(item) for item in (context.get("shown_ids") or []) if item] if skipped_names or decision.intent == "restaurant_followup" else []
    if plan.needs_reviews is False and _review_request(query):
        plan.needs_reviews = True
    tool_started = time.perf_counter()
    bag = _tool_loop(model, mcp, plan, text, exclude_ids, repository, search, web_on)
    agents.append({"name": "discovery", "ok": bool(bag.get("results")) or bool(bag.get("calls")), "latency_ms": round((time.perf_counter() - tool_started) * 1000)})
    cards = list(bag.get("results") or [])
    packet = _facts(cards, bag.get("reviews") or [], bag.get("web") or [])
    rank_started = time.perf_counter()
    cards, rank_note = _rank(model, query, cards, packet)
    agents.append({"name": "ranking", "ok": True, "latency_ms": round((time.perf_counter() - rank_started) * 1000)})
    if rank_note:
        packet["ranking_notes"] = rank_note
    synth_started = time.perf_counter()
    message, synth_note = _synthesize(model, query, plan, cards, packet, language)
    agents.append({"name": "synthesis", "ok": message is not None, "latency_ms": round((time.perf_counter() - synth_started) * 1000)})
    constraints = _constraints_dict(plan, bag)
    if message:
        answer = message
        synthesis = "written"
    else:
        answer = _fallback_answer(constraints, cards, synth_note)
        synthesis = "fallback"
    if bag.get("web"):
        lines = [answer, "", "Web sources:"]
        for page in bag["web"][:3]:
            if page.get("url"):
                lines.append(f"- {page.get('title') or 'source'}: {page['url']}")
        answer = "\n".join(lines)
    called_tools = []
    for item in bag.get("calls") or []:
        via = item.get("via") or "mcp"
        called_tools.append(f"{via}:{item.get('tool')}")
    if model is not None:
        called_tools.extend(["llm:intent", "llm:synthesis"])
    payload = _base(answer, constraints, cards)
    payload.update({
        "intent": plan.task,
        "agent_mode": "multi_agent",
        "model_name": model_name,
        "model_note": " ".join(part for part in (intent_note, rank_note, synth_note) if part),
        "llm_called": model is not None and message is not None,
        "retriever": bag.get("retriever") or "bm25",
        "tools_called": called_tools,
        "review_evidence": bag.get("reviews") or [],
        "review_note": "Confirmed review excerpts are included." if bag.get("reviews") else "",
        "exclusion_counts": {},
        "language": language,
    })
    payload["trace_extra"] = {"synthesis": synthesis, "mcp_tools": list(getattr(mcp, "tool_names", []) or [])}
    return _finish(payload, started, ["intent_agent", "discovery_agent", "ranking_agent", "synthesis_agent"], agents, mcp)


def _review_request(query: str) -> bool:
    import re

    return bool(re.search(r"based on review|from reviews|what should i eat|what to eat|popular dish|评价|评论", query or "", re.I))


def _base(answer: str, constraints: dict, results: list) -> dict:
    return {
        "answer": answer,
        "constraints": constraints,
        "results": results,
        "exclusion_counts": {},
        "needs_clarification": False,
        "sources_note": "Shown restaurants come from retrieval. Unverified fields stay unverified.",
        "tools_called": [],
        "language": "en",
        "retriever": "bm25",
    }


def _finish(payload: dict, started: float, nodes: list[str], agents: list[dict], mcp) -> dict:
    extra = payload.pop("trace_extra", {})
    mcp_status = getattr(mcp, "status", None) or "disconnected"
    payload["trace"] = {
        "total_ms": round((time.perf_counter() - started) * 1000),
        "nodes": nodes,
        "tools": payload.get("tools_called") or [],
        "llm_called": bool(payload.get("llm_called")),
        "model": payload.get("model_name") or "",
        "model_note": payload.get("model_note") or "",
        "retriever": payload.get("retriever") or "",
        "intent": payload.get("intent") or "",
        "agents": agents,
        "synthesis": extra.get("synthesis", "not_run"),
        "mcp_status": mcp_status,
        "mcp_tools": extra.get("mcp_tools") or list(getattr(mcp, "tool_names", []) or []),
        "stages": {},
        "timing_note": "total_ms is the multi-agent wall clock.",
    }
    from food_copilot.agents import discovery_graph

    discovery_graph.LAST_TRACE = payload["trace"]
    return payload
