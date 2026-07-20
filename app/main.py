import os
from datetime import datetime
from collections import deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

from .models import CommandRequest, ModeRequest, SequenceRequest, BatchMissionRequest, PlanBTextRequest
from .ai_parser import parse_commands
from .command_parser import translate_command
from .safety_checker import check_safety
from .robot_client import send_robot_command, set_dry_run, is_dry_run, poll_until_done, get_robot_status
from . import network_monitor
from . import mission_compiler
from . import tts
import json


class SpeakRequest(BaseModel):
    text: str


class NetworkThresholdRequest(BaseModel):
    good_threshold_ms: int


app = FastAPI(title="Robot Command Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

command_history: deque = deque(maxlen=50)
REAL_ROBOT_PASSPHRASE = "ENABLE REAL ROBOT"

_STOP_COMMANDS = ("stop", "emergency stop", "cancel", "halt", "freeze")

# Global abort flag — set to True when stop/estop is received.
# NOTE: this is a single process-wide flag, so if two sequences were ever run
# concurrently (two tabs/users at once) a stop from one would abort the
# other too. Fine for a single-operator kiosk-style deployment; if this ever
# becomes multi-user, swap this for a per-session/per-request abort token.
_sequence_abort = False

def _should_abort() -> bool:
    return _sequence_abort

def _set_abort(value: bool):
    global _sequence_abort
    _sequence_abort = value


def _extract_task_id(robot_response):
    """
    Try to find a robot task id from different possible response shapes.
    """
    if not isinstance(robot_response, dict):
        return None

    for key in ("task_id", "taskId", "taskid", "id", "taskID"):
        if robot_response.get(key):
            return robot_response.get(key)

    for key in ("data", "result", "results"):
        nested = robot_response.get(key)
        if isinstance(nested, dict):
            found = _extract_task_id(nested)
            if found:
                return found

    return None


def _looks_like_movement_command(interpreted: str, api_command: str, safety: dict) -> bool:
    """
    Decide whether the UI/backend should wait for the robot to finish.

    The old code only checked for "/api/move" or "go-back", which missed
    marker/navigation endpoints and made the UI say "done" too early.
    """
    interpreted = (interpreted or "").lower()
    api_command = (api_command or "").lower()
    level = (safety or {}).get("level")

    if interpreted.startswith("go to "):
        return True

    if interpreted in {
        "return to charger",
        "move forward",
        "move backward",
        "turn left",
        "turn right",
    }:
        return True

    if level == "WARNING":
        return True

    movement_keywords = (
        "/api/move",
        "go-back",
        "goto",
        "go_to",
        "marker",
        "navigate",
        "navigation",
        "chassis",
        "move",
        "position",
        "waypoint",
    )

    return any(k in api_command for k in movement_keywords)


def _normalize_robot_final_status(status):
    """
    Normalize robot/poll statuses so the frontend can display them consistently.
    """
    status = str(status or "").lower().strip()

    if status in {"succeeded", "success", "done", "completed", "complete", "arrived", "finished"}:
        return "succeeded"

    if status in {"failed", "fail", "error", "aborted", "cancelled", "canceled"}:
        return "failed"

    return status or "done"


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    network_monitor.start()
    print("[main] network monitor started")


# ── Single command helper ─────────────────────────────────────────────────────

def _execute_single(interpreted: str, confirmed: bool = False) -> dict:
    api_command = translate_command(interpreted)
    safety      = check_safety(api_command)

    result = {
        "interpreted_command": interpreted,
        "api_command":         api_command,
        "safety":              safety,
        "robot_response":      None,
        "status_message":      "",
        "dry_run":             is_dry_run(),
    }

    if safety["send_email"]:
        # TODO: no email transport is actually wired up yet — this only
        # logs to the console. Either hook up a real mailer (SMTP/SES/etc.)
        # or rename this field so it isn't implying an alert was sent.
        print(f"\n=== CRITICAL ===\nAPI: {api_command}\n================\n")
        result["status_message"] = "Command blocked. Critical alert logged."
        return result

    if safety["requires_confirmation"] and not confirmed:
        result["status_message"] = "Confirmation required before this command can run."
        return result

    should_execute = safety["allowed"] or (safety["requires_confirmation"] and confirmed)

    if should_execute:
        result["robot_response"] = send_robot_command(api_command)
        result["status_message"] = (
            "Dry-run: not sent to robot." if is_dry_run() else "Command sent to robot."
        )
    else:
        result["status_message"] = "Command blocked by safety policy."

    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    # BUGFIX: index.html lives at the project root (next to the app/
    # package), not in a nonexistent app/templates/ directory — this used
    # to raise FileNotFoundError on every request to "/".
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@app.get("/health")
async def health():
    return {
        "status":   "ok",
        "ai_model": "Qwen3.6 35B (primary) + Qwen2.5 0.5B (fallback)",
        "dry_run":  is_dry_run(),
    }


@app.post("/command")
async def run_command(req: CommandRequest):
    if not req.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty.")

    user_input = req.command.strip()
    commands   = parse_commands(user_input, allowed_locations=getattr(req, "allowed_locations", None))

    if len(commands) == 1:
        interpreted = commands[0]
        # If this is a stop or estop command, abort any running sequence
        if interpreted in _STOP_COMMANDS:
            _set_abort(True)
        res = _execute_single(interpreted, req.confirmed)
        record = {
            "user_input":          user_input,
            "interpreted_command": interpreted,
            "api_command":         res["api_command"],
            "safety":              res["safety"],
            "robot_response":      res["robot_response"],
            "status_message":      res["status_message"],
            "dry_run":             is_dry_run(),
            "timestamp":           datetime.now().isoformat(timespec="seconds"),
        }
        command_history.appendleft(record)
        return record

    # Reset abort state for a fresh multi-command batch, same as the SSE
    # sequence endpoint does.
    _set_abort(False)

    results = []
    for interpreted in commands:
        # BUGFIX: previously only the SSE /command/sequence endpoint checked
        # the abort flag between steps. A "stop" sent while a batch was
        # running through this endpoint never actually interrupted it.
        if interpreted in _STOP_COMMANDS:
            _set_abort(True)

        if _should_abort() and interpreted not in _STOP_COMMANDS:
            record = {
                "user_input":          user_input,
                "interpreted_command": interpreted,
                "api_command":         None,
                "safety":              {"level": "SAFETY", "allowed": False, "requires_confirmation": False, "send_email": False, "reason": "Skipped — stop command received."},
                "robot_response":      None,
                "status_message":      "Skipped — stop command received.",
                "dry_run":             is_dry_run(),
                "timestamp":           datetime.now().isoformat(timespec="seconds"),
            }
            command_history.appendleft(record)
            results.append(record)
            continue

        res = _execute_single(interpreted)
        record = {
            "user_input":          user_input,
            "interpreted_command": interpreted,
            "api_command":         res["api_command"],
            "safety":              res["safety"],
            "robot_response":      res["robot_response"],
            "status_message":      res["status_message"],
            "dry_run":             is_dry_run(),
            "timestamp":           datetime.now().isoformat(timespec="seconds"),
        }
        command_history.appendleft(record)
        results.append(record)

        is_movement = _looks_like_movement_command(
            interpreted,
            res["api_command"],
            res["safety"],
        )

        if is_movement and res["robot_response"] and not is_dry_run():
            task_id = _extract_task_id(res["robot_response"])
            final_status = poll_until_done(
                task_id,
                min_runtime_seconds=3.0,
                stable_done_polls=3,
            )

    first = results[0]
    first["status_message"] = f"Sequence of {len(commands)} commands executed."
    first["sequence_results"] = results
    return first


@app.get("/history")
async def get_history():
    return list(command_history)


@app.post("/mode")
async def set_mode(req: ModeRequest):
    if req.dry_run:
        set_dry_run(True)
        return {"dry_run": True, "message": "Switched to dry-run mode."}
    if req.confirmation != REAL_ROBOT_PASSPHRASE:
        raise HTTPException(status_code=403, detail=f"Wrong confirmation. Type exactly: {REAL_ROBOT_PASSPHRASE}")
    set_dry_run(False)
    return {"dry_run": False, "message": "Real robot mode enabled."}


@app.get("/mode")
async def get_mode():
    return {"dry_run": is_dry_run()}


# ── Robot ping ────────────────────────────────────────────────────────────────

@app.get("/robot/ping")
async def robot_ping():
    try:
        r = get_robot_status()
        if r:
            return {
                "connected":   True,
                "battery":     r.get("power_percent", "?"),
                "move_status": r.get("move_status", "?"),
                "floor":       r.get("current_floor", "?"),
            }
        return {"connected": False}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Network quality ───────────────────────────────────────────────────────────

@app.get("/network/status")
async def network_status():
    stats = network_monitor.get_stats()

    # Include the active threshold so the UI/debug panel can show whether
    # Plan B testing is forcing a low threshold like 1ms.
    getter = getattr(network_monitor, "get_good_threshold_ms", None)
    if callable(getter):
        stats["good_threshold_ms"] = getter()
    else:
        stats["good_threshold_ms"] = getattr(network_monitor, "GOOD_THRESHOLD", None)

    return stats


@app.post("/network/threshold")
async def set_network_threshold(req: NetworkThresholdRequest):
    """
    Runtime testing knob for Plan A / Plan B.

    The browser cannot edit .env while the server is running, so this endpoint
    lets the UI temporarily change the network degradation threshold.

    Example:
    - good_threshold_ms = 1   -> force Plan B / degraded network test
    - good_threshold_ms = 300 -> restore normal Plan A threshold

    This setting is in-memory only and resets when the server restarts.
    """
    value = max(1, int(req.good_threshold_ms))

    setter = getattr(network_monitor, "set_good_threshold_ms", None)
    if callable(setter):
        return setter(value)

    # Fallback for older network_monitor.py versions that do not yet expose
    # set_good_threshold_ms().
    network_monitor.GOOD_THRESHOLD = value
    return {
        "ok": True,
        "good_threshold_ms": value,
        "message": "Network threshold updated.",
    }


@app.get("/network/threshold")
async def get_network_threshold():
    getter = getattr(network_monitor, "get_good_threshold_ms", None)

    if callable(getter):
        value = getter()
    else:
        value = getattr(network_monitor, "GOOD_THRESHOLD", None)

    return {
        "good_threshold_ms": value,
    }


# ── Text-to-speech ────────────────────────────────────────────────────────────

@app.get("/tts/config")
async def tts_config():
    return tts.get_config_status()


@app.post("/tts/speak")
async def tts_speak(req: SpeakRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    audio, cache_status = await tts.speak(req.text)
    if audio is None:
        detail = "ElevenLabs TTS is not configured." if cache_status == "not_configured" else "TTS generation failed."
        raise HTTPException(status_code=503, detail=detail)

    return Response(content=audio, media_type="audio/mpeg", headers={"X-Cache-Status": cache_status})


# ── Batch mission (Plan B) ────────────────────────────────────────────────────

@app.post("/mission/preview")
async def mission_preview(req: BatchMissionRequest):
    """
    Compiles commands into a batch mission payload without sending it.
    Returns the payload for user review before firing.
    """
    if not req.commands:
        raise HTTPException(status_code=400, detail="No commands provided.")

    mission = mission_compiler.compile_mission(req.commands)
    return mission


@app.post("/mission/send")
async def mission_send(req: BatchMissionRequest):
    """
    Compiles and fires the full mission in one shot.
    Robot executes autonomously — no further network contact needed.
    """
    if not req.commands:
        raise HTTPException(status_code=400, detail="No commands provided.")

    mission = mission_compiler.compile_mission(req.commands)
    if not mission.get("ok"):
        raise HTTPException(status_code=400, detail=mission.get("error", "Compilation failed."))

    if is_dry_run():
        return {
            "dry_run":    True,
            "mission":    mission,
            "message":    "Dry-run: mission compiled but NOT sent to robot.",
        }

    robot_response = mission_compiler.send_mission(mission)

    record = {
        "user_input":          f"[BATCH] {len(req.commands)} commands",
        "interpreted_command": " → ".join(req.commands),
        "api_command":         mission["url"],
        "safety":              {"level": "WARNING", "allowed": True, "requires_confirmation": False, "send_email": False, "reason": "Batch mission"},
        "robot_response":      robot_response,
        "status_message":      "Batch mission dispatched to robot.",
        "dry_run":             False,
        "timestamp":           datetime.now().isoformat(timespec="seconds"),
    }
    command_history.appendleft(record)

    return {
        "mission":        mission,
        "robot_response": robot_response,
        "message":        "Batch mission dispatched. Robot will execute autonomously.",
    }


# ── Markers ───────────────────────────────────────────────────────────────────

@app.get("/markers")
async def get_markers():
    from .robot_client import CHASSIS_HOST
    import subprocess, json as _json
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", f"{CHASSIS_HOST}/api/markers/query_list"],
            capture_output=True, text=True, timeout=7
        )
        data = _json.loads(result.stdout)
        return {"ok": True, "results": data.get("results", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Sequence (SSE) ────────────────────────────────────────────────────────────

@app.post("/command/sequence")
async def run_sequence(req: SequenceRequest):
    raw = req.command.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")

    commands = parse_commands(raw, allowed_locations=getattr(req, "allowed_locations", None))
    _set_abort(False)  # reset abort flag for new sequence

    def event_stream():
        total = len(commands)
        yield f"data: {json.dumps({'type': 'start', 'total': total, 'commands': commands})}\n\n"

        for i, interpreted in enumerate(commands):
            # Check if stop/estop was received — abort sequence immediately
            if _should_abort():
                yield f"data: {json.dumps({'type': 'abort', 'index': i, 'reason': 'stop command received'})}\n\n"
                break

            api_command = translate_command(interpreted)
            safety      = check_safety(api_command)

            step = {
                "type":        "step",
                "index":       i,
                "total":       total,
                "input":       interpreted,
                "interpreted": interpreted,
                "api_command": api_command,
                "safety":      safety,
                "status":      "running",
            }

            if not safety["allowed"] and not safety["requires_confirmation"]:
                step["status"]  = "blocked"
                step["message"] = safety["reason"]
                yield f"data: {json.dumps(step)}\n\n"
                command_history.appendleft({**step, "user_input": interpreted, "robot_response": None,
                                            "status_message": safety["reason"], "dry_run": is_dry_run(),
                                            "timestamp": datetime.now().isoformat(timespec="seconds")})
                continue

            if safety["requires_confirmation"]:
                step["status"]  = "skipped"
                step["message"] = "Skipped in sequence — requires manual confirmation."
                yield f"data: {json.dumps(step)}\n\n"
                continue

            robot_response     = send_robot_command(api_command)
            step["robot_response"] = robot_response
            step["status"]     = "sent"
            yield f"data: {json.dumps(step)}\n\n"

            is_movement = _looks_like_movement_command(interpreted, api_command, safety)

            if is_movement and not is_dry_run():
                task_id = _extract_task_id(robot_response)

                step["status"] = "sent"
                step["message"] = "Command sent. Waiting for robot to finish."
                yield f"data: {json.dumps(step)}\n\n"

                final_status = poll_until_done(
                    task_id,
                    min_runtime_seconds=3.0,
                    stable_done_polls=3,
                )
                final_status = _normalize_robot_final_status(final_status)

                step["status"] = final_status
                step["message"] = f"Movement {final_status}."
                yield f"data: {json.dumps(step)}\n\n"

                if final_status == "failed":
                    yield f"data: {json.dumps({'type': 'abort', 'index': i, 'reason': 'movement failed'})}\n\n"
                    break
            else:
                step["status"] = "done"
                step["message"] = "Command completed."
                yield f"data: {json.dumps(step)}\n\n"

            command_history.appendleft({
                "user_input":          interpreted,
                "interpreted_command": interpreted,
                "api_command":         api_command,
                "safety":              safety,
                "robot_response":      robot_response if "robot_response" in step else None,
                "status_message":      step.get("message", ""),
                "dry_run":             is_dry_run(),
                "timestamp":           datetime.now().isoformat(timespec="seconds"),
            })

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/mission/send_text")
async def mission_send_text(req: PlanBTextRequest):
    """
    Plan B from natural speech/text.

    Takes raw user speech like:
    "go to waiting one then front desk then return a charger"

    Then:
    1. AI parses it into canonical commands.
    2. Invalid commands stop the mission.
    3. Batch mission is compiled.
    4. Mission is sent to robot in one shot.
    """
    raw = req.command.strip()

    if not raw:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")

    parsed_commands = parse_commands(
        raw,
        allowed_locations=getattr(req, "allowed_locations", None),
    )

    # Stop before unknown, same safety behavior as normal sequence mode.
    safe_commands = []

    for cmd in parsed_commands:
        if cmd == "unknown":
            break
        safe_commands.append(cmd)

    if not safe_commands:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "No valid batchable commands found.",
                "parsed_commands": parsed_commands,
            },
        )

    mission = mission_compiler.compile_mission(safe_commands)

    if not mission.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": mission.get("error", "Compilation failed."),
                "parsed_commands": parsed_commands,
                "safe_commands": safe_commands,
                "skipped": mission.get("skipped", []),
            },
        )

    if is_dry_run():
        return {
            "dry_run": True,
            "parsed_commands": parsed_commands,
            "safe_commands": safe_commands,
            "mission": mission,
            "message": "Dry-run: natural command parsed and mission compiled, but NOT sent to robot.",
        }

    robot_response = mission_compiler.send_mission(mission)

    record = {
        "user_input": raw,
        "interpreted_command": " → ".join(safe_commands),
        "api_command": mission["url"],
        "safety": {
            "level": "WARNING",
            "allowed": True,
            "requires_confirmation": False,
            "send_email": False,
            "reason": "Plan B batch mission from natural language",
        },
        "robot_response": robot_response,
        "status_message": "Plan B mission dispatched to robot.",
        "dry_run": False,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    command_history.appendleft(record)

    return {
        "parsed_commands": parsed_commands,
        "safe_commands": safe_commands,
        "mission": mission,
        "robot_response": robot_response,
        "message": "Plan B mission dispatched. Robot should execute autonomously.",
    }
