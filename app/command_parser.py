from urllib.parse import urlencode


class CommandResult:
    UNKNOWN = "UNKNOWN_COMMAND"
    BLOCKED_CRITICAL = "BLOCKED_CRITICAL_COMMAND"
    PATROL_NEEDS_TWO = "PATROL_NEEDS_TWO_MARKERS"


LOCATION_ALIASES = {
    "lobby": "lobby",
    "front desk": "front_desk",
    "frontdesk": "front_desk",

    "waiting1": "waiting1",
    "waiting 1": "waiting1",
    "waiting one": "waiting1",
    "waiting won": "waiting1",
    "waiting area": "waiting1",

    "charging station": "charging_station",
    "charger": "charging_station",
    "charging": "charging_station",

    "room 205": "room_205",
    "room two oh five": "room_205",
    "room two zero five": "room_205",
}


def build_api_command(path, params=None):
    if not params:
        return path
    return f"{path}?{urlencode(params)}"


def normalize_location(location):
    stripped = location.strip()
    if stripped == "":
        return ""
    key = stripped.lower()
    if key in LOCATION_ALIASES:
        return LOCATION_ALIASES[key]        # aliases still match case-insensitively
    return stripped.replace(" ", "_")       # unaliased names keep their real casing


def translate_command(text):
    original = text.strip()
    text = original.lower()

    # Read-only status commands
    if text in ["status", "robot status", "what is your status"]:
        return "/api/robot_status"

    if text in ["battery", "power", "battery status", "power status"]:
        return "/api/get_power_status"

    if text in ["where are you", "current location", "location"]:
        return "/api/robot_status"

    if text in ["list markers", "show markers", "markers", "list locations"]:
        return "/api/markers/query_list"

    if text in ["current map", "what map are you using"]:
        return "/api/map/get_current_map"

    # Safety commands
    if text in ["stop", "cancel", "stop moving", "cancel movement"]:
        return "/api/move/cancel"

    if text in ["emergency stop", "estop", "e-stop", "stop immediately", "freeze"]:
        return build_api_command("/api/estop", {"flag": "true"})

    if text in ["disable emergency stop", "turn off estop", "resume from estop"]:
        return build_api_command("/api/estop", {"flag": "false"})

    # Move to marker
    for prefix in ["go to ", "move to ", "navigate to "]:
        if text.startswith(prefix):
            location = original[len(prefix):].strip()
            if location == "":
                return CommandResult.UNKNOWN
            marker = normalize_location(location)
            return build_api_command("/api/move", {"marker": marker})

    # Patrol multiple markers
    if text.startswith("patrol "):
        raw_locations = text.replace("patrol ", "", 1).strip()
        if raw_locations == "":
            return CommandResult.UNKNOWN
        locations = [loc.strip() for loc in raw_locations.split(",") if loc.strip()]
        markers = [normalize_location(loc) for loc in locations]
        if len(markers) < 2:
            return CommandResult.PATROL_NEEDS_TWO
        return build_api_command("/api/move", {
            "markers": ",".join(markers),
            "count": "1"
        })

    # Direct movement
    if text == "move forward":
        return build_api_command("/api/joy_control", {
            "linear_velocity": "0.2", "angular_velocity": "0"
        })
    if text == "move backward":
        return build_api_command("/api/joy_control", {
            "linear_velocity": "-0.2", "angular_velocity": "0"
        })
    if text == "turn left":
        return build_api_command("/api/joy_control", {
            "linear_velocity": "0", "angular_velocity": "0.5"
        })
    if text == "turn right":
        return build_api_command("/api/joy_control", {
            "linear_velocity": "0", "angular_velocity": "-0.5"
        })

    # Critical system commands
    if text in ["shutdown", "shut down", "power off", "turn off"]:
        return "/api/shutdown"

    if text in ["reboot", "restart"]:
        return build_api_command("/api/shutdown", {"reboot": "true"})

    if text in ["change wifi", "connect wifi", "set wifi"]:
        return CommandResult.BLOCKED_CRITICAL

    if text in ["delete markers", "delete all markers"]:
        return CommandResult.BLOCKED_CRITICAL

    if text in ["update software", "software update"]:
        return build_api_command("/api/software/update")

    # Lift
    if text in ["lift cabin", "lift up", "raise cabin"]:
        return build_api_command("/api/lift_cabin_control", {"action": "up"})

    if text in ["drop cabin", "lower cabin", "put cabin down"]:
        return build_api_command("/api/lift_cabin_control", {"action": "down"})

    # Return to charging
    if text in [
        "go back",
        "go back to charging",
        "return to charging",
        "go charge",
        "return to charger",
        "back to charger",
        "go back to charger",
    ]:
        return "/api/tools/operation/task/go-back"

    return CommandResult.UNKNOWN