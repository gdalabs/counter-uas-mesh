"""
Threat Simulator — Generates hostile UAVs with various patterns.
Supports multiple simultaneous threats.
"""

import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

from common import BROKER_HOST, BROKER_PORT, make_id, now_ms


def main():
    parser = argparse.ArgumentParser(description="Threat Simulator")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--pattern", choices=["random", "linear", "swarm", "wave"], default="random")
    parser.add_argument("--interval", type=float, default=8.0, help="Seconds between waves")
    parser.add_argument("--speed", type=float, default=2.0)
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    args = parser.parse_args()

    client = mqtt.Client(
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.connect(args.host, args.port)
    client.loop_start()

    threats: list[dict] = []
    area = 120.0

    def spawn_threat(pattern="random"):
        tid = f"T-{make_id()}"
        if pattern == "linear":
            pos = [-15.0, random.uniform(20, area - 20)]
            vel = [args.speed, random.uniform(-0.5, 0.5)]
        elif pattern == "swarm":
            cx = area / 2 + random.uniform(-15, 15)
            pos = [cx, area + 10]
            vel = [random.uniform(-0.5, 0.5), -args.speed]
        else:  # random — aimed at center
            edge = random.choice(["top", "left", "right"])
            if edge == "top":
                pos = [random.uniform(20, area - 20), area + 10]
                vel = [random.uniform(-1, 1), -args.speed]
            elif edge == "left":
                pos = [-10.0, random.uniform(10, 70)]
                vel = [args.speed, random.uniform(-0.5, 0.5)]
            else:
                pos = [area + 10, random.uniform(10, 70)]
                vel = [-args.speed, random.uniform(-0.5, 0.5)]

        threats.append({"id": tid, "pos": pos, "vel": vel, "active": True})
        print(f"  🛩️  Threat {tid} spawned at ({pos[0]:.0f}, {pos[1]:.0f})")
        return tid

    # Listen for intercept confirmations
    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            if msg.topic == "mesh/intercept/status" and data.get("status") == "intercepted":
                tid = data.get("threat_id")
                for t in threats:
                    if t["id"] == tid:
                        t["active"] = False
                        print(f"  ❌ Threat {tid} neutralized!")
        except json.JSONDecodeError:
            pass

    client.on_message = on_message
    client.subscribe("mesh/intercept/status")

    print(f"Threat simulator — pattern={args.pattern}, initial={args.count}, speed={args.speed}")

    # Spawn initial threats
    for _ in range(args.count):
        spawn_threat(args.pattern)

    # Wave mode: spawn new threats periodically
    last_wave = time.time()
    wave_count = 0
    max_waves = 3 if args.pattern == "wave" else 0

    while True:
        active = [t for t in threats if t["active"]]
        if not active and wave_count >= max_waves:
            print(f"\n✅ All threats neutralized! ({len(threats)} total)")
            break

        # Wave spawning
        if args.pattern == "wave" and wave_count < max_waves:
            if time.time() - last_wave > args.interval:
                wave_count += 1
                n = random.randint(1, 3)
                print(f"\n  🌊 Wave {wave_count} — {n} threats incoming!")
                for _ in range(n):
                    spawn_threat("random")
                last_wave = time.time()

        # Move threats
        for t in [t for t in threats if t["active"]]:
            t["pos"][0] += t["vel"][0]
            t["pos"][1] += t["vel"][1]

            # Out of bounds check (generous bounds to allow intercept time)
            if t["pos"][0] < -150 or t["pos"][0] > 300 or t["pos"][1] < -150 or t["pos"][1] > 300:
                t["active"] = False
                print(f"  📤 Threat {t['id']} left area")
                continue

            client.publish("sim/threats", json.dumps({
                "threat_id": t["id"],
                "pos": [round(t["pos"][0], 1), round(t["pos"][1], 1)],
                "ts": now_ms(),
            }))

        time.sleep(1)

    time.sleep(2)
    client.loop_stop()
    print("Simulator finished.")


if __name__ == "__main__":
    main()
