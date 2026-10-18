import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"
_MEMORY_PUBLIC_ERROR = "Memory stores are unavailable."

from food_copilot.agents.context import merge_context, next_session_context
from food_copilot.agents.intent_router import classify_intent
from food_copilot.agents.orchestrator import handle_message
from food_copilot.config.settings import agent_workflow_enabled, feature_flags
from food_copilot.errors import ModelCallError, ModelConfigError
from food_copilot.mcp.tools import restaurant_details, restaurant_evidence
from food_copilot.memory.store import MemoryStore

router = APIRouter()


class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)


class DiscoveryResponse(BaseModel):
    answer: str
    constraints: dict
    results: list[dict]
    exclusion_counts: dict = Field(default_factory=dict)
    needs_clarification: bool = False
    sources_note: str
    tools_called: list[str] = Field(default_factory=list)
    language: str = ""
    retriever: str = "baseline"


class ChatRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    user_id: str | None = Field(default=None, pattern=_ID)
    session_id: str | None = Field(default=None, pattern=_ID)
    context: dict | None = None


class ChatResponse(DiscoveryResponse):
    memory_saved: bool = False
    memory_note: str = ""
    review_evidence: list[dict] = Field(default_factory=list)
    review_note: str = ""
    proposed_preferences: list[dict] = Field(default_factory=list)
    saved_preferences: list[dict] = Field(default_factory=list)
    temporary_preferences: list[str] = Field(default_factory=list)
    agent_mode: str = "deterministic"
    model_name: str = ""
    model_note: str = ""
    intent: str = ""
    trace: dict = Field(default_factory=dict)


class SessionMessageBody(BaseModel):
    user_id: str = Field(pattern=_ID)
    session_id: str = Field(pattern=_ID)
    content: str = Field(min_length=1, max_length=4000)
    role: Literal["user", "assistant"] = "user"


class PreferenceBody(BaseModel):
    user_id: str = Field(pattern=_ID)
    key: str = Field(pattern=_ID)
    value: str = Field(min_length=1, max_length=500)
    confirmed: bool = True


def _local_memory_open() -> bool:
    from food_copilot.memory.store import load_local_env
    import os

    load_local_env()
    return os.environ.get("ALLOW_UNAUTHENTICATED_MEMORY", "false").strip().lower() in {"1", "true", "yes", "on"}


def _require_local_memory() -> None:
    if not _local_memory_open():
        raise HTTPException(
            status_code=403,
            detail="A browser user id is not an account. Memory routes stay closed until an authenticated identity is configured.",
        )


def _session_history(user_id: str | None, session_id: str | None, store: MemoryStore | None = None) -> list:
    if not user_id or not session_id or not _local_memory_open():
        return []
    try:
        store = store or _memory()
        if store.session_owner(session_id) not in {None, user_id}:
            return []
        return store.recent_messages(session_id)
    except Exception:
        return []


def _session_context(session_id: str | None, store: MemoryStore | None = None) -> dict:
    if not session_id or not _local_memory_open():
        return {}
    try:
        raw = (store or _memory())._redis().get(f"session:{session_id}:context")
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        import json
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _store_session_context(session_id: str | None, payload: dict, store: MemoryStore | None = None) -> None:
    if not session_id or not _local_memory_open():
        return
    import json

    previous = _session_context(session_id, store)
    body = next_session_context(previous, payload)
    if body is None:
        return
    try:
        client = (store or _memory())._redis()
        client.set(f"session:{session_id}:context", json.dumps(body), ex=60 * 60 * 24)
    except Exception:
        return


def _memory() -> MemoryStore:
    store = MemoryStore()
    if not store.status()["postgres"] or not store.status()["redis"]:
        raise HTTPException(status_code=503, detail="Memory stores are not configured")
    return store


def _memory_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=404, detail="Not found")
    return HTTPException(status_code=503, detail=_MEMORY_PUBLIC_ERROR)


@router.get("/memory/status")
def memory_status():
    return MemoryStore().status()


@router.post("/memory/messages")
def memory_append(body: SessionMessageBody):
    _require_local_memory()
    try:
        return _memory().append_message(body.user_id, body.session_id, body.role, body.content)
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.get("/memory/users/{user_id}/sessions")
def memory_sessions(user_id: str = Path(pattern=_ID)):
    _require_local_memory()
    try:
        return {"user_id": user_id, "sessions": _memory().list_sessions(user_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.get("/ops/restaurants")
def ops_restaurants(
    q: str = Query(default="", max_length=80),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    _require_local_memory()
    from food_copilot.data.repository import get_default_repository

    needle = q.casefold().strip()
    rows = get_default_repository().list_restaurants()
    if needle:
        rows = [
            row for row in rows
            if needle in (row.get("name") or "").casefold()
            or needle in " ".join(row.get("cuisine") or []).casefold()
            or needle in " ".join(row.get("regions") or []).casefold()
        ]
    page = rows[offset:offset + limit]
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "restaurants": [
            {
                "restaurant_id": row.get("restaurant_id"),
                "name": row.get("name"),
                "cuisine": row.get("cuisine") or [],
                "regions": row.get("regions") or [],
                "address": row.get("address"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            }
            for row in page
        ],
    }


class ClearSessionsBody(BaseModel):
    confirm: str


@router.post("/ops/clear-sessions")
def ops_clear_sessions(body: ClearSessionsBody):
    _require_local_memory()
    if body.confirm != "clear-sessions":
        raise HTTPException(status_code=400, detail="Confirmation text did not match.")
    try:
        return _memory().clear_sessions()
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.get("/ops/board")
def ops_board():
    _require_local_memory()
    from food_copilot.data.repository import get_default_repository

    try:
        board = _memory().ops_snapshot()
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc
    rows = get_default_repository().list_restaurants()
    board["restaurants"] = {
        "source": "data/processed/restaurants.json plus discovered sidecar",
        "records": len(rows),
        "discovered": sum(1 for row in rows if row.get("dataset_origin") == "discovered"),
        "stored_in": "JSON file, not Neon",
    }
    return board


@router.get("/memory/sessions/{session_id}")
def memory_session(
    session_id: str = Path(pattern=_ID),
    user_id: str = Query(pattern=_ID),
):
    _require_local_memory()
    try:
        store = _memory()
        if store.session_owner(session_id) != user_id:
            raise HTTPException(status_code=404, detail="Not found")
        return {"session_id": session_id, "messages": store.recent_messages(session_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.post("/memory/preferences")
def memory_save_preference(body: PreferenceBody):
    _require_local_memory()
    try:
        return _memory().save_preference(body.user_id, body.key, body.value, body.confirmed)
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.get("/memory/preferences/{user_id}")
def memory_preferences(user_id: str = Path(pattern=_ID)):
    _require_local_memory()
    try:
        return {"user_id": user_id, "preferences": _memory().preferences(user_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


@router.delete("/memory/users/{user_id}")
def memory_delete_user(user_id: str = Path(pattern=_ID)):
    _require_local_memory()
    try:
        return _memory().delete_user(user_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _memory_error(exc) from exc


def _discover_payload(query: str) -> dict:
    outcome = handle_message(query)
    return {
        "answer": outcome["answer"],
        "constraints": outcome["constraints"],
        "results": outcome["results"],
        "exclusion_counts": outcome.get("exclusion_counts") or {},
        "needs_clarification": bool(outcome.get("needs_clarification")),
        "sources_note": outcome["sources_note"],
        "tools_called": outcome.get("tools_called") or [],
        "language": outcome.get("language") or "",
        "retriever": outcome.get("retriever") or "baseline",
    }


def _restaurant_or_404(payload: dict) -> dict:
    if payload.get("ok"):
        return payload
    status = 404 if payload.get("error") == "not_found" else 400
    raise HTTPException(status_code=status, detail=payload)


@router.get("/restaurants/{restaurant_id}")
def restaurant_route(restaurant_id: str):
    return _restaurant_or_404(restaurant_details(restaurant_id))


@router.get("/restaurants/{restaurant_id}/evidence")
def restaurant_evidence_route(restaurant_id: str):
    return _restaurant_or_404(restaurant_evidence(restaurant_id))


@router.post("/chat", response_model=ChatResponse)
def chat_route(request: ChatRequest):
    flags = feature_flags()
    memory_store = None
    if agent_workflow_enabled() or (flags["ENABLE_LANGGRAPH"] and not flags["ENABLE_LLM_AGENT"]):
        from food_copilot.agents.discovery_graph import run_discovery_graph

        history_started = time.perf_counter()
        if request.user_id and request.session_id and _local_memory_open():
            try:
                memory_store = _memory()
            except Exception:
                memory_store = None
        preview = classify_intent(request.query, [], {})
        session_state = {"owner": None, "messages": [], "context": {}}
        if memory_store is not None and request.session_id:
            try:
                session_state = memory_store.read_session(request.session_id)
            except Exception:
                session_state = {"owner": None, "messages": [], "context": {}}
        saved = session_state.get("context") or {}
        if preview.intent == "general_qa" or session_state.get("owner") not in {None, request.user_id}:
            history = []
        else:
            history = session_state.get("messages") or []
        history_ms = round((time.perf_counter() - history_started) * 1000)
        context = merge_context(saved, request.context)
        if agent_workflow_enabled():
            from food_copilot.agents.mcp_host import current_host
            from food_copilot.agents.workflow import run_agent_workflow

            host = current_host()
            payload = run_agent_workflow(
                request.query,
                history=history,
                context=context,
                mcp=host if host.status == "connected" else None,
            )
        else:
            payload = run_discovery_graph(request.query, history=history, context=context)
        payload.setdefault("trace", {}).setdefault("stages", {})["history_ms"] = history_ms
        payload["_session_owner"] = session_state.get("owner")
        payload["_saved_context"] = saved
    elif flags["ENABLE_LLM_AGENT"]:
        from food_copilot.agents.model import openai_status

        if not openai_status()["configured"]:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not set")
        if flags["ENABLE_LANGGRAPH"]:
            from food_copilot.agents.graph import run_chat_graph

            try:
                return run_chat_graph(
                    request.query,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    memory=MemoryStore(),
                )
            except ModelConfigError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ModelCallError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        from food_copilot.agents.runtime import answer_with_agents

        try:
            payload = answer_with_agents(
                request.query,
                user_id=request.user_id,
                session_id=request.session_id,
                memory=MemoryStore(),
            )
        except ModelConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ModelCallError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        payload = _discover_payload(request.query)
    payload["memory_saved"] = False
    payload["memory_note"] = ""
    saved_context = payload.pop("_saved_context", {})
    known_owner = payload.pop("_session_owner", None)
    if bool(request.user_id) != bool(request.session_id):
        payload["memory_note"] = "Both user_id and session_id are required before a conversation can be saved."
        return payload
    if request.user_id and request.session_id:
        if not _local_memory_open():
            payload["memory_note"] = "A browser user id is not an account. The answer was not saved."
            return payload
        try:
            write_started = time.perf_counter()
            store = memory_store or _memory()
            context_body = next_session_context(saved_context, payload)
            remembered = store.stage_messages(
                request.user_id,
                request.session_id,
                [("user", request.query), ("assistant", payload["answer"][:4000])],
                context_body=context_body,
                owner=known_owner,
                owner_known=memory_store is not None,
                durable_wait=0,
            )
            stored = set(remembered.get("stored_in") or [])
            durable = remembered.get("durable")
            payload["memory_saved"] = "redis" in stored and durable == "stored"
            if payload["memory_saved"]:
                payload["memory_note"] = "This turn was saved in the session cache and the database."
            elif "redis" in stored and durable == "timeout":
                payload["memory_note"] = "The reply is in the session cache. The database copy did not finish in time."
            elif "redis" in stored and durable == "queued":
                payload["memory_note"] = "The reply is in the session cache. The database copy is not confirmed yet."
            elif "redis" in stored:
                payload["memory_note"] = "The reply is in the session cache. The database copy failed."
            elif durable == "stored":
                payload["memory_note"] = "The database copy was saved. The session cache failed, so this browser may not restore the turn."
            else:
                payload["memory_note"] = "The answer was produced, but the conversation was not saved."
            if isinstance(payload.get("trace"), dict):
                payload["trace"].setdefault("stages", {})["memory_write_ms"] = round((time.perf_counter() - write_started) * 1000)
        except Exception:
            payload["memory_note"] = "The answer was produced, but the conversation was not saved."
    return payload


@router.post("/discover", response_model=DiscoveryResponse)
def discover_route(request: DiscoveryRequest):
    if agent_workflow_enabled():
        from food_copilot.agents.mcp_host import current_host
        from food_copilot.agents.workflow import run_agent_workflow

        host = current_host()
        return run_agent_workflow(request.query, mcp=host if host.status == "connected" else None)
    return _discover_payload(request.query)
