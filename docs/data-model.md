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
| use_rag, corpus_ids | Whether the last message used documents, and the corpora it was limited to |
| created_at, updated_at | `updated_at` moves when a reply is stored |

## messages

| Column | Notes |
|---|---|
| id | UUID, primary key |
| conversation_id | Foreign key to `conversations`, deleted with it |
| role | `user` or `assistant` |
| content | Text |
| provider, model, tokens_used, latency_ms, cost_usd | Set on assistant messages; `cost_usd` is null for models without pricing |
| retrieved_chunk_ids | The chunks an answer was grounded in (its citations); empty without documents |
| created_at | Orders the messages. A user message and its reply are saved together |

## corpora

| Column | Notes |
|---|---|
| id | UUID, primary key |
| name | Unique, up to 100 characters |
| description | |
| source_config | Where ingestion reads files from, e.g. `{"type": "filesystem", "path": "..."}` or `{"type": "url", "urls": [...]}`; may be empty |
| is_public | Readable by every user |
| refresh_minutes | Scheduled re-ingestion interval, from `corpora.yaml`; null means manual only |
| last_ingested_at | When ingestion last finished, manual or scheduled |
| last_ingest_error | A short summary of what failed in that run; null when all went well |
| created_by | Foreign key to `users`, set to null if that user is deleted |
| created_at | |

## corpus_access

One row per explicit grant: `corpus_id` and `user_id` (together the primary key, both deleted with their parent) and `granted_at`.

## documents

| Column | Notes |
|---|---|
| id | UUID, primary key |
| owner_id | The uploading user for a private document; null for a corpus document |
| corpus_id | The corpus for a shared document; null for a private one. A check constraint requires exactly one of `owner_id` and `corpus_id` |
| filename, size_bytes | |
| status | `ready` or `failed` (a corpus file that could not be read or embedded) |
| error | Reason for a failure |
| text | The extracted text, kept so the document can be indexed again |
| created_at | |

## chunks

| Column | Notes |
|---|---|
| id | UUID, primary key |
| document_id | Foreign key to `documents`, deleted with it |
| chunk_index, text | Position and content |
| embedding | pgvector `vector` (any length; JSON on SQLite in tests) |
| embedding_name, embedding_provider, embedding_model, embedding_dimensions | The embedding model that made the vector |
| chunking_name, chunking_method, chunk_size, chunk_overlap | The splitting strategy that cut the text |
| created_at | |

A document can have chunks from several (embedding model, strategy) pairs. Searches compare only chunks whose model identity and splitting parameters match the requested index. See [RAG](rag.md).

## Scoping rule

Every conversation query includes the owner's id (`conversation_repo.get_for_user` and `list_for_user`). Services never load a conversation by id alone. Tests assert that one user cannot read, rename, delete or post into another user's conversation.

Documents follow the retrieval rule in `app/services/rag/retriever.py`: a document is visible to its owner, and a corpus document to users with a grant or when the corpus is public. Tests assert that one user's private documents never reach another user's search, and that revoking a grant takes effect immediately.
