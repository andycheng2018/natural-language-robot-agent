# Natural Language Robot Agent

A voice- and text-controlled interface that translates natural-language instructions into safety-checked commands for a physical service robot.

The project supports both normal step-by-step execution and an offline-friendly **Plan B** that compiles an entire route into one autonomous mission when the network is degraded.

## Demo Video

Watch the robot execute natural-language commands:

[![Robot Command Agent demo](https://drive.google.com/thumbnail?id=1QsV8AOX1vbax9YXLub07znFkoCE6saX6&sz=w1200)](https://drive.google.com/file/d/1QsV8AOX1vbax9YXLub07znFkoCE6saX6/view?usp=sharing)

**[Open the full demo video in Google Drive](https://drive.google.com/file/d/1QsV8AOX1vbax9YXLub07znFkoCE6saX6/view?usp=sharing)**

**Anyone with the link can view**.

## User Manual

For a step-by-step walkthrough of the interface, command flow, safety controls, Plan A, and Plan B, see the full user guide:

**[Open the Robot Command Agent User Manual](https://docs.google.com/document/d/1KqaA28YRWo-C0sdNNKRA46MXr6iLM9BtN0A01re0K98/edit?tab=t.5r2cj8r13v7c)**


## Demo Flow

```text
Voice or text input
        ↓
Local Qwen command parser
        ↓
Canonical robot commands
        ↓
Robot REST API translation
        ↓
Safety classification
        ↓
Dry-run, confirmation, block, or dispatch
        ↓
Live progress and spoken feedback
```

Example:

```text
"Go to waiting one, then the front desk, then return to the charger"
```

becomes:

```text
go to waiting1
go to front_desk
return to charger
```

The parser only accepts locations reported by the robot and stops the sequence when it encounters an unknown destination.

## What I Built

### Natural-language command parsing

- Accepts typed commands and browser speech recognition
- Splits multi-step requests into ordered robot actions
- Normalizes alternate wording such as “go home,” “halt,” or “waiting one”
- Matches spoken destinations against the robot’s allowed marker list
- Prevents the model from inventing locations
- Uses a locally hosted Qwen 3.6 35B model as the primary parser
- Falls back to a smaller Qwen 2.5 0.5B MLX model when the primary model is unavailable
- Includes a rule-based fallback for common voice-style navigation sequences

### Safety-gated execution

Every translated API request is classified before it can reach the robot.

| Level | Behavior |
|---|---|
| `SAFE` | Read-only status and information requests are allowed |
| `SAFETY` | Stop and emergency-stop actions are allowed immediately |
| `WARNING` | Normal marker-based navigation is allowed |
| `HIGH_WARNING` | Direct movement or hardware control requires confirmation |
| `CRITICAL` | Shutdown, networking, configuration, marker deletion, and software-update operations are blocked |
| `INVALID` | Unknown or malformed commands are rejected |

The app starts in **dry-run mode**, so commands can be parsed and reviewed without controlling the real robot. Real-robot mode requires the exact confirmation phrase:

```text
ENABLE REAL ROBOT
```

### Plan A: connected sequence execution

In normal network conditions, commands are sent one at a time.

- Streams step-by-step progress to the UI with Server-Sent Events
- Waits for movement to actually finish before sending the next command
- Tracks robot task IDs when available
- Requires a minimum runtime and multiple stable completion polls to avoid reporting success too early
- Aborts the remaining sequence when a stop command is received
- Stops the sequence when a movement fails

### Plan B: autonomous mission execution

A background monitor measures robot API latency and packet loss.

When the connection becomes degraded, the UI can switch to Plan B:

1. Parse the full natural-language instruction
2. Validate destinations
3. Compile supported actions into one robot task-flow payload
4. Send the mission in a single request
5. Let the robot continue autonomously without further network contact

Plan B supports:

- Multi-stop marker navigation
- Patrol routes
- Return-to-charger actions
- Cabin docking
- Mission preview before dispatch
- Dry-run mission compilation
- Runtime network-threshold adjustment for testing Plan A and Plan B

Read-only, safety, invalid, and unsupported commands are skipped or stop compilation as appropriate.

### Robot integration

- Separate REST hosts for chassis and tool operations
- Automatic GET/POST method selection
- Marker discovery from the physical robot
- Robot connectivity, battery, movement status, and floor display
- Command completion polling
- Configurable request and polling timeouts
- Last 50 command results stored in memory

### Voice feedback

- Optional ElevenLabs text-to-speech
- Configurable voice, model, output format, stability, similarity, and style
- In-memory audio caching
- Browser speech-synthesis fallback in the frontend

### Interface

The single-page control panel includes:

- Voice and text command entry
- Robot online/offline status
- Dry-run and real-robot indicators
- Safety-level explanations
- Confirmation modal for higher-risk actions
- Pending command queue
- Live sequence progress
- Command history
- Network quality and latency information
- Plan B warning and mission controls
- Marker refresh
- Optional spoken replies
- Expandable system and maintenance commands

## Architecture

```text
index.html
   │
   ├── browser speech recognition
   ├── command queue and history UI
   ├── network/robot status panels
   └── streamed sequence updates
           │
           ▼
FastAPI — app/main.py
   │
   ├── ai_parser.py
   │     Natural language → canonical command list
   │
   ├── command_parser.py
   │     Canonical command → robot REST endpoint
   │
   ├── safety_checker.py
   │     Risk classification and execution policy
   │
   ├── robot_client.py
   │     Command dispatch and completion polling
   │
   ├── network_monitor.py
   │     Rolling latency/loss monitoring
   │
   ├── mission_compiler.py
   │     Plan B autonomous task-flow generation
   │
   └── tts.py
         ElevenLabs speech generation and cache
```

## Supported Commands

### Read-only

```text
status
battery
where are you
list markers
current map
```

### Navigation

```text
go to <marker>
patrol <marker 1>, <marker 2>
return to charger
```

### Safety

```text
stop
emergency stop
disable emergency stop
```

### Direct control

These require manual confirmation:

```text
move forward
move backward
turn left
turn right
lift cabin
drop cabin
```

### Blocked critical operations

```text
shutdown
reboot
change wifi
delete markers
update software
```

## Project Structure

```text
natural-language-robot-agent/
├── app/
│   ├── main.py
│   ├── ai_parser.py
│   ├── command_parser.py
│   ├── safety_checker.py
│   ├── robot_client.py
│   ├── mission_compiler.py
│   ├── network_monitor.py
│   ├── tts.py
│   └── models.py
├── index.html
├── requirements.txt
├── README.md
└── .gitignore
```

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows:

```bash
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
ROBOT_CHASSIS_HOST=http://ROBOT_IP:9001
ROBOT_TOOLS_HOST=http://ROBOT_IP:19001
ROBOT_TIMEOUT_SECONDS=10

CHASSIS_SN=your_chassis_serial
CABIN_SN=your_cabin_serial
CABIN_ID=your_cabin_id
TOOLS_HOST=http://ROBOT_IP:19001
STORE_ID=your_store_id
CLIENT_TOKEN=your_client_token

ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL=eleven_flash_v2_5
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
ELEVENLABS_TIMEOUT_SECONDS=15
ELEVENLABS_MAX_CHARS=500
ELEVENLABS_TTS_CACHE=true
```

ElevenLabs is optional.

### 4. Start the local language model

By default, the parser expects an OpenAI-compatible local server at:

```text
http://127.0.0.1:8080/v1/chat/completions
```

with:

```text
mlx-community/Qwen3.6-35B-A3B-6bit
```

If that server cannot be reached, the app attempts to load:

```text
mlx-community/Qwen2.5-0.5B-Instruct-4bit
```

through `mlx-lm`.

### 5. Run the API

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Serve the browser interface |
| `GET` | `/health` | App mode and AI status |
| `POST` | `/command` | Parse and execute one or more commands |
| `POST` | `/command/sequence` | Stream step-by-step sequence execution |
| `GET` | `/history` | Return the latest command records |
| `POST` | `/mode` | Switch between dry-run and real-robot mode |
| `GET` | `/mode` | Read the active mode |
| `GET` | `/robot/ping` | Check robot connectivity and basic status |
| `GET` | `/markers` | Retrieve robot navigation markers |
| `GET` | `/network/status` | Read latency, packet loss, and Plan A/B recommendation |
| `POST` | `/network/threshold` | Change the Plan B test threshold |
| `GET` | `/network/threshold` | Read the active threshold |
| `GET` | `/tts/config` | Read ElevenLabs configuration status |
| `POST` | `/tts/speak` | Generate spoken feedback |
| `POST` | `/mission/preview` | Compile a Plan B mission without sending it |
| `POST` | `/mission/send` | Compile and dispatch canonical commands |
| `POST` | `/mission/send_text` | Parse natural language and dispatch a Plan B mission |

## Example Requests

### Dry-run a command

```bash
curl -X POST http://127.0.0.1:8000/command \
  -H "Content-Type: application/json" \
  -d '{
    "command": "go to the front desk",
    "allowed_locations": ["front_desk", "waiting1"]
  }'
```

### Preview a Plan B mission

```bash
curl -X POST http://127.0.0.1:8000/mission/preview \
  -H "Content-Type: application/json" \
  -d '{
    "commands": [
      "go to waiting1",
      "go to front_desk",
      "return to charger"
    ]
  }'
```

### Change the network threshold for testing

```bash
curl -X POST http://127.0.0.1:8000/network/threshold \
  -H "Content-Type: application/json" \
  -d '{"good_threshold_ms": 1}'
```

The threshold resets when the server restarts.

## Important Notes

- This project is designed for a single operator. The sequence-abort flag is process-wide rather than session-specific.
- Command history and TTS audio are stored only in memory.
- Critical-command “alerts” are currently logged by the backend; no email transport is connected.
- Plan B intentionally supports only actions that can be represented safely in the robot’s autonomous task-flow format.
- The interface uses browser speech recognition, so voice-input support depends on the browser.
- Keep the app in dry-run mode when the physical robot is not in a controlled test environment.

## Before Publishing the Repository

Do not commit real robot credentials, serial numbers, internal IP addresses, store IDs, client tokens, or API keys.

Use environment variables and provide only placeholders in public files. Rotate any credential that has previously been committed.

## Tech Stack

- Python
- FastAPI
- Pydantic
- Local Qwen language models
- MLX / `mlx-lm`
- Vanilla HTML, CSS, and JavaScript
- Server-Sent Events
- REST APIs
- ElevenLabs TTS
- Browser Speech Recognition