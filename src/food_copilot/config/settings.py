import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
STAGING = DATA / "staging"
EVAL = DATA / "eval"
RESTAURANTS_PATH = PROCESSED / "restaurants.json"
DISCOVERED_RESTAURANTS_PATH = PROCESSED / "discovered_restaurants.json"
MERGE_CANDIDATES_PATH = PROCESSED / "merge_candidates.json"
DEMO_RESTAURANTS_PATH = DATA / "demo" / "restaurants.json"
EVAL_QUERIES_PATH = EVAL / "queries.jsonl"
EVAL_REPORT_DIR = EVAL / "reports"
WORK_REVIEW_PATH = STAGING / "okr_review_batch1_25_work.csv"


def _flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def feature_flags() -> dict[str, bool]:
    """Read optional backends at call time."""
    return {
        "ENABLE_LLM_INTENT_PARSER": _flag("ENABLE_LLM_INTENT_PARSER"),
        "ENABLE_LLM_AGENT": _flag("ENABLE_LLM_AGENT"),
        "ENABLE_BM25": _flag("ENABLE_BM25"),
        "ENABLE_MULTILINGUAL_EMBEDDINGS": _flag("ENABLE_MULTILINGUAL_EMBEDDINGS"),
        "ENABLE_HYBRID_RETRIEVAL": _flag("ENABLE_HYBRID_RETRIEVAL"),
        "ENABLE_LANGGRAPH": _flag("ENABLE_LANGGRAPH"),
        "ENABLE_REVIEW_RAG": _flag("ENABLE_REVIEW_RAG"),
        "ENABLE_AGENT_WORKFLOW": agent_workflow_enabled(),
    }


def agent_workflow_enabled() -> bool:
    """The multi-agent chat path is on unless a process turns it off.

    Tests set ENABLE_AGENT_WORKFLOW=false. The demo process leaves it on.
    """
    raw = os.environ.get("ENABLE_AGENT_WORKFLOW")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def temperature_for(role: str) -> float:
    defaults = {
        "intent": 0.1,
        "tools": 0.2,
        "rank": 0.2,
        "synthesis": 0.7,
        "general": 0.5,
    }
    env_name = {
        "intent": "TEMPERATURE_INTENT",
        "tools": "TEMPERATURE_TOOLS",
        "rank": "TEMPERATURE_RANK",
        "synthesis": "TEMPERATURE_SYNTHESIS",
        "general": "TEMPERATURE_GENERAL",
    }.get(role, "TEMPERATURE_GENERAL")
    raw = os.environ.get(env_name, "").strip()
    try:
        value = float(raw) if raw else defaults.get(role, 0.5)
    except ValueError:
        value = defaults.get(role, 0.5)
    return max(0.0, min(value, 2.0))


def web_search_enabled() -> bool:
    return _flag("ENABLE_WEB_SEARCH")


def demo_dataset_enabled() -> bool:
    return _flag("DEMO_DATASET")


def active_restaurant_path() -> Path:
    return DEMO_RESTAURANTS_PATH if demo_dataset_enabled() else RESTAURANTS_PATH


def embedding_model_name() -> str:
    return os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
