# Architecture

The normal chat path is a LangGraph-style multi-agent workflow in `agents/workflow.py`. It starts with the API. `ENABLE_AGENT_WORKFLOW` defaults on. Tests set it to false so the older deterministic graph still has coverage.

When `POST /api/chat` runs with the workflow on:

1. The intent agent calls the configured chat model at `TEMPERATURE_INTENT` and validates a JSON plan. A typed budget, area, or exclusion from the existing parser is kept even if the model omits it. A missing area uses Old Klang Road.
2. The discovery agent asks the model, at `TEMPERATURE_TOOLS`, which tools to call. `search_restaurants` and `get_restaurant_reviews` go through the MCP client. Web search is a separate tool and is not called on every turn.
3. The ranking agent keeps retrieval order unless a short model pass reorders ids that were actually retrieved.
4. The synthesis agent calls the model at `TEMPERATURE_SYNTHESIS` and that text becomes the answer. Cards still come from the search results. If the model is not configured or the call fails, the stored list is shown and the reply says it is not a model recommendation.

The API process starts one stdio MCP server in its lifespan and stops it on shutdown. `/health` reports `capabilities.mcp` from that connection, and `mcp_tools` from `list_tools`. A true environment flag is not reported as a live connection.

`agents/discovery_graph.py` remains the deterministic path used when `ENABLE_AGENT_WORKFLOW=false`.

# Components

The deterministic graph described below still runs when `ENABLE_AGENT_WORKFLOW=false`.

## Components

| Piece | Responsibility |
|---|---|
| Vue app in `frontend/` | Chat, explore, cards, map, status. Browser `user_id` and `session_id` live in `localStorage`. |
| `app.py` | FastAPI app, CORS, `/health`, `/ready`. |
| `api/routes.py` | `/api/chat`, `/api/discover`, restaurant reads, memory routes. |
| `agents/workflow.py` | Normal path: intent model, MCP tool loop, ranking, final synthesis. |
| `agents/mcp_host.py` | Stdio MCP client started with the API. |
| `agents/discovery_graph.py` | Older LangGraph path used only when the workflow flag is off. |
| `services/discovery.py` | Hard filters, then BM25 or baseline ranking, card fields, answer text. |
| `retrieval/constraints.py` | Parses and enforces explicit area, cuisine, brand, budget, and halal constraints. |
| `retrieval/web_search.py` | Bing HTML. Results are sources, not canonical rows. |
| `data/repository.py` | Reads `data/processed/restaurants.json`. |
| `memory/store.py` | Optional Neon/Postgres and Redis. Closed unless `ALLOW_UNAUTHENTICATED_MEMORY` is on. |
| `agents/graph.py` | Older two-agent LLM graph. Runs only when both `ENABLE_LLM_AGENT` and `ENABLE_LANGGRAPH` are on. |
| `reviews/` | Separate review corpus. `ENABLE_REVIEW_RAG` defaults off. `faithfulness.py` is an offline checker. |

## Request path

1. The copilot view sends `POST /api/chat` with the query, browser ids, and follow-up context built from earlier cards in that screen.
2. With LangGraph on and the LLM agent off, the route loads saved session context only when unauthenticated memory is explicitly allowed.
3. `classify_intent` chooses restaurant search, clarification, or a general question. General questions do not run retrieval.
4. `apply_history` copies an explicit area or cuisine forward and turns “any other” into an exclusion of the ids the client sent.
5. `DiscoveryService` drops rows that fail the hard constraints, then ranks the remaining canonical rows.
6. Web search runs only when the demo flag is on and the turn is not a pure follow-up exclusion. Pages are listed as sources. A page is not inserted as a canonical restaurant.
7. The answer text is assembled in Python from the filtered rows. Missing price, halal, and address stay unknown.
8. The Vue view renders cards and map pins from the JSON. Pins require stored coordinates. Evidence lines say whether the address is verified.

## What stays deterministic

Hard filters, BM25, and the card fields stay in Python. The model does not create restaurant ids. Hybrid retrieval and multilingual restaurant embeddings stay off unless their flags are set. Review vector indexes are not required for the pilot review tool, which reads `pilot_corpus.jsonl`.

## State

| State | Where it lives |
|---|---|
| Canonical restaurants | `data/processed/restaurants.json` |
| Review JSONL and vector indexes | `data/processed/reviews/`, `data/vector_store/` |
| Chat transcript on screen | Vue memory. A new session clears it. |
| Saved messages | Redis list plus Postgres, only when memory is configured and allowed |
| Constraint memory | Request `context` from the browser, plus a Redis key when memory is allowed |
| Browser ids | `localStorage` keys `mfc-user-id` and `mfc-session-id` |

## Failure behavior

- No area in the query or context: the reply asks which area and returns no restaurants.
- Lookup exception: the reply names the exception class and adds no restaurant from model memory.
- Web search failure: the source note records the error. Canonical results can still be returned.
- LLM agent on without a key: HTTP 503. The key value is not returned.
- Memory down or not allowed: the answer is still returned, with `memory_saved` false.
- Review RAG off: chat does not attach review quotes. Ambiguous review branches are not given a canonical id in the prepared file.
