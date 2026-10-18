# Production requirements

The local demo is not a production deployment. Browser `user_id` values are stored in `localStorage`. They identify a browser, not a person.

## Local start

```powershell
$env:PYTHONUTF8 = "1"
d:\project1\final-project\.python\python.exe -c "import sys; sys.path[:0]=[r'd:\project1\malaysia-food-copilot', r'd:\project1\malaysia-food-copilot\src']; import uvicorn; uvicorn.run('app:app', host='127.0.0.1', port=8767)"
```

Run that command from `malaysia-food-copilot`. The frontend is `npm run dev` in `frontend/`, which proxies `/api` to port 8767.

The portfolio process is `scripts/demo.ps1`. It sets `DEMO_DATASET=false`, `ENABLE_LLM_AGENT=false`, `ENABLE_LANGGRAPH=true`, `ENABLE_BM25=true`, and `ENABLE_WEB_SEARCH=true` for that process only.

`GET /health` reports status, dataset, record count, retrieval, LLM flag, LangGraph flag, web search flag, and discovered-record count. It does not report a database quota. `GET /ready` checks Postgres and Redis without returning connection strings. It does not call OpenAI. `authentication` is `not_configured`.

## Required environment

Copy `.env.example` to `.env`. Fill `DATABASE_URL`, `REDIS_URL`, and, only for a model demo, `OPENAI_API_KEY`. Leave `ENABLE_LLM_AGENT`, `ENABLE_LANGGRAPH`, `ENABLE_WEB_SEARCH`, and `ALLOW_UNAUTHENTICATED_MEMORY` false on a shared server. `scripts/demo.ps1` may turn LangGraph, BM25, and web search on locally. The local demo can set `ALLOW_UNAUTHENTICATED_MEMORY=true`; that only reopens the existing browser-id routes and is not login. Set `CORS_ORIGINS` to the real site origin. Do not use `*`.

## Schema, rollback, and backup

`MemoryStore.ensure_schema` creates the memory tables when the store is first used. There is no versioned migration tool and no tested backup or restore procedure. Before a public deployment, take a database backup with the Neon console or `pg_dump`, apply schema changes in a reviewed script, and keep the previous application build so it can be started again. That rollback path has not been executed here.

## What is still required before production

- An identity provider. Do not treat a caller-supplied `user_id` as login.
- A rate limit in front of `/api/chat` and the memory routes.
- A Git repository, secret store, and deployment target. `scripts/verify.ps1` runs the local checks; it is not CI.
- A tested backup and restore.
