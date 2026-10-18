# Architecture audit

## Confirmed and fixed in this pass

Follow-up context sent only the restaurant ids from the latest assistant card list. With memory routes closed, a second “any other” could show the first page again. `followUpContext` now unions every recommendation card still on the current screen. A request with no context still does not inherit another session. Evidence: `frontend/src/lib/search.ts` and `tests/test_api.py`.

## Confirmed, not changed

| Item | Evidence | Why it stays |
|---|---|---|
| `faithfulness.py` is not called by `/api/chat` | Only `tests/unit/test_review_rag.py` imports `check_answer` | Review RAG is off. The quote path is not the demo answer. |
| Default retriever is BM25 when the demo flag is on, otherwise baseline | `app.py` health and `rankers.py` | The review evaluation did not justify a new default. |
| Hybrid and multilingual restaurant retrieval are off | `feature_flags` defaults | No comparable win on the corrected review set. |
| Street-overlap reviews are unattached | `prepare.py`, identity audit | Two groups remain unresolved. Canonical JSON was not edited. |
| `data/eval/queries.jsonl` has empty restaurant relevance ids | README and the eval runner | Recall on that file is not scored. |
| Browser user id is not an account | `routes.py` returns 403 on memory routes unless `ALLOW_UNAUTHENTICATED_MEMORY` | Left closed. |

## Readiness and persistence

`/ready` returned 503 because the probe called `execute` on `_HeldConnection`. That wrapper has no `execute`. `SELECT 1` on the inner connection succeeded, and Redis `ping` succeeded. The probe also closed the cached Redis client after a successful ping. The failure was the probe, not authentication or schema.

`/health` is liveness. `/ready` is the configured search workload. Redis and Postgres are required only when `ALLOW_UNAUTHENTICATED_MEMORY` is on. Otherwise a down store is `optional_unavailable` and search can still be ready. `postgres: true` means a probe returned `up`. It is not inferred from a configured URL.

Chat used to set `memory_saved` after the Redis write while Postgres ran in a thread that swallowed errors. The screen treated that as “This turn was saved.” The save is now reported from `memory_note`. `memory_saved` is true only when both stores have accepted the turn before the response returns. The chat path does not wait for Postgres, so the usual note says the session cache holds the reply and the database copy is not confirmed yet. Reload reads Redis through `GET /api/memory/sessions/{id}` and restores transcript text.

History was three Redis reads and the write was several separate commands. Both are one pipeline now. Ordinary card replies skip the phrase model unless `ENABLE_PHRASE_LLM` is set. On the measured Korean turn the completion had been discarded and the stored list kept, so the visible answer stays the stored list.

Verified against the configured stores: readiness 200 with both states `up`, a probe write/read in Redis and Postgres, and the browser transcript after reload. Connection strings were not printed.

## Inferred, not re-verified in this pass

- Bing HTML still returns restaurant-related pages. The code records a failure string when the request fails.
- A paid model answers general questions only when a key is present and the router or general node calls it. The demo sets `ENABLE_LLM_AGENT` false.

## Risks

- Unique-name review attachment is still a name match inside Kuala Lumpur, not a visited branch.
- Food-quality review labels sit outside the top 10 because many short reviews also say “delicious.”
- The status page can clear chat sessions after two confirmations. It does not clear restaurant JSON. This pass did not call that route.
- `GET /health` includes the last discovery trace for the process. It is local debugging data, not a public status contract.
