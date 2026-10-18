# Architecture

The default chat path is the multi-agent workflow in `src/food_copilot/agents/workflow.py`. `ENABLE_AGENT_WORKFLOW` is on unless the process sets it to false. The test suite sets it to false so the older deterministic graph still has coverage.

Screenshots of the three pages are in [images/](images/).

## Request path

`POST /api/chat` and `POST /api/discover` use the workflow when the flag is on.

1. **Intent.** The model returns one JSON plan at `TEMPERATURE_INTENT` (0.1). `DeterministicIntentParser` still parses the sentence. A typed budget, area, cuisine exclusion, or brand from that parser is kept when the model omits or contradicts it. If both region and city are missing after session history is applied, the area is Old Klang Road. An explicit Kuala Lumpur or Kulim mention is kept. A follow-up inherits the previous area.
2. **Discovery.** The model chooses tools at `TEMPERATURE_TOOLS` (0.2), for at most three rounds. `search_restaurants` and `get_restaurant_reviews` go through the MCP client when the host is connected. Hard constraints from the parser override model tool arguments. Web search is a separate tool and is not called on every turn.
3. **Ranking.** Retrieval order is kept unless at least two cards were returned and a short model pass at `TEMPERATURE_RANK` (0.2) reorders ids that were actually retrieved.
4. **Synthesis.** The model writes the user-facing reply at `TEMPERATURE_SYNTHESIS` (0.7). The reply may name only ids from the candidate list. Unknown ids are dropped from the id list. Cards, map pins, and evidence lines still come from the search results. If the key is missing or the call fails, the stored list is shown and the reply says it is not a model recommendation.

General questions skip retrieval and use `TEMPERATURE_GENERAL` (0.5).

```text
Vue
  Explore  /            form, then the same discovery API
  Copilot  /copilot     transcript, map, cards, session list
  Status   /status      Neon, Redis, dataset, health
        |
        v
FastAPI app.py
  lifespan starts McpHost when the workflow is on
        |
        v
agents/workflow.py
  intent -> MCP tool loop -> rank -> synthesis
        |
        +-- mcp/server.py          stdio, child env is a copy of the API env
        +-- services/discovery.py  filter, then BM25 or baseline
        +-- data/repository.py     data/processed/restaurants.json
```

The MCP child must inherit the API environment. Otherwise `ENABLE_BM25` is dropped and retrieval falls back to the baseline ranker.

`/health` and `/ready` report capabilities from the running process. MCP status is the host connection, not the flag. Language-model intent and synthesis are `unavailable`, `configured`, or `verified`. `verified` is set only after a successful model call in that process.

## Components

| Piece | Responsibility |
|---|---|
| `frontend/` | Explore, Copilot, and Status. Warm yellow shell. Browser `user_id` and `session_id` live in `localStorage`. |
| `app.py` | FastAPI, CORS, lifespan, `/health`, `/ready`. |
| `api/routes.py` | Chat, discover, restaurant reads, memory, and the ops board. |
| `agents/workflow.py` | Intent, tool loop, ranking, synthesis, and the labeled fallback. |
| `agents/mcp_host.py` | Stdio MCP client. Tests use an in-memory MCP session. |
| `mcp/server.py`, `mcp/tools.py` | Tool surface. Search calls `DiscoveryService`, not `handle_message`, so the workflow cannot recurse. |
| `agents/intent_router.py` | Intent labels and the no-session follow-up copy. |
| `agents/discovery_graph.py` | Deterministic LangGraph path used only when `ENABLE_AGENT_WORKFLOW=false`. |
| `agents/graph.py` | Older two-agent LLM graph. Runs only when `ENABLE_LLM_AGENT` and `ENABLE_LANGGRAPH` are both on and the workflow is off. |
| `services/discovery.py` | Hard filters, ranking, card fields, map links. |
| `retrieval/constraints.py` | Area, cuisine, brand, budget, diet, and certified-halal constraints. |
| `retrieval/web_search.py` | Bing HTML. Pages are sources, not canonical rows. |
| `data/repository.py` | Reads the canonical JSON unless `DEMO_DATASET` points elsewhere. The demo file is not used. |
| `memory/store.py` | Optional Neon/Postgres and Redis. Closed unless `ALLOW_UNAUTHENTICATED_MEMORY` is on. |
| `reviews/` | Pilot corpus and an offline faithfulness check. `ENABLE_REVIEW_RAG` defaults off. |

## MCP tools

| Tool | Use |
|---|---|
| `search_restaurants` | Filtered canonical search. Parser constraints win over model arguments. |
| `get_restaurant_reviews` | Pilot corpus only, and only a confirmed `unique_name_in_area` match. |
| `discover_restaurants` | Existing discovery entry. The workflow search path does not call this, so it cannot re-enter chat. |
| `get_restaurant_details` | One stored row by exact id. |
| `get_restaurant_evidence` | Stored address, price, and halal fields. |
| `get_user_preferences` | Saved preferences. A preference is not a restaurant fact. |
| `save_user_preference` | Writes only when `confirmed` is true. |
| `get_conversation_summary` | Stored messages. It does not generate a new summary. |

## What stays deterministic

Hard filters, BM25, card fields, and unknown/unverified labels stay in Python. The model does not create restaurant ids. Ambience is a preference, not an exclusion. A missing price is not an exclusion. A verified price above a stated budget is an exclusion. Hybrid retrieval and multilingual restaurant embeddings stay off unless their flags are set.

## State

| State | Where it lives |
|---|---|
| Canonical restaurants | `data/processed/restaurants.json` (5,797 OSM rows). Gitignored. |
| Area subsets and raw OSM | `data/processed/old_klang_road/`, `data/processed/kuala_lumpur/`, `data/raw/` |
| Review corpus used by the review tool | `data/processed/reviews/pilot_corpus.jsonl` |
| Full review export and vector indexes | `data/processed/reviews/`, `data/vector_store/`. Not required for ordinary chat. |
| Chat on screen | Vue. A new session clears the previous area and cuisine. |
| Saved messages | Redis list plus Postgres, only when memory is configured and allowed |
| Constraint memory | Request `context` from the browser, plus Redis when memory is allowed |
| Browser ids | `localStorage` keys `mfc-user-id` and `mfc-session-id` |

## Failure behavior

- No area in the query or context: search Old Klang Road. Do not ask the user to pick between Old Klang Road and Kuala Lumpur.
- Lookup exception: the reply names the exception class and adds no restaurant from model memory.
- MCP host not connected: search runs locally and the trace says the host was not connected.
- Web search failure: the source note records the error. Canonical results can still be returned.
- Model key missing or synthesis failed: cards can still be returned, and the reply is labeled as a fallback.
- Memory down or not allowed: the answer is still returned, with `memory_saved` false.
- Review RAG off: ordinary chat does not attach review quotes.

## Interface

| Route | Screen |
|---|---|
| `/` | Explore. The form appends Old Klang Road unless the text already names an area. |
| `/copilot` | Transcript, session list, suggestion chips, map, and cards. |
| `/status` | Neon, Redis, recent messages, the restaurant file, and health flags. |
| `/preferences`, `/evidence` | Redirect to `/`. The Vue files remain. |

Cards omit latitude and longitude from the location line. The map and the status search still show coordinates. Cuisine is a label. Provenance sits under **Record details**. Copilot diagnostics sit under **How this answer was made**.
