# cdn-monitoring-system

A small two-service monitoring stack: an agent counts TCP connections for a target port and sends metrics to a FastAPI server that stores them in SQLite and renders a simple dashboard.

## Key features

- Docker Compose deployment with separate agent and server containers
- Token-protected ingest endpoint
- SQLite-backed metric storage
- Interactive HTML dashboard with live counts, graph, map, and history views
- Management page for adding CDNs and map placement
- JSON APIs for latest rows, series data, and map config

## Project structure

- `docker-compose.yml` — Runs the server and the agent together
- `agent/agent.py` — Collects connection counts via ss and POSTs them to the server
- `server/app.py` — FastAPI app for ingestion, storage, and dashboard rendering
- `.env.example` — Environment variables used by both services

## Requirements

- Docker and Docker Compose
- Linux-style ss command in the agent environment
- Writable ./data directory for SQLite persistence

## Setup

```bash
git clone https://github.com/biprajit007/cdn-monitoring-system.git
cd cdn-monitoring-system
cp .env.example .env
docker compose up --build
```

Then open:

```bash
https://cdn-monitor.rockstreamer.com:18443/login
```

The root URL redirects there until you log in.

Use the Management page to add or edit CDN entries and map placement.
If a CDN shows up there but has no live count, it means no agent is sending metrics with that `CDN_NAME` yet.

Default first login, if bootstrap is enabled:

- Username: `admin`
- Password: `cdn-monitor-2026!`

### Map configuration

Edit `data/cdn_map.json` to place CDNs on the Bangladesh map.
Example format:

```json
{
  "cdn1": "Dhaka",
  "cdn2": { "place_name": "Chattogram" }
}
```

You can copy `cdn_map.example.json` as a starter.

### History filters

- `24h` , default today view
- `7d` , weekly
- `30d` , monthly

## Configuration

- INGEST_TOKEN secures writes from the agent to the server.
- TARGET_PORT selects which port the agent counts active TCP connections for.
- SERVER_ENDPOINT points the agent at the API endpoint.

## Usage

### Open dashboard

```bash
http://localhost:18443/
```

### Fetch latest rows

```bash
curl http://localhost:18443/api/latest
```

## Safety notes

- The agent shells out to ss inside its container/host environment. Verify the command exists and that the reported port is the one you actually want to monitor.

## Limitations / next improvements

- No auth on the read-only dashboard
- No retention policy or charting
- Agent health and retry behavior are minimal
