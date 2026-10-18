"""Route a turn before any restaurant lookup.

Clear cases use a light rule. Ambiguous text is classified by the configured model.
A failed router does not become a restaurant search.
"""

import re
import time
from dataclasses import dataclass

from food_copilot.agents.context import is_followup_phrase, is_model_question
from food_copilot.retrieval.constraints import parse_constraints

_GENERAL = re.compile(
    r"^\s*(?:can i ask\s+)?(?:what is|what's|what are|who is|explain|define|tell me about)\b",
    re.I,
)
_GENERAL_ZH = re.compile(r"什么是|啥是|是什么|解释一下")
_SEARCH = re.compile(
    r"\b(recommend|recommendation|recomendation|find|search|show me|looking for|i want|where|restaurant|cafe|bbq|barbecue)\b|推荐|餐厅|找一家|哪里|在哪",
    re.I,
)
_FACT = re.compile(r"\b(sell|selling|serve|serves|taste)\b|卖不卖|卖什么|jual", re.I)
_CHEAP = re.compile(r"murah|cheap|affordable|便宜", re.I)
_LABELS = {"general_qa", "restaurant_search", "restaurant_followup"}

NO_SESSION_FOLLOWUP = (
    "This session has no earlier restaurant search to continue. "
    "Ask for the kind of food you want. "
    "The search area is Old Klang Road."
)


@dataclass
class IntentDecision:
    intent: str
    method: str
    clarification: str | None
    model: str
    model_note: str
    router_called: bool
    router_used: bool
    router_ms: int


def _has_restaurant_context(history: list | None, context: dict | None) -> bool:
    saved = context or {}
    if saved.get("region") or saved.get("city") or saved.get("cuisine"):
        return True
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        parsed = parse_constraints(str(item.get("content") or ""))
        return bool(parsed.region or parsed.city or parsed.cuisine)
    return False


def _clear_general(query: str) -> bool:
    if _FACT.search(query or "") and not _SEARCH.search(query or ""):
        return True
    if not (_GENERAL.search(query or "") or _GENERAL_ZH.search(query or "") or is_model_question(query)):
        return False
    parsed = parse_constraints(query or "")
    if parsed.region or parsed.city:
        return False
    if _SEARCH.search(query or ""):
        return False
    return True


def _clear_restaurant(query: str) -> bool:
    parsed = parse_constraints(query or "")
    if parsed.region or parsed.city or parsed.cuisine or parsed.max_budget_myr is not None:
        return True
    return bool(_SEARCH.search(query or "") or _CHEAP.search(query or ""))


def _rule(intent: str, clarification: str | None = None) -> IntentDecision:
    return IntentDecision(
        intent=intent,
        method="rule",
        clarification=clarification,
        model="",
        model_note="Clear request. No intent-router model call.",
        router_called=False,
        router_used=False,
        router_ms=0,
    )


def _parse_label(text: str) -> str | None:
    cleaned = (text or "").strip().lower().replace("-", "_").replace(" ", "_")
    for label in _LABELS:
        if label in cleaned:
            return label
    return None


def _route_with_model(query: str) -> IntentDecision:
    from food_copilot.agents.model import OpenAIChatModel, openai_status

    started = time.perf_counter()
    status = openai_status()
    if not status["configured"]:
        return IntentDecision(
            intent="clarify",
            method="failed",
            clarification=(
                "No model is configured, and this message is not a clear restaurant search or a clear general question. "
                "Ask it again in one of those forms. No area was assumed."
            ),
            model=status["model"],
            model_note="OPENAI_API_KEY is not set; the intent was not guessed",
            router_called=False,
            router_used=False,
            router_ms=0,
        )
    messages = [
        {
            "role": "system",
            "content": (
                "Classify the user message. Reply with exactly one label and nothing else: "
                "general_qa, restaurant_search, or restaurant_followup. "
                "general_qa is a definition, concept, or chat that is not asking where to eat. "
                "restaurant_search asks for a place to eat. "
                "restaurant_followup continues an earlier restaurant request."
            ),
        },
        {"role": "user", "content": (query or "")[:500]},
    ]
    try:
        text = OpenAIChatModel().complete(messages, timeout=6, max_tokens=16, role="intent").get("content") or ""
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return IntentDecision(
            intent="clarify",
            method="failed",
            clarification=(
                f"The intent check failed ({exc.__class__.__name__}). "
                "This was not treated as a restaurant search, and no area was required."
            ),
            model=status["model"],
            model_note=f"intent router failed ({exc.__class__.__name__})",
            router_called=True,
            router_used=False,
            router_ms=elapsed,
        )
    elapsed = round((time.perf_counter() - started) * 1000)
    label = _parse_label(text)
    if label is None:
        return IntentDecision(
            intent="clarify",
            method="failed",
            clarification=(
                "The intent check did not return a usable label. "
                "This was not treated as a restaurant search, and no area was required."
            ),
            model=status["model"],
            model_note="intent router returned an unusable label",
            router_called=True,
            router_used=False,
            router_ms=elapsed,
        )
    return IntentDecision(
        intent=label,
        method="llm",
        clarification=None,
        model=status["model"],
        model_note="intent classified by the model",
        router_called=True,
        router_used=True,
        router_ms=elapsed,
    )


def classify_intent(query: str, history: list | None = None, context: dict | None = None) -> IntentDecision:
    if _clear_general(query):
        return _rule("general_qa")
    if is_followup_phrase(query):
        if _has_restaurant_context(history, context):
            return _rule("restaurant_followup")
        return _rule("clarify", NO_SESSION_FOLLOWUP)
    if _clear_restaurant(query):
        return _rule("restaurant_search")
    decision = _route_with_model(query)
    if decision.intent == "restaurant_followup" and not _has_restaurant_context(history, context):
        decision.intent = "clarify"
        decision.clarification = NO_SESSION_FOLLOWUP
    return decision
