"""
network_monitor.py
Monitors round-trip latency to the robot and classifies network quality.
Runs in a background thread — import and call start() once at startup.
"""
import time
import threading
import subprocess
import json
from collections import deque
import os

# ── Config ────────────────────────────────────────────────────────────────────
ROBOT_HOST        = "10.1.17.225"
ROBOT_PORT        = 9001
PING_INTERVAL     = 3       # seconds between pings
WINDOW_SIZE       = 10      # rolling window of samples
GOOD_THRESHOLD    = 300     # ms — below this = GOOD
DEGRADED_LOSS     = 0.3     # 30% packet loss → DEGRADED

# ── State ─────────────────────────────────────────────────────────────────────
_lock    = threading.Lock()
_samples = deque(maxlen=WINDOW_SIZE)   # each sample: {"latency": ms|None, "ts": float}
_running = False


def _ping_once() -> float | None:
    """Returns round-trip latency in ms, or None on failure."""
    try:
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{time_total}",
               "--max-time", "2",
               f"http://{ROBOT_HOST}:{ROBOT_PORT}/api/robot_status"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip()) * 1000  # convert to ms
        return None
    except Exception:
        return None


def _monitor_loop():
    global _running
    while _running:
        latency = _ping_once()
        with _lock:
            _samples.append({"latency": latency, "ts": time.time()})
        time.sleep(PING_INTERVAL)


def start():
    """Start the background monitoring thread."""
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    print("[network_monitor] started")


def stop():
    global _running
    _running = False


def get_stats() -> dict:
    """
    Returns current network stats:
    {
        quality: "GOOD" | "DEGRADED" | "UNKNOWN",
        avg_latency_ms: float | None,
        packet_loss: float,   # 0.0 - 1.0
        samples: int,
        recommendation: "plan_a" | "plan_b"
    }
    """
    with _lock:
        samples = list(_samples)

    if not samples:
        return {
            "quality": "UNKNOWN",
            "avg_latency_ms": None,
            "packet_loss": 0.0,
            "samples": 0,
            "recommendation": "plan_a",
        }

    total    = len(samples)
    failures = sum(1 for s in samples if s["latency"] is None)
    loss     = failures / total
    good     = [s["latency"] for s in samples if s["latency"] is not None]
    avg_ms   = sum(good) / len(good) if good else None

    if total < 3:
        quality = "UNKNOWN"
        rec     = "plan_a"
    elif loss >= DEGRADED_LOSS or (avg_ms is not None and avg_ms > GOOD_THRESHOLD):
        quality = "DEGRADED"
        rec     = "plan_b"
    else:
        quality = "GOOD"
        rec     = "plan_a"

    return {
        "quality":        quality,
        "avg_latency_ms": round(avg_ms, 1) if avg_ms is not None else None,
        "packet_loss":    round(loss, 2),
        "samples":        total,
        "recommendation": rec,
    }

def set_good_threshold_ms(value: int) -> dict:
    """
    Runtime override for testing Plan B / Plan A.
    Does not edit .env. Resets when server restarts.
    """
    global GOOD_THRESHOLD

    value = int(value)

    if value < 1:
        value = 1

    GOOD_THRESHOLD = value

    return {
        "ok": True,
        "good_threshold_ms": GOOD_THRESHOLD,
    }


def get_good_threshold_ms() -> int:
    return GOOD_THRESHOLD