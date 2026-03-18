# Antigravity Swarm Worker — Copilot Instructions

## Project Overview
This is the **Antigravity HIVE Swarm Worker** — a GitHub Actions-powered autonomous agent that polls a Supabase task queue every 5 minutes and executes tasks.

## Architecture
- **worker.py** — main entry point: polls `task_queue`, routes to task handlers, updates status
- **Supabase** — backend DB (project: `ayhplxbihuyimtrzimrh`, region: eu-central-1)
- **GitHub Actions** — runs `worker.py` on schedule every 5 minutes

## Supabase Tables

### `task_queue`
| column | type | notes |
|--------|------|-------|
| id | uuid | PK |
| task_type | text | routing key (e.g. `keepalive`, `log`, `run_script`) |
| payload | jsonb | task-specific input |
| status | text | `pending` → `running` → `done` / `failed` |
| priority | int | lower = higher priority |
| assigned_to | text | agent name |
| started_at | timestamptz | set when status→running |
| completed_at | timestamptz | set when status→done |
| error | text | filled on failure |

### `agent_memory`
| column | type | notes |
|--------|------|-------|
| id | uuid | PK |
| agent_id | text | e.g. `gh_worker`, `claude_code` |
| key | text | memory key |
| value | jsonb | any JSON value |
| context_type | text | `task` / `learning` / `state` |

### `claude_outbox`
Messages from Claude to other agents. Columns: `id`, `subject`, `message`, `message_type`, `status` (unread/read), `created_at`.

### `hive_comms`
Bidirectional HIVE messages. Columns: `id`, `from_node`, `to_node`, `message`, `status`, `created_at`.

## Coding Conventions
- Python 3.12, no external deps beyond `requests`
- All Supabase calls go through `supabase_request(method, endpoint, data)`
- Task handlers: add a new `elif task_type == "..."` block in `process_tasks()`
- Status transitions: always `pending → running → done/failed`, never backwards
- Secrets via env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — never hardcode
- Commit format: `HIVE: <description>`

## Adding a New Task Type
1. Add handler logic in `process_tasks()` under the `elif task_type == "your_type":` branch
2. The handler receives `payload` dict and `task_id`
3. Call `supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {"status": "done", ...})` on success
4. Raise an exception on failure (the outer try/except marks it `failed`)

## GitHub Actions
- Workflow: `.github/workflows/worker.yml`
- Runs every 5 min via cron
- Required secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- Do NOT change the cron schedule without good reason
