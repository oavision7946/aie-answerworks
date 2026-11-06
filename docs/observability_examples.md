# Observability examples

A walk through everything the system offers today for watching itself: health checks, the status report, metrics, request ids, trace ids in the logs, and the scheduler's logs. Each step says what to run and what you should see. The reference for each feature is on the [Observability](observability.md) page.

You will need about 20 minutes and a terminal. No model keys are required.

> **What is not here:** the examples read ids from headers and logs. To send spans to a tracing backend, see [Exporting traces](observability.md#exporting-traces); no backend is bundled. Everything below works from `curl`, the log output and the web app's **Admin · System** page.

## 0. Set up

Start the system as in steps 1 to 4 of the [first example](https://github.com/oavision7946/aie-answerworks#example-run-the-whole-system-with-or-without-provider-api-keys), keyless case (database, migrations, the fake provider, the first admin, `make run-api`). Then, in a second terminal:

1. Add a metrics token to `.env` and restart `make run-api`:

    ```bash
    METRICS_TOKEN=<a long random string>
    ```

2. Set the credentials the commands use (see [Credentials used in the examples](https://github.com/oavision7946/aie-answerworks#credentials-used-in-the-examples)). Here `USER1_*` is the account you will turn into a monitor:

    ```bash
    export ADMIN_EMAIL=<admin email>            ADMIN_PASSWORD=<admin password>
    export USER1_EMAIL=<monitor's email>        USER1_TEMP_PASSWORD=<temporary password>
    export USER1_PASSWORD=<password the monitor chooses>
    export METRICS_TOKEN=<the same value as in .env>
    ```

3. Define a helper that prints an access token (it is forgotten when you close the terminal):

    ```bash
    login() {
      curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
        -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
    }
    TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
    ```

## 1. Is it alive? Is it ready?

```bash
curl -s localhost:8000/health; echo
curl -s localhost:8000/health/ready; echo
```

```json
{"status":"ok"}
{"status":"ok","checks":{"database":"ok","migrations":"ok","auth":"ok","providers":"ok"}}
```

The first answers "is the process running?" and never touches the database. The second answers "can it serve requests?": the database answers, the schema is current, `JWT_SECRET` is set and at least one provider loaded. Neither needs a token.

## 2. Give someone read access to monitoring

Create an account with the `monitor` role. Roles stack, and an account has one role: a monitor can do everything a regular user can (chat, its own documents) and also read the monitoring status, but has no admin rights. Setting the role to `monitor` therefore takes nothing away from the account.

```bash
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$USER1_EMAIL\",\"temporary_password\":\"$USER1_TEMP_PASSWORD\",\"role\":\"monitor\"}"
```

If this answers `A user with this email already exists.`, the account was created earlier (for example in another example). Creating it again changes nothing, so change its role instead, and skip the password change below if that account has already chosen its own password (then `USER1_PASSWORD` is that password):

```bash
ID=$(curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" \
  | jq -r --arg email "$USER1_EMAIL" '.[] | select(.email==$email) | .id')
curl -s -X PATCH localhost:8000/admin/users/$ID -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"role": "monitor"}'
```

Every new account must replace its temporary password before it can do anything else. You should see that for yourself:

```bash
T1=$(login "$USER1_EMAIL" "$USER1_TEMP_PASSWORD")
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/monitoring/status -H "Authorization: Bearer $T1"   # 403
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/auth/change-password -H "Authorization: Bearer $T1" \
  -H 'Content-Type: application/json' \
  -d "{\"current_password\":\"$USER1_TEMP_PASSWORD\",\"new_password\":\"$USER1_PASSWORD\"}"                # 204
MON=$(login "$USER1_EMAIL" "$USER1_PASSWORD")
```

## 3. Read the system status as the monitor

```bash
curl -s localhost:8000/monitoring/status -H "Authorization: Bearer $MON" | python3 -m json.tool | head -30
```

You should see `"status": "ok"`, the database with `"migrated": true` and the same `revision` and `head`, and every provider with `"loaded": true` or the `reason` it is not. Read it top to bottom as a checklist:

| Look at | Healthy | Unhealthy looks like |
|---|---|---|
| `status` | `ok` | `degraded` (readiness fails or a corpus is overdue) |
| `database.migrated` | `true` | `false`: run `make migrate` |
| `providers[].loaded` | `true` for the ones you use | `false` with a `reason`, for example a missing key |
| `embedding_models[].available` | `true` for the ones you use | `false`: its provider is not running |
| `corpora[].overdue` | `false` | `true`: a scheduled corpus missed its refresh |

A monitor can read this report and nothing else of the admin area:

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/admin/users -H "Authorization: Bearer $MON"   # 403
```

Administrators get the same report at `/admin/status`, and in the web app on **Admin · System**.

## 4. Generate traffic and watch the counters

Send a chat message as the admin, then read the status again:

```bash
curl -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'
curl -s localhost:8000/monitoring/status -H "Authorization: Bearer $MON" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["requests"]);print(d["counts"])'
```

`requests` counts responses by class since the API started (`2xx`, `4xx`, `5xx`) with the average time in milliseconds. `counts` shows one more conversation and two more messages. Under `providers`, the `fake` provider now lists a `complete` call with `ok: 1` and when it last succeeded.

These counters live in the API process and start from zero at every restart; `uptime_seconds` says how long they have been counting.

## 5. Follow one request through the logs

Every response carries an `X-Request-ID`. You can supply your own to make a request easy to find. Make a request that is rejected on purpose (no token):

```bash
curl -si localhost:8000/models -H 'X-Request-ID: demo-001' | grep -i -E "^HTTP|x-request-id"
```

```
HTTP/1.1 401 Unauthorized
x-request-id: demo-001
```

Now find it in the terminal running `make run-api`. Log lines carry the request id and the trace id:

```
2026-11-03 16:40:44,339 WARNING app.api.errors [request=demo-001 trace=1ff6b8ce6e4cb9424d4cc03b841a0c87] HTTP 401 for GET /models: Not authenticated.
```

A user reporting a problem only has to quote the `X-Request-ID` of the failing response (or you can search the log for the time and route). If you send no id, one is generated and returned. Ids that are longer than 64 characters or contain anything other than letters, digits, `.`, `_` and `-` are replaced.

By default the application logs warnings and errors. Set `LOG_LEVEL=INFO` (in `.env` or the environment) to see more.

## 6. Join the caller's trace

A trace id ties together everything done on behalf of one action, across services. The web app sends a `traceparent` header with every API call, and so can you:

```bash
curl -si localhost:8000/models \
  -H 'X-Request-ID: demo-002' \
  -H 'traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01' | grep -i -E "^HTTP"
```

The log line for this request shows the trace id you sent, so you can search the logs of every service for it:

```
... WARNING app.api.errors [request=demo-002 trace=4bf92f3577b34da6a3ce929d0e0e4736] HTTP 401 for GET /models: Not authenticated.
```

Without a `traceparent` header the API starts a new trace, so the `trace=` value differs for every request.

In the web app, every call to the API starts such a trace, and the API continues it, so the `trace=` value in the API's log lines for a request made from the web app is the one the web app started.

## 7. Read the metrics

`/metrics` is off unless `METRICS_TOKEN` is set, and answers 401 without it:

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/metrics                                   # 401
curl -s localhost:8000/metrics -H "Authorization: Bearer $METRICS_TOKEN" \
  | grep -E "^answerworks_(up|ready|requests_total|provider_calls_total)"
```

```
answerworks_up 1
answerworks_ready 1
answerworks_provider_calls_total{provider="fake",operation="complete",outcome="ok"} 1
answerworks_requests_total{status="2xx"} 15
answerworks_requests_total{status="4xx"} 4
```

These are the same numbers as the status report, in the text format Prometheus reads. The [Observability](observability.md#metrics-for-prometheus) page has the scrape configuration and a list of useful alerts.

## 8. Watch a scheduled run

The scheduler re-ingests corpora that have `refresh_minutes`. Each pass is one trace and one request id of the form `scheduler-<12 hex>`, so every line it logs is easy to group.

Use the keyless configuration so no model is called: copy `tests_e2e/config` to a private folder, put a folder of text files in a corpus, and point the API and scheduler at it.

```bash
cp -r tests_e2e/config /tmp/aw-obs-config && mkdir -p /tmp/aw-obs-docs
echo "Penguins live in Antarctica." > /tmp/aw-obs-docs/a.txt
cat > /tmp/aw-obs-config/corpora.yaml <<'EOF'
corpora:
  - name: handbook
    refresh_minutes: 1
    source: { type: filesystem, path: /tmp/aw-obs-docs }
EOF
export ANSWERWORKS_CONFIG_DIR=/tmp/aw-obs-config
cd api && uv run python -m scripts.scheduler --once
```

Restart the API with the same `ANSWERWORKS_CONFIG_DIR` if you want the status report to list this corpus.

```
... INFO scheduler [request=scheduler-b5c464a650ab trace=c8b08174ba4c890311549f73545d947e] Scheduled ingestion of handbook: 1 indexed, 0 failed
```

Now break it. Point the corpus at a folder that does not exist (`path: /tmp/aw-obs-missing`), wait a minute so the corpus is due again, and run it once more:

```
... ERROR scheduler [request=scheduler-cf3e718c83d9 trace=e4dc5337dffcd4ba709837556281545c] Scheduled ingestion of handbook failed: The corpus source directory does not exist on the server.
```

Then read the status report: the corpus shows `last_ingest_error`, and after more than twice its interval without a good run it shows `"overdue": true` and the overall `status` becomes `degraded`. In the web app the same appears on **Admin · Corpora**.

## 9. A failure drill

Stop the API and start it again without a signing secret:

```bash
JWT_SECRET= make run-api
```

(Stop it with Ctrl+C and start it normally when you are done with this step.)

```bash
curl -s -w " [%{http_code}]\n" localhost:8000/health
curl -s -w " [%{http_code}]\n" localhost:8000/health/ready
```

```
{"status":"ok"} [200]
{"status":"degraded","checks":{"database":"ok","migrations":"ok","auth":"unavailable","providers":"ok"}} [503]
```

The process is fine (do not restart it), but it should not receive traffic: nobody can sign in. That difference is the point of having two checks. A load balancer or orchestrator should use `/health/ready` to decide where to send requests and `/health` to decide whether to restart.

Try the same with the database stopped (`make db-down`): `/health` still answers 200 and `/health/ready` answers 503 with `"database": "unavailable"`. Start it again with `make db-up`.

## 10. Where to look when something is wrong

| Symptom | First look | Then |
|---|---|---|
| Users cannot sign in | `/health/ready`: `auth` | Set `JWT_SECRET`, restart |
| Everything returns 5xx | `/health/ready`: `database`, `migrations` | `make db-up`, `make migrate` |
| Answers fail for one model | Status: `providers[].loaded` and `reason`, and `calls[].last_error_at` | Check the key in `.env` |
| Search finds nothing new | Status: `corpora[]` `last_ingest_error`, `overdue` | Read the `scheduler-…` lines in the log |
| One user's request failed | Their response's `X-Request-ID` | Search the log for it, then for its `trace=` |

## 11. Clean up

Stop the API, then remove the temporary files and unset the variables:

```bash
rm -rf /tmp/aw-obs-config /tmp/aw-obs-docs
unset ANSWERWORKS_CONFIG_DIR METRICS_TOKEN JWT_SECRET
```

Remove the monitor's access by changing its role back to `user`, or by setting `"is_active": false`, with `PATCH /admin/users/{id}`. Remove `METRICS_TOKEN` from `.env` to turn `/metrics` off again.
