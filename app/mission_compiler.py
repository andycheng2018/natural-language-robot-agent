"""
mission_compiler.py

Compiles a list of canonical commands into a single task-flow payload
that the robot can execute autonomously — even with no further network contact.

Input commands should already be parsed by ai_parser.py, for example:
- go to waiting1
- go to front_desk
- return to charger
- patrol waiting1, front_desk
"""

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()


# ── Robot identifiers ─────────────────────────────────────────────────────────
CHASSIS_SN = os.getenv("CHASSIS_SN", "WTHT08E03B0616789")
CABIN_SN = os.getenv("CABIN_SN", "SCQS00G13C0100349")
CABIN_ID = os.getenv("CABIN_ID", "7A939508")

TOOLS_HOST = os.getenv("TOOLS_HOST", "http://10.1.17.225:19001")
STORE_ID = os.getenv("STORE_ID", "202412209218662201730709785088")
CLIENT_TOKEN = os.getenv("CLIENT_TOKEN", "41f04677025c4808a1df84138eb6e53e")


# ── Executor builders ─────────────────────────────────────────────────────────

def _exec_move(marker: str, task_id: str) -> str:
    return json.dumps({
        "optionId": "0002",
        "executionId": "move",
        "params": {
            "attach": {
                "storeId": STORE_ID,
                "taskId": [task_id],
            },
            "marker": marker,
            "maxSpeedLinear": 1,
        },
    })


def _exec_go_back(task_id: str) -> str:
    return json.dumps({
        "optionId": "1001",
        "executionId": "self_decision_go_back",
        "params": {
            "action": "GO_BACK",
            "attach": {
                "storeId": STORE_ID,
                "taskId": [task_id],
            },
        },
    })


def _exec_dock_cabin(task_id: str) -> str:
    return json.dumps({
        "optionId": "1001",
        "executionId": "docking_cabin",
        "params": {
            "cabinKey": CABIN_SN,
            "attach": {
                "storeId": STORE_ID,
                "taskId": [task_id],
            },
            "cabinType": "sweep",
            "hcp": 2,
        },
    })


# ── Main compiler ─────────────────────────────────────────────────────────────

def compile_mission(commands: list[str]) -> dict:
    """
    Takes canonical parsed commands and compiles them into one task-flow payload.

    Example input:
    [
        "go to waiting1",
        "go to front_desk",
        "return to charger"
    ]

    Returns:
    {
        "ok": True,
        "task_id": str,
        "payload": dict,
        "url": str,
        "skipped": list[str],
        "executors_count": int,
        "commands": list[str],
    }
    """
    task_id = str(int(time.time())) + uuid.uuid4().hex[:6]
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    executors = []
    skipped = []

    for cmd in commands:
        cmd = str(cmd or "").strip()

        if not cmd:
            continue

        cmd_lower = cmd.lower()

        # Navigation — use the exact marker name from ai_parser.
        # Do NOT lowercase the marker because robot markers may be case-sensitive.
        if cmd_lower.startswith("go to "):
            marker = cmd[6:].strip()

            if marker:
                executors.append(_exec_move(marker, task_id))
            else:
                skipped.append(f"{cmd} (missing marker)")

        # Return to charger
        elif cmd_lower in (
            "return to charger",
            "go back",
            "go charge",
            "back to charger",
            "return to charging",
        ):
            executors.append(_exec_go_back(task_id))

        # Dock cabin
        elif cmd_lower in ("dock cabin", "attach cabin"):
            executors.append(_exec_dock_cabin(task_id))

        # Patrol — expand into individual exact-marker moves.
        # Use the exact names from ai_parser. Do not alias/lowercase them.
        elif cmd_lower.startswith("patrol "):
            raw = cmd[7:].strip()
            locations = [loc.strip() for loc in raw.split(",") if loc.strip()]

            if not locations:
                skipped.append(f"{cmd} (no patrol locations)")
                continue

            for loc in locations:
                executors.append(_exec_move(loc, task_id))

            # Return to first marker to complete the loop.
            executors.append(_exec_move(locations[0], task_id))

        # Read-only commands — safe to skip in batch.
        elif cmd_lower in (
            "battery",
            "status",
            "where are you",
            "list markers",
            "current map",
        ):
            skipped.append(f"{cmd} (read-only, skipped in batch)")

        # Stop / safety commands — cannot be batched meaningfully.
        elif cmd_lower in (
            "stop",
            "emergency stop",
            "cancel",
            "halt",
            "freeze",
        ):
            skipped.append(f"{cmd} (safety command, skipped in batch)")

        # Invalid command — stop compiling anything after this.
        elif cmd_lower == "unknown":
            skipped.append(f"{cmd} (invalid command, stopping batch compilation)")
            break

        # Unsupported command — skip, but continue compiling later valid commands.
        else:
            skipped.append(f"{cmd} (unsupported in batch mode)")

    if not executors:
        return {
            "ok": False,
            "error": "No batchable commands found.",
            "skipped": skipped,
            "commands": commands,
        }

    executors_str = "[" + ",".join(executors) + "]"

    payload = {
        "cabinKey": "123",
        "cabinDeviceType": 456,
        "taskType": 0,
        "clientToken": CLIENT_TOKEN,
        "executors": executors_str,
        "forceCancel": False,
        "taskId": task_id,
        "versionNumber": "1",
        "timestamp": now_utc,
    }

    return {
        "ok": True,
        "task_id": task_id,
        "payload": payload,
        "url": f"{TOOLS_HOST}/api/v1/task/flow",
        "skipped": skipped,
        "executors_count": len(executors),
        "commands": commands,
    }


def send_mission(mission: dict) -> dict:
    """
    Sends the compiled mission payload to the robot in one shot.
    After this succeeds, the robot should be able to continue executing
    the mission even if Wi-Fi becomes unstable.
    """
    if not mission.get("ok"):
        return {
            "ok": False,
            "error": mission.get("error", "Invalid mission"),
        }

    payload_str = json.dumps(mission["payload"])

    cmd = [
        "curl",
        "-s",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", payload_str,
        "--max-time", "10",
        mission["url"],
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=12,
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "error": f"curl exit {result.returncode}",
                "stderr": result.stderr,
                "stdout": result.stdout,
            }

        try:
            data = json.loads(result.stdout)
            return {
                "ok": True,
                "response": data,
            }
        except json.JSONDecodeError:
            return {
                "ok": True,
                "status": "NON_JSON",
                "text": result.stdout,
            }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }