# Documents, corpora and retrieval

Every route needs a bearer token and a completed password change (see [authorization](authorization.md)). Background and the retrieval rule are in [RAG](../rag.md).

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/rag/options` | user | Embedding models (with availability), splitting strategies, defaults, accepted formats, upload limit |
| POST | `/rag/search` | user | Retrieve passages without asking a language model |
| POST | `/documents` | user | Upload and index a file (multipart). Private; administrators may add `corpus_id` |
| GET | `/documents` | user | Your uploads, or `?corpus_id=` for the documents of a corpus you can read |
| GET | `/documents/{id}` | user | One document with its indexes |
| GET | `/documents/{id}/chunks` | user | Chunks with the embedding model and strategy recorded on each (`limit`, `offset`) |
| POST | `/documents/{id}/index` | owner / admin for corpus documents | Index again with another embedding model or strategy |
| DELETE | `/documents/{id}` | owner / admin for corpus documents | Delete it and its chunks (204) |
| GET | `/corpora` | user | Corpora you can read (administrators see all) |
| POST | `/corpora` | admin | Create (`name`, `description`, `is_public`) |
| PATCH | `/corpora/{id}` | admin | Change `description` or `is_public` |
| DELETE | `/corpora/{id}` | admin | Delete it with its documents and chunks (204) |
| GET | `/corpora/{id}/access` | admin | Users who have been granted it |
| POST | `/corpora/{id}/access` | admin | Grant a user (`{"user_id": "..."}`, 204) |
| DELETE | `/corpora/{id}/access/{user_id}` | admin | Revoke (204); effective immediately |
| POST | `/corpora/{id}/ingest` | admin | Read the corpus' configured source (folder or web addresses) and index every file; unchanged documents are not embedded again |

## Corpus fields

`GET /corpora` returns, for each corpus: `id`, `name`, `description`, `is_public`, `document_count`, `has_source`, `source_type` (`filesystem`, `url` or null), `refresh_minutes` (the scheduled interval, or null), `last_ingested_at` and `last_ingest_error` (what went wrong in the last run, or null).

## Uploading

```bash
curl -s localhost:8000/documents -H "Authorization: Bearer $TOKEN" \
  -F file=@notes.txt -F embedding=openai-small -F chunking=recursive
```

Accepted types are listed by `GET /rag/options` (`supported_formats`: PDF, TXT, Markdown, DOCX, HTML by default). `embedding` and `chunking` are names from `rag.yaml`; both are optional and default to `default_embedding` and `default_chunking`. The response lists `indexes`, one per way the document was indexed:

```json
{
  "id": "…", "filename": "notes.txt", "status": "ready",
  "indexes": [{
    "embedding_name": "openai-small", "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-small", "embedding_dimensions": 1536,
    "chunking_name": "recursive", "chunking_method": "recursive",
    "chunk_size": 800, "chunk_overlap": 120, "chunk_count": 4
  }]
}
```

If parsing or embedding fails nothing is stored.

## Searching

```bash
curl -s localhost:8000/rag/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query": "where do penguins live", "embedding": "openai-small", "chunking": "recursive", "top_k": 3}'
```

Optional fields: `embedding`, `chunking` (which index to search), `corpus_ids` (limit the shared corpora; your own documents are always included, `[]` means no shared corpora) and `top_k` (1 to 50, default from `rag.yaml`). Hits below `retrieval.min_score` are dropped. Each hit has `filename`, `chunk_index`, `text`, `score` (cosine similarity) and the names of the embedding model and strategy.

## Chat with documents

`POST /chat` takes `use_rag`, `embedding`, `chunking` and `corpus_ids` with the same meaning; the response and the streaming `done` event gain `citations`. `GET /conversations/{id}` returns `citations` on each assistant message, limited to passages you can still read.

## Status codes

| Code | Meaning |
|---|---|
| 401, 403 | Not signed in, deactivated, password change pending, or an admin-only route |
| 404 | Document, corpus or user does not exist or is not visible to you |
| 409 | A corpus with that name exists, or the document could not be read and cannot be indexed again |
| 413 | File larger than `limits.max_upload_mb` |
| 422 | Unsupported or empty file, unknown embedding model or strategy, corpus without a source |
| 502, 503 | Embedding failure, or the embedding provider is not available on this server |
