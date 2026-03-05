import json
import os
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ayhplxbihuyimtrzimrh.supabase.co")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

_session = requests.Session()
_session.headers.update({
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
})

def supabase_request(method, endpoint, data=None):
    """Make a Supabase REST API request."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {}
    if method in ("POST", "PATCH"):
        headers["Prefer"] = "resolution=merge-duplicates"
    response = _session.request(method, url, json=data, headers=headers, timeout=15)
    if not response.text.strip():
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text

def keepalive():
    """Ping Supabase to prevent project pausing."""
    now = datetime.now(timezone.utc).isoformat()
    supabase_request("POST", "agent_memory", {
        "agent_id": "gh_worker",
        "key": "last_ping",
        "value": json.dumps({"timestamp": now, "source": "GitHub Actions"})
    })
    print(f"[{now}] ✅ Keepalive ping sent")

def process_tasks():
    """Check task_queue for pending tasks and process them."""
    tasks = supabase_request("GET", "task_queue?status=eq.pending&order=priority.asc&limit=10")
    if not tasks or not isinstance(tasks, list):
        return 0

    processed = 0
    for task in tasks:
        task_id = task.get("id")
        task_type = task.get("task_type", "unknown")
        payload = task.get("payload", {})
        print(f"  📋 Processing task: {task_type} (id={task_id[:8]}...)")

        # Mark as running
        supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat()
        })

        try:
            # Task routing
            if task_type == "keepalive":
                keepalive()
            elif task_type == "log":
                print(f"  📝 Log: {payload.get('message', 'No message')}")
            else:
                print(f"  ⚠️ Unknown task type: {task_type}")

            # Mark as done
            supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
                "status": "done",
                "completed_at": datetime.now(timezone.utc).isoformat()
            })
            processed += 1
        except Exception as e:
            supabase_request("PATCH", f"task_queue?id=eq.{task_id}", {
                "status": "failed",
                "error": str(e)[:500]
            })
    return processed

def main():
    print("🤖 Antigravity Swarm Worker (GitHub Actions Edge)")
    print(f"   Supabase: {SUPABASE_URL}")
    print()

    if not SERVICE_KEY:
        print("  ❌ SUPABASE_SERVICE_KEY is not set. Exiting.")
        return

    # Always send keepalive
    keepalive()

    # Process tasks
    try:
        processed = process_tasks()
        if processed > 0:
            print(f"  ✅ Processed {processed} tasks")
        else:
            print("  💤 No pending tasks.")
    except Exception as e:
        print(f"  ❌ Task processing error: {e}")

if __name__ == "__main__":
    main()
