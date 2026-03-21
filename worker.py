"""
Antigravity Swarm Worker — Specialist Edition v2.0
GitHub Actions edge node for the HIVE Sovereign Swarm.
Polls Supabase task_queue, routes to specialist handlers, reports results.
"""

import json
import os
import hashlib
import traceback
from datetime import datetime, timezone

import requests

# ── Configuration ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ayhplxbihuyimtrzimrh.supabase.co")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
WORKER_ID = "gh_swarm_worker"
WORKER_VERSION = "2.0.0"

_session = requests.Session()
_session.headers.update({
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
})


# ── Supabase Client ──
def supabase_request(method, endpoint, data=None, params=None):
    """Make a Supabase REST API request with error handling."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {}
    if method in ("POST", "PATCH"):
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    response = _session.request(method, url, json=data, headers=headers, params=params, timeout=15)
    if not response.text.strip():
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text


def log_to_system(event_type, details, status="info"):
    """Write structured log to system_logs table."""
    try:
        supabase_request("POST", "system_logs", {
            "node_id": WORKER_ID,
            "event_type": event_type,
            "details": details,
            "status": status,
        })
    except Exception:
        pass  # Non-critical


def write_hive_comm(message, to_node="all"):
    """Broadcast a message to hive_comms."""
    try:
        supabase_request("POST", "hive_comms", {
            "from_node": WORKER_ID,
            "to_node": to_node,
            "message": message,
            "status": "unread",
        })
    except Exception:
        pass


# ── Specialist Task Handlers ──

def handle_keepalive(task_id, payload):
    """Standard keepalive ping."""
    now = datetime.now(timezone.utc).isoformat()
    supabase_request("POST", "agent_memory", {
        "agent_id": WORKER_ID,
        "key": "last_ping",
        "value": json.dumps({"timestamp": now, "source": "GitHub Actions", "version": WORKER_VERSION}),
    })
    return {"status": "ok", "timestamp": now}


def handle_ping(task_id, payload):
    """Simple ping — confirms worker is alive."""
    return {"status": "pong", "worker": WORKER_ID, "version": WORKER_VERSION}


def handle_log(task_id, payload):
    """Log a message from another agent."""
    msg = payload.get("message", "No message")
    level = payload.get("level", "info")
    print(f"  [{level.upper()}] {msg}")
    log_to_system("agent_log", {"message": msg, "level": level, "task_id": task_id})
    return {"logged": True}


def handle_health_check(task_id, payload):
    """Comprehensive HIVE health check across all tables."""
    health = {}

    # Check task_queue stats
    tasks = supabase_request("GET", "task_queue?select=status&limit=100")
    if isinstance(tasks, list):
        status_counts = {}
        for t in tasks:
            s = t.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        health["task_queue"] = status_counts

    # Check agent count
    agents = supabase_request("GET", "swarm_agents?select=agent_id,status")
    if isinstance(agents, list):
        health["agents_total"] = len(agents)
        health["agents_active"] = sum(1 for a in agents if a.get("status") == "active")

    # Check unread comms
    comms = supabase_request("GET", "hive_comms?status=eq.unread&select=id")
    if isinstance(comms, list):
        health["unread_comms"] = len(comms)

    # Check unread outbox
    outbox = supabase_request("GET", "claude_outbox?status=eq.unread&select=id")
    if isinstance(outbox, list):
        health["unread_outbox"] = len(outbox)

    health["worker_version"] = WORKER_VERSION
    health["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Store health snapshot
    supabase_request("POST", "agent_memory", {
        "agent_id": WORKER_ID,
        "key": "last_health_check",
        "value": json.dumps(health),
    })

    log_to_system("health_check", health, "info")
    return health


def handle_intelligence_gather(task_id, payload):
    """Gather intelligence from a URL or topic (lightweight)."""
    topic = payload.get("topic", "")
    source = payload.get("source", "")

    result = {
        "topic": topic,
        "source": source,
        "status": "gathered",
        "note": "GitHub Actions worker gathered metadata. Deep research requires Manus or Antigravity node.",
    }

    # Store in swarm_intel
    if topic:
        supabase_request("POST", "swarm_intel", {
            "source": source or WORKER_ID,
            "title": f"Intel: {topic[:100]}",
            "content": json.dumps(payload),
            "summary": f"Intelligence request for: {topic}",
        })

    return result


def handle_notify(task_id, payload):
    """Send notification via hive_comms broadcast."""
    message = payload.get("message", "")
    to_node = payload.get("to_node", "all")
    priority = payload.get("priority", "normal")

    if message:
        write_hive_comm(f"[{priority.upper()}] {message}", to_node)
        return {"notified": True, "to": to_node}
    return {"notified": False, "error": "Empty message"}


def handle_cleanup(task_id, payload):
    """Clean up old/failed tasks from the queue."""
    target_status = payload.get("status", "failed")
    max_age_hours = payload.get("max_age_hours", 72)

    # Get old tasks with target status
    cutoff = datetime.now(timezone.utc)
    tasks = supabase_request("GET", f"task_queue?status=eq.{target_status}&select=id,created_at&limit=50")

    cleaned = 0
    if isinstance(tasks, list):
        for task in tasks:
            created = task.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("+00", "+00:00"))
                    age_hours = (cutoff - created_dt).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        supabase_request("PATCH", f"task_queue?id=eq.{task['id']}", {
                            "status": "archived",
                            "error": f"Auto-archived by cleanup (age: {age_hours:.0f}h)",
                        })
                        cleaned += 1
                except Exception:
                    pass

    log_to_system("cleanup", {"cleaned": cleaned, "target_status": target_status})
    return {"cleaned": cleaned, "target_status": target_status}


def handle_dispatch(task_id, payload):
    """Dispatch a sub-task to a specific specialist agent via task_queue."""
    target_agent = payload.get("agent", "")
    sub_task_type = payload.get("sub_task_type", "")
    sub_payload = payload.get("sub_payload", {})
    priority = payload.get("priority", 5)

    if not target_agent or not sub_task_type:
        return {"dispatched": False, "error": "Missing agent or sub_task_type"}

    new_task = supabase_request("POST", "task_queue", {
        "task_type": sub_task_type,
        "payload": sub_payload,
        "status": "pending",
        "priority": priority,
        "assigned_to": target_agent,
    })

    write_hive_comm(f"Dispatched {sub_task_type} to {target_agent} (priority: {priority})", target_agent)
    return {"dispatched": True, "target": target_agent, "sub_task_type": sub_task_type}


def handle_sync_state(task_id, payload):
    """Synchronize shared swarm state to shared_memory."""
    key = payload.get("key", "")
    value = payload.get("value", {})

    if not key:
        return {"synced": False, "error": "Missing key"}

    supabase_request("POST", "shared_memory", {
        "key": key,
        "value": json.dumps(value) if not isinstance(value, str) else value,
        "written_by": WORKER_ID,
    })

    return {"synced": True, "key": key}


def handle_shell(task_id, payload):
    """Execute a safe shell command (whitelisted only)."""
    command = payload.get("command", "")
    SAFE_COMMANDS = ["echo", "date", "whoami", "uname", "hostname", "uptime", "df", "free"]

    if not command:
        return {"executed": False, "error": "No command"}

    base_cmd = command.split()[0] if command else ""
    if base_cmd not in SAFE_COMMANDS:
        return {"executed": False, "error": f"Command '{base_cmd}' not in whitelist: {SAFE_COMMANDS}"}

    import subprocess
    try:
        result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
        return {
            "executed": True,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
        }
    except Exception as e:
        return {"executed": False, "error": str(e)[:500]}


# ── Task Router ──
TASK_HANDLERS = {
    "keepalive": handle_keepalive,
    "ping": handle_ping,
    "log": handle_log,
    "health_check": handle_health_check,
    "intelligence_gather": handle_intelligence_gather,
    "notify": handle_notify,
    "cleanup": handle_cleanup,
    "dispatch": handle_dispatch,
    "sync_state": handle_sync_state,
    "shell": handle_shell,
}


def process_tasks():
    """Check task_queue for pending tasks and route to specialist handlers."""
    tasks = supabase_request("GET", "task_queue?status=eq.pending&order=priority.asc,created_at.asc&limit=10")
    if not tasks or not isinstance(tasks, list):
        return 0

    processed = 0
    for task in tasks:
        task_id = task.get("id", "unknown")
        task_type = task.get("task_type", "unknown")
        payload = task.get("payload", {})
        assigned = task.get("assigned_to", "")
        short_id = task_id[:8] if len(task_id) > 8 else task_id

        # Skip tasks assigned to other agents
        if assigned and assigned not in ("", WORKER_ID, "gh_worker", "swarm"):
            continue

        print(f"  [{short_id}] Processing: {task_type}")

        # Mark as running
        supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
            "status": "running",
            "assigned_to": WORKER_ID,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        try:
            handler = TASK_HANDLERS.get(task_type)
            if handler:
                result = handler(task_id, payload)
                result_json = json.dumps(result) if isinstance(result, dict) else str(result)
            else:
                result_json = json.dumps({
                    "status": "unknown_type",
                    "note": f"No handler for task_type '{task_type}'. Available: {list(TASK_HANDLERS.keys())}",
                })
                print(f"  [{short_id}] Unknown task type: {task_type}")

            # Mark as done
            supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
                "status": "done",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            processed += 1

        except Exception as e:
            error_msg = f"{str(e)[:400]}\n{traceback.format_exc()[-200:]}"
            supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
                "status": "failed",
                "error": error_msg,
            })
            log_to_system("task_error", {"task_id": task_id, "task_type": task_type, "error": error_msg}, "error")
            print(f"  [{short_id}] FAILED: {str(e)[:100]}")

    return processed


def main():
    """Main entry point for the Specialist Swarm Worker."""
    print(f"🐝 Antigravity Specialist Swarm Worker v{WORKER_VERSION}")
    print(f"   Node: {WORKER_ID}")
    print(f"   Supabase: {SUPABASE_URL}")
    print(f"   Handlers: {list(TASK_HANDLERS.keys())}")
    print()

    if not SERVICE_KEY:
        print("  ❌ SUPABASE_SERVICE_KEY is not set. Exiting.")
        return

    # Always send keepalive
    handle_keepalive("startup", {})
    print("  ✅ Keepalive sent")

    # Process pending tasks
    try:
        processed = process_tasks()
        if processed > 0:
            print(f"\n  ✅ Processed {processed} task(s)")
        else:
            print("  💤 No pending tasks")
    except Exception as e:
        print(f"  ❌ Task processing error: {e}")
        log_to_system("worker_error", {"error": str(e)[:500]}, "error")

    # Run periodic health check (every run)
    try:
        health = handle_health_check("periodic", {})
        print(f"  📊 Health: {health.get('agents_active', '?')}/{health.get('agents_total', '?')} agents, "
              f"queue: {health.get('task_queue', {})}")
    except Exception as e:
        print(f"  ⚠️ Health check failed: {e}")

    print("\n  🏁 Worker cycle complete")


if __name__ == "__main__":
    main()
