# Conversations and chat

Saved conversations are per user. Every route needs a bearer token and a completed password change (see [authorization](authorization.md)). A conversation that belongs to someone else answers 404, the same as one that does not exist.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | Send a message; start a new conversation or continue one |
| POST | `/conversations` | Create an empty conversation (optional `title`, `provider`, `model`) |
| GET | `/conversations` | List your conversations, newest activity first (`limit` 1 to 200, `offset`) |
| GET | `/conversations/{id}` | One conversation with its messages in order |
| PATCH | `/conversations/{id}` | Rename (`title`, 1 to 200 characters) |
| DELETE | `/conversations/{id}` | Delete it and its messages (204) |

## Sending a message

```bash
curl -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message": "Summarise our options", "conversation_id": "<optional id>"}'
```

| Field | Notes |
|---|---|
| `message` | Required, up to 20000 characters, trimmed |
| `conversation_id` | Omit to start a new conversation, titled from the first 60 characters of the message |
| `provider`, `model` | Optional. Omitted: the conversation's last model, then the default model. If the stored model is no longer configured, the default is used |
| `stream` | `true` returns server-sent events |

The response holds `conversation_id`, `message_id`, `answer`, `provider`, `model`, `tokens_used`, `latency_ms` and `cost_usd` (`null` when the model has no pricing).

### Streaming

`text/event-stream` with these events:

- `delta`: `{"content": "..."}`, repeated.
- `done`: the same fields as the non-streaming response, sent after the reply is stored.
- `error`: `{"detail": "..."}`. Nothing is stored.

Errors found before streaming starts (unknown conversation, unknown model, no provider configured) are ordinary HTTP errors.

## What the model sees

The most recent `chat.history_messages` stored messages (default 20, in `config/app.yaml`) followed by the new message. Older messages stay stored but are not sent.

## Storage rules

- The user message and the assistant reply are stored together, only after the model answered. A failed call leaves no trace, so the same message can be sent again.
- Each assistant message records its own provider, model, tokens, latency and cost. The conversation remembers the last provider and model used.
- Concurrent messages to one conversation are not serialised: each one reads the history as it was when the request started.

## Status codes

| Code | Meaning |
|---|---|
| 401, 403 | Not signed in, deactivated account, or password change pending |
| 404 | Conversation does not exist or is not yours (also if it was deleted during the call) |
| 422 | Invalid request or unknown provider/model |
| 502, 503 | Provider failure or no provider available; details are not exposed |
