# Observability

What the system offers to check, from outside or in a dashboard, that its parts are working. It reports health and activity, not the quality of answers.

| Endpoint | Who | Answers |
|---|---|---|
| `GET /health` | anyone | Is the API process running? (liveness) |
| `GET /health/ready` | anyone | Can it serve requests? (readiness) |
| `GET /admin/status` | administrators | Everything below in detail, as JSON |
| `GET /monitoring/status` | administrators and monitors | The same report as `/admin/status` |
| `GET /metrics` | holder of `METRICS_TOKEN` | The same numbers in the Prometheus text format |

The web app shows `/admin/status` on **Admin · System**.

## Liveness and readiness

`/health` returns `{"status": "ok"}` and never touches the database. Use it to decide whether to *restart* the process. The container images use it as their health check.

`/health/ready` returns 200 when everything the API needs is in place and 503 otherwise. Use it to decide whether to *send traffic*:

```json
{"status": "ok", "checks": {"database": "ok", "migrations": "ok", "auth": "ok", "providers": "ok", "pgvector": "ok"}}
```

| Check | Fails when |
|---|---|
| `database` | The database does not answer |
| `migrations` | The database schema is not at the newest version of this build (run `make migrate`) |
| `auth` | `JWT_SECRET` is not set, so nobody can sign in |
| `providers` | No model provider loaded (every key missing) |
| `pgvector` | PostgreSQL without the `vector` extension (shown only on PostgreSQL) |

The response contains no hostnames, paths or error text, because the route is open.

## System status (administrators)

`GET /admin/status` returns:

- **database**: status, round-trip time, applied schema `revision` against the build's `head`, `migrated`, `pgvector`.
- **providers**: each provider enabled in `providers.yaml`: `loaded`, the `reason` when it is not (for example `ANTHROPIC_API_KEY is not set`), whether it is the default, its model count, and for each operation (`complete`, `stream`, `embed`) the successes, failures, average time and the last failure.
- **embedding_models**: each model from `rag.yaml` and whether its provider is available.
- **corpora**: documents, source type, refresh interval, last ingestion and its problem, and `overdue` for a scheduled corpus that has gone more than twice its interval without a run.
- **counts**: users, active users, conversations, messages, documents, chunks.
- **requests**: responses since start by status class (`2xx`, `4xx`, `5xx`) and the average time.
- **status**: `ok`, or `degraded` when readiness fails or a corpus is overdue. Also `version`, `environment` and `uptime_seconds`.

The provider and request figures are counters kept in memory by the API process. They start from zero at every restart (`uptime_seconds` says how long they have been counting), and with several workers each has its own. Calls made by the scheduler are counted in the scheduler's process, not shown here; its log and each corpus's `last_ingested_at` show that it is working.

## Metrics for Prometheus

Set `METRICS_TOKEN` in `.env` (any long random string) to turn on `GET /metrics`; without it the route answers 404. Scrape it with the token as a bearer token:

```yaml
scrape_configs:
  - job_name: answerworks
    metrics_path: /metrics
    authorization: { credentials: "<METRICS_TOKEN>" }
    static_configs: [{ targets: ["api:8000"] }]
```

| Metric | Type | Meaning |
|---|---|---|
| `answerworks_up`, `answerworks_ready` | gauge | Process running; ready to serve |
| `answerworks_uptime_seconds` | gauge | Seconds since start |
| `answerworks_database_up`, `answerworks_database_latency_ms` | gauge | Database answers; time of the last check |
| `answerworks_provider_loaded{provider}` | gauge | Provider configured and its key present |
| `answerworks_provider_calls_total{provider,operation,outcome}` | counter | Calls since start, `ok` or `error` |
| `answerworks_requests_total{status}` | counter | Responses by class |
| `answerworks_request_duration_seconds_sum`, `_count` | counter | Total and number of timed requests |
| `answerworks_rows{kind}` | gauge | Row counts |
| `answerworks_corpus_last_ingested_timestamp_seconds{corpus}` | gauge | When a corpus was last ingested |
| `answerworks_corpus_overdue{corpus}` | gauge | 1 when a scheduled corpus missed its refresh |

Useful alerts: `answerworks_ready == 0` for a few minutes, `answerworks_corpus_overdue == 1`, and a rising ratio of `outcome="error"` to `outcome="ok"` for a provider.

## The other services

- **Database:** the Compose file runs `pg_isready` against it. The API reports its own view of the connection above.
- **Web app:** Streamlit answers `GET /_stcore/health`, which the Compose health check and `make test-e2e` use. The API cannot see it, so check it separately.
- **Scheduler:** logs one line per scheduled run; see the corpora table above for its results.
