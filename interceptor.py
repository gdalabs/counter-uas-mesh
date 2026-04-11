"""
Interceptor Node — Bids on threats, pursues and intercepts.
Handles multiple interceptors competing, failover on loss.
"""

import argparse
import json
import threading
import time

import paho.mqtt.client as mqtt

from common import (
    BROKER_HOST, BROKER_PORT,
    TOPIC_HEARTBEAT, TOPIC_CONFIRM, TOPIC_BID, TOPIC_ASSIGN, TOPIC_STATUS, TOPIC_ALERT,
    now_ms, distance, pub,
)

# State
peers: dict[str, dict] = {}
current_target: dict | None = None
fuel: float = 100.0
status: str = "idle"
pos_current: list[float] = [0.0, 0.0]

# Bidding
bid_submitted: set[str] = set()  # threats we already bid on
assigned_threats: set[str] = set()  # threats already assigned to someone
confirmed_threat_positions: dict[str, tuple] = {}  # threat_id -> (x, y)

STALE_MS = 10_000
SPEED = 5.0
INTERCEPT_RANGE = 5.0
FAILOVER_CHECK_MS = 8_000  # If assigned interceptor goes offline, reassign after this


def on_connect(client, userdata, flags, rc, props=None):
    print(f"[{userdata['id']}] Connected to FoxMQ (rc={rc})")
    client.subscribe("mesh/#")


def on_message(client, userdata, msg):
    global current_target, status

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
                "target": data.get("target"),
                "fuel": data.get("fuel", 0),
            }
            if was_offline:
                print(f"[{node_id}] 🟢 Peer {peer_id} back online")

    elif msg.topic == TOPIC_CONFIRM:
        threat_id = data.get("threat_id")
        threat_pos = tuple(data.get("pos", [0, 0]))

        if not threat_id:
            return

        # Always store position for re-bidding later
        confirmed_threat_positions[threat_id] = threat_pos

        if threat_id in bid_submitted:
            return  # Already bid
        if threat_id in assigned_threats:
            return  # Already assigned to someone
        if current_target is not None:
            # Busy — will re-bid when idle
            return

        bid_submitted.add(threat_id)
        dist = distance(tuple(pos_current), threat_pos)
        print(f"[{node_id}] 📡 Threat {threat_id} at {threat_pos} — dist {dist:.0f}, bidding")

        pub(client, TOPIC_BID, {
            "interceptor_id": node_id,
            "threat_id": threat_id,
            "distance": round(dist, 1),
            "fuel": round(fuel, 1),
            "threat_pos": list(threat_pos),
            "ts": now_ms(),
        }, qos=2)

    elif msg.topic == TOPIC_BID:
        # Deterministic auction: all nodes see bids in same order (Vertex guarantee)
        threat_id = data.get("threat_id")
        if not threat_id or threat_id in assigned_threats:
            return

        # Collect bid, wait briefly, then resolve
        if not hasattr(on_message, '_bid_cache'):
            on_message._bid_cache = {}
        if threat_id not in on_message._bid_cache:
            on_message._bid_cache[threat_id] = {"bids": [], "first": now_ms()}
        on_message._bid_cache[threat_id]["bids"].append(data)

        # Resolve after collecting — check number of known interceptors
        cache = on_message._bid_cache[threat_id]
        known_interceptors = sum(
            1 for p in peers.values()
            if p["type"] == "interceptor" and p["status"] != "offline"
        ) + 1  # include self
        elapsed = now_ms() - cache["first"]

        # Resolve when all interceptors have bid OR timeout
        if len(cache["bids"]) >= known_interceptors or elapsed > 2000:
            resolve_auction(client, node_id, threat_id, cache["bids"])
            del on_message._bid_cache[threat_id]

    elif msg.topic == TOPIC_ASSIGN:
        threat_id = data.get("threat_id")
        assigned_threats.add(threat_id)

        if data.get("interceptor_id") == node_id and current_target is None:
            target_pos = tuple(data.get("target_pos", [0, 0]))
            current_target = {"threat_id": threat_id, "pos": target_pos}
            status = "pursuing"
            print(f"[{node_id}] 🎯 ASSIGNED → intercept {threat_id} at {target_pos}")

    elif msg.topic == TOPIC_STATUS:
        if data.get("status") == "intercepted":
            threat_id = data.get("threat_id")
            assigned_threats.add(threat_id)
            if current_target and current_target["threat_id"] == threat_id:
                current_target = None
                status = "idle"

    elif msg.topic == TOPIC_ALERT:
        if data.get("type") == "interceptor_lost":
            # Another interceptor went down — check if we should take over
            lost_id = data.get("node_id")
            threat_id = data.get("active_threat")
            threat_pos = data.get("threat_pos")
            if threat_id and threat_pos and current_target is None:
                # Re-bid for the orphaned threat
                assigned_threats.discard(threat_id)
                bid_submitted.discard(threat_id)
                dist = distance(tuple(pos_current), tuple(threat_pos))
                print(f"[{node_id}] 🔄 FAILOVER — re-bidding for {threat_id} (lost {lost_id})")
                pub(client, TOPIC_BID, {
                    "interceptor_id": node_id,
                    "threat_id": threat_id,
                    "distance": round(dist, 1),
                    "fuel": round(fuel, 1),
                    "threat_pos": threat_pos,
                    "ts": now_ms(),
                }, qos=2)


def resolve_auction(client, node_id, threat_id, bids):
    if threat_id in assigned_threats:
        return

    # Deterministic: sort by distance, break ties by node_id
    bids.sort(key=lambda b: (b["distance"], b["interceptor_id"]))

    # Find first available (not busy) interceptor
    # Check which interceptors are currently pursuing something
    busy_interceptors = set()
    for p_id, p in peers.items():
        if p.get("type") == "interceptor" and p.get("target"):
            busy_interceptors.add(p_id)
    if current_target is not None:
        busy_interceptors.add(node_id)

    winner = None
    for bid in bids:
        if bid["interceptor_id"] not in busy_interceptors:
            winner = bid
            break

    # Fallback: if all busy, pick closest anyway
    if not winner:
        winner = bids[0]

    if winner["interceptor_id"] == node_id:
        print(f"[{node_id}] 🏆 Won auction for {threat_id}")
        target_pos = winner.get("threat_pos", [50, 50])
        pub(client, TOPIC_ASSIGN, {
            "threat_id": threat_id,
            "interceptor_id": node_id,
            "target_pos": target_pos,
            "ts": now_ms(),
        }, qos=2)


def heartbeat_loop(client, node_id):
    while True:
        pub(client, TOPIC_HEARTBEAT, {
            "node_id": node_id,
            "type": "interceptor",
            "pos": list(pos_current),
            "status": status,
            "fuel": round(fuel, 1),
            "target": current_target["threat_id"] if current_target else None,
            "ts": now_ms(),
        })

        # Check for offline peers — trigger failover if interceptor lost
        now = now_ms()
        for pid in list(peers):
            p = peers[pid]
            if now - p["last_seen"] > STALE_MS:
                if p["status"] != "offline":
                    print(f"[{node_id}] ⚡ Peer {pid} went OFFLINE")
                    p["status"] = "offline"

                    # If lost peer was an interceptor with an active target, alert
                    if p["type"] == "interceptor" and p.get("target"):
                        print(f"[{node_id}] 🚨 Interceptor {pid} lost while pursuing {p['target']}!")
                        pub(client, TOPIC_ALERT, {
                            "type": "interceptor_lost",
                            "node_id": pid,
                            "active_threat": p["target"],
                            "threat_pos": list(p.get("pos", [50, 50])),
                            "ts": now_ms(),
                        }, qos=2)

        time.sleep(2)


def pursuit_loop(client, node_id):
    global current_target, status, fuel

    while True:
        if current_target and status == "pursuing":
            tgt = current_target["pos"]
            dist = distance(tuple(pos_current), tgt)

            if dist < INTERCEPT_RANGE:
                status = "intercepting"
                print(f"[{node_id}] 💥 INTERCEPTED {current_target['threat_id']}!")
                pub(client, TOPIC_STATUS, {
                    "interceptor_id": node_id,
                    "threat_id": current_target["threat_id"],
                    "status": "intercepted",
                    "pos": list(pos_current),
                    "ts": now_ms(),
                }, qos=2)
                time.sleep(1)
                current_target = None
                status = "idle"
                print(f"[{node_id}] ✅ Idle — ready for next threat")

                # Check for unassigned threats and re-bid
                for tid, tpos in confirmed_threat_positions.items():
                    if tid not in assigned_threats and tid not in bid_submitted:
                        dist = distance(tuple(pos_current), tpos)
                        print(f"[{node_id}] 🔄 Re-bidding for unassigned {tid}")
                        bid_submitted.add(tid)
                        pub(client, TOPIC_BID, {
                            "interceptor_id": node_id,
                            "threat_id": tid,
                            "distance": round(dist, 1),
                            "fuel": round(fuel, 1),
                            "threat_pos": list(tpos),
                            "ts": now_ms(),
                        }, qos=2)
            else:
                dx = tgt[0] - pos_current[0]
                dy = tgt[1] - pos_current[1]
                mag = (dx**2 + dy**2) ** 0.5
                pos_current[0] = round(pos_current[0] + dx / mag * SPEED, 1)
                pos_current[1] = round(pos_current[1] + dy / mag * SPEED, 1)
                fuel = max(0, fuel - 0.5)

        time.sleep(1)


def main():
    global pos_current

    parser = argparse.ArgumentParser(description="Interceptor Node")
    parser.add_argument("--id", required=True)
    parser.add_argument("--pos", required=True, help="x,y")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    args = parser.parse_args()

    pos = tuple(float(x) for x in args.pos.split(","))
    pos_current[:] = list(pos)
    userdata = {"id": args.id, "pos": pos}

    client = mqtt.Client(
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        userdata=userdata,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port)

    threading.Thread(target=heartbeat_loop, args=(client, args.id), daemon=True).start()
    threading.Thread(target=pursuit_loop, args=(client, args.id), daemon=True).start()

    print(f"[{args.id}] Interceptor started at ({pos[0]}, {pos[1]})")
    client.loop_forever()


if __name__ == "__main__":
    main()
