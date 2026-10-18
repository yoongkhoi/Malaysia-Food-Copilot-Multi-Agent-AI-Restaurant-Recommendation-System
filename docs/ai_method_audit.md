# AI method audit

Checked against the code on 2026-10-17. A name in a document is not treated as an implementation.

## Zero-shot prompting

Implemented. `review_preferences` in `src/food_copilot/agents/preference.py` and `recommend` in `src/food_copilot/agents/recommendation.py` send a system instruction and the user text. Neither prompt contains a worked input/output example.

Contribution: tells the model to return preference JSON, or to recommend only tool results and not mention internal filenames.

Limitation: the instruction does not stop a model from inventing text. `recommend` still replaces the deterministic answer with model text when that text cites no ineligible restaurant ID. Python still filters the `results` list.

Tests: `tests/unit/test_agents.py`, `tests/unit/test_graph.py`. These mock the model. They do not prove a live provider follows the prompt.

## Few-shot prompting

Not implemented. No prompt template in `src/` includes example question/answer pairs.

## RAG

Partly implemented, and it is not an embedding index.

`DiscoveryService.from_constraints` in `src/food_copilot/services/discovery.py` loads `data/processed/restaurants.json` through `LocalRestaurantRepository`, applies `apply_constraints`, then ranks the eligible rows. The demo process uses `BM25Retriever`. Otherwise the ranker is `BaselineRetriever`. The answer is built from those rows.

`src/food_copilot/agents/discovery_graph.py` runs that retrieval and a real Bing search in one LangGraph. The search titles are appended as sources. They are not copied into the restaurant cards. A page is written to `data/processed/discovered_restaurants.json` only when it has a street signal, is not a listicle, and does not match an existing name.

When `ENABLE_LLM_AGENT` is also on, `recommend` passes tool JSON back to the model. The demo process does not do that. `ENABLE_MULTILINGUAL_EMBEDDINGS` and `ENABLE_HYBRID_RETRIEVAL` default to false. The embedding model is not installed.

Limitation: canonical prices are `not_verified`, so cards omit the price. A restaurant is not removed only because the price is missing. Ranking cannot make a region or cuisine mismatch eligible. `restaurants_final_verified_full.json` is not loaded. DuckDuckGo HTML returned HTTP 202 with an anomaly page on this machine, so the live tool is Bing.

Tests: `tests/integration/test_chat_smoke.py`, `tests/unit/test_price_evidence.py`, `tests/integration/test_canonical_load.py`.

## Tool calling

Two different tools exist.

The demo LangGraph calls `search_web` in `retrieval/web_search.py`. A live Bing request on 2026-10-17 returned HTTP 200 and real page titles. The chat payload listed `web_search` in `tools_called`.

The LLM agent, behind `ENABLE_LLM_AGENT`, loops up to four times. It executes only `discover_restaurants`, `get_restaurant_details`, and `get_restaurant_evidence`. The demo process leaves this flag false. `mcp_call` in `src/food_copilot/agents/mcp_client.py` is the executor for that path.

Tests: `tests/unit/test_agents.py`, `tests/unit/test_mcp_tools.py`. Mocked. A mocked tool test proves the application runs the requested tool and checks the result. It does not prove the live provider.

## Deterministic validation

Implemented and used on every discovery path. `parse_constraints` and `apply_constraints` in `src/food_copilot/retrieval/constraints.py` enforce region, cuisine, vegetarian diet, a stated numeric cap, and certified-halal phrases. A missing price is not an exclusion. `price_support` rejects a verified price whose only URL is a Google search link, and the card then shows the price as unknown. Plain “halal” does not set the halal filter. The LLM LangGraph `validate` node runs the same filter again.

Tests: `tests/unit/test_hard_constraints.py`, `tests/test_constraints.py`, `tests/unit/test_price_evidence.py`.

## Memory

Implemented. Redis key `session:{id}:messages` keeps a capped recent list with a TTL. Postgres stores the durable transcript and confirmed preferences. A new session id gets a new key; old messages are not copied. Preferences are saved only after an explicit confirmation phrase. See `docs/redis_memory_policy.md`.

## Comparison

Same five queries in `data/eval/queries.jsonl`. Same canonical dataset, 5,797 records. Retriever: baseline. Flags: LLM agent false, LangGraph false.

| Method | What ran | Result |
|---|---|---|
| A. Zero-shot | NOT RUN | Would call the live model without restaurant evidence. Not executed. |
| B. Few-shot | NOT RUN | No few-shot prompt exists. |
| C. RAG / deterministic retrieval | `scripts/copilot.py evaluate` | 5 unlabeled queries, 5 empty eligible sets, 0 budget/region/halal violations. Recall@5 and NDCG@5 are NOT EVALUABLE because `relevant_restaurant_ids` are empty. |
| D. RAG + few-shot | NOT RUN | Few-shot is not implemented. |

The 2026-10-17 portfolio pass did not call the chat model. It did call Bing and BM25. An earlier same-day pass, under the old rule that an unknown price cannot pass RM20, called the live model with `ENABLE_LLM_AGENT` set only in that process. Those older empty RM20 counts are not the current product result. The key is configured and the model name is `gpt-4o-mini`. `ENABLE_LLM_AGENT` stays false in the demo process.
