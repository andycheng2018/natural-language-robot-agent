<<<<<<< HEAD
# natural-language-robot-agent
A voice and text interface that turns natural-language commands into safety-checked robot actions.
=======
# Robot Command Agent

A voice-enabled robot command interface that combines the conversational UX of an AI receptionist with a safety-gated robot command pipeline.

Speak or type a natural language command → OpenAI interprets it → the safety checker classifies risk → allowed commands are dispatched to the physical robot via its REST API.

## Architecture

```
User (voice or text)
  → Browser speech recognition
  → POST /command
  → ai_parser.ai_normalize_command()    # OpenAI: NL → canonical command string
  → command_parser.translate_command()  # canonical string → robot API path
  → safety_checker.check_safety()       # classify risk level
  → robot_client.send_robot_command()   # dispatch if allowed
  → Response + ElevenLabs TTS feedback
```

## Main Files

```
robot-agent/
  app/
    main.py            # FastAPI app, routes, orchestration
    ai_parser.py       # OpenAI-based NL → command normalizer
    command_parser.py  # Canonical string → robot API path
    safety_checker.py  # Risk classification + allow/block/confirm logic
    robot_client.py    # HTTP dispatch to robot chassis/tools endpoints
    tts.py             # ElevenLabs TTS (with browser fallback)
    models.py          # Pydantic request/response schemas
  tests/
    test_commands.py   # Pytest suite for parser + safety (no API key needed)
  index.html           # Single-page UI
  requirements.txt
  .env.example
```

## Safety Levels

| Level        | Behaviour                                           |
|--------------|-----------------------------------------------------|
| SAFE         | Read-only queries. Always allowed.                  |
| SAFETY       | Stop/e-stop commands. Always allowed.               |
| WARNING      | Normal navigation. Allowed without confirmation.    |
| HIGH_WARNING | Direct motion or hardware. Requires confirmation.   |
| CRITICAL     | System/config/shutdown. Blocked + alert logged.     |
| INVALID      | Unknown or unparseable command.                     |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in OPENAI_API_KEY (required) and optionally ELEVENLABS_* keys
```

## Running

```bash
uvicorn app.main:app --reload
```

Open: http://127.0.0.1:8000

## Environment Variables

| Variable                  | Description                              | Default               |
|---------------------------|------------------------------------------|-----------------------|
| `OPENAI_API_KEY`          | Required for AI command interpretation   | —                     |
| `OPENAI_MODEL`            | OpenAI model to use                      | `gpt-4.1-mini`        |
| `ELEVENLABS_API_KEY`      | Optional TTS                             | —                     |
| `ELEVENLABS_VOICE_ID`     | ElevenLabs voice ID                      | —                     |
| `ROBOT_CHASSIS_HOST`      | Robot chassis REST API base URL          | `http://10.1.16.127:9001` |
| `ROBOT_TOOLS_HOST`        | Robot tools REST API base URL            | `http://10.1.16.127:19001` |
| `ROBOT_TIMEOUT_SECONDS`   | Timeout for robot HTTP calls             | `10`                  |

## API Endpoints

```
GET  /           Browser UI
GET  /health     System status (OpenAI, ElevenLabs, dry-run mode)
POST /command    Run a command  {"command": "go to lobby", "confirmed": false}
GET  /history    Last 50 command results
POST /mode       Set dry-run or real mode
GET  /mode       Current mode
GET  /tts/config ElevenLabs configuration status
POST /tts/speak  Generate MP3 audio {"text": "..."}
```

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests cover the parser and safety checker without requiring an OpenAI key.

## Key Differences from Original Flask Version

- **FastAPI** instead of Flask — async, typed, auto-documented at `/docs`
- **OpenAI** instead of local MLX model — more reliable NL understanding, no GPU required
- **ElevenLabs TTS** with browser speech synthesis fallback — same as the receptionist project
- **`requests`** instead of `subprocess + curl` for robot HTTP calls
- **JSON API** instead of Jinja2 form submission — UI is a proper single-page app
- **Pytest suite** with assertions instead of a print-only test script
- **`deque(maxlen=50)`** for thread-safe history instead of a global list with manual pop
- **Dry-run default is True** — you have to explicitly unlock real robot mode

## Modes

The app starts in **dry-run mode** — commands are parsed and safety-checked but not sent.

To enable real dispatch, type exactly `ENABLE REAL ROBOT` in the mode panel.
## Changelog (bug-fix / cleanup pass)

- Fixed `poll_until_done()` crashing with `UnboundLocalError` the first time a real (non-dry-run) move command polled robot status.
- Fixed `GET /` throwing `FileNotFoundError` — it was looking for `app/templates/index.html`, which never existed; `index.html` lives at the project root.
- Fixed the `app/*` import structure so it matches what the test suite expects (`from app.command_parser import ...`) — imports inside the package are now relative.
- `/tts/config` and `/tts/speak` were documented in this README but never implemented in `main.py`; they're wired up now.
- A "stop" command sent mid-batch through the plain `/command` endpoint (as opposed to the streaming `/command/sequence` endpoint) now actually aborts the remaining queued commands instead of being ignored.
- Capped the in-memory TTS cache so it can't grow unbounded over a long-running process.
- Removed dead code (`_exec_estop` stub in `mission_compiler.py`).
- Refreshed `index.html`'s visual design (mission-control theme, no functional/JS changes).
>>>>>>> 0ed89e5 (Initial commit)
