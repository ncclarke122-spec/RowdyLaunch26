"""
AntiDoze Fleet Dynamic Database Manager
========================================
Enterprise SQLite database layer for logging real-time driver vigilance telemetry,
managing strike status, and dispatching high-priority safety alerts to fleet managers.

Key Features:
  1. Thread-safe SQLite database with WAL (Write-Ahead Logging) mode.
  2. Automated 10-second heartbeat telemetry logging & event-driven alert triggers.
  3. Dynamic driver registry with live strike count and vigilance metrics.
  4. Explicit 'is_critical' flag and dedicated high-priority fleet alerts queue.
  5. JSON API-ready query helpers for Web & Terminal Fleet Manager Dashboards.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DB_FILENAME = "antidoze_fleet.db"


def get_default_db_path() -> str:
    """Returns absolute path to the default fleet database file in the project directory."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(project_dir, DEFAULT_DB_FILENAME)


class FleetDatabase:
    """
    Thread-safe SQLite database manager for AntiDoze fleet operations.
    Handles concurrent reads & writes between the AntiDoze vehicle client
    and the Fleet Manager monitoring portal.
    """

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(FleetDatabase, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return

        self.db_path = db_path or get_default_db_path()
        self._lock = threading.RLock()
        self._live_cache: Dict[str, Any] = {}
        self._live_frame_bytes: Optional[bytes] = None
        self._live_frame_time: float = 0.0
        self._live_frame_meta: Dict[str, Any] = {"is_active": False, "width": 0, "height": 0, "fps": 0.0}
        self._init_db()
        self._initialized = True

    def set_live_video_frame(self, frame_bytes: bytes, width: int = 0, height: int = 0, fps: float = 0.0) -> None:
        """Stores the latest live camera frame as JPEG bytes for remote MJPEG video streaming."""
        with self._lock:
            self._live_frame_bytes = frame_bytes if frame_bytes else None
            self._live_frame_time = time.time() if frame_bytes else 0.0
            self._live_frame_meta = {
                "is_active": bool(frame_bytes and len(frame_bytes) > 0),
                "width": width,
                "height": height,
                "fps": fps,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def get_live_video_frame(self, max_age_sec: float = 3.5) -> Optional[bytes]:
        """Returns the latest JPEG frame bytes if updated within max_age_sec, else None."""
        with self._lock:
            frame = getattr(self, "_live_frame_bytes", None)
            if not frame:
                return None
            frame_time = getattr(self, "_live_frame_time", 0.0)
            if (time.time() - frame_time) > max_age_sec:
                return None
            return frame

    def get_live_video_meta(self) -> Dict[str, Any]:
        """Returns metadata for the live video stream (dimensions, fps, is_active)."""
        with self._lock:
            meta = dict(getattr(self, "_live_frame_meta", {}))
            meta["is_active"] = bool(self.get_live_video_frame() is not None)
            return meta

    def set_remote_upload_frame(self, frame_bytes: bytes) -> None:
        """Stores a camera frame uploaded from a remote computer/smartphone."""
        with self._lock:
            self._remote_upload_frame = frame_bytes
            self._remote_upload_time = time.time()

    def get_remote_upload_frame(self, max_age_sec: float = 3.5) -> Optional[bytes]:
        """Retrieves remote uploaded frame if recent."""
        with self._lock:
            frame = getattr(self, "_remote_upload_frame", None)
            if not frame:
                return None
            if (time.time() - getattr(self, "_remote_upload_time", 0.0)) > max_age_sec:
                return None
            return frame

    def set_live_telemetry(self, driver_id: str, data: Dict[str, Any]):
        """Updates in-memory live telemetry from the active non-simulation cab client."""
        with self._lock:
            data["driver_id"] = driver_id
            data["is_connected"] = data.get("is_connected", True)
            data["connection_status"] = "CONNECTED" if data["is_connected"] else "INACTIVE"
            data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data["last_heartbeat_time"] = datetime.now().timestamp()
            self._live_cache = dict(data)

    def get_live_telemetry(self) -> Dict[str, Any]:
        """Returns the latest live telemetry from the active vehicle client."""
        with self._lock:
            cache = dict(getattr(self, "_live_cache", {}))
            if not cache:
                return {
                    "driver_id": None,
                    "is_connected": False,
                    "connection_status": "INACTIVE",
                    "client_status": "CAB OFFLINE (DISCONNECTED)",
                }

            # Check if last heartbeat is older than 15 seconds (detect abrupt disconnect)
            last_ts = cache.get("last_heartbeat_time")
            if last_ts and (datetime.now().timestamp() - last_ts) > 15.0:
                cache["is_connected"] = False
                cache["connection_status"] = "INACTIVE"
                cache["client_status"] = "CAB OFFLINE (HEARTBEAT TIMEOUT)"
            return cache

    def set_driver_active(
        self,
        driver_id: str,
        vehicle_id: Optional[str] = None,
        camera_mode: str = "ACTIVE",
        reset_strikes: bool = True,
    ) -> None:
        """Explicitly flags a driver as ACTIVE & CONNECTED in the database and live cache."""
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT vehicle_id FROM drivers WHERE driver_id = ?;", (driver_id,))
            row = cursor.fetchone()
            if row:
                if reset_strikes:
                    cursor.execute(
                        """
                        UPDATE drivers
                        SET status = 'ACTIVE',
                            is_connected = 1,
                            strike_count = 0,
                            strike_status = 'TOP DRIVER',
                            is_critical = 0,
                            clean_streak = '00:00',
                            trip_elapsed = '00:00',
                            camera_mode = ?,
                            last_update = ?
                        WHERE driver_id = ?;
                        """,
                        (camera_mode, now_ts, driver_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE drivers
                        SET status = 'ACTIVE',
                            is_connected = 1,
                            camera_mode = ?,
                            last_update = ?
                        WHERE driver_id = ?;
                        """,
                        (camera_mode, now_ts, driver_id),
                    )
            else:
                veh = vehicle_id or f"TRK-{driver_id.replace('DRV-', '')}"
                cursor.execute(
                    """
                    INSERT INTO drivers (driver_id, driver_name, vehicle_id, route_name, strike_count, strike_status, is_critical, clean_streak, trip_elapsed, camera_mode, status, is_connected, last_update)
                    VALUES (?, ?, ?, 'Regional Highway Route', 0, 'TOP DRIVER', 0, '00:00', '00:00', ?, 'ACTIVE', 1, ?);
                    """,
                    (driver_id, f"Driver {driver_id}", veh, camera_mode, now_ts),
                )
            conn.commit()
            conn.close()

            self._live_cache["driver_id"] = driver_id
            self._live_cache["is_connected"] = True
            self._live_cache["connection_status"] = "CONNECTED"
            self._live_cache["client_status"] = "ONLINE (LIVE CAMERA STREAMING)"
            if reset_strikes:
                self._live_cache["strike_count"] = 0
                self._live_cache["strike_status"] = "TOP DRIVER"
                self._live_cache["is_critical"] = False
                self._live_cache["clean_streak"] = "00:00"
                self._live_cache["trip_elapsed"] = "00:00"
            self._live_cache["updated_at"] = now_ts
            self._live_cache["last_heartbeat_time"] = datetime.now().timestamp()

    def set_driver_inactive(
        self,
        driver_id: str,
        strike_count: Optional[int] = None,
        strike_status: Optional[str] = None,
        clean_streak: Optional[str] = None,
        trip_elapsed: Optional[str] = None,
    ) -> None:
        """Explicitly flags a driver as INACTIVE & DISCONNECTED in the database and live cache."""
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            updates = ["status = 'INACTIVE'", "is_connected = 0", "is_critical = 0", "last_update = ?"]
            params = [now_ts]
            if strike_count is not None:
                updates.append("strike_count = ?")
                params.append(strike_count)
            if strike_status is not None:
                updates.append("strike_status = ?")
                params.append(strike_status)
            if clean_streak is not None:
                updates.append("clean_streak = ?")
                params.append(clean_streak)
            if trip_elapsed is not None:
                updates.append("trip_elapsed = ?")
                params.append(trip_elapsed)
            params.append(driver_id)

            cursor.execute(f"UPDATE drivers SET {', '.join(updates)} WHERE driver_id = ?;", params)
            conn.commit()
            conn.close()

            if getattr(self, "_live_cache", {}).get("driver_id") == driver_id:
                self._live_cache["is_connected"] = False
                self._live_cache["is_critical"] = False
                self._live_cache["connection_status"] = "INACTIVE"
                self._live_cache["client_status"] = "CAB OFFLINE (DISCONNECTED)"
                self._live_cache["updated_at"] = now_ts
                self._live_frame_bytes = None
                self._live_frame_time = 0.0
                if hasattr(self, "_live_frame_meta"):
                    self._live_frame_meta["is_active"] = False

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection with row factories and WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for non-blocking concurrent reads and writes
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """Initializes tables, indexes, and initial driver fleet profiles."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 1. Driver Registry Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS drivers (
                    driver_id TEXT PRIMARY KEY,
                    driver_name TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    route_name TEXT NOT NULL,
                    strike_count INTEGER NOT NULL DEFAULT 0,
                    strike_status TEXT NOT NULL DEFAULT 'TOP DRIVER',
                    is_critical INTEGER NOT NULL DEFAULT 0,
                    clean_streak TEXT DEFAULT '00:00',
                    trip_elapsed TEXT DEFAULT '00:00',
                    camera_mode TEXT DEFAULT 'ACTIVE',
                    status TEXT DEFAULT 'INACTIVE',
                    is_connected INTEGER NOT NULL DEFAULT 0,
                    last_update DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # Add is_connected column if upgrading existing database
            try:
                cursor.execute("ALTER TABLE drivers ADD COLUMN is_connected INTEGER NOT NULL DEFAULT 0;")
            except Exception:
                pass

            # 2. Dynamic Telemetry Logs Table (Updates every 10 seconds & on violations)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    driver_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    strike_count INTEGER NOT NULL,
                    strike_status TEXT NOT NULL,
                    is_critical INTEGER NOT NULL DEFAULT 0,
                    alert_type TEXT NOT NULL,
                    ear_value REAL,
                    head_pitch REAL,
                    glance_direction TEXT,
                    clean_streak TEXT,
                    trip_elapsed TEXT,
                    camera_mode TEXT,
                    vehicle_id TEXT,
                    location TEXT,
                    notes TEXT,
                    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
                );
                """
            )

            # 3. Fleet Incident Alerts Table (Urgent interventions for Fleet Manager)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    driver_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    strike_count INTEGER NOT NULL,
                    strike_status TEXT NOT NULL,
                    alert_level TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    vehicle_id TEXT,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    acknowledged_at DATETIME,
                    acknowledged_by TEXT,
                    FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
                );
                """
            )

            # Create query performance indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON telemetry_logs(timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_driver ON telemetry_logs(driver_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_critical ON telemetry_logs(is_critical, timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ack ON fleet_alerts(acknowledged, timestamp DESC);")

            # Seed default demo drivers if table is empty
            cursor.execute("SELECT COUNT(*) FROM drivers;")
            if cursor.fetchone()[0] == 0:
                initial_drivers = [
                    ("DRV-101", "Alex Miller", "TRK-9021", "Chicago, IL -> Denver, CO (I-80 W)", 0, "TOP DRIVER", 0, "00:00", "00:00", "ACTIVE", "ACTIVE"),
                    ("DRV-204", "Sarah Connor", "TRK-4412", "Dallas, TX -> Atlanta, GA (I-20 E)", 0, "TOP DRIVER", 0, "15:20", "02:10:00", "ACTIVE", "ACTIVE"),
                    ("DRV-308", "Marcus Vance", "TRK-8850", "Seattle, WA -> Boise, ID (I-84 E)", 1, "CAUTION", 0, "04:12", "04:45:00", "ACTIVE", "ACTIVE"),
                    ("DRV-415", "Elena Rostova", "TRK-2209", "Los Angeles, CA -> Phoenix, AZ (I-10 E)", 0, "TOP DRIVER", 0, "28:50", "01:30:00", "ACTIVE", "ACTIVE"),
                ]
                cursor.executemany(
                    """
                    INSERT INTO drivers (driver_id, driver_name, vehicle_id, route_name, strike_count, strike_status, is_critical, clean_streak, trip_elapsed, camera_mode, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    initial_drivers,
                )

            conn.commit()
            conn.close()

    def register_or_update_driver(
        self,
        driver_id: str,
        driver_name: Optional[str] = None,
        vehicle_id: Optional[str] = None,
        route_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Registers a driver if not existing, or returns existing driver info."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM drivers WHERE driver_id = ?;", (driver_id,))
            row = cursor.fetchone()

            if row is None:
                name = driver_name or f"Driver {driver_id}"
                veh = vehicle_id or f"TRK-{driver_id.replace('DRV-', '')}"
                route = route_name or "Regional Route"
                cursor.execute(
                    """
                    INSERT INTO drivers (driver_id, driver_name, vehicle_id, route_name, strike_count, strike_status, is_critical, status)
                    VALUES (?, ?, ?, ?, 0, 'TOP DRIVER', 0, 'ACTIVE');
                    """,
                    (driver_id, name, veh, route),
                )
                conn.commit()
                cursor.execute("SELECT * FROM drivers WHERE driver_id = ?;", (driver_id,))
                row = cursor.fetchone()

            res = dict(row)
            conn.close()
            return res

    def log_telemetry(
        self,
        driver_id: str,
        strike_count: int,
        strike_status: str,
        alert_type: str = "10s HEARTBEAT",
        ear_value: Optional[float] = None,
        head_pitch: Optional[float] = None,
        glance_direction: Optional[str] = None,
        clean_streak: str = "00:00",
        trip_elapsed: str = "00:00",
        camera_mode: str = "ACTIVE",
        vehicle_id: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Inserts a dynamic telemetry entry. Automatically detects CRITICAL status
        (strike_count >= 3 or strike_status == 'CRITICAL') to flag is_critical = 1
        and generate a high-priority incident alert for the fleet manager.
        """
        now_ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        is_critical = 1 if (strike_count >= 3 or "CRITICAL" in strike_status.upper()) else 0

        # Detect active vs inactive connection from alert type
        is_disconnect = any(x in alert_type.upper() for x in ("DISCONNECT", "OFFLINE", "SHUTDOWN", "INACTIVE"))
        cab_status = "INACTIVE" if is_disconnect else "ACTIVE"
        conn_flag = 0 if is_disconnect else 1

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Ensure driver exists
            cursor.execute("SELECT vehicle_id, route_name FROM drivers WHERE driver_id = ?;", (driver_id,))
            driver_info = cursor.fetchone()
            if driver_info:
                actual_vehicle_id = vehicle_id or driver_info["vehicle_id"]
            else:
                actual_vehicle_id = vehicle_id or f"TRK-{driver_id.replace('DRV-', '')}"
                cursor.execute(
                    """
                    INSERT INTO drivers (driver_id, driver_name, vehicle_id, route_name, strike_count, strike_status, is_critical, status, is_connected, last_update)
                    VALUES (?, ?, ?, 'Dispatched Highway Route', ?, ?, ?, ?, ?, ?);
                    """,
                    (driver_id, f"Driver {driver_id}", actual_vehicle_id, strike_count, strike_status, is_critical, cab_status, conn_flag, now_ts),
                )

            # Insert Telemetry Log
            cursor.execute(
                """
                INSERT INTO telemetry_logs (
                    driver_id, timestamp, strike_count, strike_status, is_critical,
                    alert_type, ear_value, head_pitch, glance_direction,
                    clean_streak, trip_elapsed, camera_mode, vehicle_id, location, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    driver_id,
                    now_ts,
                    strike_count,
                    strike_status,
                    is_critical,
                    alert_type,
                    ear_value,
                    head_pitch,
                    glance_direction,
                    clean_streak,
                    trip_elapsed,
                    camera_mode,
                    actual_vehicle_id,
                    location,
                    notes,
                ),
            )
            log_id = cursor.lastrowid

            # Update Driver Registry live status including connection status
            cursor.execute(
                """
                UPDATE drivers
                SET strike_count = ?,
                    strike_status = ?,
                    is_critical = ?,
                    clean_streak = ?,
                    trip_elapsed = ?,
                    camera_mode = ?,
                    status = ?,
                    is_connected = ?,
                    last_update = ?
                WHERE driver_id = ?;
                """,
                (strike_count, strike_status, is_critical, clean_streak, trip_elapsed, camera_mode, cab_status, conn_flag, now_ts, driver_id),
            )

            # If Critical, or if violation event occurred, insert into fleet_alerts
            is_violation = (strike_count > 0 and alert_type != "10s HEARTBEAT") or is_critical == 1
            if is_violation:
                alert_level = "CRITICAL" if is_critical else ("WARNING" if strike_count == 2 else "CAUTION")
                msg = f"Driver {driver_id} triggered {strike_status} via {alert_type}."
                if is_critical:
                    msg = f"EMERGENCY: Driver {driver_id} reached 3/3 CRITICAL STRIKES! Melodic alarm active in cab. Immediate rest required."

                cursor.execute(
                    """
                    INSERT INTO fleet_alerts (
                        driver_id, timestamp, strike_count, strike_status, alert_level,
                        alert_type, message, vehicle_id, acknowledged
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0);
                    """,
                    (driver_id, now_ts, strike_count, strike_status, alert_level, alert_type, msg, actual_vehicle_id),
                )

            conn.commit()
            conn.close()

            return log_id

    def get_recent_logs(
        self,
        limit: int = 50,
        driver_id: Optional[str] = None,
        critical_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieves recent telemetry logs sorted by timestamp descending."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = "SELECT * FROM telemetry_logs WHERE 1=1"
            params: List[Any] = []

            if driver_id:
                query += " AND driver_id = ?"
                params.append(driver_id)

            if critical_only:
                query += " AND is_critical = 1"

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows

    def _expire_stale_drivers(self, cursor: sqlite3.Cursor) -> List[str]:
        """Automatically marks drivers inactive if no heartbeat received for > 25 seconds."""
        now = datetime.now()
        cursor.execute("SELECT driver_id, last_update FROM drivers WHERE is_connected = 1 OR status = 'ACTIVE';")
        stale_ids = []
        for row in cursor.fetchall():
            drv_id = row["driver_id"]
            last_up = row["last_update"]
            if last_up:
                try:
                    last_dt = datetime.strptime(last_up, "%Y-%m-%d %H:%M:%S")
                    if (now - last_dt).total_seconds() > 25.0:
                        stale_ids.append(drv_id)
                except Exception:
                    pass
        if stale_ids:
            cursor.executemany("UPDATE drivers SET is_connected = 0, status = 'INACTIVE', is_critical = 0 WHERE driver_id = ?;", [(d,) for d in stale_ids])
            if getattr(self, "_live_cache", {}).get("driver_id") in stale_ids:
                self._live_cache["is_connected"] = False
                self._live_cache["is_critical"] = False
                self._live_cache["connection_status"] = "INACTIVE"
                self._live_cache["client_status"] = "CAB OFFLINE (DISCONNECTED)"
        return stale_ids

    def get_all_drivers(self) -> List[Dict[str, Any]]:
        """Returns all drivers and their active vigilance & connection status."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            stale_ids = self._expire_stale_drivers(cursor)
            if stale_ids:
                conn.commit()

            cursor.execute("SELECT * FROM drivers ORDER BY is_connected DESC, is_critical DESC, strike_count DESC, driver_id ASC;")
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows

    def get_active_alerts(self, unacknowledged_only: bool = True) -> List[Dict[str, Any]]:
        """Returns urgent safety alerts for fleet manager intervention."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if unacknowledged_only:
                cursor.execute(
                    """
                    SELECT fa.* FROM fleet_alerts fa
                    LEFT JOIN drivers d ON fa.driver_id = d.driver_id
                    WHERE fa.acknowledged = 0 AND (d.is_connected = 1 OR d.is_connected IS NULL)
                    ORDER BY fa.alert_level = 'CRITICAL' DESC, fa.alert_id DESC LIMIT 50;
                    """
                )
            else:
                cursor.execute("SELECT * FROM fleet_alerts ORDER BY alert_id DESC LIMIT 50;")
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows

    def acknowledge_alert(self, alert_id: int, manager_name: str = "Fleet Supervisor") -> bool:
        """Marks an alert as acknowledged by the fleet manager."""
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE fleet_alerts
                SET acknowledged = 1, acknowledged_at = ?, acknowledged_by = ?
                WHERE alert_id = ?;
                """,
                (now_ts, manager_name, alert_id),
            )
            affected = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return affected

    def get_fleet_kpis(self) -> Dict[str, Any]:
        """Calculates fleet-wide safety metrics."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            stale_ids = self._expire_stale_drivers(cursor)
            if stale_ids:
                conn.commit()

            cursor.execute("SELECT COUNT(*) FROM drivers;")
            total_drivers = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_connected = 1;")
            active_drivers = cursor.fetchone()[0]

            # Inactive drivers do not display active warnings; only count warnings for active/connected drivers
            cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_connected = 1 AND is_critical = 1;")
            critical_drivers = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_connected = 1 AND strike_count = 2 AND is_critical = 0;")
            warning_drivers = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_connected = 1 AND strike_count = 1;")
            caution_drivers = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_connected = 1 AND strike_count = 0;")
            top_drivers = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM telemetry_logs;")
            total_logs = cursor.fetchone()[0]

            # Pending alerts only for active/connected drivers
            cursor.execute(
                """
                SELECT COUNT(*) FROM fleet_alerts fa
                LEFT JOIN drivers d ON fa.driver_id = d.driver_id
                WHERE fa.acknowledged = 0 AND (d.is_connected = 1 OR d.is_connected IS NULL);
                """
            )
            pending_alerts = cursor.fetchone()[0]

            conn.close()

            return {
                "total_drivers": total_drivers,
                "active_drivers": active_drivers,
                "inactive_drivers": max(0, total_drivers - active_drivers),
                "critical_drivers": critical_drivers,
                "warning_drivers": warning_drivers,
                "caution_drivers": caution_drivers,
                "top_drivers": top_drivers,
                "total_logs": total_logs,
                "pending_alerts": pending_alerts,
                "last_refresh": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def delete_log(self, log_id: int) -> bool:
        """Deletes a specific telemetry log entry by id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_logs WHERE id = ?;", (log_id,))
            affected = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return affected

    def clear_logs(self, driver_id: Optional[str] = None) -> int:
        """Clears telemetry logs, optionally filtered by driver_id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if driver_id:
                cursor.execute("DELETE FROM telemetry_logs WHERE driver_id = ?;", (driver_id,))
            else:
                cursor.execute("DELETE FROM telemetry_logs;")
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            return affected

    def toggle_driver_connection(self, driver_id: str, is_connected: Optional[bool] = None) -> Dict[str, Any]:
        """Toggles or sets the connection status of a driver."""
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT is_connected, status, strike_count, strike_status FROM drivers WHERE driver_id = ?;", (driver_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return {"success": False, "error": f"Driver {driver_id} not found"}

            if is_connected is None:
                new_conn = 0 if row["is_connected"] == 1 else 1
            else:
                new_conn = 1 if is_connected else 0

            new_status = "ACTIVE" if new_conn == 1 else "INACTIVE"
            if new_conn == 1:
                cursor.execute(
                    "UPDATE drivers SET is_connected = 1, status = 'ACTIVE', strike_count = 0, strike_status = 'TOP DRIVER', is_critical = 0, clean_streak = '00:00', trip_elapsed = '00:00', last_update = ? WHERE driver_id = ?;",
                    (now_ts, driver_id),
                )
            else:
                cursor.execute(
                    "UPDATE drivers SET is_connected = 0, status = 'INACTIVE', is_critical = 0, last_update = ? WHERE driver_id = ?;",
                    (now_ts, driver_id),
                )
            conn.commit()
            conn.close()

            # If this is the active live cab in memory, update cache
            if getattr(self, "_live_cache", {}).get("driver_id") == driver_id:
                self._live_cache["is_connected"] = bool(new_conn == 1)
                self._live_cache["is_critical"] = False
                self._live_cache["connection_status"] = "CONNECTED" if new_conn == 1 else "INACTIVE"
                self._live_cache["client_status"] = "ONLINE (LIVE CAMERA STREAMING)" if new_conn == 1 else "CAB OFFLINE (DISCONNECTED)"
                if new_conn == 1:
                    self._live_cache["strike_count"] = 0
                    self._live_cache["strike_status"] = "TOP DRIVER"
                    self._live_cache["is_critical"] = False
                self._live_cache["updated_at"] = now_ts

            return {
                "success": True,
                "driver_id": driver_id,
                "is_connected": new_conn,
                "status": new_status,
                "message": f"Driver {driver_id} toggled to {new_status}"
            }

    def clear_database(self):
        """Clears logs and alerts while preserving drivers (for testing)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_logs;")
            cursor.execute("DELETE FROM fleet_alerts;")
            cursor.execute("UPDATE drivers SET strike_count = 0, strike_status = 'TOP DRIVER', is_critical = 0;")
            conn.commit()
            conn.close()


# Singleton accessor
def get_fleet_db(db_path: Optional[str] = None) -> FleetDatabase:
    return FleetDatabase(db_path=db_path)


if __name__ == "__main__":
    db = get_fleet_db()
    print(f"[INFO] Fleet Database initialized at: {db.db_path}")
    kpis = db.get_fleet_kpis()
    print(f"[INFO] Fleet KPIs: {kpis}")
    logs = db.get_recent_logs(limit=5)
    print(f"[INFO] Found {len(logs)} recent logs.")
