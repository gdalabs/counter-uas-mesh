# Counter-UAS Mesh

> Decentralized counter-drone defense network — detect, triangulate, and intercept hostile UAVs without a central command server. No internet required.

Built with [Vertex/FoxMQ](https://docs.tashi.network/) for the **Vertex Swarm Challenge 2026** (Track 3: Agent Economy) by [GDA Labs](https://github.com/gdalabs).

---

## Why DAG — The Technical Case for Hashgraph in Defense

### The Problem No One Has Solved

Modern drone defense systems rely on a central command server. When that server is destroyed — which is the *first* thing an adversary targets — the entire defense network goes dark. Every sensor stops reporting, every interceptor loses its mission.

This is not a theoretical risk. Post-2022 Ukraine, the destruction of communication infrastructure is the opening move of every engagement.

### Why Blockchain Doesn't Work Here

| Approach | Consensus Speed | BFT | Internet Required | Cost/tx | Verdict |
|----------|----------------|-----|-------------------|---------|---------|
| Ethereum | 12-15 seconds | ✅ | ✅ | $2-50 | Drone escapes in 15 seconds |
| Solana | ~400ms | ✅ | ✅ | $0.0025 | Still needs internet. Jammed = dead |
| Raft/Paxos | 1-10ms | ❌ | ❌ | Free | One compromised node = consensus failure |
| **Hashgraph DAG** | **26-103ms** | **✅** | **❌** | **Free** | **The only option** |

The critical insight: **Raft is fast but not Byzantine fault-tolerant** (one malicious node breaks consensus). **Blockchain is BFT but too slow and internet-dependent.** Hashgraph DAG is the *only* technology that achieves both speed AND Byzantine fault tolerance AND works without internet.

### How Hashgraph Virtual Voting Works

Traditional BFT protocols (PBFT, HotStuff) require nodes to exchange vote messages — O(n²) messages per round. This creates network overhead that limits speed.

Hashgraph eliminates vote messages entirely through **virtual voting**:

1. Nodes gossip events to each other (who they've talked to, what they've seen)
2. Each node builds a local DAG of all events
3. From the DAG structure, each node can **mathematically calculate** how every other node *would* vote — without actually sending votes
4. Consensus is reached by computation, not communication

```
Traditional BFT:
  Node A → "I vote X" → Node B
  Node B → "I vote X" → Node C
  Node C → "I vote X" → Node A
  (n² messages per round)

Hashgraph:
  Node A gossips to B: "Here's what I've seen"
  Node B gossips to C: "Here's what I've seen"
  Each node computes: "Given what everyone has seen, the consensus is X"
  (No vote messages. Pure computation.)
```

This is why 26ms consensus is possible. The bottleneck is network latency, not protocol overhead.

### Why "No Internet" Is the Killer Feature

In a defense scenario:

```
Cell towers:     Destroyed ❌
Satellite comm:  Jammed ❌
Fiber optic:     Cut ❌
Cloud servers:   Unreachable ❌

Drone-to-drone WiFi/mesh radio:  ✅ Still works
Vertex DAG over local mesh:      ✅ Full BFT consensus in 26ms
```

Solana, Ethereum, and every cloud-based system fails the moment internet connectivity is lost. Vertex nodes only need IP connectivity *to each other* — WiFi Direct, mesh radio, Bluetooth, any transport. The consensus algorithm doesn't care about the internet. It cares about the DAG.

### Why This Matters for Counter-UAS

A drone flying at 100 km/h moves:
- **11 meters** in 400ms (Solana consensus time)
- **0.7 meters** in 26ms (Vertex consensus time)

When your interceptor is computing a firing solution, 11 meters of uncertainty vs 0.7 meters is the difference between a hit and a miss.

### The Untapped Opportunity

The current state of drone swarm coordination research:

| Approach Used | BFT? | Speed | Used By |
|---------------|-------|-------|---------|
| Raft consensus | ❌ | Fast | Academic papers (SwarmRaft, 2025) |
| Ethereum/blockchain | ✅ | Slow | Some research prototypes |
| Centralized C2 | N/A | Fast | Most military systems |
| **Hashgraph DAG** | **✅** | **Fast** | **This project (Counter-UAS Mesh)** |

The Pentagon is [actively soliciting](https://defensescoop.com/2026/03/31/pentagon-preparing-drone-swarm-crucible/) drone swarm systems with "decentralized control" and "no single point of failure." The academic community is attempting this with Raft (not BFT) or blockchain (too slow). **No one is using Hashgraph DAG for defense — the technology that was literally designed for this problem.**

Hashgraph was invented in 2016 but locked behind Swirlds' patents. In 2022, [Hedera purchased the IP and open-sourced it](https://hedera.com/blog/hedera-governing-council-votes-to-purchase-hashgraph-ip-commits-to-open-source-worlds-most-advanced-distributed-ledger-technology/) under Apache 2.0. Tashi built Vertex — the first edge-native implementation. Counter-UAS Mesh is, to our knowledge, the first application of Hashgraph consensus to defense.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│              P2P Mesh (FoxMQ / Vertex DAG)            │
│                                                      │
│  Sensor A ──┐                                        │
│             ├── consensus → Triangulate → Auction ──► Interceptor X
│  Sensor B ──┤                                        │
│             ├── consensus → Track       → Auction ──► Interceptor Y
│  Sensor C ──┘                                        │
│                                                      │
│  No central command. No internet. No single point    │
│  of failure. Byzantine fault tolerant.               │
└──────────────────────────────────────────────────────┘
```

## How It Works

### 1. Detection
Each sensor node continuously scans for hostile UAVs within 150m range. When detected, the sensor publishes bearing (direction) and RSSI (signal strength) to the mesh.

### 2. Triangulation
When 2+ sensors detect the same threat, the DAG-ordered messages enable deterministic triangulation. Every node computes the same position from the same data in the same order — guaranteed by Vertex consensus.

### 3. Deterministic Auction
Available interceptors bid with their distance to the target. Because Vertex delivers messages in identical order to all nodes, every node runs the same auction logic and arrives at the same winner — **without any explicit voting or coordination message**. This is the power of consensus-ordered messaging.

```python
# Every interceptor runs this independently.
# Vertex guarantees they all see bids in the same order.
# Therefore they all compute the same winner. No voting needed.

bids.sort(key=lambda b: (b["distance"], b["interceptor_id"]))
winner = next(b for b in bids if b["interceptor_id"] not in busy)
```

### 4. Pursuit & Intercept
The winning interceptor tracks the target, with position updates shared across the mesh. Other nodes monitor for interceptor failure.

### 5. Failover
If an interceptor goes offline (heartbeat timeout), the mesh detects the loss and triggers re-auction. The next-nearest available interceptor takes over — automatically, within seconds.

## Resilience Scenarios

| Scenario | Response | BFT Required? |
|----------|----------|---------------|
| Sensor destroyed | Remaining sensors continue (degraded accuracy with 2+ nodes) | No |
| Interceptor destroyed mid-pursuit | Heartbeat loss detected → automatic re-auction → next interceptor takes over | Yes — enemy could fake heartbeats |
| Network partition | Each partition operates independently | Yes — partitions must not be tricked |
| Compromised node sends false data | BFT consensus filters out Byzantine behavior (up to ⌊(n-1)/3⌋ malicious nodes) | **This is why Raft fails** |
| Multiple simultaneous threats | Parallel detection + auction. N threats → N interceptors, distance-optimized | No |
| All comms infrastructure destroyed | Nodes fall back to local mesh radio. Vertex works on any IP transport | **This is why Solana fails** |

## Nodes

| Node Type | Role | Count |
|-----------|------|-------|
| **Sensor** | Detect hostile UAVs, report bearing + RSSI | 3+ |
| **Interceptor** | Bid on threats, pursue and neutralize | 2+ |
| **Observer** | Web dashboard for real-time 2D map visualization | 1 |
| **Threat Sim** | Generate hostile UAV scenarios for testing | 1 |

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Coordination | FoxMQ (MQTT 5.0 on Vertex DAG) | BFT consensus-ordered messaging |
| Agents | Python + paho-mqtt | Rapid prototyping, FoxMQ compatible |
| Consensus | Hashgraph (via Tashi Vertex) | 26-103ms BFT, no internet, gasless |
| Visualization | HTML Canvas + polling API | Real-time 2D battle map |
| Transport | UDP (QUIC) | Low-latency, NAT traversal |

## Quick Start

### Prerequisites
- Python 3.10+
- [FoxMQ binary](https://github.com/tashigit/foxmq/releases) (or Docker)

### Setup

```bash
# Download FoxMQ
curl -LO https://github.com/tashigit/foxmq/releases/download/v0.3.1/foxmq_0.3.1_macos-universal.zip
unzip foxmq_0.3.1_macos-universal.zip && chmod +x foxmq

# Generate keys and start broker
./foxmq address-book from-range 127.0.0.1 19793 19793
./foxmq run --secret-key-file=foxmq.d/key_0.pem --allow-anonymous-login &

# Install Python dependency
pip install paho-mqtt
```

### Run the Demo

```bash
# Terminal 1: Observer dashboard
python3 observer.py
# Open http://localhost:8090

# Terminal 2-4: Sensor nodes (triangle formation)
python3 sensor.py --id S1 --pos 0,0
python3 sensor.py --id S2 --pos 100,0
python3 sensor.py --id S3 --pos 50,87

# Terminal 5-6: Interceptor nodes
python3 interceptor.py --id I1 --pos 30,30
python3 interceptor.py --id I2 --pos 70,30

# Terminal 7: Launch threats
python3 threat_sim.py --count 2 --speed 2
```

### What You'll See

```
[S1] 🔍 Detected T-abc123 — bearing 13.3°, RSSI 78
[S2] 🔍 Detected T-abc123 — bearing 339.2°, RSSI 13
[S2] ⚠️  THREAT CONFIRMED: T-abc123 at (54.5, 106.1)
[I1] 📡 Threat T-abc123 at (54.5, 106.1) — dist 82, bidding
[I2] 📡 Threat T-abc123 at (54.5, 106.1) — dist 50, bidding
[I2] 🏆 Won auction for T-abc123
[I2] 🎯 ASSIGNED → intercept T-abc123
[I2] → Moving to (60.1, 45.2), dist=35, fuel=96%
[I2] 💥 INTERCEPTED T-abc123!
✅ All threats neutralized!
```

## Project Structure

```
counter-uas-mesh/
├── common.py          # Shared utilities, triangulation, topics
├── sensor.py          # Sensor node — detection + triangulation
├── interceptor.py     # Interceptor node — auction + pursuit + failover
├── threat_sim.py      # Threat simulator — configurable scenarios
├── observer.py        # Web dashboard — 2D map + event log
├── foxmq              # FoxMQ binary (not in git)
├── foxmq.d/           # FoxMQ config (generated, not in git)
└── README.md
```

## MQTT Topic Schema

| Topic | QoS | Publisher | Purpose |
|-------|-----|----------|---------|
| `mesh/heartbeat` | 1 | All nodes | Liveness + state (pos, status, fuel) |
| `mesh/threat/detect` | 2 | Sensors | Bearing + RSSI per detection |
| `mesh/threat/confirm` | 2 | Sensors | Triangulated position (consensus) |
| `mesh/intercept/bid` | 2 | Interceptors | Distance-based auction bids |
| `mesh/intercept/assign` | 2 | Interceptors | Deterministic winner assignment |
| `mesh/intercept/status` | 2 | Interceptors | Intercept result |
| `mesh/alert` | 2 | All | Failover alerts (node loss) |

## References

- [Tashi Vertex SDK](https://github.com/tashigg/tashi-vertex-rs)
- [FoxMQ — Decentralized MQTT on Vertex](https://github.com/tashigit/foxmq)
- [Hedera Hashgraph IP Open Source Announcement (2022)](https://hedera.com/blog/hedera-governing-council-votes-to-purchase-hashgraph-ip-commits-to-open-source-worlds-most-advanced-distributed-ledger-technology/)
- [Pentagon Drone Swarm Crucible (2026)](https://defensescoop.com/2026/03/31/pentagon-preparing-drone-swarm-crucible/)
- [SwarmRaft: Raft-based drone coordination (2025)](https://arxiv.org/html/2508.00622v1)

## License

MIT — [GDA Labs](https://github.com/gdalabs)
