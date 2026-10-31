"""
AntiDoze Fleet Manager Web Server
==================================
Runs an asynchronous REST & Web interface for the Fleet Manager.
Uses Python standard library http.server (no external web framework dependencies).

Endpoints:
  GET  /                     -> Dynamic Fleet Manager Dashboard (HTML)
  GET  /api/kpis             -> High-level fleet safety metrics
  GET  /api/drivers          -> List of all monitored drivers & current vigilance status
  GET  /api/logs             -> Filtered stream of database telemetry logs (10s updates)
  GET  /api/alerts           -> Urgent safety incidents queue
  POST /api/alerts/ack       -> Acknowledge alert
  POST /api/telemetry        -> Push telemetry update from cab to database
  GET  /api/export-csv       -> Download database records as CSV
"""

import argparse
import csv
import io
import json
import os
import socket
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List
from urllib.parse import parse_qs, urlparse

from fleet_database import get_fleet_db

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML_PATH = os.path.join(PROJECT_DIR, "fleet_manager_dashboard.html")


def get_lan_ip_addresses() -> List[str]:
    """Detects all non-loopback LAN IPv4 addresses on this machine."""
    ips = []
    # 1. Primary outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and not primary.startswith("127."):
            ips.append(primary)
    except Exception:
        pass

    # 2. Hostname resolution
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips


_STANDBY_FRAME_CACHE = None


def get_standby_frame_bytes() -> bytes:
    """Returns a pre-rendered JPEG standby frame when the cab camera is offline."""
    global _STANDBY_FRAME_CACHE
    if _STANDBY_FRAME_CACHE is not None:
        return _STANDBY_FRAME_CACHE

    standby_path = os.path.join(PROJECT_DIR, "sample_1080p_standby.png")
    if os.path.exists(standby_path):
        try:
            import cv2
            img = cv2.imread(standby_path)
            if img is not None:
                h, w = img.shape[:2]
                img_resized = cv2.resize(img, (960, int(h * (960 / w))))
                ok, buf = cv2.imencode('.jpg', img_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    _STANDBY_FRAME_CACHE = buf.tobytes()
                    return _STANDBY_FRAME_CACHE
        except Exception:
            pass

    try:
        import cv2
        import numpy as np
        img = np.zeros((540, 960, 3), dtype=np.uint8)
        cv2.rectangle(img, (20, 20), (940, 520), (51, 65, 85), 2)
        cv2.putText(img, "ANTIDOZE CAB CAMERA STANDBY", (220, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (148, 163, 184), 2, cv2.LINE_AA)
        cv2.putText(img, "Connect AntiDoze client to view live stream", (250, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 116, 139), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if ok:
            _STANDBY_FRAME_CACHE = buf.tobytes()
            return _STANDBY_FRAME_CACHE
    except Exception:
        pass

    _STANDBY_FRAME_CACHE = b""
    return _STANDBY_FRAME_CACHE


CAMERA_VIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AntiDoze Cab Live Camera Stream</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #060A12; color: #F1F5F9; font-family: system-ui, -apple-system, sans-serif; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }
    header { background: #0B1322; border-bottom: 1px solid #1E293B; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; z-index: 10; }
    .title { font-weight: 800; font-size: 15px; display: flex; align-items: center; gap: 10px; }
    .rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #EF4444; box-shadow: 0 0 10px #EF4444; animation: recBlink 1s infinite alternate; }
    @keyframes recBlink { 0% { opacity: 1; } 100% { opacity: 0.3; } }
    .btn { background: #1E293B; color: #F1F5F9; border: 1px solid #334155; padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 13px; text-decoration: none; cursor: pointer; transition: all 0.2s; }
    .btn:hover { background: #334155; border-color: #38BDF8; }
    .btn-primary { background: #0284C7; border-color: #38BDF8; color: #FFF; }
    .viewport { flex: 1; position: relative; display: flex; align-items: center; justify-content: center; background: #000; overflow: hidden; }
    .stream-img { max-width: 100%; max-height: 100%; object-fit: contain; width: auto; height: auto; box-shadow: 0 0 40px rgba(0,0,0,0.8); }
    .overlay-info { position: absolute; bottom: 20px; left: 20px; background: rgba(11, 19, 34, 0.85); backdrop-filter: blur(8px); border: 1px solid #334155; padding: 10px 16px; border-radius: 8px; font-size: 12px; display: flex; gap: 16px; align-items: center; }
  </style>
</head>
<body>
  <header>
    <div class="title">
      <div class="rec-dot"></div>
      <span>AntiDoze Live Cab Camera • Remote Stream</span>
      <span style="font-size: 12px; color: #94A3B8; font-weight: 400;">960x540 • Live AI Stream</span>
    </div>
    <div style="display: flex; gap: 8px;">
      <a href="/" class="btn">← Back to Command Dashboard</a>
      <button class="btn" onclick="takeSnapshot()">📸 Capture Snapshot</button>
      <button class="btn btn-primary" onclick="toggleFullscreen()">⛶ Fullscreen</button>
    </div>
  </header>
  <div class="viewport">
    <img class="stream-img" id="streamImg" src="/api/camera/stream" alt="AntiDoze Live Cab Stream" />
    <div class="overlay-info">
      <div>Driver: <strong id="drvVal" style="color: #38BDF8;">DRV-101</strong></div>
      <div>Strikes: <strong id="strVal" style="color: #34D399;">0/3 (TOP DRIVER)</strong></div>
      <div>EAR: <strong id="earVal" style="color: #F1F5F9;">0.30</strong></div>
      <div>Status: <span style="color: #34D399;">● LIVE STREAM ACTIVE</span></div>
    </div>
  </div>
  <script>
    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(()=>{});
      } else {
        document.exitFullscreen().catch(()=>{});
      }
    }
    function takeSnapshot() {
      window.open('/api/camera/snapshot.jpg', '_blank');
    }
    setInterval(async () => {
      try {
        const res = await fetch('/api/live');
        if (res.ok) {
          const d = await res.json();
          if (d.driver_id) document.getElementById('drvVal').innerText = d.driver_id;
          if (d.strike_status) document.getElementById('strVal').innerText = `${d.strike_count || 0}/3 (${d.strike_status})`;
          if (d.ear !== null && d.ear !== undefined) document.getElementById('earVal').innerText = Number(d.ear).toFixed(2);
        }
      } catch(e){}
    }, 1000);
  </script>
</body>
</html>"""


CAMERA_SOURCE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AntiDoze Wireless Remote Camera Sender</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0B1322; color: #F1F5F9; font-family: system-ui, sans-serif; text-align: center; padding: 20px; }
    h1 { font-size: 20px; margin-bottom: 8px; color: #38BDF8; font-weight: 800; }
    p { font-size: 14px; color: #94A3B8; margin-bottom: 20px; }
    .video-box { max-width: 640px; margin: 0 auto; border: 2px solid #334155; border-radius: 12px; overflow: hidden; background: #000; position: relative; }
    video { width: 100%; height: auto; transform: scaleX(-1); }
    .controls { margin-top: 15px; display: flex; justify-content: center; gap: 10px; }
    .btn { background: #0284C7; color: #FFF; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; }
    .status-badge { display: inline-block; padding: 6px 14px; border-radius: 12px; font-size: 12px; font-weight: 700; margin-top: 15px; background: #1E293B; color: #94A3B8; border: 1px solid #334155; }
  </style>
</head>
<body>
  <h1>📱 AntiDoze Wireless Remote Camera Sender</h1>
  <p>Stream this phone or computer's camera directly to AntiDoze over Wi-Fi</p>
  <div class="video-box">
    <video id="webcamVideo" autoplay playsinline muted></video>
  </div>
  <div class="controls">
    <button class="btn" id="btnToggleCam" onclick="toggleWebcam()">Start Camera Stream</button>
  </div>
  <div class="status-badge" id="streamStatus">Standby • Click Start Camera to begin</div>
  <canvas id="sendCanvas" style="display: none;"></canvas>
  <script>
    let streaming = false;
    let streamObj = null;
    let sendTimer = null;
    const video = document.getElementById("webcamVideo");
    const canvas = document.getElementById("sendCanvas");
    const statusEl = document.getElementById("streamStatus");
    const btn = document.getElementById("btnToggleCam");

    async function toggleWebcam() {
      if (streaming) {
        stopStreaming();
      } else {
        startStreaming();
      }
    }

    async function startStreaming() {
      try {
        streamObj = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" }
        });
        video.srcObject = streamObj;
        streaming = true;
        btn.innerText = "Stop Camera Stream";
        btn.style.background = "#DC2626";
        statusEl.innerText = "● Streaming live camera to AntiDoze server...";
        statusEl.style.background = "#065F46";
        statusEl.style.color = "#34D399";
        statusEl.style.borderColor = "#10B981";

        sendTimer = setInterval(sendFrame, 65);
      } catch (err) {
        alert("Camera access denied or unavailable: " + err);
      }
    }

    function stopStreaming() {
      if (sendTimer) clearInterval(sendTimer);
      if (streamObj) streamObj.getTracks().forEach(t => t.stop());
      video.srcObject = null;
      streaming = false;
      btn.innerText = "Start Camera Stream";
      btn.style.background = "#0284C7";
      statusEl.innerText = "○ Stream Stopped";
      statusEl.style.background = "#1E293B";
      statusEl.style.color = "#94A3B8";
      statusEl.style.borderColor = "#334155";
    }

    async function sendFrame() {
      if (!streaming || video.videoWidth === 0) return;
      canvas.width = 640;
      canvas.height = Math.round(video.videoHeight * (640 / video.videoWidth));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(async (blob) => {
        if (!blob) return;
        try {
          await fetch("/api/camera/upload", {
            method: "POST",
            headers: { "Content-Type": "image/jpeg" },
            body: blob
          });
        } catch (e) {}
      }, "image/jpeg", 0.65);
    }
  </script>
</body>
</html>"""


class DualStackThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class FleetManagerRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for Fleet Command Dashboard & REST API."""

    def _set_json_headers(self, status: int = HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def _set_html_headers(self, status: int = HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        db = get_fleet_db()

        # 1. Main Dashboard HTML
        if path in ("/", "/dashboard", "/index.html"):
            if os.path.exists(DASHBOARD_HTML_PATH):
                with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
                    content = f.read().encode("utf-8")
                self._set_html_headers()
                self.wfile.write(content)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Dashboard HTML not found")
            return

        # Dedicated Fullscreen Camera View for Remote Monitors
        if path in ("/camera", "/camera.html", "/live_camera"):
            self._set_html_headers()
            self.wfile.write(CAMERA_VIEW_HTML.encode("utf-8"))
            return

        # Mobile / Web Remote Camera Sender
        if path in ("/camera_source", "/mobile_camera", "/sender"):
            self._set_html_headers()
            self.wfile.write(CAMERA_SOURCE_HTML.encode("utf-8"))
            return

        # Live MJPEG Video Stream (Viewable in browsers, VLC, or remote computers)
        if path in ("/api/camera/stream", "/video_feed", "/stream.mjpg"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()

            try:
                last_frame = None
                while True:
                    frame = db.get_live_video_frame()
                    if frame is None:
                        frame = get_standby_frame_bytes()
                        time.sleep(0.3)
                    else:
                        time.sleep(0.04)  # ~25 FPS max

                    if frame and frame != last_frame:
                        last_frame = frame
                        header = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode("utf-8") + b"\r\n\r\n"
                        self.wfile.write(header)
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass
            return

        # Single Camera Snapshot (JPEG)
        if path in ("/api/camera/snapshot", "/api/camera/snapshot.jpg", "/snapshot.jpg"):
            frame = db.get_live_video_frame()
            if frame is None:
                frame = get_standby_frame_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(frame)
            return

        # Camera Stream Metadata
        if path in ("/api/camera/status", "/api/camera/meta"):
            meta = db.get_live_video_meta()
            lan_ips = get_lan_ip_addresses()
            srv_port = _SERVER_PORT or 8080
            meta["stream_url"] = f"http://{lan_ips[0] if lan_ips else '127.0.0.1'}:{srv_port}/api/camera/stream"
            meta["snapshot_url"] = f"http://{lan_ips[0] if lan_ips else '127.0.0.1'}:{srv_port}/api/camera/snapshot.jpg"
            self._set_json_headers()
            self.wfile.write(json.dumps(meta).encode("utf-8"))
            return

        # 2. API: Live Non-Simulation Cab Telemetry Stream
        if path == "/api/live":
            live_data = db.get_live_telemetry()
            self._set_json_headers()
            self.wfile.write(json.dumps(live_data).encode("utf-8"))
            return

        # API: Network Connection Info (for multi-computer & LAN access)
        if path == "/api/network-info":
            lan_ips = get_lan_ip_addresses()
            srv_port = _SERVER_PORT or 8080
            info = {
                "hostname": socket.gethostname(),
                "lan_ips": lan_ips,
                "primary_ip": lan_ips[0] if lan_ips else "127.0.0.1",
                "port": srv_port,
                "urls": [f"http://{ip}:{srv_port}/" for ip in lan_ips],
                "local_url": f"http://localhost:{srv_port}/",
            }
            self._set_json_headers()
            self.wfile.write(json.dumps(info).encode("utf-8"))
            return

        # 3. API: Fleet KPIs
        if path == "/api/kpis":
            kpis = db.get_fleet_kpis()
            self._set_json_headers()
            self.wfile.write(json.dumps(kpis).encode("utf-8"))
            return

        # 3. API: Drivers List
        if path == "/api/drivers":
            drivers = db.get_all_drivers()
            self._set_json_headers()
            self.wfile.write(json.dumps(drivers).encode("utf-8"))
            return

        # 4. API: Telemetry Logs
        if path == "/api/logs":
            limit = int(query.get("limit", [100])[0])
            driver_id = query.get("driver_id", [None])[0]
            critical_only = bool(query.get("critical_only", [0])[0] in ("1", "true", "True"))

            logs = db.get_recent_logs(limit=limit, driver_id=driver_id, critical_only=critical_only)
            self._set_json_headers()
            self.wfile.write(json.dumps(logs).encode("utf-8"))
            return

        # 5. API: Urgent Alerts
        if path == "/api/alerts":
            unack_only = bool(query.get("unack_only", ["1"])[0] in ("1", "true"))
            alerts = db.get_active_alerts(unacknowledged_only=unack_only)
            self._set_json_headers()
            self.wfile.write(json.dumps(alerts).encode("utf-8"))
            return

        # 6. API: Export CSV
        if path == "/api/export-csv":
            logs = db.get_recent_logs(limit=1000)
            output = io.StringIO()
            if logs:
                writer = csv.DictWriter(output, fieldnames=list(logs[0].keys()))
                writer.writeheader()
                writer.writerows(logs)
            csv_bytes = output.getvalue().encode("utf-8")

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="antidoze_telemetry_logs.csv"')
            self.end_headers()
            self.wfile.write(csv_bytes)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        db = get_fleet_db()

        # API: Remote Camera Frame Upload (binary JPEG from phone/webcam)
        if path == "/api/camera/upload":
            content_len = int(self.headers.get("Content-Length", 0))
            frame_bytes = self.rfile.read(content_len) if content_len > 0 else b""
            if frame_bytes:
                db.set_remote_upload_frame(frame_bytes)
            self._set_json_headers()
            self.wfile.write(b'{"success": true}')
            return

        # Read JSON body
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        # 1. API: Acknowledge Alert
        if path in ("/api/alerts/ack", "/api/alerts/acknowledge"):
            alert_id = data.get("alert_id")
            mgr = data.get("manager_name", "Fleet Supervisor")
            if alert_id is not None:
                ok = db.acknowledge_alert(int(alert_id), manager_name=mgr)
                self._set_json_headers()
                self.wfile.write(json.dumps({"success": ok}).encode("utf-8"))
                return
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing alert_id")
                return

        # 2. API: Ingest Telemetry
        if path == "/api/telemetry":
            driver_id = data.get("driver_id", "DRV-UNKNOWN")
            strike_count = int(data.get("strike_count", 0))
            strike_status = data.get("strike_status", "TOP DRIVER")
            alert_type = data.get("alert_type", "10s HEARTBEAT")

            log_id = db.log_telemetry(
                driver_id=driver_id,
                strike_count=strike_count,
                strike_status=strike_status,
                alert_type=alert_type,
                ear_value=data.get("ear_value"),
                head_pitch=data.get("head_pitch"),
                glance_direction=data.get("glance_direction"),
                clean_streak=data.get("clean_streak", "00:00"),
                trip_elapsed=data.get("trip_elapsed", "00:00"),
                camera_mode=data.get("camera_mode", "ACTIVE"),
                vehicle_id=data.get("vehicle_id"),
                location=data.get("location"),
                notes=data.get("notes"),
            )
            self._set_json_headers(HTTPStatus.CREATED)
            self.wfile.write(json.dumps({"success": True, "log_id": log_id}).encode("utf-8"))
            return

        # 3. API: Delete Specific Drive Log
        if path in ("/api/logs/delete", "/api/logs/remove"):
            log_id = data.get("log_id") or data.get("id")
            if log_id is not None:
                ok = db.delete_log(int(log_id))
                self._set_json_headers()
                self.wfile.write(json.dumps({"success": ok, "log_id": log_id}).encode("utf-8"))
                return
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing log_id")
                return

        # 4. API: Clear Drive Logs (optionally by driver)
        if path in ("/api/logs/clear", "/api/logs/delete-all"):
            driver_id = data.get("driver_id")
            count = db.clear_logs(driver_id=driver_id)
            self._set_json_headers()
            self.wfile.write(json.dumps({"success": True, "deleted_count": count}).encode("utf-8"))
            return

        # 5. API: Toggle Driver Online / Offline Connection Status
        if path in ("/api/drivers/toggle", "/api/drivers/status"):
            driver_id = data.get("driver_id")
            is_connected = data.get("is_connected")
            if driver_id:
                res = db.toggle_driver_connection(driver_id=driver_id, is_connected=is_connected)
                self._set_json_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
                return
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing driver_id")
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        db = get_fleet_db()

        # API: DELETE /api/logs?id=<id> OR /api/logs?all=1
        if path == "/api/logs":
            log_id = query.get("id", [None])[0] or query.get("log_id", [None])[0]
            clear_all = query.get("all", [None])[0]
            driver_id = query.get("driver_id", [None])[0]

            if log_id is not None:
                ok = db.delete_log(int(log_id))
                self._set_json_headers()
                self.wfile.write(json.dumps({"success": ok, "deleted_id": log_id}).encode("utf-8"))
                return
            elif clear_all or driver_id:
                count = db.clear_logs(driver_id=driver_id)
                self._set_json_headers()
                self.wfile.write(json.dumps({"success": True, "deleted_count": count}).encode("utf-8"))
                return
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing id or all parameter")
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def log_message(self, format, *args):
        # Quieter console logging for clean CLI output
        pass


_SERVER_INSTANCE = None
_SERVER_THREAD = None
_SERVER_PORT = 8080


def start_fleet_server_background(port: int = 8080, host: str = "0.0.0.0") -> int:
    """Starts the Fleet Manager web server in a daemon background thread if not already running."""
    global _SERVER_INSTANCE, _SERVER_THREAD, _SERVER_PORT
    if _SERVER_INSTANCE is not None:
        return _SERVER_PORT

    lan_ips = get_lan_ip_addresses()
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"

    # Prioritize 0.0.0.0 across ports to guarantee multi-computer network accessibility
    hosts_order = [host]
    if "0.0.0.0" not in hosts_order:
        hosts_order.append("0.0.0.0")
    if "127.0.0.1" not in hosts_order:
        hosts_order.append("127.0.0.1")

    for current_port in range(port, port + 20):
        for h in hosts_order:
            try:
                httpd = DualStackThreadingServer((h, current_port), FleetManagerRequestHandler)
                _SERVER_INSTANCE = httpd
                _SERVER_PORT = current_port
                _SERVER_THREAD = threading.Thread(target=httpd.serve_forever, daemon=True)
                _SERVER_THREAD.start()
                print(f" * Fleet Web Portal (This PC)       : http://localhost:{current_port}/")
                print(f" * Network Access URL (Other PCs)   : http://{primary_ip}:{current_port}/")
                if len(lan_ips) > 1:
                    print(f" * Alternate Network Interfaces     : {', '.join([f'http://{ip}:{current_port}/' for ip in lan_ips[1:]])}")
                return current_port
            except OSError:
                continue

    return _SERVER_PORT


def run_fleet_server(port: int = 8080, host: str = "0.0.0.0"):
    """Starts the DualStackThreadingServer for the Fleet Manager Portal."""
    db = get_fleet_db()
    lan_ips = get_lan_ip_addresses()
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"
    hostname = socket.gethostname()

    httpd = None
    actual_port = port
    hosts_order = [host]
    if "0.0.0.0" not in hosts_order:
        hosts_order.append("0.0.0.0")
    if "127.0.0.1" not in hosts_order:
        hosts_order.append("127.0.0.1")

    for p in range(port, port + 20):
        for h in hosts_order:
            try:
                httpd = DualStackThreadingServer((h, p), FleetManagerRequestHandler)
                actual_port = p
                break
            except OSError:
                continue
        if httpd:
            break

    if not httpd:
        print(f"[ERROR] Could not bind to port {port}-{port+20}.")
        return

    print("=" * 72)
    print(" ANTIDOZE FLEET COMMAND PORTAL & DYNAMIC DATABASE SERVER ")
    print("=" * 72)
    print(f" * Database Path              : {db.db_path}")
    print(f" * Local Portal URL (This PC) : http://localhost:{actual_port}/")
    print(f" * Network Access (Other PCs) : http://{primary_ip}:{actual_port}/")
    if len(lan_ips) > 1:
        print(f" * Alternate Network IPs      : {', '.join([f'http://{ip}:{actual_port}/' for ip in lan_ips[1:]])}")
    print(f" * Hostname Access URL        : http://{hostname}:{actual_port}/")
    print(f" * Dynamic Telemetry Stream   : Auto-refreshing database every 10 seconds")
    print("=" * 72)
    print(" [HOW TO ACCESS FROM ANOTHER COMPUTER / PHONE / TABLET]")
    print(" 1. Make sure both computers are connected to the same Wi-Fi / Local Network.")
    print(" 2. Open any web browser on the other computer (Chrome, Edge, Safari, Firefox).")
    print(f" 3. Enter URL in browser address bar: http://{primary_ip}:{actual_port}/")
    print("=" * 72)
    print(" * Press Ctrl+C to stop server")
    print("=" * 72)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Fleet Server stopped safely.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AntiDoze Fleet Manager Web Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding host (default: 0.0.0.0 for LAN access)")
    args = parser.parse_args()
    run_fleet_server(port=args.port, host=args.host)
    run_fleet_server(port=args.port, host=args.host)
