# Cleanup audit

Date: 2026-10-18. Phase: audit only. No project file was deleted, moved, renamed, merged, or regenerated. `D:\project1\final-project` was not touched.

The active demo is Vue (`frontend`) to FastAPI (`app.py`) to one LangGraph workflow in `src/food_copilot/agents/discovery_graph.py`. `scripts/demo.ps1` serves that API on `127.0.0.1:8767` with BM25, LangGraph, and Bing search on, and the old LLM-agent graph off.

## 1. Active path

Browser routes in `frontend/src/router.ts`:

- `/` Explore (`ExploreView.vue`) calls `POST /api/discover`.
- `/copilot` (`CopilotView.vue`) calls `POST /api/chat`, then session memory when it is allowed.
- `/status` (`StatusView.vue`) calls `/health`, `/api/memory/status`, and `/api/ops/board`.
- `/preferences` and `/evidence` redirect to `/`. The view files still exist and are not linked from `AppShell.vue`.

Chat request, when `ENABLE_LANGGRAPH` is on and `ENABLE_LLM_AGENT` is off:

1. `routes.chat_route` reads one Redis pipeline for history and saved constraints.
2. `classify_intent` then `apply_history`.
3. `DiscoveryService.from_constraints` loads `data/processed/restaurants.json` through `active_restaurant_path()`, applies hard filters, then BM25.
4. Bing search uses `web_query`, with one alternate query on `no_results` or `parse_failed`.
5. `present_results` builds the user text. The longer `build_answer` text from the service is replaced here.
6. A review request loads `data/processed/reviews/pilot_corpus.jsonl`. Ordinary turns do not. `ENABLE_REVIEW_RAG` stays off.
7. Redis stores the turn. Postgres is attempted in the background and is not confirmed in the response.

`GET /health` is liveness and the dataset count. `GET /ready` probes Postgres and Redis without closing the shared clients. Memory is required only when `ALLOW_UNAUTHENTICATED_MEMORY` is on.

Verified dataset: `data/processed/restaurants.json` has 5,797 records, 7,355,478 bytes, sha256 prefix `85b8b7033466`. `settings.RESTAURANTS_PATH` and `repository.active_restaurant_path()` point here unless `DEMO_DATASET` is true. `data/demo/restaurants.json` is not on disk. The demo script sets `DEMO_DATASET=false`.

## 2. Code that is easy to confuse

| Item | Class | Evidence | Benefit of a later cleanup |
|---|---|---|---|
| `present_results` and `build_answer` | D for both today | Chat shows `present_results`. `build_answer` still feeds the service payload, the old agent graph, and `recommendation.py`. | One reply builder would remove contradictory wording. Do not merge until both outputs are compared on the same fixtures. |
| `agents/graph.py`, `agents/runtime.py`, `agents/recommendation.py`, `agents/preference.py` | B | Used only when `ENABLE_LLM_AGENT` is true. The demo sets that flag false. Tests still import them. | Not part of the live demo. Keep until the portfolio decision is to drop the old agent. |
| `agents/orchestrator.py`, `mcp/`, `scripts/mcp_server.py` | B | `/api` restaurant detail routes and the MCP server use them. The Vue copilot does not. | Keep the detail routes. The MCP process is optional. |
| `ui/app.py`, `scripts/launch_ui.py`, `gradio` in `requirements.txt` | B | Gradio UI is a second interface. The demo script does not start it. | Removing Gradio drops a dependency only after the CLI/UI is confirmed unused for the portfolio. |
| `services/restaurant_service.py` | B | A third `discover()` implementation. The API uses `DiscoveryService`. | Folding it in is a behavior risk, not a deletion. |
| `ENABLE_LLM_INTENT_PARSER` | A after one more check | Declared in `feature_flags` and not read anywhere else under `src/` or `tests/`. | Dead flag. Safe to remove only after a final search at cleanup time. |
| `retrieval/embeddings.py`, `HybridRetriever` | C | Imported when hybrid flags are on. Defaults are off. Review evaluation did not adopt hybrid. | Keep the code. Do not delete the flags just because they default to false. |
| `reviews/*`, `scripts/prepare_reviews.py`, `scripts/index_reviews.py`, `scripts/index_multilingual_reviews.py`, `scripts/evaluate_review_retrieval.py` | C | Live chat calls `reviews/recommend.py` only for an explicit review request, and only the pilot JSONL. The indexes are not opened on that path. | Keep. Do not rebuild indexes. |
| `frontend/src/views/EvidenceView.vue`, `PreferencesView.vue`, `EvidenceSection.vue` | B | Routes redirect to `/`. Nothing in the shell links to them. Dialog UI is imported only by Preferences. Sheet UI is used by the live sidebar. | Unreachable pages. Deleting them needs approval because the redirect still names the URLs. |
| Root `hello.ts`, `neon.ts`, root `package.json` | B | `tsconfig.json` includes only those two files. They configure a Neon function named Hello. They are not imported by FastAPI or Vue. | Not the restaurant app. Do not delete without confirming the Neon project still needs them. |
| `cli.py`, `scripts/copilot.py`, `scripts/normalize_data.py`, `scripts/collect_osm.py` | B | Offline entry points. The running demo does not call them. | Keep as reproduction tools until a script inventory is approved. |
| `discovery.py` answer plus graph answer | D | Two strings are built per chat. Only the second is returned. | Simplifying this changes tests that read the service payload. |

Do not remove a feature only because its flag defaults to false. Review RAG, hybrid retrieval, and the old agent graph are portfolio scope that is intentionally off.

## 3. Data inventory

Sizes are bytes on disk on 2026-10-18. sha256 is the first 12 hex characters. External review CSVs are grouped after the table. Hashes were not computed for files larger than 30 MB.

| Path | Bytes | Count | Role | Read by the demo? | Action |
|---|---:|---:|---|---|---|
| `data/processed/restaurants.json` | 7,355,478 | 5,797 records | Authoritative OSM restaurants. sha256 `85b8b7033466`. | Yes. | KEEP |
| `data/processed/kuala_lumpur/restaurants.json` | 7,354,291 | 5,796 records | Near copy. sha256 `609f23689e39`. | No import found. | REVIEW MANUALLY |
| `data/processed/old_klang_road/restaurants.json` | 1,034,745 | 798 records | Area extract. sha256 `aea544790785`. All 798 ids are in the canonical file. | No. | REGENERATABLE from the canonical file, but KEEP until a filter script is approved |
| `data/processed/old_klang_road/restaurants_final_verified_full.json` | 1,300,604 | 798 records | Unaccepted draft. sha256 `f7954fde435a`. Same 798 ids. Audit says prices and halal values are not acceptable. | No. Tests assert the name is not shown. | ARCHIVE. Do not import |
| `data/raw/kuala_lumpur/osm.json` | 3,376,846 | 5,797 records | Raw OSM snapshot. sha256 `97b4bf9b0bf1`. | No, at runtime. | KEEP |
| `data/raw/old_klang_road/osm.json` | 466,814 | 798 records | Raw OKR snapshot. sha256 `d8b5fedd7ba5`. | No, at runtime. | KEEP |
| `data/raw/osm_kulim.json` | 57,878 | 114 records | Kulim snapshot. sha256 `f6b816441919`. | No. | KEEP |
| `data/history/kulim/osm_kulim.json` | 57,878 | 114 records | Exact duplicate of `data/raw/osm_kulim.json`. Same sha256. | No. | CONSOLIDATE only the duplicate copy, after approval. Keep one Kulim snapshot |
| `data/history/kulim/restaurants.json` | 116,339 | 96 records | Historical processed Kulim set. | No. | KEEP |
| `data/history/kulim/rejected.json` | 26,994 | 18 records | Historical rejects. | No. | KEEP |
| `data/history/kulim/restaurant_review.csv` | 21,332 | 115 lines | Historical review sheet. | No. | KEEP |
| `data/processed/rejected.json` | 2 | 0 records | Empty list. sha256 `4f53cda18c2b`. | No. | REVIEW MANUALLY |
| `data/processed/reviews/reviews.jsonl` | 331,946,150 | 361,791 lines | Prepared full review file. Gitignored. | No. The live path does not read it. | REGENERATABLE by `scripts/prepare_reviews.py`, but KEEP. Do not rebuild as part of cleanup |
| `data/processed/reviews/pilot_corpus.jsonl` | 5,358,015 | 5,991 lines | Pilot reviews. sha256 `fdc4ff04e03d`. | Yes, only when the user asks for a review recommendation. | KEEP |
| `data/processed/reviews/rating_summary.jsonl` | 28,295 | 124 lines | Rating rollup. | Not by chat. | KEEP with the review audit |
| `data/processed/reviews/quality_report.json` | 1,607 | report | Prepare counts. | No. | KEEP |
| `data/vector_store/restaurant_reviews/` | 27.5 MB | MiniLM index | Experimental. Gitignored. | Not by the live chat path. | KEEP. Do not rebuild |
| `data/vector_store/restaurant_reviews_multilingual_minilm/` | 27.4 MB | Multilingual index | Experimental. Not the winner on the corrected eval. | No. | KEEP. Do not rebuild |
| `data/eval/queries.jsonl` | 1,077 | 5 lines | Restaurant eval. Relevance ids are empty. | Eval runner only. | KEEP |
| `data/eval/kulim_queries.jsonl` | 464 | 3 lines | Old area eval. | No live use found. | KEEP |
| `data/eval/review_retrieval_cases.jsonl` | 4,783 | 14 lines | Review retrieval labels. | Eval script. | KEEP |
| `data/eval/review_answer_cases.jsonl` | 3,937 | 9 lines | Faithfulness fixtures. | Unit tests. | KEEP |
| `data/eval/relevance_review_template.jsonl` | 1,314 | 5 lines | Empty-label template. | No. | KEEP |
| `data/eval/reports/latest.json` | 1,241 | report | Latest restaurant eval. | No. | KEEP |
| `data/eval/reports/restaurants_final_verified_full_audit.json` | 2,055 | report | Why the 798-row draft stays out. | No. | KEEP |
| `data/staging/restaurant_review.csv` | 1,144,197 | 5,799 lines | Staging sheet. | No live read found. | ARCHIVE |
| `data/staging/okr_review_batch1_25.csv` | 5,721 | 26 lines | Draft batch. sha256 `0999d3b4c392`. | No. | ARCHIVE |
| `data/staging/okr_review_batch1_25_work.csv` | 5,721 | 26 lines | Exact duplicate of the batch above. Same sha256. Settings still names this path for the Gradio UI. | Only if Gradio/CLI opens `WORK_REVIEW_PATH`. | REVIEW MANUALLY before deleting either copy |
| `data/staging/okr_review_batch1_25_researched_updated.csv` | 20,293 | 26 lines | Unaccepted price research. | No. | ARCHIVE. Do not import |
| `data/staging/okr_review_batch1_25_updated_with_prices.csv` | 20,271 | 26 lines | Unaccepted prices. | No. | ARCHIVE. Do not import |
| `data/staging/okr_review_batch1_first5_audit.json` | 7,744 | audit | Manual audit note. | No. | KEEP |
| `data/staging/okr_review_batch2_50.csv` | 11,174 | 51 lines | Later draft batch. | No. | ARCHIVE |

`data/processed/discovered_restaurants.json` and `data/processed/merge_candidates.json` are not on disk. The web-discovery code can create them later. `data/demo/restaurants.json` is already absent. `restaurants_final_prices.json` and `restaurants_final_with_urls.json` are not on disk.

The one id in the canonical file and not in `kuala_lumpur/restaurants.json` is `MY-OSM-way-1254826817`. Its name, regions, and address are empty. That is not enough to delete it. It needs a manual decision.

### External review dataset

`data/Malaysia Restaurant Review Datasets/` is 227.3 MB. It is the source for `scripts/prepare_reviews.py`. The demo does not read it. `quality_report.json` records that cleaned copies were not the prepare input, and that no license file was found beside the CSVs. Do not delete this folder because the demo ignores it.

Largest members:

| Path | Bytes | Lines | sha256 prefix |
|---|---:|---:|---|
| `data_cleaned/TripAdvisor_data_cleaned.csv` | 66,295,227 | 163,108 | not hashed, over 30 MB |
| `data/review/TripAdvisor/reviews_all_KL.csv` | 34,827,473 | 82,430 | not hashed, over 30 MB |
| `data_cleaned/GoogleReview_data_cleaned.csv` | 33,556,796 | 222,021 | not hashed, over 30 MB |
| `data/review/GoogleReview/GoogleReview_Petaling Jaya.csv` | 16,850,655 | 50,037 | `d6de571723a5` |
| `data/review/GoogleReview/GoogleReview_KL.csv` | 10,035,988 | 27,853 | `b089209a5935` |
| `data/review/GoogleReview/GoogleReview_Penang.csv` | 9,751,721 | 32,966 | `e682c5fd5d57` |
| `data/review/GoogleReview/GoogleReview_JB.csv` | 8,011,997 | 28,694 | `22f3797786bd` |

City restaurant lists under `data/restaurant/` are 120 to 4,440 lines each (`restaurants_ori.csv` is 5,151 lines, 831,776 bytes). They are a different schema from the OSM canonical file. They are not duplicates of `restaurants.json`.

`data_cleaned/` is a second copy of the review export. The prepare report says those cleaned files were not used. Treat them as REVIEW MANUALLY, not as safe deletes, until the prepare script's input list is checked line by line.

## 4. Duplicate findings

- `data/raw/osm_kulim.json` and `data/history/kulim/osm_kulim.json` are the same file (sha256 `f6b816441919`, 57,878 bytes, 114 records).
- `data/staging/okr_review_batch1_25.csv` and `data/staging/okr_review_batch1_25_work.csv` are the same file (sha256 `0999d3b4c392`, 5,721 bytes, 26 lines).
- `kuala_lumpur/restaurants.json` shares 5,796 ids with the canonical file and is not byte-identical. It is not a safe replacement.
- `old_klang_road/restaurants.json` and `restaurants_final_verified_full.json` share the same 798 ids, all of which are already in the canonical file. The verified-full file is a different document (different hash) and remains an unaccepted draft.
- The two Chroma directories are separate indexes (different sqlite hashes were not needed; their meta files name different models). Do not treat them as duplicates.

No restaurant records were merged. No price, halal, address, or review field was promoted.

## 5. Documentation

These overlap and disagree in places:

- `README.md` is the portfolio overview and is still the best entry point.
- `PLAN.md` is a long historical log. It still describes Gradio launch, deleted demo data, and Neon `hello.ts`. Useful as history, confusing as the current map.
- `docs/architecture.md` is the short current map.
- `docs/architecture-audit.md` and `docs/verification-report.md` are pass logs. The verification report is the latest behavior note. Earlier sections inside it describe `/ready` 503, which later sections correct.
- `docs/end_to_end_workflow_and_test_report.md` and `docs/ai_method_audit.md` predate the date-atmosphere and review-request changes.
- `docs/review_rag_experiment.md` is the review-eval record. It is still the right place for those numbers.
- `docs/feature-matrix.md`, `docs/production.md`, and `docs/redis_memory_policy.md` are narrower notes.

Proposed later action: keep `README.md`, `docs/architecture.md`, and `docs/verification-report.md` as current. Mark `PLAN.md` and the older audits as history. Do not delete them in the first cleanup.

## 6. Dependencies

`requirements.txt` lists FastAPI, Uvicorn, Pydantic, pytest, requests, Gradio, psycopg, redis, mcp, openai, and langgraph. All of those are used by either the demo or a kept optional path, except that Gradio is only the old UI.

Chroma and fastembed are installed in `.venv` and are not in `requirements.txt`. They belong to the review indexes. Do not change versions. Do not uninstall them during cleanup without a separate decision.

Root `package.json` is the Neon sample (`@neon/config`, `@neon/env`). The Vue app has its own `frontend/package.json`. The two `npm` projects are easy to confuse. `npm test` and `npm run build` for the demo must be run in `frontend`.

## 7. Proposed target shape

No move is recommended until approval. A later shape that keeps the demo obvious:

- `src/food_copilot/api`, `agents/discovery_graph.py`, `agents/context.py`, `agents/intent_router.py`, `services/discovery.py`, `retrieval/`, `memory/`, `data/repository.py` stay where they are.
- Optional paths stay, but a short comment at the top of `graph.py`, `ui/app.py`, and `cli.py` should say they are not the demo. That is a comment change, not a move.
- `data/processed/restaurants.json` stays the only runtime restaurant file.
- `data/raw/` and `data/history/kulim/` stay.
- `data/processed/reviews/` and `data/vector_store/` stay gitignored and are not relocated.
- External CSVs stay in place until a license note exists.
- Unreachable Vue views stay until you approve removing the redirect routes.

## 8. Staged plan

1. Docs only. Add a one-line pointer at the top of `PLAN.md` and the older workflow audits saying the current behavior is `docs/verification-report.md`. No code, no data.
2. Remove `ENABLE_LLM_INTENT_PARSER` after repeating the search. No behavior change if the search is still empty.
3. Decide the exact Kulim OSM duplicate and the exact staging CSV duplicate. Keep one of each. Do not touch canonical JSON.
4. Stop building two user-facing answers inside one chat only after fixture output is compared. This is the highest-value code change and the easiest one to get wrong.
5. After approval, remove or keep the unreachable Evidence and Preferences pages. Sheet and sidebar components stay.
6. Do not archive external reviews, pilot JSONL, full `reviews.jsonl`, or either vector index in the first implementation pass.
7. Do not drop Gradio, MCP, or the old agent graph until you say they are outside the portfolio.

Riskiest, and not part of an early pass: replacing `kuala_lumpur/restaurants.json` with a filter of the canonical file, editing the unnamed extra OSM way, or regenerating review files.

## 9. Risks and rollback

- Deleting `restaurants.json`, either OSM raw file, the pilot corpus, or a vector index cannot be undone from this audit. Those files are not all in git, and this audit did not create a backup.
- `reviews.jsonl` is 332 MB and gitignored. Treat it as costly to regenerate.
- The two staging CSVs with the same hash are still named by `WORK_REVIEW_PATH`. Deleting the `_work` copy without updating that constant breaks the Gradio path.
- Web discovery can create `discovered_restaurants.json` on a later chat. Cleanup must not assume that file stays absent.
- Rollback for any later deletion is a restored copy of the file. Do not rely on git history until a repository is confirmed.

## 10. Baseline

Commands run for this audit. They do not write restaurant data or indexes.

| Command | Result |
|---|---|
| `d:\project1\final-project\.python\python.exe -m pytest tests/test_api.py tests/unit tests/safety tests/test_constraints.py tests/test_regions.py tests/test_ingestion.py tests/test_metrics.py tests/integration/test_chat_smoke.py -q` | Exit 0. 192 passed, 1 skipped. The skip is the Chroma test, which needs the package in `.venv`, not the portable interpreter. |
| `npm test` in `frontend` | Exit 0. 14 passed. |

Not run:

- `tests/integration/test_memory_roundtrip.py` writes and deletes a probe session in the configured Redis and Postgres.
- `npm run build` rewrites `frontend/dist`. The last known build from the previous pass is `dist/assets/index-jwm9WHC4.js`. It was not rebuilt here.
- Review prepare and index scripts. They rewrite generated data.

## 11. Needs explicit approval

- Any deletion, including the byte-identical Kulim OSM copy and the byte-identical staging CSV.
- Removing Evidence and Preferences pages.
- Removing Gradio, MCP, CLI, or the old agent graph.
- Archiving or compressing the 227 MB external review folder, or the 332 MB prepared JSONL.
- Rebuilding or deleting either Chroma index.
- Changing `data/processed/restaurants.json`, including the unnamed extra way `MY-OSM-way-1254826817`.
- Importing any staging CSV or `restaurants_final_verified_full.json`.
- Editing `hello.ts` or `neon.ts`.
- Collapsing `present_results` and `build_answer`.
