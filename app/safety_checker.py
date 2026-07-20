from urllib.parse import parse_qs
from .command_parser import CommandResult


class RiskLevel:
    SAFE = "SAFE"
    WARNING = "WARNING"
    HIGH_WARNING = "HIGH_WARNING"
    CRITICAL = "CRITICAL"
    SAFETY = "SAFETY"
    INVALID = "INVALID"


COMMAND_RISK = {
    # SAFE: Read-only commands
    "/api/robot_status": RiskLevel.SAFE,
    "/api/robot_info": RiskLevel.SAFE,
    "/api/get_power_status": RiskLevel.SAFE,
    "/api/get_current_location": RiskLevel.SAFE,
    "/api/lift_status": RiskLevel.SAFE,
    "/api/request_data": RiskLevel.SAFE,
    "/api/markers/query_list": RiskLevel.SAFE,
    "/api/markers/query_brief": RiskLevel.SAFE,
    "/api/markers/count": RiskLevel.SAFE,
    "/api/map/list": RiskLevel.SAFE,
    "/api/map/get_current_map": RiskLevel.SAFE,
    "/api/map/list_info": RiskLevel.SAFE,
    "/api/get_planned_path": RiskLevel.SAFE,
    "/api/make_plan": RiskLevel.SAFE,
    "/api/wifi/list": RiskLevel.SAFE,
    "/api/wifi/detail_list": RiskLevel.SAFE,
    "/api/wifi/get_active_connection": RiskLevel.SAFE,
    "/api/wifi/info": RiskLevel.SAFE,
    "/api/software/get_version": RiskLevel.SAFE,

    # WARNING: Normal navigation
    "/api/move": RiskLevel.WARNING,
    "/api/tools/operation/task/go-back": RiskLevel.WARNING,

    # SAFETY: Stop/cancel
    "/api/move/cancel": RiskLevel.SAFETY,

    # HIGH_WARNING: Direct control or hardware changes
    "/api/joy_control": RiskLevel.HIGH_WARNING,
    "/api/markers/insert": RiskLevel.HIGH_WARNING,
    "/api/markers/insert_by_pose": RiskLevel.HIGH_WARNING,
    "/api/position_adjust": RiskLevel.HIGH_WARNING,
    "/api/docking": RiskLevel.HIGH_WARNING,
    "/api/lift_cabin_control": RiskLevel.HIGH_WARNING,

    # CRITICAL: System/config/shutdown
    "/api/markers/delete": RiskLevel.CRITICAL,
    "/api/position_adjust_by_pose": RiskLevel.CRITICAL,
    "/api/map/set_current_map": RiskLevel.CRITICAL,
    "/api/shutdown": RiskLevel.CRITICAL,
    "/api/wifi/connect": RiskLevel.CRITICAL,
    "/api/software/check_for_update": RiskLevel.CRITICAL,
    "/api/software/update": RiskLevel.CRITICAL,

    # Parameter-dependent
    "/api/estop": "PARAM_DEPENDENT",
}


def parse_api_command(api_command):
    if "?" not in api_command:
        return api_command, {}
    path, query_string = api_command.split("?", 1)
    parsed = parse_qs(query_string)
    params = {key: value[0] if value else "" for key, value in parsed.items()}
    return path, params


def classify_command(api_command):
    if api_command in (CommandResult.UNKNOWN, CommandResult.PATROL_NEEDS_TWO):
        return RiskLevel.INVALID

    if api_command == CommandResult.BLOCKED_CRITICAL:
        return RiskLevel.CRITICAL

    path, params = parse_api_command(api_command)

    if path == "/api/estop":
        if params.get("flag") == "true":
            return RiskLevel.SAFETY
        return RiskLevel.CRITICAL

    if path == "/api/lift_cabin_control":
        if params.get("action") == "up":
            return RiskLevel.HIGH_WARNING
        return RiskLevel.CRITICAL

    if path == "/api/move":
        if "marker" in params or "markers" in params:
            return RiskLevel.WARNING
        if "location" in params:
            return RiskLevel.HIGH_WARNING
        return RiskLevel.CRITICAL

    if path == "/api/request_data":
        topic = params.get("topic")
        if topic in ["robot_status", "robot_velocity", "human_detection"]:
            return RiskLevel.SAFE
        return RiskLevel.CRITICAL

    return COMMAND_RISK.get(path, RiskLevel.CRITICAL)


def check_safety(api_command):
    level = classify_command(api_command)

    if level == RiskLevel.INVALID:
        reason = "Patrol commands need at least two locations." \
            if api_command == CommandResult.PATROL_NEEDS_TWO \
            else "Command is unclear or unsupported."
        return {
            "level": RiskLevel.INVALID,
            "allowed": False,
            "requires_confirmation": False,
            "send_email": False,
            "reason": reason,
        }

    if api_command == CommandResult.BLOCKED_CRITICAL:
        return {
            "level": RiskLevel.CRITICAL,
            "allowed": False,
            "requires_confirmation": False,
            "send_email": True,
            "reason": "This command could affect robot system safety or configuration.",
        }

    if level == RiskLevel.SAFE:
        return {
            "level": level,
            "allowed": True,
            "requires_confirmation": False,
            "send_email": False,
            "reason": "Read-only command — no robot state will change.",
        }

    if level == RiskLevel.SAFETY:
        return {
            "level": level,
            "allowed": True,
            "requires_confirmation": False,
            "send_email": False,
            "reason": "Safety command — stops or cancels robot movement.",
        }

    if level == RiskLevel.WARNING:
        return {
            "level": level,
            "allowed": True,
            "requires_confirmation": False,
            "send_email": False,
            "reason": "Normal navigation — robot will move using pathfinding.",
        }

    if level == RiskLevel.HIGH_WARNING:
        return {
            "level": level,
            "allowed": False,
            "requires_confirmation": True,
            "send_email": False,
            "reason": "Direct hardware or motion control — requires confirmation before execution.",
        }

    if level == RiskLevel.CRITICAL:
        return {
            "level": level,
            "allowed": False,
            "requires_confirmation": False,
            "send_email": True,
            "reason": "Command may affect safety, configuration, networking, shutdown, or software — blocked.",
        }

    # Defensive fallback
    return {
        "level": RiskLevel.CRITICAL,
        "allowed": False,
        "requires_confirmation": False,
        "send_email": True,
        "reason": "Unknown safety level — blocked by default.",
    }