import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from food_copilot.api.routes import router
from food_copilot.config.settings import feature_flags, web_search_enabled

_DEFAULT_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"


def _capabilities(flags: dict | None = None) -> dict:
    """Report what this process has actually connected. A flag alone is not enough."""
    from food_copilot.agents.mcp_host import current_host
    from food_copilot.agents.model import openai_status
    from food_copilot.config.settings import ROOT, agent_workflow_enabled, web_search_enabled as web_on

    flags = flags if flags is not None else feature_flags()
    host = current_host()
    llm = openai_status()
    verified = bool((__import__("food_copilot.agents.discovery_graph", fromlist=["LAST_TRACE"]).LAST_TRACE or {}).get("llm_called"))
    if not agent_workflow_enabled():
        llm_state = "unavailable"
    elif not llm["configured"]:
        llm_state = "unavailable"
    elif verified:
        llm_state = "verified"
    else:
        llm_state = "configured"
    pilot = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"
    return {
        "llm_intent": llm_state,
        "final_synthesis": llm_state,
        "multi_agent": "enabled" if agent_workflow_enabled() else "unavailable",
        "mcp": host.status,
        "mcp_tools": list(host.tool_names),
        "mcp_error": host.error,
        "web_search": "configured" if web_on() else "unavailable",
        "review_retrieval": "ready" if pilot.exists() else "unavailable",
        "retrieval": "bm25" if flags.get("ENABLE_BM25") else "baseline",
        "model": llm.get("model") or "",
    }


def allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", _DEFAULT_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip() and item.strip() != "*"]
    return origins or [item.strip() for item in _DEFAULT_ORIGINS.split(",")]


@asynccontextmanager
async def _lifespan(_app):
    from food_copilot.config.settings import agent_workflow_enabled
    from food_copilot.memory.store import MemoryStore, startup_cleanup_enabled

    host = None
    if agent_workflow_enabled():
        from food_copilot.agents.mcp_host import current_host

        host = current_host()
        host.start()
    if startup_cleanup_enabled():
        store = MemoryStore()
        if store.status().get("redis"):
            try:
                store.cleanup_sessions()
            except Exception:
                pass
    yield
    if host is not None:
        host.stop()


app = FastAPI(
    title="Malaysia Food & Local Discovery Copilot",
    version="0.1.0",
    description="Evidence-grounded restaurant discovery for Old Klang Road, with Kuala Lumpur as the expansion area.",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(router, prefix="/api")


@app.get("/health")
def health_check():
    from food_copilot.data.repository import get_default_repository

    flags = feature_flags()
    repository = get_default_repository()
    rows = repository.list_restaurants()
    origins = {row.get("dataset_origin") or "canonical" for row in rows}
    dataset = "demo" if origins == {"demo"} else "canonical"
    return {
        "status": "ok",
        "pilot": "Old Klang Road",
        "expansion": "Kuala Lumpur",
        "dataset": dataset,
        "dataset_records": len(rows),
        "llm_agent": flags["ENABLE_LLM_AGENT"],
        "langgraph": flags["ENABLE_LANGGRAPH"],
        "retrieval": "bm25" if flags["ENABLE_BM25"] else "baseline",
        "web_search": web_search_enabled(),
        "capabilities": _capabilities(flags),
        "discovered_records": sum(1 for row in rows if row.get("dataset_origin") == "discovered"),
        "last_request": __import__("food_copilot.agents.discovery_graph", fromlist=["LAST_TRACE"]).LAST_TRACE,
    }


@app.get("/ready")
def ready_check():
    """Readiness is the configured restaurant-search workload.

    Liveness is ``/health``. Session memory is optional unless
    ``ALLOW_UNAUTHENTICATED_MEMORY`` is on. A disabled or failed optional
    store stays reported as not up, and it does not by itself make search unready.
    """
    import os

    from food_copilot.memory.store import MemoryStore

    flags = feature_flags()
    store = MemoryStore()
    configured = store.status()
    required = os.environ.get("ALLOW_UNAUTHENTICATED_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}
    postgres_state = _dependency_state(configured["postgres"], store._postgres)
    redis_state = _dependency_state(configured["redis"], store._redis)
    postgres = postgres_state == "up"
    redis_up = redis_state == "up"
    optional = []
    if required:
        status = "ready" if postgres and redis_up else "not_ready"
    else:
        status = "ready"
        if postgres_state != "up":
            optional.append("postgres")
        if redis_state != "up":
            optional.append("redis")
    body = {
        "status": status,
        "liveness": "ok",
        "memory_required": required,
        "postgres": postgres,
        "redis": redis_up,
        "postgres_state": postgres_state,
        "redis_state": redis_state,
        "optional_unavailable": optional,
        "llm_agent": flags["ENABLE_LLM_AGENT"],
        "langgraph": flags["ENABLE_LANGGRAPH"],
        "authentication": "not_configured",
        "capabilities": _capabilities(flags),
    }
    if status != "ready":
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=body)
    return body


def _dependency_state(configured: bool, connect) -> str:
    """Return disabled, up, down, or timeout. Never close a shared client."""
    if not configured:
        return "disabled"
    try:
        resource = connect()
        if hasattr(resource, "ping"):
            resource.ping()
        elif hasattr(resource, "__enter__"):
            with resource as connection:
                connection.execute("SELECT 1")
        else:
            resource.execute("SELECT 1")
        return "up"
    except Exception as exc:
        if isinstance(exc, TimeoutError) or "timeout" in exc.__class__.__name__.lower():
            return "timeout"
        return "down"
