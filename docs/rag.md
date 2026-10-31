# Retrieval-augmented generation (RAG)

With documents turned on, a chat message is answered from passages found in files you uploaded and in shared corpora you may read. The passages are placed in front of your question, and the answer lists them as sources.

## The pipeline

```
file -> parse -> split into chunks -> embed each chunk -> store -> (later) embed the question -> nearest chunks
```

1. **Parse.** PDF, TXT and Markdown are turned into plain text. Anything else is refused with a message. The text is stored with the document so it can be indexed again without the original file.
2. **Split.** The text is cut into chunks by the chosen *splitting strategy*.
3. **Embed.** Every chunk is turned into a vector by the chosen *embedding model*.
4. **Store.** Chunks and vectors go into the `chunks` table (pgvector), together with a record of how they were made.
5. **Retrieve.** The question is embedded with the same model, and the closest chunks by cosine similarity are returned, restricted to the documents the user may read.

## Several embedding models and splitting strategies

Both are named entries in [config/rag.yaml](../config/rag.yaml), and you can define as many as you like.

```yaml
embedding_models:
  openai-small: { provider: openai, model: text-embedding-3-small, dimensions: 1536 }
  openai-large: { provider: openai, model: text-embedding-3-large, dimensions: 3072 }
  local-nomic:  { provider: local,  model: nomic-embed-text,       dimensions: 768 }
default_embedding: openai-small

chunking_strategies:
  recursive: { method: recursive, size: 800,  overlap: 120 }
  paragraph: { method: paragraph, size: 1200, overlap: 0 }
  sentence:  { method: sentence,  size: 500,  overlap: 100 }
  fixed:     { method: fixed,     size: 1000, overlap: 200 }
default_chunking: recursive
```

- `provider` names a provider in `providers.yaml` that can create embeddings (`openai`, `openai_compatible`, `fake`). Anthropic cannot, and the configuration is rejected at startup if you point at it. A provider that is disabled or has no key is simply unavailable: its models show as unavailable and using one answers 503.
- `dimensions` is the length of the vectors the model returns. A model that returns another length is refused instead of storing mismatched vectors.
- `size` and `overlap` are in characters, and `overlap` must be smaller than `size`.

| Method | How it cuts |
|---|---|
| `fixed` | A sliding window of `size` characters that advances by `size - overlap`. Fast and predictable, but cuts mid-word. |
| `recursive` | Prefers paragraph breaks, then lines, sentences and words, so pieces stay as whole as possible, then packs them up to `size`. A good default. |
| `paragraph` | One unit per blank-line separated paragraph, packed up to `size`. An oversized paragraph is split recursively. |
| `sentence` | One unit per sentence, packed up to `size`. Overlap repeats the last sentences of the previous chunk. |

Every chunk is at most `size` characters. With overlap, the next chunk starts with the trailing units of the previous one that fit in `overlap` characters.

## What is recorded about each chunk

Each row in `chunks` stores how it was produced:

| Column | Meaning |
|---|---|
| `embedding_name`, `embedding_provider`, `embedding_model`, `embedding_dimensions` | Which embedding model made the vector |
| `chunking_name`, `chunking_method`, `chunk_size`, `chunk_overlap` | Which strategy cut the text |
| `chunk_index` | Position of the chunk in the document, for the index it belongs to |

The values are copied, not referenced, so the record stays true even after `rag.yaml` changes. You can see them in the Documents page ("How it was indexed", "Show chunks"), in `GET /documents/{id}` (per index, with a chunk count) and in `GET /documents/{id}/chunks`. Answers list the index behind each source.

**Why it matters.** Vectors from different models, and even from different dimensions, cannot be compared. Retrieval therefore only looks at chunks whose model identity (provider, model, dimensions) and splitting parameters equal those of the index you ask for. The *names* are labels: renaming an entry does not orphan its chunks, but changing its model, dimensions, method, size or overlap does. After such a change the old chunks no longer match; index the document again (`POST /documents/{id}/index`, or the Documents page) to create chunks for the new settings. Chunks made earlier stay until the document is deleted or re-ingested with changed text.

A document can have several indexes at once, for example `openai-small / recursive` and `openai-large / sentence`, so you can compare how each setup retrieves.

## Who can read what

A document is eligible for a user when it is ready and either belongs to that user, or belongs to a corpus that is public or has been granted to that user. This rule lives in one place (`app/services/rag/retriever.py`) and every search, source list and history lookup goes through it.

- Uploads are private by default. Nobody else, including administrators, can list, read, search, change or delete them; they answer 404.
- Corpora are shared collections managed by administrators: members are chosen with explicit grants, or the corpus is made public. Administrators also need a grant (or the public flag) for a corpus to be searched on their own behalf.
- Revoking a grant, or clearing the public flag, takes effect on the very next request. Sources already stored with an old answer disappear from the history when the reader can no longer see them.

See [Documents and corpora](api/documents.md) for the endpoints.

## Using it in chat

`POST /chat` accepts `use_rag: true`, optionally `embedding`, `chunking` and `corpus_ids`. The model receives the question preceded by numbered excerpts and is asked to cite them as `[1]`, `[2]`. The stored user message stays your original question. Each answer returns `citations` (filename, passage, similarity, and the embedding model and strategy of the index). When nothing relevant is found, the question is sent unchanged. Retrieval failures (unknown model, unavailable embedding provider) are reported before the language model is called and nothing is stored.

`POST /rag/search` runs only the retrieval step, without a language model, which is useful for comparing indexes.

## Limits and notes

- Uploads are processed while the request waits. The size limit is `limits.max_upload_mb` in `config/app.yaml`.
- Similarity is exact (a scan of the matching chunks), not approximate. There is no vector index yet, because vectors of different sizes share one column.
- The fake provider's embeddings are a hashed bag of words: they find passages that share words with the question. They are for demos and tests; real embedding models also match meaning.
- The first `ingest` of a corpus creates the corpus from `config/corpora.yaml`; later runs update it.
