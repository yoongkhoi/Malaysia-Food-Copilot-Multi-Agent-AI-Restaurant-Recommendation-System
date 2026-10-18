"""LangGraph discovery path. Parsing, retrieval, and checks are Python. Search is a real tool call."""

import re
import time
from typing import TypedDict

from food_copilot.agents.context import alternative_web_query, apply_history, present_results, web_query
from food_copilot.agents.intent_router import classify_intent
from food_copilot.config.settings import feature_flags, web_search_enabled
from food_copilot.retrieval.web_search import source_is_restaurant
from food_copilot.data.discoveries import consider_web_result
from food_copilot.services.discovery import DiscoveryService, DeterministicIntentParser, reply_language


class DiscoveryState(TypedDict, total=False):
    query: str
    history: list
    context: dict
    intent: str
    intent_method: str
    router_called: bool
    router_used: bool
    context_update: str
    model_name: str
    model_note: str
    reply_language: str
    request: dict
    exclude_names: list
    exclude_ids: list
    skip_web: bool
    local: dict
    web: dict
    discoveries: list
    payload: dict
    stages: dict
    nodes_run: list


def build_discovery_graph(repository=None, search=None):
    from langgraph.graph import END, START, StateGraph

    service = DiscoveryService(repository=repository)
    parser = DeterministicIntentParser()
    search_fn = search

    def intent(state: DiscoveryState) -> dict:
        started = time.perf_counter()
        decision = classify_intent(state.get("query") or "", state.get("history") or [], state.get("context") or {})
        stages = {"intent_ms": round((time.perf_counter() - started) * 1000), "route_llm_ms": decision.router_ms}
        language = reply_language(state.get("query") or "", state.get("history") or [])
        common = {
            "intent": decision.intent,
            "intent_method": decision.method,
            "router_called": decision.router_called,
            "router_used": decision.router_used,
            "model_name": decision.model,
            "model_note": decision.model_note,
            "reply_language": language,
            "stages": stages,
            "nodes_run": ["intent"],
        }
        if decision.intent == "general_qa":
            return {**common, "context_update": "keep"}
        if decision.intent == "clarify":
            return {
                **common,
                "context_update": "keep",
                "request": {
                    "text": state.get("query") or "",
                    "language": "en",
                    "clarification": decision.clarification,
                    "constraints": {},
                },
            }
        text, exclude = apply_history(state.get("query") or "", state.get("history") or [], state.get("context") or {})
        request = parser.parse(text)
        if request.clarification and request.constraints.cuisine:
            context_update = "partial"
        elif request.clarification:
            context_update = "keep"
        else:
            context_update = "accumulate" if exclude else "replace"
        return {
            **common,
            "request": {
                "text": request.text,
                "language": request.language,
                "clarification": request.clarification,
                "constraints": request.constraints.model_dump(),
            },
            "exclude_names": exclude,
            "exclude_ids": [str(item) for item in ((state.get("context") or {}).get("shown_ids") or []) if item] if exclude else [],
            "skip_web": bool(exclude) or bool(request.constraints.name_contains and not request.constraints.cuisine),
            "context_update": context_update,
        }

    def after_intent(state: DiscoveryState) -> str:
        if state.get("intent") == "general_qa":
            return "general"
        if (state.get("request") or {}).get("clarification"):
            return "finalize"
        return "retrieve"

    def general(state: DiscoveryState) -> dict:
        cached = _cached_general(state.get("query") or "")
        if cached:
            answer = cached["answer"]
            model_name = cached["model"]
            model_note = "reused the earlier model answer for this question; the model was not called again"
            called = False
            llm_ms = 0
            tools = ["answer_cache"]
        else:
            answer, model_name, model_note, called, llm_ms = _answer_general(
                state.get("query") or "",
                state.get("reply_language") or "en",
            )
            tools = ["intent_router"] if state.get("router_called") else []
            tools.append("llm" if called else "intent")
            if called:
                _store_general(state.get("query") or "", answer, model_name)
        note = model_note
        if state.get("router_called") and not cached:
            note = f"{state.get('model_note') or ''} {model_note}".strip()
        stages = dict(state.get("stages") or {})
        stages["answer_llm_ms"] = llm_ms
        payload = _empty_payload(answer, tools, model_name or state.get("model_name") or "", note)
        payload["intent"] = "general_qa"
        payload["context_update"] = "keep"
        payload["llm_called"] = called or bool(state.get("router_used"))
        payload["retriever"] = "none"
        return {
            "payload": payload,
            "stages": stages,
            "nodes_run": [*(state.get("nodes_run") or []), "general"],
            "model_name": payload["model_name"],
            "model_note": note,
        }

    def retrieve(state: DiscoveryState) -> dict:
        started = time.perf_counter()
        from food_copilot.domain.models import UserRequest
        from food_copilot.retrieval.constraints import QueryConstraints

        stored = state["request"]
        request = UserRequest(
            text=stored["text"],
            language=stored["language"],
            constraints=QueryConstraints.model_validate(stored["constraints"]),
            clarification=stored.get("clarification"),
        )
        try:
            local = service.from_constraints(
                request.constraints,
                query_text=request.text,
                request=request,
                include_web=False,
                exclude_names=state.get("exclude_names") or [],
                exclude_ids=state.get("exclude_ids") or [],
            )
        except Exception as exc:
            local = {
                "answer": (
                    f"The restaurant lookup failed ({exc.__class__.__name__}). "
                    "No restaurant names were added from model memory."
                ),
                "results": [],
                "constraints": request.constraints.model_dump(),
                "tools_called": [],
                "needs_clarification": False,
                "match_count": 0,
                "cuisine_counts": {},
                "lookup_error": True,
            }
        local.pop("raw_results", None)
        local.pop("constraints_model", None)
        stages = dict(state.get("stages") or {})
        stages["retrieve_ms"] = round((time.perf_counter() - started) * 1000)
        if isinstance(local.get("candidate_count"), int):
            stages["candidate_count"] = local["candidate_count"]
        if isinstance(local.get("match_count"), int):
            stages["eligible_count"] = local["match_count"]
        return {
            "local": local,
            "stages": stages,
            "nodes_run": [*(state.get("nodes_run") or []), "retrieve"],
        }

    def search_node(state: DiscoveryState) -> dict:
        started = time.perf_counter()
        local_count = int((state.get("local") or {}).get("match_count") or 0)
        if state.get("skip_web") or (state.get("intent") == "restaurant_followup" and local_count > 0):
            web = {"ok": False, "error": "skipped_follow_up", "results": [], "query": ""}
        else:
            constraints = (state.get("request") or {}).get("constraints") or {}
            query = web_query(constraints)
            if search_fn is None and not web_search_enabled():
                web = {"ok": False, "error": "disabled", "results": [], "query": query}
            else:
                fn = search_fn or _live_search
                try:
                    web = fn(query)
                except Exception as exc:
                    web = {"ok": False, "error": exc.__class__.__name__, "results": [], "query": query}
                if web.get("error") in {"no_results", "parse_failed"}:
                    alternate = alternative_web_query(constraints)
                    if alternate and alternate != query:
                        try:
                            second = fn(alternate)
                        except Exception as exc:
                            second = {"ok": False, "error": exc.__class__.__name__, "results": [], "query": alternate}
                        web = dict(web)
                        web["alternative_query"] = alternate
                        web["alternative_error"] = second.get("error")
                        if second.get("ok") and second.get("results"):
                            web = dict(second)
                            web["alternative_query"] = alternate
        stages = dict(state.get("stages") or {})
        stages["search_ms"] = round((time.perf_counter() - started) * 1000)
        return {"web": web, "stages": stages, "nodes_run": [*(state.get("nodes_run") or []), "search"]}

    def match(state: DiscoveryState) -> dict:
        started = time.perf_counter()
        local = state.get("local") or {}
        web = state.get("web") or {"ok": False, "error": "not_run", "results": []}
        try:
            names = [
                (row.get("restaurant_id") or "", row.get("name") or "")
                for row in service.repository.list_restaurants()
            ]
        except Exception:
            names = []
        notes = []
        constraints = (state.get("request") or {}).get("constraints") or {}
        if local.get("lookup_error"):
            local["agent_mode"] = "langgraph"
            local["intent"] = state.get("intent") or "restaurant_search"
            local["llm_called"] = False
            local["model_note"] = "Restaurant lookup failed before ranking. The model was not asked to fill the list."
            stages = dict(state.get("stages") or {})
            stages["match_ms"] = round((time.perf_counter() - started) * 1000)
            stages["phrase_llm_ms"] = 0
            return {
                "payload": local,
                "discoveries": [],
                "stages": stages,
                "nodes_run": [*(state.get("nodes_run") or []), "match"],
            }
        web_results = [item for item in (web.get("results") or []) if source_is_restaurant(item)]
        visible_sources = []
        outside_area = 0
        for item in web_results:
            note = consider_web_result(item, constraints, names)
            notes.append(note)
            if note.get("action") == "skipped":
                if note.get("reason") == "region_not_in_source":
                    outside_area += 1
            else:
                visible_sources.append(item)
        answer = present_results(
            constraints,
            local.get("results") or [],
            local.get("match_count"),
            local.get("cuisine_counts"),
        )
        tools = list(local.get("tools_called") or [])
        tools.append("bm25" if getattr(service.ranker, "name", "") == "bm25" else "baseline_retrieval")
        if constraints.get("name_contains"):
            lines = []
        elif web.get("error") == "skipped_follow_up":
            lines = ["Web search skipped for this follow-up so the next local matches return faster."]
        elif web.get("ok"):
            tools.append("web_search")
            lines = ["Web sources, not treated as a confirmed branch:"]
            for item in visible_sources:
                lines.append(f"- {item.get('title')}: {item.get('url')}")
            if outside_area:
                lines.append(
                    f"{outside_area} web result(s) named a place outside the requested area and were not listed."
                )
            if not visible_sources:
                lines.append("No web result was verified as a canonical restaurant in the requested area.")
            inserted = [item["restaurant_id"] for item in notes if item.get("action") == "inserted"]
            if inserted:
                lines.append(
                    "Unconfirmed discoveries saved for later retrieval: "
                    + ", ".join(inserted)
                    + ". Address, price, and halal status were not filled in."
                )
        else:
            tools.append("web_search")
            if local.get("results"):
                lines = [f"Web search failed ({web.get('error')}). Local restaurant matches are still listed."]
            else:
                lines = [f"Web search failed ({web.get('error')}). No local restaurant was listed."]
            if web.get("alternative_error"):
                lines.append(f"A second search also failed ({web.get('alternative_error')}).")
        local["answer"] = answer + "\n" + "\n".join(lines)
        local["tools_called"] = tools
        local["agent_mode"] = "langgraph"
        local["discoveries"] = notes
        local["reply_language"] = state.get("reply_language") or "en"
        checked_ms = round((time.perf_counter() - started) * 1000)
        count_question = bool(re.search(r"how many|berapa|多少|几家", state.get("query") or "", re.I))
        has_cards = bool(local.get("results"))
        atmosphere_unknown = constraints.get("ambience") and local.get("atmosphere") != "supported"
        if _wants_reviews(state.get("query") or ""):
            from food_copilot.reviews.recommend import apply_review_recommendation

            try:
                canonical_rows = service.repository.list_restaurants()
            except Exception:
                canonical_rows = []
            apply_review_recommendation(local, state.get("query") or "", constraints, canonical_rows)
        elif feature_flags().get("ENABLE_REVIEW_RAG"):
            try:
                canonical_rows = service.repository.list_restaurants()
            except Exception:
                canonical_rows = []
            from food_copilot.reviews.evidence import append_review_evidence

            append_review_evidence(local, state.get("query") or "", constraints, canonical_rows)
        if search_fn is not None:
            phrased, model_name, model_note, called, phrase_ms = (
                local["answer"], "", "model step skipped in this test", False, 0,
            )
        elif atmosphere_unknown:
            phrased, model_name, model_note, called, phrase_ms = (
                local["answer"],
                "",
                "The model was not called. Stored records do not support the requested atmosphere, so the model was not asked to invent it.",
                False,
                0,
            )
        elif not has_cards or count_question or (constraints.get("name_contains") and not constraints.get("cuisine") and not constraints.get("cuisines")):
            phrased, model_name, model_note, called, phrase_ms = (
                local["answer"],
                "",
                "The stored records answer this directly. The model was not asked to rewrite the count or the branch list.",
                False,
                0,
            )
        else:
            from food_copilot.config.settings import _flag

            if _flag("ENABLE_PHRASE_LLM"):
                phrased, model_name, model_note, called, phrase_ms = _phrase(state.get("query") or "", local)
                grounded, grounded_note = _ground_phrase(phrased, local.get("results") or [])
                if grounded is None:
                    phrased = local["answer"]
                    model_note = grounded_note
            else:
                phrased, model_name, model_note, called, phrase_ms = (
                    local["answer"],
                    "",
                    "The stored restaurant list is the reply. A rewrite model was not called.",
                    False,
                    0,
                )
        local["answer"] = phrased
        local["model_name"] = model_name
        local["model_note"] = model_note
        if called:
            local["tools_called"] = tools + ["llm"]
        local["intent"] = state.get("intent") or "restaurant_search"
        local["context_update"] = state.get("context_update") or "replace"
        local["llm_called"] = called or bool(state.get("router_used"))
        if state.get("router_called") and "intent_router" not in local["tools_called"]:
            local["tools_called"] = ["intent_router", *local["tools_called"]]
        stages = dict(state.get("stages") or {})
        stages["match_ms"] = checked_ms
        stages["phrase_llm_ms"] = phrase_ms
        return {
            "payload": local,
            "discoveries": notes,
            "stages": stages,
            "nodes_run": [*(state.get("nodes_run") or []), "match"],
        }

    def finalize(state: DiscoveryState) -> dict:
        nodes = [*(state.get("nodes_run") or []), "finalize"]
        if state.get("payload"):
            return {"nodes_run": nodes}
        request = state.get("request") or {}
        clarification = request.get("clarification") or "The request could not continue."
        tools = ["intent_router"] if state.get("router_called") else ["intent"]
        outcome = _empty_payload(
            clarification,
            tools,
            state.get("model_name") or "",
            state.get("model_note") or "No model answer. Restaurant retrieval did not run.",
        )
        outcome["needs_clarification"] = True
        outcome["intent"] = state.get("intent") or "clarify"
        outcome["context_update"] = state.get("context_update") or "keep"
        outcome["llm_called"] = bool(state.get("router_used"))
        outcome["retriever"] = "none"
        outcome["constraints"] = request.get("constraints") or {}
        return {"payload": outcome, "nodes_run": nodes}

    graph = StateGraph(DiscoveryState)
    graph.add_node("intent", intent)
    graph.add_node("general", general)
    graph.add_node("retrieve", retrieve)
    graph.add_node("search", search_node)
    graph.add_node("match", match)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent",
        after_intent,
        {"general": "general", "retrieve": "retrieve", "finalize": "finalize"},
    )
    graph.add_edge("general", "finalize")
    graph.add_edge("retrieve", "search")
    graph.add_edge("search", "match")
    graph.add_edge("match", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _language_order(language: str) -> str:
    if language == "ms":
        return "Reply only in Malay."
    if language in {"zh", "mixed"}:
        return "只用中文回答。"
    return "Reply only in English."


def _ground_phrase(text: str, cards: list[dict]) -> tuple[str | None, str]:
    """Reject a completion that names a restaurant outside the retrieved cards."""
    allowed = " ".join(
        [
            *(str(card.get("name") or "") for card in cards),
            *(str(card.get("stored_address") or "") for card in cards),
            *(str(card.get("cuisine_label") or "") for card in cards),
            "old klang road kuala lumpur korean japanese chinese malay indian thai cafe bbq chicken",
        ]
    ).casefold()
    suspects = re.findall(r"\b[A-Z][a-zA-Z'&]{2,}(?:\s+[A-Z][a-zA-Z'&]{2,}){0,3}", text or "")
    for name in suspects:
        if name.casefold() not in allowed:
            return None, "The completion named a restaurant that is not in the retrieved records, so the stored list was kept."
    return text, ""


def _phrase(query: str, local: dict) -> tuple[str, str, str, bool, int]:
    """One short completion. A timeout keeps the Python answer."""
    from food_copilot.agents.model import OpenAIChatModel, openai_status

    started = time.perf_counter()
    status = openai_status()
    template = local.get("answer") or ""
    if not status["configured"]:
        return template, status["model"], "OPENAI_API_KEY is not set. This reply is the Python template.", False, 0
    names = [item.get("name") for item in (local.get("results") or []) if item.get("name")]
    messages = [
        {
            "role": "system",
            "content": (
                "You write a short restaurant reply. Use only the restaurant names provided. "
                "Do not invent prices, addresses, reviews, or halal certification. "
                "If a price is unknown, say it is omitted. "
                + _language_order(local.get("reply_language") or "en")
            ),
        },
        {
            "role": "user",
            "content": f"Question: {query}\nRestaurants: {', '.join(names) or 'none'}\nFacts:\n{template[:1200]}",
        },
    ]
    try:
        text = OpenAIChatModel().complete(messages, timeout=4, role="synthesis").get("content") or ""
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return template, status["model"], f"model call failed ({exc.__class__.__name__}); Python template kept", False, elapsed
    elapsed = round((time.perf_counter() - started) * 1000)
    if not text.strip():
        return template, status["model"], "model returned empty text; Python template kept", False, elapsed
    return text.strip(), status["model"], "one completion; restaurant cards stay on the stored records", True, elapsed


def _answer_general(query: str, language: str = "en") -> tuple[str, str, str, bool, int]:
    """Answer a non-restaurant question with the configured model. Never invent that answer."""
    from food_copilot.agents.model import OpenAIChatModel, openai_status

    started = time.perf_counter()
    status = openai_status()
    if not status["configured"]:
        return (
            "No model is configured, so this general question was not answered. No restaurant search was run.",
            status["model"],
            "OPENAI_API_KEY is not set",
            False,
            0,
        )
    messages = [
        {
            "role": "system",
            "content": (
                "Answer the user's general question directly and briefly. "
                "Do not recommend restaurants and do not ask for a city or area. "
                f"If they ask which model is in use, say the configured model id is {status['model']}. "
                "Never mention API keys, passwords, or connection strings. "
                + _language_order(language)
            ),
        },
        {"role": "user", "content": query[:1000]},
    ]
    try:
        text = OpenAIChatModel().complete(messages, timeout=12, max_tokens=400, role="general").get("content") or ""
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return (
            f"The model call failed ({exc.__class__.__name__}). No restaurant search was run, and this text is not a model answer.",
            status["model"],
            f"model call failed ({exc.__class__.__name__})",
            False,
            elapsed,
        )
    elapsed = round((time.perf_counter() - started) * 1000)
    if not text.strip():
        return (
            "The model returned empty text. No restaurant search was run, and this text is not a model answer.",
            status["model"],
            "model returned empty text",
            False,
            elapsed,
        )
    return text.strip(), status["model"], "general question answered by the model; restaurant retrieval was not run", True, elapsed


LAST_TRACE: dict = {}
_GENERAL_CACHE: dict[str, dict] = {}
_GENERAL_CACHE_TTL = 60 * 60


def _general_key(query: str) -> str:
    chars = []
    for ch in (query or "").lower():
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def _cached_general(query: str) -> dict | None:
    item = _GENERAL_CACHE.get(_general_key(query))
    if not item:
        return None
    if time.time() - item["at"] > _GENERAL_CACHE_TTL:
        _GENERAL_CACHE.pop(_general_key(query), None)
        return None
    return item


def _store_general(query: str, answer: str, model: str) -> None:
    _GENERAL_CACHE[_general_key(query)] = {"at": time.time(), "answer": answer, "model": model}


def _wants_reviews(query: str) -> bool:
    return bool(re.search(
        r"based on review|from reviews|according to reviews|what should i eat|what to eat|popular dish|recommend based on review",
        query or "",
        re.I,
    ))


def _live_search(query: str) -> dict:
    from food_copilot.retrieval.web_search import search_web

    return search_web(query)


def _empty_payload(answer: str, tools: list[str], model_name: str, model_note: str) -> dict:
    return {
        "answer": answer,
        "constraints": {},
        "results": [],
        "exclusion_counts": {},
        "needs_clarification": False,
        "sources_note": "Shown facts come from stored records. Unverified fields stay unverified.",
        "tools_called": tools,
        "language": "en",
        "retriever": "bm25",
        "agent_mode": "langgraph",
        "model_name": model_name,
        "model_note": model_note,
    }


def run_discovery_graph(query: str, repository=None, search=None, history: list | None = None, context: dict | None = None) -> dict:
    from food_copilot.config.settings import agent_workflow_enabled

    if agent_workflow_enabled():
        from food_copilot.agents.workflow import run_agent_workflow

        return run_agent_workflow(query, repository=repository, search=search, history=history, context=context)
    started = time.perf_counter()
    graph = build_discovery_graph(repository=repository, search=search)
    result = graph.invoke({"query": query, "history": history or [], "context": context or {}})
    payload = dict(result.get("payload") or {})
    payload.setdefault("agent_mode", "langgraph")
    payload.pop("raw_results", None)
    payload.pop("constraints_model", None)
    payload.pop("discoveries", None)
    tools = payload.get("tools_called") or []
    payload["trace"] = {
        "total_ms": round((time.perf_counter() - started) * 1000),
        "nodes": result.get("nodes_run") or [],
        "tools": tools,
        "llm_called": bool(payload.get("llm_called")) or "llm" in tools,
        "model": payload.get("model_name") or "",
        "model_note": payload.get("model_note") or "",
        "retriever": payload.get("retriever") or "",
        "intent": payload.get("intent") or "",
        "stages": result.get("stages") or {},
        "timing_note": "total_ms is graph wall-clock. Stage times are separate measurements and are not added together.",
    }
    global LAST_TRACE
    LAST_TRACE = payload["trace"]
    return payload
