# Verification report

Date: 2026-10-18. Scope: `malaysia-food-copilot` only. Canonical `restaurants.json` was not edited. Review indexes were not rebuilt.

## 1. Initial defects

Verified from code, then fixed:

- Follow-up chat sent only the restaurant ids from the latest card list. With memory routes closed, a later “any other” could repeat an earlier page. `followUpContext` now unions every card still on the current screen.

Verified from a failing test, then aligned with the current copy:

- `test_normal_old_klang_road_request_stays_inside_the_region` required the internal token `old_klang_road` inside `match_reason`. The card reason now says the stored region tag matches the requested area and does not treat coordinates as proof. The region constraint assertion stayed. The reason assertion now checks that sentence.

Confirmed and left in place:

- `faithfulness.py` is used by the offline answer fixtures, not by `/api/chat`. Review RAG stays off.
- BM25 is the demo retriever. Hybrid and multilingual restaurant retrieval stay off.
- Street-overlap review rows stay unattached. Two groups are unresolved.
- `data/eval/queries.jsonl` still has empty relevance ids, so that file does not produce Recall@5.

## 2. Files changed

- `frontend/src/lib/search.ts` and `search.test.ts`: accumulate shown restaurant ids.
- `frontend/src/views/CopilotView.vue`: send that context.
- `tests/test_api.py`: three-step follow-up and a fresh session.
- `tests/integration/test_chat_smoke.py`: region reason text.
- `README.md`: links to the architecture notes.
- `docs/architecture.md`, `docs/architecture.mmd`, `docs/request-flow.mmd`, `docs/architecture-audit.md`, `docs/feature-matrix.md`, this report.

## 3. Architecture

The demo path is Vue to `POST /api/chat` to one LangGraph workflow: intent, hard filters, BM25, optional Bing sources, then a Python answer. Ordinary recommendation cards use that stored list. `ENABLE_PHRASE_LLM` turns the rewrite back on, and a completion that names a restaurant outside the retrieved list is still dropped. The older two-agent graph stays off unless `ENABLE_LLM_AGENT` is also on.

## 4. Tests

| Command | Result |
|---|---|
| `d:\project1\final-project\.python\python.exe -m pytest tests/test_api.py tests/unit -q` | 141 passed, 1 skipped |
| `d:\project1\final-project\.python\python.exe -m pytest tests/integration tests/safety tests/test_constraints.py tests/test_regions.py tests/test_ingestion.py tests/test_metrics.py -q` | 24 passed, 1 failed |
| `d:\project1\final-project\.python\python.exe -m pytest tests/integration/test_chat_smoke.py -q` after the reason assertion | 5 passed |
| `npm test` in `frontend` | 9 passed |
| `npm run build` | Failed once on `Array.at`, then succeeded. Output `dist/assets/index-yWDF9myO.js` |

The skipped test imports Chroma, which is installed in `.venv`, not in the portable interpreter. The project `.venv` does not have FastAPI, so the suite uses the portable interpreter. That interpreter was not modified.

## 5. End-to-end smoke

The API was already listening on `127.0.0.1:8767`. The Vite app was already on port 5173.

`GET /health`: 200, `dataset=canonical`, `dataset_records=5797`, `retrieval=bm25`, `langgraph=true`, `web_search=true`, `llm_agent=false`.

`GET /ready` on the process that was already running returned 503:

```json
{"status":"not_ready","postgres":false,"redis":true,"llm_agent":false,"langgraph":true,"authentication":"not_configured"}
```

Redis answered `ping`. Postgres answered `SELECT 1` on the connection inside the holder. The holder itself has no `execute`, and the old probe called `execute` on the holder, so Postgres was reported down. The probe also called `close()` on the shared Redis client. That was an application defect, not an authentication, network, or schema failure. Section 10 records the check after the fix.

`POST /api/chat` “Korean BBQ around Old Klang Road”: 8 results, region `old_klang_road`, wall clock 7,182 ms. Stage times, not summed: `retrieve_ms` 16, `search_ms` 387, `match_ms` 294, `phrase_llm_ms` 1,740, `history_ms` 2,545, `memory_write_ms` 1,548. Retrieval is not the slow part.

Follow-up “any other recommendations?” with those ids: 1 result, overlap 0. A different session with the same follow-up and no context: 0 results, `needs_clarification=true`.

Browser, `http://127.0.0.1:5173/copilot`: the Korean example rendered Sae Ma Eul BBQ and seven other canonical cards, map pins, and the lines “Identity: stored name only” and “street address is not on file.” The status line said `gpt-4o-mini (called)` and that the completion named a restaurant outside the retrieved list, so the stored list was kept. The next “any other recommendations?” added Uncle Jang and did not repeat the first eight names. Web search was skipped on that follow-up (`search_ms` 0). New session changed the session id and cleared the cards.

## 6. Performance

No retrieval or ranking change was made in the first pass. BM25 retrieve was 8–16 ms. Section 10 records the later history, memory, and phrase changes and the warm before/after wall clock for the same Korean query.

## 7. What was verified where

| Behavior | Runtime | Tests |
|---|---|---|
| Canonical Korean cards and honest address copy | Browser and `/api/chat` | API and dialogue tests |
| Follow-up excludes earlier ids | Browser and `/api/chat` | `test_api.py`, Vitest |
| New session does not keep the previous area | Browser cleared the screen; API with a new id asked for an area | `test_api.py` |
| Phrase model can run while the agent flag is off, and a bad name is dropped | Browser status line | Not a separate unit of the live key |
| Review faithfulness checker | Not on the chat path | Offline fixtures |
| Neon and Redis both reachable | Section 10: `/ready` 200 after the probe fix, plus a write/read of one probe session | Fakes in unit tests; `test_memory_roundtrip.py` on the configured stores |

## 8. Remaining limits

- The chat response does not wait for Postgres. `memory_saved` is true only when Redis and Postgres have both accepted the turn before the response is sent. The usual note is that the reply is in the session cache and the database copy is not confirmed yet. A later read can still find the rows.
- Ordinary recommendation cards do not call the rewrite model unless `ENABLE_PHRASE_LLM` is true. General questions still use the model. The old two-agent graph stays off.
- Review RAG, hybrid retrieval, and the old LLM-agent graph stay off.
- Restaurant relevance labels in `data/eval/queries.jsonl` are still empty.
- Unique-name review attachment and the two street-overlap groups are not manually confirmed identities.
- Reload restores the saved transcript text. It does not rebuild the restaurant cards from that text.

## 10. Readiness, persistence, and latency

Date of this pass: 2026-10-18.

Liveness is `GET /health`: the process and the loaded dataset. Readiness is `GET /ready`: the services required for the configured workload. Restaurant search does not need Redis or Postgres. Those stores are optional unless `ALLOW_UNAUTHENTICATED_MEMORY` is on. A disabled or failed optional store is listed in `optional_unavailable` and does not by itself return 503. A required store that is down or timed out stays 503, and it is not reported as up. The body has no connection strings.

After restarting the API with `scripts/demo.ps1`, `GET /ready` returned 200. `postgres` and `redis` were both `up`, and `memory_required` was true in that process. `demo.ps1` does not set the allow flag; the process already had it. `GET /health` stayed 200 with `dataset=canonical`, `dataset_records=5797`, `retrieval=bm25`, `langgraph=true`, `web_search=true`, `llm_agent=false`.

Persistence path: `/api/chat` reads the session with one Redis pipeline, then `stage_messages` writes the transcript with one pipeline. Postgres insert runs after that and is not joined on the chat path. The screen shows `memory_note`. It does not say the turn was saved unless both stores accepted it.

The same Korean BBQ query, a new session, warm process:

| Measurement | Before | After |
|---|---:|---:|
| HTTP wall clock | 6.062 s | 0.839 s |
| Graph `total_ms` | 2507 | 336 |
| `history_ms` | 1556 | 251 |
| `memory_write_ms` | 1502 | 247 |
| `phrase_llm_ms` | 2019 | 0 |
| `search_ms` | 431 | 297 |
| `retrieve_ms` | 14 | 8 |

Stage times are not added to make the wall-clock number. Before, the phrase completion was discarded because it named a restaurant that was not retrieved, and the stored list was kept. After, the stored list is the reply and the model was not called. Both turns returned 8 results in `old_klang_road`.

A separate probe session was written and read back from Redis (2 messages) and from Postgres (`conversation_summary` ok, count 2). The chat note at response time still said the database copy was not confirmed yet. The rows were present on the later read. The integration test `tests/integration/test_memory_roundtrip.py` passed against the configured stores and deleted only that probe session.

Browser at `http://127.0.0.1:5173/copilot`: a new session, the Korean example, eight canonical cards including Sae Ma Eul BBQ, and the note that the database copy is not confirmed yet. “Any other recommendations?” added Uncle Jang and did not repeat the first eight names. Reload kept session `9f1ba950-ef64-4e0c-86d7-2350a29a6fc3` and restored the transcript text, including Sae Ma Eul BBQ and Uncle Jang. Card headings were not rebuilt from that text.

Commands and results for this pass:

| Command | Result |
|---|---|
| `d:\project1\final-project\.python\python.exe -m pytest tests/test_api.py tests/unit -q` | 156 passed, 1 skipped |
| `d:\project1\final-project\.python\python.exe -m pytest tests/unit/test_memory_bounds.py tests/integration tests/safety tests/test_constraints.py tests/test_regions.py tests/test_ingestion.py tests/test_metrics.py -q` | 31 passed |
| `npm test` in `frontend` | 12 passed |
| `npm run build` | Succeeded. Output `dist/assets/index-Dm0dWvR6.js` |

The skipped test still needs Chroma from `.venv`. The portable interpreter was not modified. Canonical restaurant JSON and the review indexes were not changed. Review RAG and the old multi-agent graph stay off.

## 11. Date recommendations and review requests

Date of this pass: 2026-10-18.

The live sentence “I want a restaurant for a date” was parsed as ambience `date` with the session area Old Klang Road. `exclusion_code` then rejected every record that lacked a stored ambience value or a description containing date-night or romantic wording. The canonical file has 5,797 rows, 0 `ambience` values, and 0 descriptions, so the candidate list was empty. `present_results` turned that empty list into “No stored date atmosphere evidence”. The model note “The stored records answer this directly” is the branch for a turn with no cards. The model was not called because that branch skips the rewrite, not because a sufficiency check decided the atmosphere was answered.

The web query was `restaurant restaurant Old Klang Road Kuala Lumpur`. A live Bing page for that query contained `b_algo` blocks, and every block failed the restaurant-source check, so the code returned `no_results`. A later page for a normal restaurant query had HTTP 200, zero `b_algo` blocks, and zero external links. That is a parse failure, not an empty restaurant search. The reply still said local matches were listed.

Ambience is no longer a hard exclusion. Location, cuisine, brand, and shown-id exclusions stay hard. A record with a stored description that matches the requested atmosphere is preferred. Cuisine is not atmosphere evidence. When no description matches, the reply lists up to five named in-area restaurants and says ambience has not been verified. Unnamed rows are left off that shortlist.

The date web query is now `romantic dinner restaurant Old Klang Road Kuala Lumpur`. `date` is not sent as a search word because Bing treated it as a calendar. If the first page is `no_results` or `parse_failed`, one alternative query is `restaurants in Old Klang Road Kuala Lumpur`. HTTP errors stay exception names. A page with no result blocks is `parse_failed`. Blocks that parse but are not restaurant sources stay `no_results`. Pages that do not mention the requested area are not added to the card list.

Live `POST /api/chat` for “i want a restaurant for a date, any recommendation?” with Old Klang Road, after restart: HTTP 200, wall clock 3.810 s. Graph `total_ms` 2116. Stages, not added together: `candidate_count` 5797, `eligible_count` 5, `retrieve_ms` 16, `search_ms` 388, `match_ms` 4, `phrase_llm_ms` 0, `history_ms` 1396, `memory_write_ms` 246. `llm_called` false. Model note: the model was not called because it would have had to invent atmosphere. Five named cards: Take A Bow, A&W, Restoran Yan Yang A One, Chi I Vegetarian, Restoran O For U. The answer says ambience has not been verified. The web section says no result was verified as a canonical restaurant in the area.

Review RAG was not on the live path unless `ENABLE_REVIEW_RAG` was set. That flag is still off by default. “I don't know what to eat, can you recommend based on review?” now loads the pilot corpus only for that request. Confirmed evidence is `unique_name_in_area` only. Ambiguous and street-overlap rows are not attached. The pilot has 368 such reviews and 2 canonical restaurants, both in Kuala Lumpur and none in Old Klang Road: Iketeru (210 ratings, average 4.12, Google) and Dining in the Dark KL. No dish field is tagged, so the reply does not name a dish. Positive and lower-rated excerpts are both quoted and labelled as opinions.

The same review sentence with Old Klang Road returned HTTP 200 in 1.326 s. `candidate_count` 5797, `eligible_count` 686 before the named cap, `retrieve_ms` 22, `search_ms` 601. The note says no confirmed review is attached in that area and review ranking was not applied. Five named stored restaurants were listed. The same sentence with Kuala Lumpur returned Iketeru and Dining in the Dark KL, four opinion excerpts, and no invented rating.

| Command | Result |
|---|---|
| `d:\project1\final-project\.python\python.exe -m pytest tests/test_api.py tests/unit -q` | 185 passed, 1 skipped, then the outside-area assertion was corrected |
| `d:\project1\final-project\.python\python.exe -m pytest tests/unit/test_date_and_reviews.py tests/integration tests/safety tests/test_constraints.py tests/test_regions.py tests/test_ingestion.py tests/test_metrics.py -q` | 38 passed |
| `npm test` in `frontend` | 14 passed |
| `npm run build` | Succeeded. Output `dist/assets/index-jwm9WHC4.js` |

Remaining limits: canonical rows still have no atmosphere text, so a date request cannot cite a romantic description from the dataset. Bing HTML often has no organic links, so web evidence is frequently unavailable. The pilot review set does not cover Old Klang Road. Review RAG remains off for ordinary restaurant turns. The old multi-agent graph stays off. Canonical JSON and the review indexes were not modified.

## 9. Start locally

```powershell
powershell -File d:\project1\malaysia-food-copilot\scripts\demo.ps1
```

```powershell
cd d:\project1\malaysia-food-copilot\frontend
$env:PATH = "d:\project1\malaysia-food-copilot\.node-src\node-v22.21.0-win-x64;" + $env:PATH
npm run dev
```

Open http://127.0.0.1:5173/copilot . API: http://127.0.0.1:8767/health .
