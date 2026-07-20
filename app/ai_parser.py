import json
import re
import urllib.request

# ── Model config ──────────────────────────────────────────────────────────────
USE_LARGE_MODEL  = True
LARGE_MODEL_URL  = "http://127.0.0.1:8080/v1/chat/completions"
LARGE_MODEL_NAME = "mlx-community/Qwen3.6-35B-A3B-6bit"

SMALL_MODEL_NAME = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
_model     = None
_tokenizer = None


BASE_MASTER_PROMPT = """\
You are a robot command parser. Your job is to convert natural language into a list of robot commands.

VALID COMMANDS:
- status
- battery
- where are you
- list markers
- current map
- stop
- emergency stop
- disable emergency stop
- go to <EXACT_LOCATION_FROM_ALLOWED_LIST>
- return to charger
- patrol <EXACT_LOCATION_FROM_ALLOWED_LIST>, <EXACT_LOCATION_FROM_ALLOWED_LIST>
- move forward
- move backward
- turn left
- turn right
- lift cabin
- drop cabin
- shutdown
- reboot
- change wifi
- delete markers
- update software
- unknown

OUTPUT FORMAT:
Always output a JSON array. One command per item. No explanation. No markdown. No thinking.

Example:
["command one", "command two"]

IMPORTANT LOCATION RULES:
- If the user asks to go to a place, choose the closest matching destination from ALLOWED LOCATIONS.
- For go-to commands, output the exact marker name from ALLOWED LOCATIONS.
- Do NOT invent locations.
- Do NOT output a location unless it appears exactly in ALLOWED LOCATIONS.
- If one destination in a multi-step sequence is not in ALLOWED LOCATIONS, output "unknown" only for that step.
- Keep valid earlier steps before the unknown step.
- Do not include any steps after the first unknown step.
- If the first destination is invalid, output ["unknown"].
- In a multi-step navigation command, later destinations may be written without repeating "go to".
- Example: "go to steakhouse then waiting one then waiting" means ["go to steakhouse", "go to waiting1", "go to waiting"].
- If the first command is valid, keep parsing later commands until the first invalid destination.

LOCATION EXAMPLES:
- If ALLOWED LOCATIONS contains "front_desk", and user says "front desk", output ["go to front_desk"].
- If ALLOWED LOCATIONS contains "waiting", and user says "go to waiting", output ["go to waiting"].
- If ALLOWED LOCATIONS contains "waiting1", and user says "waiting one", output ["go to waiting1"].
- If ALLOWED LOCATIONS contains "steakhouse", "waiting1", and "waiting", and user says "go to steakhouse then waiting one then waiting then return a charger", output ["go to steakhouse", "go to waiting1", "go to waiting", "return to charger"].
- If ALLOWED LOCATIONS contains "waiting1" and "front_desk", and user says "go to waiting one then front desk then banana", output ["go to waiting1", "go to front_desk", "unknown"].
- If user says "go to banana then front desk", output ["unknown"].

GENERAL RULES:
- If the input contains multiple tasks, split them into separate items.
- If the input is one task, return a single-item array.
- If not a robot command, such as greetings, chat, or questions about you, output ["unknown"].
- "battery" / "power" / "charge level" / "what's your battery" -> "battery"
- "where can you go" / "what locations" / "show markers" / "list the markers" -> "list markers"
- "halt" / "freeze" / "cancel" / "stop moving" -> "stop"
- "e-stop" / "estop" -> "emergency stop"
- "go back" / "go charge" / "back to charger" / "return to dock" / "go home" / "head back to base" -> "return to charger"
- "return a charger", "return charger", "back charger", "go charger", "go to charging", "go charging" -> "return to charger"
- "power off" / "shut down" / "turn off" -> "shutdown"
- "restart" -> "reboot"
- "hi" / "hello" / "hey" / "how are you" / "what's your name" -> "unknown"
- "where are you" / "what's your location" / "current position" -> "where are you"
- Multi-task indicators: "and", "also", "then", "after that", "as well", "plus", "next", "after"
- "come back" / "come home" / "return" at end of sequence -> "return to charger"

EXAMPLES:
Input: check the battery and list the markers
Output: ["battery", "list markers"]

Input: go home
Output: ["return to charger"]

Input: hello there
Output: ["unknown"]

Input: what's your battery and where are you
Output: ["battery", "where are you"]

Input: go to steakhouse then waiting one then waiting then return a charger
Output: ["go to steakhouse", "go to waiting1", "go to waiting", "return to charger"]
"""


_NORMALISE = {
    "status battery":              "battery",
    "check battery":               "battery",
    "check the battery":           "battery",
    "check power":                 "battery",
    "check status":                "status",
    "battery status":              "battery",
    "power status":                "battery",
    "power":                       "battery",
    "charge level":                "battery",
    "robot status":                "status",
    "what is your status":         "status",

    "current location":            "where are you",
    "location":                    "where are you",
    "what is your location":       "where are you",
    "current position":            "where are you",

    "show markers":                "list markers",
    "markers":                     "list markers",
    "list locations":              "list markers",
    "where can you go":            "list markers",
    "list the markers":            "list markers",
    "show me the markers":         "list markers",

    "what map are you using":      "current map",

    "cancel":                      "stop",
    "stop moving":                 "stop",
    "halt":                        "stop",
    "freeze":                      "stop",
    "e-stop":                      "emergency stop",
    "estop":                       "emergency stop",

    "go back":                     "return to charger",
    "go charge":                   "return to charger",
    "back to charger":             "return to charger",
    "go back to charger":          "return to charger",
    "return to charging":          "return to charger",
    "go to charger":               "return to charger",
    "return to dock":              "return to charger",
    "go to dock":                  "return to charger",
    "go home":                     "return to charger",
    "head back to base":           "return to charger",
    "go plug yourself in":         "return to charger",
    "come back":                   "return to charger",
    "come home":                   "return to charger",
    "return":                      "return to charger",
    "base":                        "return to charger",

    # Common speech-recognition mistakes
    "return a charger":            "return to charger",
    "return charger":              "return to charger",
    "back charger":                "return to charger",
    "go charger":                  "return to charger",
    "go charging":                 "return to charger",
    "go to charging":              "return to charger",
    "go back charging":            "return to charger",
    "return charging":             "return to charger",

    "power off":                   "shutdown",
    "shut down":                   "shutdown",
    "turn off":                    "shutdown",
    "restart":                     "reboot",

    "hi":                          "unknown",
    "hello":                       "unknown",
    "hey":                         "unknown",
    "how are you":                 "unknown",
    "whoami":                      "unknown",
    "what is your name":           "unknown",
    "whats your name":             "unknown",
    "who are you":                 "unknown",
    "speed":                       "unknown",
    "how fast":                    "unknown",
}

_KNOWN_COMMANDS = {
    "status",
    "battery",
    "where are you",
    "list markers",
    "current map",
    "stop",
    "emergency stop",
    "disable emergency stop",
    "return to charger",
    "move forward",
    "move backward",
    "turn left",
    "turn right",
    "lift cabin",
    "drop cabin",
    "shutdown",
    "reboot",
    "change wifi",
    "delete markers",
    "update software",
    "unknown",
}


def _build_prompt(allowed_locations: list[str] | None = None) -> str:
    locations = [str(x).strip() for x in (allowed_locations or []) if str(x).strip()]

    if not locations:
        location_block = """
ALLOWED LOCATIONS:
None provided.

Because no allowed locations were provided:
- Any go-to or patrol destination must become ["unknown"].
- Read-only commands like battery, status, list markers, and where are you are still valid.
"""
    else:
        location_lines = "\n".join(f"- {loc}" for loc in locations)
        location_block = f"""
ALLOWED LOCATIONS:
{location_lines}

You must use these exact marker names for navigation commands.
"""

    return BASE_MASTER_PROMPT + "\n" + location_block


def _is_exact_allowed_location(place: str, allowed_locations: list[str] | None) -> bool:
    if not allowed_locations:
        return False

    allowed = {str(loc).strip() for loc in allowed_locations if str(loc).strip()}
    return place.strip() in allowed


def _post_process(command: str, allowed_locations: list[str] | None = None):
    original = command.strip()
    cmd = original.lower().strip()

    if cmd in _NORMALISE:
        return _NORMALISE[cmd]

    for prefix in [
        "go to ",
        "move to ",
        "navigate to ",
        "head to ",
        "head over to ",
        "take me to ",
        "bring me to ",
        "visit ",
    ]:
        if cmd.startswith(prefix):
            place = original[len(prefix):].strip()

            # Final safety check:
            # The AI must output an exact marker name from allowed_locations.
            if not _is_exact_allowed_location(place, allowed_locations):
                return "unknown"

            return "go to " + place

    if cmd.startswith("patrol "):
        places_text = original[len("patrol "):].strip()
        raw_places = re.split(r",|\band\b|\bthen\b", places_text, flags=re.IGNORECASE)

        places = []

        for place in raw_places:
            place = place.strip()
            if not place:
                continue

            if not _is_exact_allowed_location(place, allowed_locations):
                return "unknown"

            places.append(place)

        if not places:
            return "unknown"

        return "patrol " + ", ".join(places)

    if cmd in _KNOWN_COMMANDS:
        return cmd

    return "unknown"


def _extract_array(text: str):
    """Extract a JSON array of strings from model output, handling think tags."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if not match:
        return None

    try:
        result = json.loads(match.group(0))
        if isinstance(result, list) and all(isinstance(i, str) for i in result):
            return [s.strip() for s in result if s.strip()]
    except json.JSONDecodeError:
        pass

    return None


def _strip_model_location_output(raw: str) -> str:
    """
    Make model location output usable without doing fuzzy normalization.

    Handles:
    - steakhouse
    - "steakhouse"
    - ["steakhouse"]
    - go to steakhouse

    It does NOT convert front desk -> front_desk.
    The AI must still choose the exact marker name.
    """
    clean = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    clean = clean.strip().strip('"').strip("'").strip()

    arr = _extract_array(clean)
    if arr and len(arr) == 1:
        clean = arr[0].strip()

    lower = clean.lower()
    if lower.startswith("go to "):
        clean = clean[6:].strip()

    clean = clean.rstrip(".").strip()
    return clean


def _ai_match_single_location(place_text: str, allowed_locations: list[str]) -> str | None:
    """
    Ask the model to map one short location phrase to exactly one marker.
    Returns exact marker name or None.
    """
    if not allowed_locations:
        return None

    allowed = [str(loc).strip() for loc in allowed_locations if str(loc).strip()]
    allowed_set = set(allowed)

    # If the phrase is already an exact marker, accept it.
    if place_text.strip() in allowed_set:
        return place_text.strip()

    location_lines = "\n".join(f"- {loc}" for loc in allowed)

    prompt = f"""\
You map a spoken destination phrase to one exact robot marker.

ALLOWED LOCATIONS:
{location_lines}

RULES:
- Return exactly one marker name from ALLOWED LOCATIONS.
- Return only the marker name.
- Do not return JSON.
- Do not say "go to".
- Do not explain.
- If there is no clear match, return unknown.

Examples:
User: front desk
Assistant: front_desk

User: waiting one
Assistant: waiting1

User: banana
Assistant: unknown
"""

    try:
        payload = json.dumps({
            "model": LARGE_MODEL_NAME if USE_LARGE_MODEL else SMALL_MODEL_NAME,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": place_text},
            ],
            "max_tokens": 40,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(
            LARGE_MODEL_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]

            raw = (
                msg.get("content") or
                msg.get("reasoning_content") or
                msg.get("reasoning") or
                ""
            )

            clean = _strip_model_location_output(raw)

            print(
                f"[ai_parser/location_match] "
                f"{repr(place_text)} -> raw={repr(raw)} clean={repr(clean)}"
            )

            if clean in allowed_set:
                return clean

            return None

    except Exception as e:
        print(f"[ai_parser/location_match] error: {e}")
        return None


def _basic_sequence_fallback(user_input: str, allowed_locations: list[str] | None = None):
    """
    Backup parser for common voice-style multi-destination commands.

    It helps with commands like:
    "go to Steakhouse then waiting one then waiting then return a charger"

    It still uses allowed_locations as the source of truth.
    It does not invent destinations.
    """
    if not allowed_locations:
        return ["unknown"]

    text = user_input.strip()
    lower = text.lower().strip()

    nav_starters = (
        "go to ",
        "go ",
        "navigate to ",
        "head to ",
        "take me to ",
        "bring me to ",
        "visit ",
    )

    if not lower.startswith(nav_starters):
        return ["unknown"]

    # Remove the first navigation starter.
    for starter in nav_starters:
        if lower.startswith(starter):
            text = text[len(starter):].strip()
            break

    # Split on common sequence words.
    parts = re.split(
        r"\bthen\b|\bafter that\b|\bnext\b|\band then\b|\band\b|,",
        text,
        flags=re.IGNORECASE,
    )

    allowed = [str(loc).strip() for loc in allowed_locations if str(loc).strip()]
    commands = []

    for raw_part in parts:
        part = raw_part.strip()
        if not part:
            continue

        part_lower = part.lower().strip()

        if part_lower in _NORMALISE:
            normalized = _NORMALISE[part_lower]
            commands.append(normalized)
            if normalized == "unknown":
                break
            continue

        if part_lower in {
            "return a charger",
            "return charger",
            "return to charger",
            "back charger",
            "back to charger",
            "go charger",
            "go to charger",
            "go home",
            "come back",
            "return",
            "return charging",
            "return to charging",
            "go charging",
            "go to charging",
        }:
            commands.append("return to charger")
            continue

        # Later parts may still say "go to X"; remove that local prefix.
        for prefix in [
            "go to ",
            "go ",
            "move to ",
            "navigate to ",
            "head to ",
            "head over to ",
            "take me to ",
            "bring me to ",
            "visit ",
        ]:
            if part_lower.startswith(prefix):
                part = part[len(prefix):].strip()
                part_lower = part.lower().strip()
                break

        match = _ai_match_single_location(part, allowed)

        if match:
            commands.append("go to " + match)
        else:
            commands.append("unknown")
            break

    return commands if commands else ["unknown"]


def _call_large_model(
    user_input: str,
    allowed_locations: list[str] | None = None,
    max_tokens: int = 200,
):
    try:
        payload = json.dumps({
            "model": LARGE_MODEL_NAME,
            "messages": [
                {"role": "system", "content": _build_prompt(allowed_locations)},
                {"role": "user", "content": user_input},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(
            LARGE_MODEL_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]

            raw_text = (
                msg.get("content") or
                msg.get("reasoning_content") or
                msg.get("reasoning") or
                ""
            )

            clean = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

            print(f"[ai_parser/35B] raw: {repr(clean)}")
            return clean if clean else None

    except Exception as e:
        print(f"[ai_parser/35B] error: {e}")
        return None


def _load_model_once():
    global _model, _tokenizer

    if _model is None or _tokenizer is None:
        from mlx_lm import load
        print(f"Loading MLX model {SMALL_MODEL_NAME}…")
        _model, _tokenizer = load(SMALL_MODEL_NAME)
        print("MLX model ready.")

    return _model, _tokenizer


def _call_small_model(
    user_input: str,
    allowed_locations: list[str] | None = None,
    max_tokens: int = 60,
):
    try:
        from mlx_lm import generate

        model, tokenizer = _load_model_once()

        messages = [
            {"role": "system", "content": _build_prompt(allowed_locations)},
            {"role": "user", "content": user_input},
        ]

        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        response = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            verbose=False,
        )

        print(f"[ai_parser/0.5B] raw: {repr(response)}")
        return response

    except Exception as e:
        print(f"[ai_parser/0.5B] error: {e}")
        return None


def _call_model(
    user_input: str,
    allowed_locations: list[str] | None = None,
    max_tokens: int = 200,
):
    if USE_LARGE_MODEL:
        raw = _call_large_model(user_input, allowed_locations, max_tokens)

        if raw is None:
            print("[ai_parser] 35B unavailable, falling back to 0.5B")
            raw = _call_small_model(user_input, allowed_locations, max_tokens)

    else:
        raw = _call_small_model(user_input, allowed_locations, max_tokens)

    return raw


def _process_command_list(commands: list[str], allowed_locations: list[str] | None = None):
    result = []

    for cmd in commands:
        processed = _post_process(cmd, allowed_locations)

        if not processed:
            continue

        result.append(processed)

        # Desired safety behavior:
        # - Execute valid commands before the first invalid command.
        # - Stop the sequence once the first unknown appears.
        if processed == "unknown":
            break

    return result if result else ["unknown"]


def parse_commands(user_input: str, allowed_locations: list[str] | None = None):
    raw = _call_model(user_input, allowed_locations)

    if not raw:
        return ["unknown"]

    commands = _extract_array(raw)

    if not commands:
        first_line = raw.strip().split("\n")[0].strip()
        commands = [first_line] if first_line else ["unknown"]

    result = _process_command_list(commands, allowed_locations)

    # Voice/multi-destination fallback:
    # If the main AI parser gave up entirely, try a targeted step splitter.
    if result == ["unknown"]:
        fallback = _basic_sequence_fallback(user_input, allowed_locations)
        fallback_processed = _process_command_list(fallback, allowed_locations)

        if fallback_processed != ["unknown"]:
            result = fallback_processed

    print(f"[ai_parser] allowed_locations: {allowed_locations}")
    print(f"[ai_parser] -> {result}")

    return result


def ai_normalize_command(user_input: str, allowed_locations: list[str] | None = None):
    return parse_commands(user_input, allowed_locations)[0]


def split_commands(user_input: str, allowed_locations: list[str] | None = None):
    return parse_commands(user_input, allowed_locations)