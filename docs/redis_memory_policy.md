# Redis and Postgres memory policy

Redis is the short session store. Postgres is the durable store. A browser `user_id` is not an account. `ALLOW_UNAUTHENTICATED_MEMORY` stays false for any shared server.

## What is stored

| Store | Key or table | Bound |
|---|---|---|
| Redis | `session:{session_id}:messages` | Last `SESSION_MESSAGE_LIMIT` messages, default 10, maximum 20 |
| Redis | `session:{session_id}:user` | Owner id only |
| Postgres | `messages` | Same clipped text as Redis. The table can hold older rows; reads used by the app take the last limit. |
| Postgres | `user_preferences` | Confirmed preferences only. Value clipped to `PREFERENCE_VALUE_MAX_CHARS`, default 200. Reads return at most `PREFERENCE_LIMIT`, default 20. |

Each message is clipped to `SESSION_MESSAGE_MAX_CHARS` before either store writes it. Default 2,000 characters. Allowed range 200–4,000.

`SESSION_TTL_SECONDS` sets the Redis expiration. Default 86,400 seconds. Allowed range 60 seconds to 7 days. Postgres rows are not deleted by that TTL.

## Isolation

`append_message` writes only the session id it was given. It does not read another session and copy that history. If the session already has a different owner, it raises `PermissionError`.

Opening a new session id creates `session:{new_id}:messages`. The previous session key is left unchanged until its TTL expires or the user is deleted.

## Startup cleanup

`REDIS_STARTUP_CLEANUP` defaults to false. When true, application startup calls `MemoryStore.cleanup_sessions`.

That function scans keys matching `session:*`. It changes a key only when the name matches `session:{id}:messages` or `session:{id}:user`. It trims an over-long message list and sets a TTL when the key has none. It does not delete keys that already fit the policy. It does not call `FLUSHDB` or `FLUSHALL`. Keys from another application are skipped.

No measured memory saving is claimed. The bounds limit future growth; existing Redis usage was not measured in this pass.

## Consent

Long-term preferences are written only when the user text contains an explicit remember/save phrase and `confirmed` is true. Seeing a recommendation does not save a preference. Dietary or price text in a preference is not restaurant evidence. The discovery LangGraph used by the portfolio demo does not write preferences by itself.
