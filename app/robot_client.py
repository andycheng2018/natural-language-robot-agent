import os
import json
import time
import subprocess

DRY_RUN = True

CHASSIS_HOST  = os.getenv("ROBOT_CHASSIS_HOST", "http://10.1.17.225:9001")
TOOLS_HOST    = os.getenv("ROBOT_TOOLS_HOST",   "http://10.1.17.225:19001")
ROBOT_TIMEOUT = int(os.getenv("ROBOT_TIMEOUT_SECONDS", "10"))
POLL_INTERVAL = 1   # seconds between status checks
POLL_TIMEOUT  = 300 # max seconds to wait for a command to complete


def set_dry_run(value: bool):
    global DRY_RUN
    DRY_RUN = value


def is_dry_run() -> bool:
    return DRY_RUN


def get_host_for_command(api_command: str) -> str:
    if api_command.startswith("/api/tools/"):
        return TOOLS_HOST
    return CHASSIS_HOST


def get_method_for_command(api_command: str) -> str:
    if api_command == "/api/tools/operation/task/go-back":
        return "POST"
    return "GET"


def _curl(url: str, method: str = "GET") -> dict:
    """Fire a single curl request and return parsed JSON."""
    cmd = ["curl", "-s", "--max-time", str(ROBOT_TIMEOUT), url]
    if method == "POST":
        cmd += ["-X", "POST", "-d", ""]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=ROBOT_TIMEOUT + 2)
    if result.returncode != 0:
        return {"status": "ERROR", "error_message": result.stderr.strip() or f"curl exit {result.returncode}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "NON_JSON_RESPONSE", "text": result.stdout}


def send_robot_command(api_command: str) -> dict:
    method   = get_method_for_command(api_command)
    base_url = get_host_for_command(api_command)
    url      = base_url + api_command

    if DRY_RUN:
        return {
            "dry_run": True,
            "method":  method,
            "url":     url,
            "message": "Dry-run mode is ON. Command was not sent to robot.",
        }

    try:
        return _curl(url, method)
    except subprocess.TimeoutExpired:
        return {"status": "ERROR", "url": url, "error_message": f"Timed out after {ROBOT_TIMEOUT}s"}
    except Exception as e:
        return {"status": "ERROR", "url": url, "error_message": str(e)}


def get_robot_status() -> dict:
    """Return the robot_status results dict, or empty dict on failure."""
    try:
        data = _curl(f"{CHASSIS_HOST}/api/robot_status")
        return data.get("results", {})
    except Exception:
        return {}


def poll_until_done(
    task_id=None,
    min_runtime_seconds=3.0,
    stable_done_polls=3,
):
    """
    Poll robot status until the current movement is truly finished.

    Fixes premature completion by requiring:
    - the robot to run for at least min_runtime_seconds
    - several consecutive done/idle statuses before returning success
    - task_id matching when the robot exposes task_id
    """
    if DRY_RUN:
        return "succeeded"

    start = time.time()
    deadline = start + POLL_TIMEOUT

    seen_running = False
    consecutive_done = 0

    running_states = {
        "running",
        "moving",
        "navigating",
        "executing",
        "busy",
        "active",
        "in_progress",
    }

    done_states = {
        "succeeded",
        "success",
        "completed",
        "complete",
        "done",
        "finished",
        "arrived",
        "idle",
    }

    failed_states = {
        "failed",
        "fail",
        "error",
        "canceled",
        "cancelled",
        "aborted",
    }

    while time.time() < deadline:
        status = get_robot_status()

        move_status_raw = status.get("move_status", "")
        move_status = str(move_status_raw).lower().strip()

        current_task = (
            status.get("task_id")
            or status.get("taskId")
            or status.get("current_task_id")
            or ""
        )

        elapsed = time.time() - start

        print(
            f"[poll] elapsed={elapsed:.1f}s "
            f"move_status={move_status} "
            f"task_id={current_task} "
            f"target_task_id={task_id} "
            f"seen_running={seen_running} "
            f"done_count={consecutive_done}"
        )

        # If the robot provides task IDs, ignore statuses from the wrong task.
        if task_id and current_task and str(current_task) != str(task_id):
            time.sleep(POLL_INTERVAL)
            continue

        if move_status in failed_states:
            return "failed"

        if move_status in running_states:
            seen_running = True
            consecutive_done = 0
            time.sleep(POLL_INTERVAL)
            continue

        if move_status in done_states:
            # Do not trust immediate idle/done right after sending command.
            if elapsed < min_runtime_seconds:
                consecutive_done = 0
                time.sleep(POLL_INTERVAL)
                continue

            # For movement commands, prefer seeing running first.
            # But some robot APIs may never report running, so after the
            # minimum runtime we allow stable done states.
            consecutive_done += 1

            if consecutive_done >= stable_done_polls:
                if move_status in {"failed", "error", "canceled", "cancelled", "aborted"}:
                    return "failed"
                return "succeeded"

            time.sleep(POLL_INTERVAL)
            continue

        # Empty or unknown status should not count as done.
        consecutive_done = 0
        time.sleep(POLL_INTERVAL)

    return "timeout"