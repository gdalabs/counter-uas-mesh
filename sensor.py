"""
Sensor Node — Detects hostile UAVs, reports bearing + RSSI.
Participates in triangulation consensus.
Handles peer loss gracefully.
"""

import argparse
import json
import random
import threading
import time

import paho.mqtt.client as mqtt

from common import (
    BROKER_HOST, BROKER_PORT,
    TOPIC_HEARTBEAT, TOPIC_DETECT, TOPIC_CONFIRM,
    now_ms, bearing_from, distance, triangulate, pub,
)

# State
peers: dict[str, dict] = {}
pending_threats: dict[str, list[dict]] = {}
confirmed_threats: set[str] = set()

STALE_MS = 10_000
CONFIRM_THRESHOLD = 2


def on_connect(client, userdata, flags, rc, props=None):
    print(f"[{userdata['id']}] Connected to FoxMQ (rc={rc})")
    client.subscribe("mesh/#")
    client.subscribe("sim/threats")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except json.JSONDecodeError:
        return

    node_id = userdata["id"]

    if msg.topic == TOPIC_HEARTBEAT:
        peer_id = data.get("node_id")
        if peer_id and peer_id != node_id:
            was_offline = peers.get(peer_id, {}).get("status") == "offline"
            peers[peer_id] = {
                "type": data.get("type"),
                "pos": tuple(data.get("pos", [0, 0])),
                "last_seen": now_ms(),
                "status": data.get("status", "active"),
            }
            if was_offline:
                print(f"[{node_id}] 🟢 Peer {peer_id} back online")

    elif msg.topic == TOPIC_DETECT:
        sensor_id = data.get("sensor_id")
        threat_id = data.get("threat_id")
        if sensor_id == node_id or not threat_id:
            return
        if threat_id in confirmed_threats:
            return

        if threat_id not in pending_threats:
            pending_threats[threat_id] = []

        # Dedup by sensor
        existing_sensors = {d["sensor_id"] for d in pending_threats[threat_id]}
        if sensor_id in existing_sensors:
            # Update latest detection
            pending_threats[threat_id] = [
                d for d in pending_threats[threat_id] if d["sensor_id"] != sensor_id
            ]

        pending_threats[threat_id].append({
            "sensor_id": sensor_id,
            "pos": tuple(data.get("sensor_pos", [0, 0])),
            "bearing": data.get("bearing", 0),
            "rssi": data.get("rssi", 0),
            "ts": data.get("ts", now_ms()),
        })

        # Try triangulation
        all_detections = pending_threats[threat_id]
        unique_sensors = set(d["sensor_id"] for d in all_detections)

        if len(unique_sensors) >= CONFIRM_THRESHOLD:
            pos = triangulate(all_detections)
            if pos:
                confirmed_threats.add(threat_id)
                print(f"[{node_id}] ⚠️  THREAT CONFIRMED: {threat_id} at ({pos[0]}, {pos[1]})")
                pub(client, TOPIC_CONFIRM, {
                    "threat_id": threat_id,
                    "pos": list(pos),
                    "confidence": min(len(unique_sensors) / 3.0, 1.0),
                    "confirmers": list(unique_sensors),
                    "ts": now_ms(),
                })


def heartbeat_loop(client, node_id, pos):
    while True:
        active_sensors = sum(
            1 for p in peers.values()
            if p["type"] == "sensor" and p["status"] != "offline"
        )
        pub(client, TOPIC_HEARTBEAT, {
            "node_id": node_id,
            "type": "sensor",
            "pos": list(pos),
            "status": "active",
            "active_sensors": active_sensors + 1,  # include self
            "ts": now_ms(),
        })

        now = now_ms()
        for pid in list(peers):
            if now - peers[pid]["last_seen"] > STALE_MS:
                if peers[pid]["status"] != "offline":
                    print(f"[{node_id}] ⚡ Peer {pid} went OFFLINE")
                    peers[pid]["status"] = "offline"

        time.sleep(2)


def scan_loop(client, node_id, pos, threat_positions):
    SCAN_RANGE = 150.0
    SCAN_INTERVAL = 3.0

    while True:
        for tid, tpos in list(threat_positions.items()):
            dist = distance(pos, tpos)
            if dist < SCAN_RANGE:
                bearing = bearing_from(pos, tpos)
                rssi = max(0, 100 - int(dist * 0.7))
                noise = random.uniform(-3, 3)

                print(f"[{node_id}] 🔍 Detected {tid} — bearing {bearing + noise:.1f}°, RSSI {rssi}")

                pub(client, TOPIC_DETECT, {
                    "sensor_id": node_id,
                    "threat_id": tid,
                    "sensor_pos": list(pos),
                    "bearing": round(bearing + noise, 1),
                    "rssi": rssi,
                    "ts": now_ms(),
                }, qos=2)

        time.sleep(SCAN_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="Sensor Node")
    parser.add_argument("--id", required=True)
    parser.add_argument("--pos", required=True, help="x,y")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    args = parser.parse_args()

    pos = tuple(float(x) for x in args.pos.split(","))
    userdata = {"id": args.id, "pos": pos}
    threat_positions: dict[str, tuple[float, float]] = {}

    client = mqtt.Client(
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        userdata=userdata,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    def on_threat(client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            if "threat_id" in data and "pos" in data:
                threat_positions[data["threat_id"]] = tuple(data["pos"])
        except json.JSONDecodeError:
            pass

    client.message_callback_add("sim/threats", on_threat)
    client.connect(args.host, args.port)

    threading.Thread(target=heartbeat_loop, args=(client, args.id, pos), daemon=True).start()
    threading.Thread(target=scan_loop, args=(client, args.id, pos, threat_positions), daemon=True).start()

    print(f"[{args.id}] Sensor node started at ({pos[0]}, {pos[1]})")
    client.loop_forever()


if __name__ == "__main__":
    main()
