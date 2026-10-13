# Unblock – Slack Engineering Knowledge Retrieval

Unblock is an engineering assistant that helps developers find relevant discussions and solutions from Slack when they are blocked by an issue.

## Overview

The system collects useful engineering conversations from Slack, processes them, and makes them searchable.

High-level flow:

```text
Slack
  ↓
Slack Ingestion
  ↓
Thread Grouping & Filtering
  ↓
Database
  ↓
Keyword + Vector Search
  ↓
Relevant Threads
  ↓
AI-generated Answer
  ↓
Slack
```

## Folder structure

```
ingestion/   Dev 1 — Slack backfill, pagination, thread grouping, noise filtering
storage/     Dev 2 — DB access layer + schema migrations
retrieval/   Dev 3 — embeddings, hybrid search, merge & rank, Gemini synthesis
bot/         Dev 4 — Slack app, /unblock command, Block Kit formatting, feedback
shared/      Types used by more than one track (see shared/models.py) —
             changes here affect Dev 3 and Dev 4 directly, flag them to the team
```

## Setup

1. Clone the repo.
2. Copy the env template and fill in real values:
   ```
   cp .env.example .env
   ```
3. Start Postgres (with pgvector). It's mapped to **host port 5433**, not the
   default 5432, to avoid clashing with a locally installed Postgres:
   ```
   docker-compose up -d db
   ```
   On first container start this only enables the pgvector extension
   (`storage/migrations/0001_initial_schema.sql`) — no tables exist yet.
4. Create a virtualenv and install Python dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. Create the tables by running the Alembic migrations:
   ```
   alembic upgrade head
   ```
6. You should now have a running database at the `DATABASE_URL` in your `.env`
   (default `postgresql://unblock:unblock@localhost:5433/unblock`) with all
   tables created: `channels`, `threads`, `messages`, `embeddings`,
   `ingestion_runs`, `feedback`.

### Inspecting the database in DBeaver

Create a new PostgreSQL connection with:

| Field    | Value      |
|----------|------------|
| Host     | `localhost`|
| Port     | `5433`     |
| Database | `unblock`  |
| Username | `unblock`  |
| Password | `unblock`  |

Leave SSL disabled — it's a local dev container. Once connected, expand
`unblock` → `Schemas` → `public` → `Tables` to browse the schema.

## Dev 1: Slack ingestion

Create and install a Slack app in the target workspace with the bot token
scopes `channels:history` and `channels:read`. Use the app's bot token (usually
starts with `xoxb-`) as `SLACK_BOT_TOKEN`; do not put a user token (`xoxp-`) in
this setting. Invite the bot to each monitored public channel.

For private channels, add the bot scopes `groups:history` and `groups:read`,
reinstall the app so the new scopes take effect, and invite the bot to each
private channel. A scope alone does not grant access to a private channel.

Use channel IDs, not channel names, in `SLACK_CHANNEL_IDS` and API paths. For
example, `C0123ABCD456` is an ID-shaped value; replace it with the ID copied
from the actual channel in your workspace. The channel and token must belong
to the same Slack workspace. Keep tokens in `.env` and never commit them.
`SLACK_CHANNEL_IDS` uses JSON list syntax, for example
`["C0123ABCD456"]`.

If Slack returns `channel_not_found`, verify the channel ID and workspace,
confirm that the app was reinstalled after adding scopes, and confirm the bot
was invited to the channel. Slack may return this error when the token cannot
access a private channel as well as when the ID is invalid.

Run one backfill manually:

```sh
python -m ingestion.scripts.backfill --channel C0123ABCD456
```

Or omit `--channel` to use `SLACK_CHANNEL_IDS`. The pipeline reads each
channel after its saved timestamp, follows Slack pagination cursors, fetches
full replies for affected threads (including roots older than the checkpoint),
groups and deduplicates messages, and filters bot/system/reaction noise. It
writes the current batch as JSON to `output/threads.json` by default. Each
thread includes its channel ID, root timestamp, root message, and ordered
messages; these map to Dev 2's channel, thread, and message records.

The JSON output is atomically replaced before any channel checkpoint advances.
If output writing fails, the next run fetches the same messages again. The
checkpoint file is `storage/checkpoints.json`; the script takes a non-blocking
process lock so two manual backfill runs cannot race over that
checkpoint/output. Ongoing scheduled ingestion is handled by the API process
described below.

### Ingestion API

The API ingests one channel per request and writes channels, threads, and
messages to the existing PostgreSQL schema. Set a private `INGESTION_API_KEY`
in `.env`, then start the API:

```sh
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Generate a private API key (for example, `openssl rand -hex 32`) and put it in
`.env` as `INGESTION_API_KEY`. Trigger ingestion using the same value in the
`X-API-Key` header. Replace the example channel ID and header value below:

```sh
curl -X POST http://localhost:8000/api/v1/ingestion/channels/${channel_id} \
   -H "X-API-Key: YOUR_INGESTION_API_KEY"
```

The API commits the database transaction before advancing the channel
checkpoint. Repeated requests upsert by Slack timestamp, so retries do not
duplicate stored rows. Use `GET /api/v1/threads` or
`GET /api/v1/threads/{thread_id}` with the same header to inspect stored data;
`GET /health` checks the database connection. Interactive docs are at
`http://localhost:8000/docs`.

### Scheduled ingestion

The FastAPI process starts one background ingestion loop during application
startup. It waits 300 seconds, reads `SLACK_CHANNEL_IDS`, and runs the same
Slack ingestion and persistence flow for each configured channel. It then
waits another 300 seconds and repeats. No separate cron process is required.

Run exactly one API worker so only one scheduler loop is active:

```sh
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## Schema & migrations (Dev 2)

Schema is owned by SQLAlchemy models in `storage/models/` (declarative base in
`storage/models/base.py`) and applied via Alembic (`alembic.ini`, `alembic/`).
`storage/migrations/0001_initial_schema.sql` is legacy — it now only enables
the `vector` extension on first container start; it no longer creates tables.

To change the schema:
1. Edit or add a model in `storage/models/` (and import it in
   `storage/models/__init__.py` so Alembic sees it).
2. Generate a migration:
   ```
   alembic revision --autogenerate -m "describe the change"
   ```
3. Review the generated file in `alembic/versions/` — autogenerate doesn't
   always get pgvector imports or naming quite right, adjust if needed.
4. Apply it:
   ```
   alembic upgrade head
   ```

Because Dev 1 (ingestion) and Dev 3 (retrieval) both write to and read from
this schema, flag changes here to the team the same day they happen.

## Contribution workflow

- Branch off `main` per feature (`git checkout -b dev1/backfill-script`).
- Open a PR before merging; at least one other developer reviews it.
- Anyone touching `shared/models.py` pings the team first — Dev 3 and Dev 4
  both build directly against those types, so a silent change there breaks
  someone else's work without warning.
