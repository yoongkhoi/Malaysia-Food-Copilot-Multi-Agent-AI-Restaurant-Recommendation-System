# Feature matrix

| Feature | Code | Runtime in the demo process | Tests | Limit |
|---|---|---|---|---|
| Chat UI | `frontend/src/views/CopilotView.vue` | Used | Vitest for context and API client | Needs the API on port 8767 |
| Follow-up constraints | `agents/context.py`, `followUpContext` | Used when LangGraph is on | Unit tests plus `test_api.py` | Screen context is lost on a full reload unless memory is allowed |
| Hard cuisine and area filters | `retrieval/constraints.py` | Used before ranking | `test_hard_constraints.py`, dialogue tests | A missing area is Old Klang Road. An explicit city is kept |
| BM25 | `retrieval/rankers.py` | On in `demo.ps1` | Ranker and API tests | Default process without the flag uses baseline token overlap |
| Vector or hybrid restaurant retrieval | `rankers.py` hybrid class | Off | Flag-off tests | Not the demo retriever |
| Web search | `retrieval/web_search.py` | On in `demo.ps1` | Search filter tests | Failure is reported. Pages are not canonical rows |
| Multi-agent workflow | `agents/workflow.py` | On by default and in `demo.ps1` | `test_agent_workflow.py` | Intent, MCP tools, rank, synthesis. Tests turn the flag off |
| Deterministic discovery graph | `agents/discovery_graph.py` | Only when `ENABLE_AGENT_WORKFLOW=false` | `test_discovery_graph.py` | Python answer. Not the demo path |
| Older two-agent graph | `agents/graph.py` | Off | Fake-model tests | Needs the workflow off, plus `ENABLE_LLM_AGENT` and a key |
| Canonical cards and map | `RestaurantCard.vue`, `RestaurantMap.vue` | Used | Evidence line tests | Pins only where coordinates exist. Address verified only when the field says so |
| Health | `app.py` `/health` | Used | `test_api.py` | Dataset count is the loaded JSON |
| Memory | `memory/store.py` | Routes closed unless the allow flag is set | Memory and security tests | No `FLUSHDB` in the app |
| Review RAG | `reviews/evidence.py` | Off | `test_review_rag.py` | Faithfulness checker is offline. Indexes were not rebuilt here |
| MCP tools | `mcp/server.py`, `agents/mcp_host.py` | Stdio child started with the API | `test_mcp_tools.py`, `test_mcp_stdio.py` | The browser talks to FastAPI. The API talks to MCP |
