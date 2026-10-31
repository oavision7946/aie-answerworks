# Data model

PostgreSQL, managed with Alembic (`make migrate`). A test checks that the models and the migrations agree.

## users

| Column | Notes |
|---|---|
| id | UUID, primary key |
| email | Unique, stored lowercase |
| password_hash | Argon2 |
| role | `admin` or `user` |
| is_active | Deactivated accounts cannot sign in |
| must_change_password | Blocks every route except change-password and `/auth/me` |
| created_at | |

## conversations

| Column | Notes |
|---|---|
| id | UUID, primary key |
| user_id | Owner; foreign key to `users`, deleted with the user |
| title | Up to 200 characters |
| provider, model | Last provider and model used; null means the default |
| use_rag, corpus_ids | Present for document-grounded answers; chat does not use them yet |
| created_at, updated_at | `updated_at` moves when a reply is stored |

## messages

| Column | Notes |
|---|---|
| id | UUID, primary key |
| conversation_id | Foreign key to `conversations`, deleted with it |
| role | `user` or `assistant` |
| content | Text |
| provider, model, tokens_used, latency_ms, cost_usd | Set on assistant messages; `cost_usd` is null for models without pricing |
| retrieved_chunk_ids | Citations; empty until document retrieval exists |
| created_at | Orders the messages. A user message and its reply are saved together |

## Scoping rule

Every conversation query includes the owner's id (`conversation_repo.get_for_user` and `list_for_user`). Services never load a conversation by id alone. Tests assert that one user cannot read, rename, delete or post into another user's conversation.
