# End-to-end workflow and test report

Date: 2026-10-17. Dataset used by the app: `data/processed/restaurants.json` (5,797 records). `restaurants_final_verified_full.json` is not loaded.

## A. System workflow

```mermaid
flowchart TD
  vue[Vue chat or Explore] --> api[POST /api/chat]
  api --> flags{process flags}
  flags -->|LangGraph on, LLM off| discoveryGraph[intent, BM25, Bing, match, answer]
  flags -->|both false| discover[DiscoveryService]
  flags -->|LLM on and LangGraph on| graph[memory, preference agent, recommend, validate]
  flags -->|LLM on only| agents[preference agent then recommendation agent]
  discoveryGraph --> response[JSON answer, constraints, results, sources]
  discover --> filters[parse_constraints and apply_constraints]
  filters --> rank[BM25 when enabled, otherwise baseline]
  rank --> answer[build_answer]
  agents --> tools[MCP tools]
  graph --> tools
  answer --> response
```

`.env.example` leaves the flags false. `scripts/demo.ps1` turns on LangGraph, BM25, and web search for one process and leaves the LLM off. That path does not need an API key. Filters run before ranking and again after ranking. A missing price stays in the result with the amount omitted. A known price above a stated cap is excluded.

Failure handling: the LLM path without a key returns 503; a model call error returns 502 without the key; Bing failure is written into the answer as `Web search failed`; memory failure keeps the answer and sets `memory_note`.

## B. Component map

| Component | File | Input / output | Technology | Failure |
|---|---|---|---|---|
| Vue | `frontend/src` | User text to `/api/chat` or `/api/discover` | Vue 3, Vite | Proxy target 127.0.0.1:8767 must be the API |
| Chat route | `api/routes.py` `chat_route` | Query in, discovery or agent payload out | FastAPI | Flags on without a key: 503 |
| Discovery | `services/discovery.py` | Query to cards and answer | Python | Missing area asks for clarification |
| Constraints | `retrieval/constraints.py` | Query and records to eligible rows | Python | Search-link prices do not count as verified |
| Ranker | `retrieval/rankers.py` | Eligible rows only | BM25 in the demo process, otherwise token overlap | Cannot override a failed constraint |
| Web search | `retrieval/web_search.py` | Query to titles, URLs, snippets | Bing HTML | Non-200, timeout, or no parseable results stay a failure |
| Discovery graph | `agents/discovery_graph.py` | Query to the chat payload | LangGraph 0.6.11, no model call | Clarification skips search |
| Tools | `mcp/tools.py`, `agents/mcp_client.py` | Tool name and arguments | MCP SDK | Timeout 20s; failure returns no restaurants |
| Agents | `agents/recommendation.py`, `preference.py`, `graph.py` | Model replies and tool JSON | OpenAI SDK, LangGraph | Off unless flags are true |
| Memory | `memory/store.py` | Session messages and confirmed preferences | Redis, Postgres | Closed unless local memory flag is true |
| Canonical data | `data/repository.py` | `RESTAURANTS_PATH` | JSON | Invalid rows are skipped and counted |

## C. Testing matrix

| Component | Test type | Command / case | Expected | Actual | Status | Remaining issue |
|---|---|---|---|---|---|---|
| Backend | Unit and integration | `pytest -q` | New price and cuisine rules, discovery graph, memory bounds | 111 passed, 2 warnings | PASS | Warnings are from MCP and LangGraph libraries |
| Budget | API smoke | `Old Klang Road under RM20` | Unpriced rows remain; known prices above 20 do not | Non-empty canonical results, omitted prices | PASS | Older empty-result expectation was the previous rule |
| Location and cuisine | API smoke and live chat | Korean BBQ around Old Klang Road | Region and cuisine both apply | 8 OSM Korean rows, first Sae Ma Eul BBQ | PASS | Ambience is parsed and is not a hard filter |
| Dietary | API smoke | verified halal under RM25 in Old Klang Road | Unchecked halal cannot pass | `results` empty, `require_halal_verified` true | PASS | Price is excluded before halal on this dataset |
| Empty / unsupported | API smoke | `Find a cheap restaurant` | No invented restaurant | Clarification, empty results, area not guessed | PASS | |
| Leakage | API smoke | All four chat bodies | No filename, path, URL credential, or traceback | None of those strings present | PASS | Model text can still replace the answer when an agent flag is on |
| Tool calling | Mocked unit | `tests/unit/test_agents.py` | Requested tool runs and result is checked | Passed inside the 108 | PASS | Proves application logic, not the live provider |
| RAG relevance | Offline eval | `scripts/copilot.py evaluate` | No constraint violations | 5 queries, 0 eligible, 0 violations | PASS | Recall@5 and NDCG@5 NOT EVALUABLE |
| Data | Validation | review-check, evidence-check, validate | 0 issues, 5797 loaded | Exit 0 for each | PASS | |
| Frontend | Test and build | `npm test`, `npm run build` | Pass and build | 5 passed; build exit 0 | PASS | |
| Zero-shot / few-shot live | Model comparison | Same five queries | Recorded outputs | Not executed | SKIP | Flags are false; few-shot does not exist |
| Live OpenAI tool loop | Process-local flag, not `.env` | Same 4 queries below with `ENABLE_LLM_AGENT=true` | Model called, MCP tool executed, result returned to the model, Python rechecks | 4/4 HTTP 200. See the live comparison | PASS | LangGraph stayed off. Flag was not written to `.env` |
| Redis memory bytes | Measurement | Inspect live Redis | Measured savings | Not measured | SKIP | Policy is unit-tested with a fake client |

The earlier chat smoke used FastAPI `TestClient` and did not call OpenAI. On 2026-10-17, before the price-rule change, the same app was called again with instrumentation. `scripts/copilot.py flags` printed every flag `false`. That earlier `pytest -q` was 108 passed. The later suite after the rule change was 111 passed. `validate` loaded 5,797 and skipped 0. `evaluate` had 5 unlabeled queries, 0 eligible rows, and 0 constraint violations. Frontend `npm test` was 5 passed and `npm run build` exited 0.

## Live agent comparison

The agent flag was set only in that process. LangGraph stayed off. `.env` was not edited. After the run, a new process still reads the flags as false. Counts below come from wrappers around `OpenAIChatModel.complete`, `mcp_call`, and `apply_constraints`, plus the HTTP logs `CallToolRequest` and `chat/completions` 200. They are not inferred from the answer text.

| Query | Baseline | Live agent | Constraint result | Status |
|---|---|---|---|---|
| Find restaurants in Old Klang Road. | 488 ms, 798 IDs, `region_mismatch` 4999, 0 model calls, 2 discovery checks | 17,892 ms, same first IDs, 798 results, 3 model calls, `discover_restaurants` returned 798 and that result was in the next model call, 1 agent recheck, 2 discovery checks | 0 violations. Agent `exclusion_counts` was empty because the recheck only sees eligible rows | PASS |
| Find restaurants in Old Klang Road under RM20. | 11 ms, 0 results, hard cap RM20, `price_unverified` 798 | 5,120 ms, 0 results, same constraints and exclusion counts, tool eligible 0 | No unverified price was returned | PASS |
| Find verified halal restaurants in Old Klang Road. | 12 ms, 0 results, `halal_not_verified` 798 | 5,308 ms, 0 results, same exclusion counts, tool eligible 0 | No unverified halal row was returned | PASS |
| Find affordable restaurants in Old Klang Road. | 15 ms, flexible mode, no numeric cap, 0 results, `price_unverified` 798 | 5,220 ms, same constraints and exclusion counts, tool eligible 0 | No price was invented | PASS |

The agent adds a prose explanation. It does not add a restaurant the baseline rejected, and it does not remove the hard-budget or halal refusal. The non-empty query's structured exclusion counts are dropped after a successful recheck. That is a reporting gap, not a constraint bypass.

## D. AI method decisions

Keep deterministic Python validation on every path. Keep tool calling and the two agents behind flags. Keep the current retrieval as the evidence source. Do not add few-shot examples until there are reviewed restaurant IDs to use as examples. Do not enable embedding or hybrid retrieval before those labels exist. Do not load `restaurants_final_verified_full.json`.

## E. Risk register

| Rank | Risk | Why it remains |
|---|---|---|
| CRITICAL | Unsupported price and halal claims | Canonical rows are not verified. The candidate file's verified prices are Google search links and were not imported. |
| HIGH | No labelled ground truth | Recall@5 and NDCG@5 cannot be computed. |
| HIGH | Agent answer text | When a flag is on, model prose can replace the evidence answer if it does not cite a bad ID. The result IDs stay filtered. |
| MEDIUM | Browser id is not login | Local `.env` may allow unauthenticated memory. Do not copy that setting to a public server. |
| MEDIUM | Web results are not branches | Bing can return unrelated pages. They are listed as sources and are not inserted without a street signal. |
| LOW | Redis size | Caps exist. Current Redis usage was not measured. |
| LOW | Latency and cost | Default chat does not call a model. |

## F. Runbook

From `malaysia-food-copilot`:

```powershell
$env:PYTHONUTF8 = "1"
d:\project1\final-project\.python\python.exe -m pytest -q
d:\project1\final-project\.python\python.exe scripts\copilot.py review-check
d:\project1\final-project\.python\python.exe scripts\copilot.py evidence-check
d:\project1\final-project\.python\python.exe scripts\copilot.py validate
d:\project1\final-project\.python\python.exe scripts\copilot.py evaluate
```

Frontend, from `frontend/`:

```powershell
$env:PATH = "d:\project1\malaysia-food-copilot\.node-src\node-v22.21.0-win-x64;" + $env:PATH
npm test
npm run build
```

API, from `malaysia-food-copilot`:

```powershell
d:\project1\final-project\.python\python.exe -c "import sys; sys.path[:0]=[r'd:\project1\malaysia-food-copilot', r'd:\project1\malaysia-food-copilot\src']; import uvicorn; uvicorn.run('app:app', host='127.0.0.1', port=8767)"
```

Then `npm run dev` in `frontend/`. `GET /health` checks the process. `GET /ready` checks Postgres and Redis and does not print their URLs.

If a card shows a price, that amount came from a non-search source. An unknown price is omitted and is not a confirmed budget match. If the UI cannot reach the API, confirm port 8767 is this application's process. The portfolio command is `scripts/demo.ps1`.

## Portfolio demo

`scripts/demo.ps1` starts the API on port 8767 with process-only flags: `DEMO_DATASET=false`, `ENABLE_LLM_AGENT=false`, `ENABLE_LANGGRAPH=true`, `ENABLE_BM25=true`, `ENABLE_WEB_SEARCH=true`. It does not edit `.env`. It loads `data/processed/restaurants.json`. The old eight-row demo file has been removed. The frontend is `cd frontend; npm run dev`, then open http://127.0.0.1:5173/copilot .

LangGraph nodes are Python: parse the request, BM25 retrieval, a live Bing HTML search, match sources to existing names, then a template answer. A missing price is omitted and does not remove the restaurant. A known price above a stated cap is still excluded. Plain “halal” is not a filter. Web pages are listed as sources, not as confirmed branches. DuckDuckGo HTML from this machine returned HTTP 202 with an anomaly page, so it is not used.

Live check on 2026-10-17 against the restarted API, not a mock:

| Query | Result | Evidence |
|---|---|---|
| I want Korean BBQ around Old Klang Road. | 200 in 1975 ms, 8 OSM rows, first is Sae Ma Eul BBQ | `agent_mode=langgraph`, retriever `bm25`, tools `bm25,web_search`, prices null, Google Maps coordinate links, duplicate brand name dropped |
| Find a family-friendly restaurant in Old Klang Road under RM20. | 200 in 449 ms, 8 OSM rows, region `old_klang_road`, budget 20 | Price status `unknown` and no amount. Answer says a restaurant without a price is still shown |

`/health` reported dataset `canonical`, 5797 records, LLM agent off, LangGraph on, retrieval `bm25`, web search on, discovered records 0. The status page at `/status` shows the same fields and says the database quota cannot be read from the current interface. Embedding retrieval is not enabled.

A separate Bing call for “Korean BBQ restaurant Old Klang Road Kuala Lumpur” returned three real pages (Wikipedia and a Korean-learning site). Those titles were not saved as restaurants. Backend pytest: 111 passed. Frontend vitest: 5 passed. Production build exited 0.

## Follow-up fix, 2026-10-17 evening

The second turn replied “does not name a supported area” because intent ran on the new sentence alone. Redis history was not enough once the answer text no longer listed `- Name:` lines, and the client did not send the previous constraints.

The chat request now keeps `region`, `cuisine`, and `shown_names` for the open session, on the server in `session:{id}:context` and from the previous response. “还有没有其他的推荐” keeps Korean and Old Klang Road and skips names already shown. “What about Japanese food?” keeps the area and changes cuisine. “cafes in Kuala Lumpur” replaces both. A new session starts with an empty turn list, so it does not send that context.

A live call after the restart: first query server `total_ms` 6484, `llm_called` true, model `gpt-4o-mini`, tools `bm25,web_search,llm`, first card Sae Ma Eul BBQ, map host `openstreetmap.org`. Second query region `old_klang_road`, cuisine `korean`, first card Midam Korean Barbeque, `needs_clarification` false. Then `POST /api/ops/clear-sessions` removed 24 messages, 7 conversations, and 15 Redis session keys. Restaurant rows were not deleted.

The PowerShell round trip was about 30s and 22s. The server trace for the first call was 6.5s. The gap was not broken down further in that client.

## G. Verdict

Changed Redis session bounds, message clipping, preference caps, and a prefix-only startup cleanup that is off by default. Added tests and the three documents in `docs/`.

Backend 111 passed. Frontend 5 passed and the production build exited 0. The live API used canonical OSM rows, BM25, and a real Bing search. Canonical `restaurants.json` was not modified. Recall@5 and NDCG@5 remain NOT EVALUABLE. A safe cleanup action for discovered rows, and a measured database byte size, are not implemented; the status page says the quota cannot be read.

Local demonstration of the deterministic app is safe: it refuses unverified prices and halal claims and does not expose the candidate filename. It is not ready for public deployment. Authentication is not configured, and restaurant evidence is still unverified.

Next three priorities:

1. Run one live multi-turn memory demo against the local Redis and Neon stores, then show a saved diet preference changing the next recommendation.
2. Keep the canonical 5,797-row file unchanged. The deleted demo file is not the portfolio path.
3. Add labelled evaluation IDs only when a demo or reviewed set is chosen as the scoring set. Do not invent them.
