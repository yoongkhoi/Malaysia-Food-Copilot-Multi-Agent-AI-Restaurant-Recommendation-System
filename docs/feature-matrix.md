# Feature matrix

| Feature | Code | Runtime in the demo process | Tests | Limit |
|---|---|---|---|---|
| Chat UI | `frontend/src/views/CopilotView.vue` | Used | Vitest for context and API client | Needs the API on port 8767 |
| Follow-up constraints | `agents/context.py`, `followUpContext` | Used when LangGraph is on | Unit tests plus `test_api.py` | Screen context is lost on a full reload unless memory is allowed |
| Hard cuisine and area filters | `retrieval/constraints.py` | Used before ranking | `test_hard_constraints.py`, dialogue tests | An unsupported area is asked, not invented |
| BM25 | `retrieval/rankers.py` | On in `demo.ps1` | Ranker and API tests | Default process without the flag uses baseline token overlap |
| Vector or hybrid restaurant retrieval | `rankers.py` hybrid class | Off | Flag-off tests | Not the demo retriever |
| Web search | `retrieval/web_search.py` | On in `demo.ps1` | Search filter tests | Failure is reported. Pages are not canonical rows |
| LangGraph discovery | `agents/discovery_graph.py` | On in `demo.ps1` | `test_discovery_graph.py`, API smoke | One workflow, not several agents |
| LLM agents | `agents/graph.py` | Off | Fake-model tests | Needs `ENABLE_LLM_AGENT` and a key |
| Canonical cards and map | `RestaurantCard.vue`, `RestaurantMap.vue` | Used | Evidence line tests | Pins only where coordinates exist. Address verified only when the field says so |
| Health | `app.py` `/health` | Used | `test_api.py` | Dataset count is the loaded JSON |
| Memory | `memory/store.py` | Routes closed unless the allow flag is set | Memory and security tests | No `FLUSHDB` in the app |
| Review RAG | `reviews/evidence.py` | Off | `test_review_rag.py` | Faithfulness checker is offline. Indexes were not rebuilt here |
| MCP tools | `mcp/tools.py` | Separate stdio process | `test_mcp_tools.py` | The browser does not connect to MCP |
