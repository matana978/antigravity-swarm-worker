import subprocess
import json
import os
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ayhplxbihuyimtrzimrh.supabase.co")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def supabase_request(method, endpoint, data=None):
    """Make a Supabase REST API request via curl."""
    cmd = ["curl", "-s", "-X", method, f"{SUPABASE_URL}/rest/v1/{endpoint}",
           "-H", f"apikey: {SERVICE_KEY}",
           "-H", f"Authorization: Bearer {SERVICE_KEY}",
           "-H", "Content-Type: application/json"]
    if method in ["POST", "PATCH"]:
        cmd.extend(["-H", "Prefer: resolution=merge-duplicates"])
    if data:
        cmd.extend(["-d", json.dumps(data)])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except:
        return result.stdout

def keepalive():
    """Ping Supabase to prevent project pausing."""
    now = datetime.utcnow().isoformat()
    supabase_request("POST", "agent_memory", {
        "agent_id": "gh_worker",
        "key": "last_ping",
        "value": json.dumps({"timestamp": now, "source": "GitHub Actions"})
    })
    print(f"[{now}] ✅ Keepalive ping sent")

def process_tasks():
    """Check task_queue for pending tasks and process them."""
    tasks = supabase_request("GET", "task_queue?status=eq.pending&order=priority.asc&limit=10")
    if not tasks or not isinstance(tasks, list) or len(tasks) == 0:
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
            "started_at": datetime.utcnow().isoformat()
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
                "completed_at": datetime.utcnow().isoformat()
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
