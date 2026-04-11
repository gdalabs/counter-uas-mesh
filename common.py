"""Shared utilities for Counter-UAS Mesh nodes."""

import json
import math
import time
import uuid

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883

# Topics
TOPIC_HEARTBEAT = "mesh/heartbeat"        # {node_id, type, pos, status, ts}
TOPIC_DETECT = "mesh/threat/detect"       # {sensor_id, threat_id, bearing, rssi, ts}
TOPIC_CONFIRM = "mesh/threat/confirm"     # {threat_id, pos, confidence, confirmers}
TOPIC_BID = "mesh/intercept/bid"          # {interceptor_id, threat_id, distance, fuel, ts}
TOPIC_ASSIGN = "mesh/intercept/assign"    # {threat_id, interceptor_id, target_pos}
TOPIC_STATUS = "mesh/intercept/status"    # {interceptor_id, threat_id, status, ts}
TOPIC_ALERT = "mesh/alert"               # {type, message, ts}


def now_ms() -> int:
    return int(time.time() * 1000)


def make_id() -> str:
    return uuid.uuid4().hex[:8]


def distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def bearing_from(src: tuple[float, float], tgt: tuple[float, float]) -> float:
    """Bearing in degrees from src to tgt (0=north, 90=east)."""
    dx = tgt[0] - src[0]
    dy = tgt[1] - src[1]
    angle = math.degrees(math.atan2(dx, dy)) % 360
    return round(angle, 1)


def triangulate(
    detections: list[dict],
) -> tuple[float, float] | None:
    """
    Simple triangulation from 2+ bearing/position pairs.
    Uses least-squares intersection of bearing lines.
    """
    if len(detections) < 2:
        return None

    # Convert bearings to unit vectors
    lines = []
    for d in detections:
        px, py = d["pos"]
        b = math.radians(d["bearing"])
        dx = math.sin(b)
        dy = math.cos(b)
        lines.append((px, py, dx, dy))

    # Least-squares intersection
    ax, ay, bx, by = 0.0, 0.0, 0.0, 0.0
    for px, py, dx, dy in lines:
        # Normal to bearing line: (-dy, dx)
        nx, ny = -dy, dx
        dot = nx * px + ny * py
        ax += nx * nx
        ay += nx * ny
        bx += ny * nx
        by += ny * ny
        # Accumulate RHS

    # Simplified: use first two lines intersection
    p1x, p1y, d1x, d1y = lines[0]
    p2x, p2y, d2x, d2y = lines[1]

    det = d1x * d2y - d1y * d2x
    if abs(det) < 1e-6:
        return None  # Parallel lines

    t = ((p2x - p1x) * d2y - (p2y - p1y) * d2x) / det

    ix = p1x + t * d1x
    iy = p1y + t * d1y

    return (round(ix, 1), round(iy, 1))


def pub(client, topic: str, payload: dict, qos: int = 1):
    """Publish JSON message."""
    client.publish(topic, json.dumps(payload), qos=qos)
