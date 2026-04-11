"""
Observer Node — Web dashboard for real-time 2D map visualization.
Connects to FoxMQ and serves a WebSocket-powered HTML dashboard.
"""

import argparse
import json
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
import asyncio
import socket

import paho.mqtt.client as mqtt

from common import BROKER_HOST, BROKER_PORT, now_ms

# Global state
state = {
    "nodes": {},      # node_id -> {type, pos, status, fuel, target, ts}
    "threats": {},    # threat_id -> {pos, status, ts}
    "events": [],     # last 50 events [{type, message, ts}]
    "stats": {
        "threats_detected": 0,
        "threats_intercepted": 0,
        "active_sensors": 0,
        "active_interceptors": 0,
    },
}

MAX_EVENTS = 50


def add_event(event_type: str, message: str):
    state["events"].append({
        "type": event_type,
        "message": message,
        "ts": now_ms(),
    })
    if len(state["events"]) > MAX_EVENTS:
        state["events"] = state["events"][-MAX_EVENTS:]


def on_connect(client, userdata, flags, rc, props=None):
    print("[Observer] Connected to FoxMQ")
    client.subscribe("mesh/#")
    client.subscribe("sim/threats")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except json.JSONDecodeError:
        return

    if msg.topic == "mesh/heartbeat":
        nid = data.get("node_id")
        if nid:
            state["nodes"][nid] = {
                "type": data.get("type"),
                "pos": data.get("pos", [0, 0]),
                "status": data.get("status", "active"),
                "fuel": data.get("fuel"),
                "target": data.get("target"),
                "ts": now_ms(),
            }
            # Update stats
            state["stats"]["active_sensors"] = sum(
                1 for n in state["nodes"].values()
                if n["type"] == "sensor" and n["status"] != "offline"
            )
            state["stats"]["active_interceptors"] = sum(
                1 for n in state["nodes"].values()
                if n["type"] == "interceptor" and n["status"] != "offline"
            )

    elif msg.topic == "mesh/threat/confirm":
        tid = data.get("threat_id")
        if tid:
            state["threats"][tid] = {
                "pos": data.get("pos", [0, 0]),
                "status": "confirmed",
                "ts": now_ms(),
            }
            state["stats"]["threats_detected"] += 1
            add_event("threat", f"⚠️ Threat {tid} confirmed at ({data['pos'][0]}, {data['pos'][1]})")

    elif msg.topic == "mesh/intercept/assign":
        tid = data.get("threat_id")
        iid = data.get("interceptor_id")
        if tid and iid:
            if tid in state["threats"]:
                state["threats"][tid]["status"] = "assigned"
            add_event("assign", f"🎯 {iid} assigned to {tid}")

    elif msg.topic == "mesh/intercept/status":
        if data.get("status") == "intercepted":
            tid = data.get("threat_id")
            iid = data.get("interceptor_id")
            if tid:
                if tid in state["threats"]:
                    state["threats"][tid]["status"] = "intercepted"
                state["stats"]["threats_intercepted"] += 1
                add_event("intercept", f"💥 {iid} intercepted {tid}")

    elif msg.topic == "mesh/alert":
        if data.get("type") == "interceptor_lost":
            add_event("alert", f"🚨 Interceptor {data.get('node_id')} LOST — failover initiated")

    elif msg.topic == "sim/threats":
        tid = data.get("threat_id")
        if tid:
            existing = state["threats"].get(tid, {})
            state["threats"][tid] = {
                "pos": data.get("pos", [0, 0]),
                "status": existing.get("status", "active"),
                "ts": now_ms(),
            }


def state_json() -> str:
    return json.dumps(state)


# Simple HTTP server that serves dashboard + state API
class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(state_json().encode())
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Counter-UAS Mesh — Live Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #0a0a0f; color: #e8e8f0; font-family: system-ui, sans-serif; }
.header { padding: 12px 20px; background: #12121a; border-bottom: 1px solid #2a2a3a; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 16px; font-weight: 700; }
.header h1 span { color: #ef4444; }
.stats { display: flex; gap: 16px; font-size: 12px; color: #888; }
.stat-val { color: #e8e8f0; font-weight: 700; }
.main { display: flex; height: calc(100vh - 48px); }
.map-container { flex: 1; position: relative; }
canvas { width: 100%; height: 100%; }
.sidebar { width: 280px; background: #12121a; border-left: 1px solid #2a2a3a; overflow-y: auto; padding: 12px; }
.sidebar h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #666; margin: 12px 0 6px; }
.node-item { font-size: 12px; padding: 6px 8px; border-radius: 6px; margin-bottom: 4px; background: #1a1a25; }
.node-item .name { font-weight: 600; }
.node-item .meta { color: #888; font-size: 11px; }
.event-item { font-size: 11px; padding: 4px 0; border-bottom: 1px solid #1a1a25; color: #aaa; }
.online { color: #10b981; }
.offline { color: #ef4444; }
.pursuing { color: #f59e0b; }
@media (max-width: 768px) { .sidebar { display: none; } }
</style>
</head>
<body>
<div class="header">
  <h1>Counter-<span>UAS</span> Mesh</h1>
  <div class="stats" id="stats"></div>
</div>
<div class="main">
  <div class="map-container">
    <canvas id="map"></canvas>
  </div>
  <div class="sidebar">
    <h3>Nodes</h3>
    <div id="nodes"></div>
    <h3>Events</h3>
    <div id="events"></div>
  </div>
</div>
<script>
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const SCALE = 4;
const OFFSET = 40;

function resize() {
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;
}
resize();
window.addEventListener('resize', resize);

function toScreen(x, y) {
  return [x * SCALE + OFFSET, canvas.height - (y * SCALE + OFFSET)];
}

function draw(state) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Grid
  ctx.strokeStyle = '#1a1a25';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 200; i += 20) {
    const [sx, sy] = toScreen(i, 0);
    const [ex, ey] = toScreen(i, 200);
    ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
    const [sx2, sy2] = toScreen(0, i);
    const [ex2, ey2] = toScreen(200, i);
    ctx.beginPath(); ctx.moveTo(sx2, sy2); ctx.lineTo(ex2, ey2); ctx.stroke();
  }

  // Sensor ranges
  for (const [id, n] of Object.entries(state.nodes)) {
    if (n.type !== 'sensor' || n.status === 'offline') continue;
    const [x, y] = toScreen(n.pos[0], n.pos[1]);
    ctx.beginPath();
    ctx.arc(x, y, 150 * SCALE, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(16, 185, 129, 0.03)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(16, 185, 129, 0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Threats
  for (const [id, t] of Object.entries(state.threats)) {
    const [x, y] = toScreen(t.pos[0], t.pos[1]);
    if (t.status === 'intercepted') {
      ctx.fillStyle = '#444';
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#666'; ctx.font = '10px monospace';
      ctx.fillText('✕', x - 4, y + 3);
    } else {
      // Pulsing red
      const pulse = 1 + 0.3 * Math.sin(Date.now() / 200);
      ctx.fillStyle = t.status === 'confirmed' ? '#ef4444' : '#ff6b6b';
      ctx.beginPath(); ctx.arc(x, y, 7 * pulse, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = '9px monospace';
      ctx.fillText(id.slice(-4), x + 10, y + 3);
    }
  }

  // Nodes
  for (const [id, n] of Object.entries(state.nodes)) {
    const [x, y] = toScreen(n.pos[0], n.pos[1]);

    if (n.type === 'sensor') {
      ctx.fillStyle = n.status === 'offline' ? '#333' : '#10b981';
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#000'; ctx.font = 'bold 9px monospace';
      ctx.fillText('S', x - 3, y + 3);
    } else if (n.type === 'interceptor') {
      ctx.fillStyle = n.status === 'offline' ? '#333' :
                      n.status === 'pursuing' ? '#f59e0b' :
                      n.status === 'intercepting' ? '#ef4444' : '#6366f1';
      // Diamond shape
      ctx.beginPath();
      ctx.moveTo(x, y - 10); ctx.lineTo(x + 8, y);
      ctx.lineTo(x, y + 10); ctx.lineTo(x - 8, y);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 8px monospace';
      ctx.fillText('I', x - 3, y + 3);

      // Line to target
      if (n.target && state.threats[n.target]) {
        const tp = state.threats[n.target].pos;
        const [tx, ty] = toScreen(tp[0], tp[1]);
        ctx.strokeStyle = 'rgba(245, 158, 11, 0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(tx, ty); ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Label
    ctx.fillStyle = '#888'; ctx.font = '10px monospace';
    ctx.fillText(id, x + 12, y - 8);
  }
}

function updateSidebar(state) {
  // Stats
  const s = state.stats;
  document.getElementById('stats').innerHTML =
    `<span>Sensors: <span class="stat-val">${s.active_sensors}</span></span>` +
    `<span>Interceptors: <span class="stat-val">${s.active_interceptors}</span></span>` +
    `<span>Detected: <span class="stat-val">${s.threats_detected}</span></span>` +
    `<span>Intercepted: <span class="stat-val">${s.threats_intercepted}</span></span>`;

  // Nodes
  const nodesDiv = document.getElementById('nodes');
  nodesDiv.innerHTML = Object.entries(state.nodes).map(([id, n]) => {
    const cls = n.status === 'offline' ? 'offline' : n.status === 'pursuing' ? 'pursuing' : 'online';
    return `<div class="node-item"><span class="name ${cls}">${id}</span> (${n.type})<div class="meta">${n.status}${n.fuel != null ? ' · fuel: ' + n.fuel + '%' : ''}${n.target ? ' · → ' + n.target : ''}</div></div>`;
  }).join('');

  // Events
  const eventsDiv = document.getElementById('events');
  eventsDiv.innerHTML = state.events.slice(-20).reverse().map(e =>
    `<div class="event-item">${e.message}</div>`
  ).join('');
}

// Poll state
async function poll() {
  try {
    const res = await fetch('/api/state');
    const data = await res.json();
    draw(data);
    updateSidebar(data);
  } catch {}
  requestAnimationFrame(poll);
}

// Start with slower poll interval
setInterval(async () => {
  try {
    const res = await fetch('/api/state');
    const data = await res.json();
    draw(data);
    updateSidebar(data);
  } catch {}
}, 500);
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Observer Dashboard")
    parser.add_argument("--mqtt-host", default=BROKER_HOST)
    parser.add_argument("--mqtt-port", type=int, default=BROKER_PORT)
    parser.add_argument("--http-port", type=int, default=8090)
    args = parser.parse_args()

    # MQTT client
    client = mqtt.Client(
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.mqtt_host, args.mqtt_port)
    threading.Thread(target=client.loop_forever, daemon=True).start()

    # HTTP server
    server = HTTPServer(("0.0.0.0", args.http_port), DashboardHandler)
    print(f"[Observer] Dashboard at http://localhost:{args.http_port}")
    print(f"[Observer] Connected to FoxMQ at {args.mqtt_host}:{args.mqtt_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
