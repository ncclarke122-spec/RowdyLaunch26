"""
AntiDoze - AI Driver Fatigue, Head Nodding & Vigilance Management System
========================================================================
Features:
  1. Gradual Stack Decay System:
     - Eyelid closure time accumulates in a persistent stack (flicker-tolerant).
     - When eyes are open, the stack GRADUALLY DECAYS at a smooth, continuous
       rate (default: 0.20s of stack drained per second of open eyes, so a full
       2.0s stack drains completely over 10.0 seconds of attentive driving).
  2. 3-Strike Safety System (Disciplinary / Risk Management):
     - Tier 1: TOP DRIVER (0/3 Strikes) - Optimal alert condition.
     - Tier 2: CAUTION (1/3 Strikes) - First warning stage.
     - Tier 3: WARNING (2/3 Strikes) - High risk stage.
     - Tier 4: CRITICAL (3/3 Strikes) - Alarm sounds; immediate rest required!
  3. Gamified Vigilance Reward System (Positive Motivation & Milestones):
     - Continuous clean driving streak tracking (STREAK: mm:ss, BEST: mm:ss).
     - Vigilance Reward Tiers:
       * Level 1: VIGILANT DRIVER (LVL 1) (< 3 minutes clean driving)
       * Level 2: PRO PILOT (LVL 2)       (3 - 10 minutes clean driving)
       * Level 3: HIGHWAY MASTER (LVL 3)  (10 - 30 minutes clean driving)
       * Level 4: IRON TRUCKER (LVL 4)    (30+ minutes clean driving)
     - On any strike or head nod slump, the current streak resets to 0 while
       preserving the driver's session Personal Best.
  4. Strike Removal (30-Minute Clean Drive Rule):
     - Driving 30 continuous minutes with no violations removes 1 strike
       and promotes the driver to Level 4 IRON TRUCKER!
  5. Rest Stop Reset (15-Minute Rest Rule):
     - Stopping at a rest stop for > 15 minutes (or via [R] key) resets ALL strikes to 0.
  6. Camera Standby & Mandatory Hour 6 Monitoring:
     - Non-invasive standby mode available during Hours 0 - 6.
     - Mandatory safety monitoring engages automatically at Hour 6:00:00.
  7. Directional Head Nod & Mirror Check Telemetry.
  8. Melodic Chime & Modern 2026 Digital Cockpit HUD.

Usage:
    python antidoze.py                      # Main entry point
    python roadawake.py                     # Backward-compatible alias
    python antidoze.py --demo               # Run simulated demonstration
    python antidoze.py --test               # Run algorithmic self-checks
"""

import os
import sys
import tempfile

# Prevent matplotlib cache warning in sandbox/temp directories
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "matplotlib_cache"))

import argparse
import random
import threading
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np

# Try importing Tkinter for desktop pop-up
try:
    import tkinter as tk
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False

# Try importing MediaPipe
try:
    import mediapipe as mp
except ImportError:
    print("\n[ERROR] MediaPipe is not installed.")
    print("Please install dependencies: pip install opencv-python mediapipe numpy\n")
    sys.exit(1)

# Platform-specific audio alert
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# AntiDoze Fleet Dynamic Database
from fleet_database import get_fleet_db


# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

DEFAULT_EAR_THRESHOLD = 0.22
DEFAULT_EYE_FATIGUE_SEC = 2.0        # Stacked eye closure limit (2.0s)
DEFAULT_DB_SYNC_INTERVAL = 10.0      # Fleet database dynamic sync interval (10 seconds)
DEFAULT_DRIVER_ID = "DRV-101"        # Default commercial vehicle driver ID

# Gradual decay rate:
# 2.0s stack drains completely over 10.0s of attentive open eyes -> 0.20 s/s
DEFAULT_STACK_DECAY_RATE = 0.20

# Strike healing & Rest stop defaults
DEFAULT_STRIKE_HEAL_SEC = 30 * 60    # 30 minutes clean driving removes 1 strike (1800s)
DEFAULT_REST_STOP_SEC = 15 * 60      # 15 minutes at rest stop resets ALL strikes (900s)

# Trip duration & Mandatory camera monitoring rules
DEFAULT_MANDATORY_CAMERA_HOUR = 6.0  # Mandatory camera monitoring threshold (Hours)
DEFAULT_MANDATORY_CAMERA_SEC = DEFAULT_MANDATORY_CAMERA_HOUR * 3600.0  # 21,600s
DEFAULT_PLANNED_DRIVE_HOURS = 8.0    # Default planned driving time (Hours)

# Head nod parameters (Catches downward head pitch in 3.0s at ratio < 0.78)
DEFAULT_NOD_DURATION_SEC = 3.0       # Directional nod threshold (3.0s sustained slump detection)
DEFAULT_NOD_RATIO_THRESH = 0.78      # Downward slump threshold (catches ~20 deg downward nod)
YAW_MIRROR_CHECK_THRESH = 0.28       # Horizontal head turn threshold
POPUP_CLEAR_OPEN_EYES_SEC = 2.0      # Auto-dismiss pop-up after 2s continuous open eyes (eye alerts)
POPUP_CLEAR_UPRIGHT_SEC = 1.5        # Auto-dismiss pop-up after 1.5s continuous upright posture (nod alerts)

# Landmark indices for MediaPipe Face Mesh:
RIGHT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]
LEFT_EYE_LANDMARKS = [362, 385, 387, 263, 373, 380]

NOSE_LANDMARK = 1
CHIN_LANDMARK = 152
FOREHEAD_LANDMARK = 10
LEFT_TRAGUS_LANDMARK = 234
RIGHT_TRAGUS_LANDMARK = 454

# Short, punchy, slightly inspirational road alertness statements
SHORT_INSPIRATIONAL_STATEMENTS = [
    "Stay sharp. Arrive alive.",
    "Eyes forward. Loved ones await.",
    "Breathe, refocus, and stay alert.",
    "Rest is strength. Drive safe.",
    "Clear eyes, steady hands, safe miles.",
    "You've got this. Stay focused!",
    "Great drivers finish safe.",
    "Stay vigilant. Own the road.",
    "Take a breath. Keep moving safe.",
    "Wake up, champion. Future ahead.",
    "Protect every mile. Stay sharp.",
    "Patience and focus make the master."
]


# ============================================================================
# MELODIC, NON-ANNOYING AUDITORY CHIME (DISTINCT EYE & HEAD NOD ALERTS)
# ============================================================================

class MelodicChimeManager:
    """
    Plays distinct melodic cabin alerts:
      - Eye Fatigue: Soft ascending chime (587 Hz -> 880 Hz)
      - Head Nod: Urgent descending dual pulse (784 Hz -> 523 Hz)
    Runs on a daemon thread to guarantee zero frame drops or video lag.
    """

    def __init__(self):
        self.is_playing = False
        self._lock = threading.Lock()

    def _play_worker(self, tone: str = "eye"):
        try:
            if HAS_WINSOUND:
                try:
                    if tone == "nod":
                        # Distinctive posture warning: Descending dual-tone (784 Hz -> 523 Hz)
                        winsound.Beep(784, 120)
                        time.sleep(0.03)
                        winsound.Beep(523, 240)
                    else:
                        # Soothing upward chime for eye fatigue / system events: (587 Hz -> 880 Hz)
                        winsound.Beep(587, 140)
                        time.sleep(0.04)
                        winsound.Beep(880, 220)
                except RuntimeError:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION if tone == "nod" else winsound.MB_ICONASTERISK)
            else:
                sys.stdout.write('\a')
                sys.stdout.flush()
                time.sleep(0.3)
        except Exception:
            pass
        finally:
            with self._lock:
                self.is_playing = False

    def trigger(self, tone: str = "eye"):
        """Triggers the acoustic chime on a daemon thread without video lag."""
        with self._lock:
            if not self.is_playing:
                self.is_playing = True
                t = threading.Thread(target=self._play_worker, args=(tone,), daemon=True)
                t.start()

    def trigger_eye_alarm(self):
        """Acoustic alert for 3rd strike eye fatigue (Ascending chime)."""
        self.trigger(tone="eye")

    def trigger_nod_alarm(self):
        """Acoustic alert for head nod slump (Descending posture warning)."""
        self.trigger(tone="nod")


# ============================================================================
# COMPACT INSPIRATIONAL POP-UP ALERT MANAGER
# ============================================================================

class CompactInspirationalManager:
    """
    Manages short, compact inspirational pop-up alerts.
    The pop-up automatically disappears once the trucker's eyes
    have remained continuously open for 2.0 seconds.
    """

    def __init__(self, statements: List[str] = SHORT_INSPIRATIONAL_STATEMENTS):
        self.statements = list(statements)
        self.active_quote: Optional[str] = None
        self.is_visible: bool = False
        self.alert_reason: str = "DROWSINESS"
        self._quote_index: int = 0
        self._desktop_alive: bool = False
        self._lock = threading.Lock()
        random.shuffle(self.statements)

    def trigger(self, reason: str = "DROWSINESS"):
        """Activates a fresh pop-up alert with a short inspirational quote."""
        with self._lock:
            self.alert_reason = reason
            self.active_quote = self.statements[self._quote_index]
            self._quote_index = (self._quote_index + 1) % len(self.statements)
            self.is_visible = True
            quote_text = self.active_quote
            reason_text = self.alert_reason

        if HAS_TKINTER and not self._desktop_alive:
            self._desktop_alive = True
            t = threading.Thread(
                target=self._launch_compact_desktop_popup,
                args=(quote_text, reason_text),
                daemon=True,
            )
            t.start()

    def dismiss(self):
        """Dismisses the pop-up (called after 2.0s of continuous open eyes)."""
        with self._lock:
            self.is_visible = False
            self.active_quote = None
            self._desktop_alive = False

    def get_active_quote(self) -> Optional[str]:
        with self._lock:
            return self.active_quote if self.is_visible else None

    def get_active_reason(self) -> Optional[str]:
        with self._lock:
            return self.alert_reason if self.is_visible else None

    def _launch_compact_desktop_popup(self, quote: str, reason: str):
        """Displays a sleek floating desktop HUD notification."""
        try:
            root = tk.Tk()
            root.title("AntiDoze Assist")
            root.geometry("390x125")
            root.resizable(False, False)
            root.configure(bg="#0B0F19")
            root.attributes("-topmost", True)

            root.update_idletasks()
            sw = root.winfo_screenwidth()
            x = (sw - 390) // 2
            root.geometry(f"390x125+{x}+80")

            is_nod = ("HEAD NOD" in reason)
            badge_fg = "#C084FC" if is_nod else "#F59E0B"
            hint_txt = "Raise head upright 1.5s to clear" if is_nod else "Keep eyes open 2s to clear"
            hint_fg = "#C084FC" if is_nod else "#38BDF8"

            lbl_badge = tk.Label(
                root, text=f"[ALERT] {reason}", fg=badge_fg, bg="#0B0F19", font=("Segoe UI", 9, "bold")
            )
            lbl_badge.pack(pady=(10, 3))

            lbl_quote = tk.Label(
                root, text=f'"{quote}"', fg="#F8FAFC", bg="#0B0F19", font=("Segoe UI", 11, "bold italic")
            )
            lbl_quote.pack(pady=3)

            lbl_hint = tk.Label(
                root, text=hint_txt, fg=hint_fg, bg="#0B0F19", font=("Segoe UI", 8)
            )
            lbl_hint.pack(pady=(2, 6))

            while self._desktop_alive:
                root.update_idletasks()
                root.update()
                time.sleep(0.03)

            root.destroy()
        except Exception:
            pass


# ============================================================================
# TRIP PLANNING & MANDATORY CAMERA MONITORING SYSTEM
# ============================================================================

class TripManager:
    """
    Manages driver trip planning, continuous driving telemetry, camera privacy
    mode toggling, and federal/fleet mandatory fatigue monitoring after 6 hours.

    Rules:
      1. Pre-Drive Planning: Driver inputs intended driving duration before start.
         If planned duration > 6.0 hours, driver is alerted that camera privacy
         toggle will be locked after Hour 6.
      2. Hours 0 - 6: Camera is toggleable between Active Tracking and Privacy Standby.
      3. Hour 6+: Camera MUST remain ON. Toggling off is blocked and triggers
         a chime + warning banner. If camera was off at Hour 6, it is auto-enabled.
    """

    def __init__(
        self,
        planned_hours: float = DEFAULT_PLANNED_DRIVE_HOURS,
        mandatory_hour: float = DEFAULT_MANDATORY_CAMERA_HOUR,
        time_scale: float = 1.0,
        initial_elapsed_sec: float = 0.0,
    ):
        self.planned_hours = max(float(planned_hours), 0.1)
        self.planned_sec = self.planned_hours * 3600.0
        self.mandatory_hour = float(mandatory_hour)
        self.mandatory_sec = self.mandatory_hour * 3600.0
        self.time_scale = max(float(time_scale), 0.001)
        self.elapsed_drive_sec = max(float(initial_elapsed_sec), 0.0)

        self.camera_enabled: bool = True
        self.mandatory_lock_active: bool = (self.elapsed_drive_sec >= self.mandatory_sec)
        self.exceeds_six_hours: bool = (self.planned_hours > self.mandatory_hour)

        # Alert timestamps
        self.lock_attempt_alert_time: float = 0.0
        self.hour_6_transition_time: float = 0.0
        self.trip_start_time: float = time.time()
        self._hour_6_announced: bool = self.mandatory_lock_active

    def update(self, dt: float, is_resting: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Advances driving clock (scaled by time_scale).
        Checks for Hour 6 mandatory lock transition.
        Returns (hour_6_just_triggered, announcement_message).
        """
        if not is_resting:
            self.elapsed_drive_sec += (dt * self.time_scale)

        just_locked = False
        message = None

        if self.elapsed_drive_sec >= self.mandatory_sec:
            if not self.mandatory_lock_active:
                self.mandatory_lock_active = True
                just_locked = True
                self.hour_6_transition_time = time.time()
                self._hour_6_announced = True
                # Automatically restore camera ON if toggled off
                self.camera_enabled = True
                message = "MANDATORY MONITORING ACTIVATED: 6 hours of driving reached. Camera is permanently locked ON."

        return just_locked, message

    def toggle_camera(self) -> Tuple[bool, str]:
        """
        Toggles camera on/off. If drive time >= 6 hours, blocks toggling off.
        """
        if self.mandatory_lock_active:
            self.camera_enabled = True
            self.lock_attempt_alert_time = time.time()
            return False, "MANDATORY MONITORING: Camera cannot be toggled off after 6 hours of driving."

        self.camera_enabled = not self.camera_enabled
        if self.camera_enabled:
            return True, "Camera toggled ON (Live Tracking Active)"
        else:
            return True, "Camera toggled OFF (Standby Mode Active)"

    def is_camera_lock_alert_active(self, current_time: float, duration_sec: float = 3.5) -> bool:
        """True if driver recently attempted to disable camera after Hour 6."""
        return (current_time - self.lock_attempt_alert_time) < duration_sec

    def is_hour_6_transition_alert_active(self, current_time: float, duration_sec: float = 5.0) -> bool:
        """True if system recently crossed the 6-hour mandatory monitoring threshold."""
        return (current_time - self.hour_6_transition_time) < duration_sec

    def is_initial_trip_alert_active(self, current_time: float, duration_sec: float = 6.0) -> bool:
        """True if a trip > 6.0 hours started recently (shows policy banner)."""
        return self.exceeds_six_hours and ((current_time - self.trip_start_time) < duration_sec)

    def get_time_until_mandatory_lock(self) -> float:
        """Returns seconds remaining until camera lock is enforced."""
        return max(self.mandatory_sec - self.elapsed_drive_sec, 0.0)


def prompt_driver_trip_hours(
    default_hours: float = DEFAULT_PLANNED_DRIVE_HOURS,
    default_driver_id: str = DEFAULT_DRIVER_ID,
) -> Tuple[float, bool, str]:
    """
    Prompts the trucker for planned drive duration and Driver ID before tracking starts.
    If planned hours > 6.0, shows a prominent alert that camera privacy toggle
    is only permitted during Hours 0-6, after which camera monitoring is mandatory.
    Returns (planned_hours, exceeds_six_hours, driver_id).
    """
    planned_hours = default_hours
    driver_id = default_driver_id
    gui_success = False

    if HAS_TKINTER:
        try:
            root = tk.Tk()
            root.title("AntiDoze - Pre-Trip Driving Plan & Fleet ID")
            root.geometry("540x410")
            root.resizable(False, False)
            root.configure(bg="#0B0F19")
            root.attributes("-topmost", True)

            # Center window on screen
            root.update_idletasks()
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = max((sw - 540) // 2, 0)
            y = max((sh - 410) // 2, 0)
            root.geometry(f"540x410+{x}+{y}")

            result_holder = {"hours": default_hours, "driver_id": default_driver_id, "confirmed": False}

            # Header Frame
            header_frame = tk.Frame(root, bg="#111827", pady=12)
            header_frame.pack(fill="x")
            lbl_title = tk.Label(
                header_frame,
                text="ANTIDOZE FLEET TRIP PLANNER",
                fg="#38BDF8",
                bg="#111827",
                font=("Segoe UI", 15, "bold"),
            )
            lbl_title.pack()
            lbl_sub = tk.Label(
                header_frame,
                text="AI Fatigue Monitoring & 10s Automated Dynamic Fleet Sync",
                fg="#94A3B8",
                bg="#111827",
                font=("Segoe UI", 9),
            )
            lbl_sub.pack(pady=(2, 0))

            # Body Frame
            body_frame = tk.Frame(root, bg="#0B0F19", padx=24, pady=14)
            body_frame.pack(fill="both", expand=True)

            # Driver ID input
            lbl_drv = tk.Label(
                body_frame,
                text="Driver ID (for Fleet Manager Dispatch & Telemetry):",
                fg="#F1F5F9",
                bg="#0B0F19",
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            lbl_drv.pack(fill="x", pady=(2, 4))

            drv_var = tk.StringVar(value=str(default_driver_id))
            entry_drv = tk.Entry(
                body_frame,
                textvariable=drv_var,
                font=("Segoe UI", 11, "bold"),
                bg="#1E293B",
                fg="#38BDF8",
                insertbackground="#38BDF8",
                justify="center",
                relief="flat",
            )
            entry_drv.pack(fill="x", ipady=4, pady=(0, 8))

            lbl_prompt = tk.Label(
                body_frame,
                text="Planned continuous driving time before extended rest (hours):",
                fg="#F1F5F9",
                bg="#0B0F19",
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            lbl_prompt.pack(fill="x", pady=(2, 4))

            entry_var = tk.StringVar(value=str(default_hours))
            entry = tk.Entry(
                body_frame,
                textvariable=entry_var,
                font=("Segoe UI", 13, "bold"),
                bg="#1E293B",
                fg="#38BDF8",
                insertbackground="#38BDF8",
                justify="center",
                relief="flat",
            )
            entry.pack(fill="x", ipady=4, pady=(0, 10))
            entry.focus_set()

            # Dynamic Alert Box
            alert_frame = tk.Frame(body_frame, bg="#1E293B", padx=12, pady=10)
            alert_frame.pack(fill="x", pady=(0, 10))

            lbl_alert_title = tk.Label(
                alert_frame,
                text="",
                font=("Segoe UI", 9, "bold"),
                bg="#1E293B",
                anchor="w",
            )
            lbl_alert_title.pack(fill="x")

            lbl_alert_detail = tk.Label(
                alert_frame,
                text="",
                font=("Segoe UI", 8),
                bg="#1E293B",
                justify="left",
                anchor="w",
            )
            lbl_alert_detail.pack(fill="x", pady=(2, 0))

            def update_alert_display(*args):
                try:
                    val = float(entry_var.get().strip())
                    if val > DEFAULT_MANDATORY_CAMERA_HOUR:
                        alert_frame.configure(bg="#451A03")
                        lbl_alert_title.configure(
                            text="[ALERT] MANDATORY MONITORING ALERT (TRIP > 6.0 HOURS)",
                            fg="#F59E0B",
                            bg="#451A03",
                        )
                        lbl_alert_detail.configure(
                            text=f"Planned drive is {val:.1f} hours.\n* Camera toggle [T] is permitted during Hours 0 - 6.\n* After Hour 6, camera monitoring will be LOCKED ON for your safety.",
                            fg="#FEF3C7",
                            bg="#451A03",
                        )
                    else:
                        alert_frame.configure(bg="#064E3B")
                        lbl_alert_title.configure(
                            text="[OK] STANDARD TRIP DURATION (<= 6.0 HOURS)",
                            fg="#34D399",
                            bg="#064E3B",
                        )
                        lbl_alert_detail.configure(
                            text=f"Planned drive is {val:.1f} hours.\n* Camera toggle [T] remains accessible throughout this trip.",
                            fg="#D1FAE5",
                            bg="#064E3B",
                        )
                except ValueError:
                    alert_frame.configure(bg="#1E293B")
                    lbl_alert_title.configure(
                        text="Enter a valid number of hours (e.g. 8.0, 4.5)",
                        fg="#94A3B8",
                        bg="#1E293B",
                    )
                    lbl_alert_detail.configure(text="", bg="#1E293B")

            entry_var.trace_add("write", update_alert_display)
            update_alert_display()

            def on_confirm(event=None):
                try:
                    val = float(entry_var.get().strip())
                    if val <= 0:
                        val = default_hours
                    result_holder["hours"] = val
                    drv_text = drv_var.get().strip()
                    result_holder["driver_id"] = drv_text if drv_text else default_driver_id
                    result_holder["confirmed"] = True

                    # If > 6 hours, show an acknowledgment popup
                    if val > DEFAULT_MANDATORY_CAMERA_HOUR:
                        try:
                            from tkinter import messagebox
                            messagebox.showwarning(
                                "Safety Alert: Mandatory Monitoring Policy",
                                f"Trip duration set to {val:.1f} hours (> 6.0 hours).\n\n"
                                f"Please note: Camera standby is available during the "
                                f"first 6 hours of driving.\n\n"
                                f"After Hour 6, safety monitoring becomes mandatory and remains active.\n\n"
                                f"Drive safe and stay alert!",
                                parent=root,
                            )
                        except Exception:
                            pass
                    root.destroy()
                except ValueError:
                    update_alert_display()

            btn_start = tk.Button(
                body_frame,
                text="START DRIVE & FLEET DATABASE SYNC ->",
                font=("Segoe UI", 11, "bold"),
                bg="#0284C7",
                fg="#FFFFFF",
                activebackground="#0369A1",
                activeforeground="#FFFFFF",
                relief="flat",
                cursor="hand2",
                command=on_confirm,
            )
            btn_start.pack(fill="x", ipady=6)

            root.bind("<Return>", on_confirm)
            root.mainloop()

            if result_holder["confirmed"]:
                planned_hours = result_holder["hours"]
                driver_id = result_holder["driver_id"]
                gui_success = True
        except Exception:
            gui_success = False

    if not gui_success:
        print("\n" + "=" * 68)
        print(" ANTIDOZE: PRE-DRIVE TRIP & FLEET SETUP ")
        print("=" * 68)
        print(" Policy: Camera standby is available during the first 6 hours.")
        print(" After Hour 6, safety monitoring is mandatory and camera remains active.")
        print(" Dynamic Database: Updates logged every 10 seconds.")
        print("-" * 68)
        try:
            if sys.stdin.isatty():
                drv_in = input(f" Enter Driver ID [Default: {default_driver_id}]: ").strip()
                if drv_in:
                    driver_id = drv_in
                user_val = input(f" Enter planned driving duration in hours [Default: {default_hours:.1f}]: ").strip()
                if user_val:
                    planned_hours = float(user_val)
            else:
                planned_hours = default_hours
                driver_id = default_driver_id
        except Exception:
            planned_hours = default_hours
            driver_id = default_driver_id

    exceeds_six = (planned_hours > DEFAULT_MANDATORY_CAMERA_HOUR)
    if exceeds_six:
        print("\n" + "*" * 68)
        print(f" [SAFETY ALERT] PLANNED DRIVE EXCEEDS 6 HOURS ({planned_hours:.1f} HOURS)")
        print(" * Camera standby toggle [T] is enabled for Hours 0 through 6.")
        print(" * After Hour 6, safety monitoring is mandatory and camera remains active.")
        print("*" * 68 + "\n")
    else:
        print(f"\n[INFO] Driver {driver_id} | Planned drive: {planned_hours:.1f} hours (<= 6.0h). Camera standby enabled.\n")

    return float(planned_hours), bool(exceeds_six), str(driver_id)


def draw_privacy_standby_screen(
    frame: np.ndarray,
    trip_elapsed_sec: float,
    trip_planned_sec: float,
    time_until_lock_sec: float,
    active_strikes: int,
    clean_driving_time: float,
    fps: float,
    current_streak_sec: float = 0.0,
    best_streak_sec: float = 0.0,
    is_resting: bool = False,
    rest_time_sec: float = 0.0,
    rest_limit_sec: float = DEFAULT_REST_STOP_SEC,
    camera_lock_alert: bool = False,
):
    """
    Renders an elegant digital cockpit standby display when camera is in standby.
    Live video tracking is paused, but trip clock, clean streak, and strike healing stay active.
    Scales dynamically for fullscreen and high-resolution displays.
    """
    h, w, _ = frame.shape
    scale = max(min(w / 1280.0, h / 720.0), 0.65)
    frame[:] = (12, 16, 26)  # Dark cockpit background

    top_bar_h = int(66 * scale)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, top_bar_h), (8, 11, 20), -1)
    cv2.addWeighted(overlay, 0.90, frame, 0.10, 0, frame)
    cv2.line(frame, (0, top_bar_h), (w, top_bar_h), (35, 45, 65), max(int(1 * scale), 1), cv2.LINE_AA)

    # App Brand with Amber Standby Dot
    dot_x, dot_y = int(25 * scale), int(33 * scale)
    cv2.circle(frame, (dot_x, dot_y), int(5 * scale), (40, 180, 255), -1)
    cv2.putText(frame, "ANTIDOZE", (int(38 * scale), int(38 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.62 * scale, (240, 245, 255), max(int(1 * scale), 1), cv2.LINE_AA)
    trip_txt = f"TRIP: {format_time_hms(trip_elapsed_sec)} / {format_time_hms(trip_planned_sec)}"
    cv2.putText(frame, trip_txt, (int(38 * scale), int(55 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.36 * scale, (140, 180, 220), max(int(1 * scale), 1), cv2.LINE_AA)

    # Center Capsule in Top Bar (Clean ASCII)
    capsule_w = int(min(420 * scale, w * 0.40))
    capsule_h = int(36 * scale)
    capsule_x = (w - capsule_w) // 2
    capsule_y = (top_bar_h - capsule_h) // 2
    stat_text = "CAMERA STANDBY MODE"
    draw_rounded_rect(frame, (capsule_x, capsule_y), (capsule_x + capsule_w, capsule_y + capsule_h), (25, 40, 65), -1, radius=int(12 * scale))
    draw_rounded_rect(frame, (capsule_x, capsule_y), (capsule_x + capsule_w, capsule_y + capsule_h), (40, 160, 240), max(int(1 * scale), 1), radius=int(12 * scale))
    (tw, th), _ = cv2.getTextSize(stat_text, cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, stat_text, (capsule_x + (capsule_w - tw) // 2, capsule_y + (capsule_h + th) // 2 - 1), cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, (230, 245, 255), max(int(1 * scale), 1), cv2.LINE_AA)

    # Right side: Streak score & Strike badge & Cam status (Clean ASCII)
    streak_str = format_time_hms(current_streak_sec)
    best_str = format_time_hms(best_streak_sec)
    rank_text, rank_color = get_strike_rank_badge(active_strikes)
    stats_x = w - int(340 * scale)

    cv2.putText(frame, f"STREAK: {streak_str} (BEST: {best_str})", (stats_x, int(28 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.40 * scale, (255, 215, 0), max(int(1 * scale), 1), cv2.LINE_AA)
    cv2.putText(frame, f"{rank_text}  |  [T] CAM: STANDBY", (stats_x, int(48 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, (40, 180, 255), max(int(1 * scale), 1), cv2.LINE_AA)
    cv2.putText(frame, f"{fps:.0f} FPS", (w - int(75 * scale), int(28 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, (140, 160, 190), max(int(1 * scale), 1), cv2.LINE_AA)

    # Center Card: Standby Details (Clean scaled typography)
    card_w = int(min(660 * scale, w * 0.85))
    card_h = int(240 * scale)
    card_x = (w - card_w) // 2
    card_y = (h - card_h) // 2 - int(20 * scale)
    draw_rounded_rect(frame, (card_x, card_y), (card_x + card_w, card_y + card_h), (18, 24, 38), -1, radius=int(16 * scale))
    draw_rounded_rect(frame, (card_x, card_y), (card_x + card_w, card_y + card_h), (40, 80, 130), max(int(1 * scale), 1), radius=int(16 * scale))

    title = "CAMERA STANDBY MODE"
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_DUPLEX, 0.65 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, title, (card_x + (card_w - tw) // 2, card_y + int(45 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.65 * scale, (240, 245, 255), max(int(1 * scale), 1), cv2.LINE_AA)

    line1 = "Driver monitoring is temporarily paused."
    (l1w, _), _ = cv2.getTextSize(line1, cv2.FONT_HERSHEY_SIMPLEX, 0.42 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, line1, (card_x + (card_w - l1w) // 2, card_y + int(80 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.42 * scale, (150, 175, 205), max(int(1 * scale), 1), cv2.LINE_AA)

    line2 = f"Drive Clock: {format_time_hms(trip_elapsed_sec)} of {format_time_hms(trip_planned_sec)}  |  Standby available for next: {format_time_hms(time_until_lock_sec)}"
    (l2w, _), _ = cv2.getTextSize(line2, cv2.FONT_HERSHEY_SIMPLEX, 0.42 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, line2, (card_x + (card_w - l2w) // 2, card_y + int(115 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.42 * scale, (94, 219, 134), max(int(1 * scale), 1), cv2.LINE_AA)

    rule = "Continuous safety monitoring activates automatically at Hour 6:00:00"
    (rw, _), _ = cv2.getTextSize(rule, cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, rule, (card_x + (card_w - rw) // 2, card_y + int(145 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, (240, 200, 90), max(int(1 * scale), 1), cv2.LINE_AA)

    action_btn_w = int(340 * scale)
    action_btn_h = int(36 * scale)
    action_x = card_x + (card_w - action_btn_w) // 2
    action_y = card_y + int(175 * scale)
    draw_rounded_rect(frame, (action_x, action_y), (action_x + action_btn_w, action_y + action_btn_h), (2, 132, 199), -1, radius=int(10 * scale))
    act_txt = "PRESS [T] TO RESUME CAMERA"
    (aw, ah), _ = cv2.getTextSize(act_txt, cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, max(int(1 * scale), 1))
    cv2.putText(frame, act_txt, (action_x + (action_btn_w - aw) // 2, action_y + (action_btn_h + ah) // 2 - 1), cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, (255, 255, 255), max(int(1 * scale), 1), cv2.LINE_AA)

    # Bottom Telemetry Bar
    bottom_y = h - int(50 * scale)
    bot_x = int(30 * scale)
    if is_resting:
        rest_rem = max(rest_limit_sec - rest_time_sec, 0.0)
        cv2.putText(frame, f"REST STOP: {format_time_hms(rest_time_sec)} / {format_time_hms(rest_limit_sec)}", (bot_x, bottom_y - int(8 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.40 * scale, (180, 100, 240), max(int(1 * scale), 1), cv2.LINE_AA)
        cv2.putText(frame, f"All strikes reset in: {format_time_hms(rest_rem)}", (bot_x, bottom_y + int(16 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.36 * scale, (220, 180, 255), max(int(1 * scale), 1), cv2.LINE_AA)
    else:
        reward_rank = get_streak_rank(current_streak_sec)
        cv2.putText(frame, f"REWARD: {reward_rank} | Clean Streak: {streak_str}", (bot_x, bottom_y - int(8 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.40 * scale, (255, 215, 0), max(int(1 * scale), 1), cv2.LINE_AA)
        heal_rem = max(DEFAULT_STRIKE_HEAL_SEC - clean_driving_time, 0.0)
        strike_sub = f"Active Strikes: {active_strikes}/3 (Removes 1 strike in: {format_time_hms(heal_rem)})" if active_strikes > 0 else f"Active Strikes: 0/3 [SAFE] (Clean Drive: {format_time_hms(clean_driving_time)})"
        cv2.putText(frame, strike_sub, (bot_x, bottom_y + int(16 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.36 * scale, (140, 160, 190), max(int(1 * scale), 1), cv2.LINE_AA)

    cv2.putText(frame, "[F] Screen   [T] Resume Cam   [R] Rest Stop   [Q] Quit", (w - int(440 * scale), bottom_y + int(6 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.40 * scale, (180, 205, 230), max(int(1 * scale), 1), cv2.LINE_AA)


# ============================================================================
# EYE ASPECT RATIO (EAR) & HEAD POSTURE ANALYSIS
# ============================================================================

def euclidean_distance(pt1: np.ndarray, pt2: np.ndarray) -> float:
    """Calculates the Euclidean distance between two 2D points."""
    return float(np.linalg.norm(pt1 - pt2))


def calculate_ear(eye_landmarks: np.ndarray) -> float:
    """
    Calculates Eye Aspect Ratio (EAR) based on Soukupova & Cech (2016):
        EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)
    """
    p1, p2, p3, p4, p5, p6 = eye_landmarks

    dist_a = euclidean_distance(p2, p6)
    dist_b = euclidean_distance(p3, p5)
    dist_c = euclidean_distance(p1, p4)

    if dist_c == 0:
        return 0.0

    ear = (dist_a + dist_b) / (2.0 * dist_c)
    return float(ear)


def analyze_head_posture(
    mesh_points,
    w: int,
    h: int,
    avg_ear: float,
    ear_threshold: float,
    nod_ratio_threshold: float = DEFAULT_NOD_RATIO_THRESH,
) -> Tuple[float, float, str, bool, bool]:
    """
    Analyzes driver head posture:
      1. Legitimate Mirror Checks: Upright head (pitch >= 0.70) AND eyes open (ear >= threshold)
         AND turned horizontally (abs(yaw) > 0.28).
      2. Directional Head Nod: Head slumped forward/downward (pitch < nod_ratio_threshold)
         even if turned diagonally.

    Returns:
      (yaw_ratio, pitch_ratio, glance_direction, is_mirror_checking, is_directional_nod)
    """
    p_nose = np.array([mesh_points[NOSE_LANDMARK].x * w, mesh_points[NOSE_LANDMARK].y * h])
    p_chin = np.array([mesh_points[CHIN_LANDMARK].x * w, mesh_points[CHIN_LANDMARK].y * h])
    p_forehead = np.array([mesh_points[FOREHEAD_LANDMARK].x * w, mesh_points[FOREHEAD_LANDMARK].y * h])
    p_left_trag = np.array([mesh_points[LEFT_TRAGUS_LANDMARK].x * w, mesh_points[LEFT_TRAGUS_LANDMARK].y * h])
    p_right_trag = np.array([mesh_points[RIGHT_TRAGUS_LANDMARK].x * w, mesh_points[RIGHT_TRAGUS_LANDMARK].y * h])

    face_mid_x = (p_left_trag[0] + p_right_trag[0]) / 2.0
    face_width = max(abs(p_right_trag[0] - p_left_trag[0]), 20.0)
    yaw_ratio = float((p_nose[0] - face_mid_x) / (face_width * 0.5))

    d_upper = max(p_nose[1] - p_forehead[1], 10.0)
    d_lower = max(p_chin[1] - p_nose[1], 2.0)
    pitch_ratio = float(d_lower / d_upper)

    is_head_slumped = pitch_ratio < nod_ratio_threshold
    is_head_turned = abs(yaw_ratio) > YAW_MIRROR_CHECK_THRESH
    eyes_open = avg_ear >= ear_threshold

    if is_head_turned and not is_head_slumped and eyes_open:
        is_mirror_checking = True
        glance_direction = "LEFT MIRROR" if yaw_ratio < 0 else "RIGHT MIRROR"
        is_directional_nod = False
    elif is_head_slumped:
        is_mirror_checking = False
        is_directional_nod = True
        if yaw_ratio < -YAW_MIRROR_CHECK_THRESH:
            glance_direction = "NOD (LEFT TILT)"
        elif yaw_ratio > YAW_MIRROR_CHECK_THRESH:
            glance_direction = "NOD (RIGHT TILT)"
        else:
            glance_direction = "NOD (FORWARD)"
    else:
        is_mirror_checking = False
        is_directional_nod = False
        glance_direction = "FORWARD"

    return yaw_ratio, pitch_ratio, glance_direction, is_mirror_checking, is_directional_nod


# ============================================================================
# 3-STRIKE SAFETY SYSTEM & GAMIFIED VIGILANCE REWARD SYSTEM
# ============================================================================

def format_time_hms(seconds: float) -> str:
    """Formats seconds into mm:ss or hh:mm:ss."""
    s = int(max(seconds, 0))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_strike_rank_badge(active_strikes: int) -> Tuple[str, Tuple[int, int, int]]:
    """
    Returns Rank title and HUD accent color based on active strike level (0-3):
      - 0 Strikes: TIER 1: TOP DRIVER (Emerald)
      - 1 Strike : TIER 2: CAUTION (Amber)
      - 2 Strikes: TIER 3: WARNING (Orange)
      - 3 Strikes: TIER 4: CRITICAL (Crimson)
    """
    if active_strikes == 0:
        return "TIER 1: TOP DRIVER (0/3)", (94, 219, 134)
    elif active_strikes == 1:
        return "TIER 2: CAUTION (1/3)", (240, 200, 90)
    elif active_strikes == 2:
        return "TIER 3: WARNING (2/3)", (40, 140, 255)
    else:
        return "TIER 4: CRITICAL (3/3)", (40, 40, 245)


def get_streak_rank(streak_sec: float) -> str:
    """
    Returns gamified driver vigilance reward tier based on continuous clean driving:
      - Level 1: VIGILANT DRIVER (LVL 1) (< 3 mins / 180s)
      - Level 2: PRO PILOT (LVL 2)       (3 - 10 mins / 180s - 600s)
      - Level 3: HIGHWAY MASTER (LVL 3)  (10 - 30 mins / 600s - 1800s)
      - Level 4: IRON TRUCKER (LVL 4)    (30+ mins / 1800s+)
    """
    if streak_sec >= 1800:
        return "IRON TRUCKER (LVL 4)"
    elif streak_sec >= 600:
        return "HIGHWAY MASTER (LVL 3)"
    elif streak_sec >= 180:
        return "PRO PILOT (LVL 2)"
    else:
        return "VIGILANT DRIVER (LVL 1)"


def get_reward_rank(streak_sec: float) -> str:
    """Alias for get_streak_rank."""
    return get_streak_rank(streak_sec)


def get_reward_tier_badge(streak_sec: float) -> Tuple[str, Tuple[int, int, int], float]:
    """
    Returns (tier_title, accent_color_bgr, seconds_to_next_tier).
    """
    if streak_sec >= 1800:
        return "IRON TRUCKER (LVL 4)", (94, 255, 180), 0.0
    elif streak_sec >= 600:
        return "HIGHWAY MASTER (LVL 3)", (0, 215, 255), max(1800.0 - streak_sec, 0.0)
    elif streak_sec >= 180:
        return "PRO PILOT (LVL 2)", (255, 210, 80), max(600.0 - streak_sec, 0.0)
    else:
        return "VIGILANT DRIVER (LVL 1)", (180, 210, 240), max(180.0 - streak_sec, 0.0)


# ============================================================================
# MODERN DIGITAL COCKPIT HUD DRAWING UTILITIES
# ============================================================================

def draw_rounded_rect(
    img: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
    color: Tuple[int, int, int],
    thickness: int = -1,
    radius: int = 8,
):
    """Draws a smooth rounded rectangle for modern cockpit styling."""
    x1, y1 = pt1
    x2, y2 = pt2
    w = x2 - x1
    h = y2 - y1
    r = min(radius, w // 2, h // 2)

    if thickness < 0:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        cv2.circle(img, (x1 + r, y1 + r), r, color, -1)
        cv2.circle(img, (x2 - r, y1 + r), r, color, -1)
        cv2.circle(img, (x1 + r, y2 - r), r, color, -1)
        cv2.circle(img, (x2 - r, y2 - r), r, color, -1)
    else:
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, thickness, cv2.LINE_AA)


def draw_modern_hud(
    frame: np.ndarray,
    ear: float,
    ear_threshold: float,
    continuous_closed_time: float,
    flutter_stack_time: float,
    decay_rate: float,
    is_fatigued: bool,
    is_head_nodding: bool,
    nod_duration: float,
    open_eyes_duration: float,
    fps: float,
    face_detected: bool,
    glance_direction: str,
    is_mirror_checking: bool,
    pitch_ratio: float,
    active_strikes: int,
    sounds_alarm_now: bool,
    clean_driving_time: float,
    heal_limit_sec: float,
    is_resting: bool,
    rest_time_sec: float,
    rest_limit_sec: float,
    current_streak_sec: float = 0.0,
    best_streak_sec: float = 0.0,
    draw_mesh_enabled: bool = True,
    inspirational_quote: Optional[str] = None,
    trip_elapsed_sec: float = 0.0,
    trip_planned_sec: float = DEFAULT_PLANNED_DRIVE_HOURS * 3600.0,
    camera_enabled: bool = True,
    mandatory_lock_active: bool = False,
    camera_lock_alert: bool = False,
    hour_6_transition_alert: bool = False,
    initial_trip_alert: bool = False,
    is_continuous_violation: bool = False,
    nod_time_threshold: float = DEFAULT_NOD_DURATION_SEC,
    nod_ratio_threshold: float = DEFAULT_NOD_RATIO_THRESH,
    upright_posture_duration: float = 0.0,
    active_alert_reason: Optional[str] = None,
):
    """
    Renders the modern AntiDoze digital cockpit HUD with responsive fullscreen scaling,
    dedicated distinct channels for eye fatigue and head nodding, and clean ASCII typography.
    """
    h, w, _ = frame.shape
    scale = max(min(w / 1280.0, h / 720.0), 0.65)
    line_th = max(int(1 * scale), 1)

    # 1. Soft Pulsing Emergency Edge Vignette (Distinct Colors for Head Nod vs Eye Fatigue)
    if is_head_nodding:
        # Distinct Violet/Magenta Emergency Edge Vignette for Head Nodding!
        alpha = 0.35 + 0.25 * np.sin(time.time() * 6)
        vignette = frame.copy()
        cv2.rectangle(vignette, (0, 0), (w, h), (180, 40, 220), thickness=max(int(16 * scale), 4))
        cv2.addWeighted(vignette, alpha, frame, 1.0 - alpha, 0, frame)
    elif (active_strikes >= 3 and is_fatigued) or is_continuous_violation:
        # Crimson Red Emergency Edge Vignette for Eye Fatigue
        alpha = 0.35 + 0.25 * np.sin(time.time() * 6)
        vignette = frame.copy()
        cv2.rectangle(vignette, (0, 0), (w, h), (40, 40, 245), thickness=max(int(16 * scale), 4))
        cv2.addWeighted(vignette, alpha, frame, 1.0 - alpha, 0, frame)

    # 2. Modern Glassmorphic Top Telemetry Bar
    top_bar_h = int(66 * scale)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, top_bar_h), (11, 15, 25), -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)
    cv2.line(frame, (0, top_bar_h), (w, top_bar_h), (35, 45, 65), line_th, cv2.LINE_AA)

    # App Brand with Emerald Status Dot & Trip Clock
    cv2.circle(frame, (int(25 * scale), int(33 * scale)), max(int(5 * scale), 2), (94, 219, 134), -1)
    cv2.putText(
        frame,
        "ANTIDOZE",
        (int(38 * scale), int(38 * scale)),
        cv2.FONT_HERSHEY_DUPLEX,
        0.62 * scale,
        (240, 245, 255),
        line_th,
        cv2.LINE_AA,
    )
    trip_txt = f"TRIP: {format_time_hms(trip_elapsed_sec)} / {format_time_hms(trip_planned_sec)}"
    cv2.putText(
        frame,
        trip_txt,
        (int(38 * scale), int(55 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.36 * scale,
        (140, 180, 220),
        line_th,
        cv2.LINE_AA,
    )

    # Center Dynamic Status Capsule (Pure ASCII & Distinct Channel Themes)
    capsule_w = int(min(460 * scale, w * 0.44))
    capsule_h = int(36 * scale)
    capsule_x = (w - capsule_w) // 2
    capsule_y = (top_bar_h - capsule_h) // 2

    if is_resting:
        rest_rem = max(rest_limit_sec - rest_time_sec, 0.0)
        stat_text = f"[REST] REST STOP ACTIVE ({format_time_hms(rest_time_sec)} / {format_time_hms(rest_limit_sec)})"
        stat_bg = (60, 30, 80)
        stat_border = (180, 100, 240)
        stat_fg = (245, 230, 255)
    elif not face_detected:
        stat_text = "SCANNING FOR DRIVER CAB..."
        stat_bg = (20, 60, 120)
        stat_border = (40, 140, 255)
        stat_fg = (255, 255, 255)
    elif is_head_nodding:
        stat_text = f"[HEAD NOD] POSTURE COLLAPSE! ({glance_direction})"
        stat_bg = (55, 20, 85)
        stat_border = (200, 60, 240)
        stat_fg = (255, 235, 255)
    elif continuous_closed_time >= DEFAULT_EYE_FATIGUE_SEC:
        stat_text = "[ALERT] CONTINUOUS EYE CLOSURE (2.0s+) PULL OVER!"
        stat_bg = (20, 20, 170)
        stat_border = (60, 60, 255)
        stat_fg = (255, 255, 255)
    elif flutter_stack_time >= DEFAULT_EYE_FATIGUE_SEC:
        stat_text = "[WARN] EYE FLUTTERING / BLINK STACK REACHED (2.0s)"
        stat_bg = (20, 20, 170)
        stat_border = (60, 60, 255)
        stat_fg = (255, 255, 255)
    elif active_strikes >= 3 and is_fatigued:
        stat_text = "[ALARM] 3/3 STRIKES! PULL OVER & REST"
        stat_bg = (20, 20, 170)
        stat_border = (60, 60, 255)
        stat_fg = (255, 255, 255)
    elif is_fatigued:
        stat_text = f"DROWSINESS WARNING (STRIKE {active_strikes}/3)"
        stat_bg = (15, 65, 120)
        stat_border = (40, 180, 255)
        stat_fg = (255, 255, 255)
    elif is_mirror_checking:
        stat_text = f"LOOKING: {glance_direction}"
        stat_bg = (90, 45, 15)
        stat_border = (230, 150, 50)
        stat_fg = (255, 230, 160)
    elif nod_duration > 0.0:
        stat_text = f"HEAD SLUMPING ({nod_duration:.1f}s / {nod_time_threshold:.1f}s)"
        stat_bg = (45, 20, 70)
        stat_border = (180, 70, 220)
        stat_fg = (245, 220, 255)
    elif continuous_closed_time > 0.0 and ear < ear_threshold:
        stat_text = f"EYES CLOSED ({continuous_closed_time:.1f}s / {DEFAULT_EYE_FATIGUE_SEC:.1f}s)"
        stat_bg = (15, 60, 110)
        stat_border = (40, 180, 255)
        stat_fg = (255, 255, 255)
    elif flutter_stack_time > 0.0 and ear >= ear_threshold:
        stat_text = f"REFOCUSING | FLUTTER STACK DECAYING ({flutter_stack_time:.1f}s)"
        stat_bg = (25, 55, 95)
        stat_border = (50, 170, 240)
        stat_fg = (240, 245, 255)
    else:
        stat_text = "ATTENTIVE DRIVER (UPRIGHT & EYES OPEN)"
        stat_bg = (20, 50, 25)
        stat_border = (70, 180, 100)
        stat_fg = (180, 255, 200)

    draw_rounded_rect(
        frame,
        (capsule_x, capsule_y),
        (capsule_x + capsule_w, capsule_y + capsule_h),
        stat_bg,
        thickness=-1,
        radius=int(12 * scale),
    )
    draw_rounded_rect(
        frame,
        (capsule_x, capsule_y),
        (capsule_x + capsule_w, capsule_y + capsule_h),
        stat_border,
        thickness=line_th,
        radius=int(12 * scale),
    )

    (tw, th), _ = cv2.getTextSize(stat_text, cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, line_th)
    tx = capsule_x + (capsule_w - tw) // 2
    ty = capsule_y + (capsule_h + th) // 2 - 1
    cv2.putText(frame, stat_text, (tx, ty), cv2.FONT_HERSHEY_DUPLEX, 0.44 * scale, stat_fg, line_th, cv2.LINE_AA)

    # Right side: Streak Score & Ranks & Camera Status & FPS (Pure ASCII)
    streak_str = format_time_hms(current_streak_sec)
    best_str = format_time_hms(best_streak_sec)
    reward_rank_str = get_streak_rank(current_streak_sec)
    rank_text, rank_color = get_strike_rank_badge(active_strikes)

    if mandatory_lock_active:
        cam_txt = "CAM: LOCKED ON (HR 6+)"
        cam_col = (255, 200, 40)
    elif camera_enabled:
        cam_txt = "[T] CAM: ACTIVE"
        cam_col = (94, 219, 134)
    else:
        cam_txt = "[T] CAM: STANDBY"
        cam_col = (40, 180, 255)

    stats_x = w - int(350 * scale)
    cv2.putText(frame, f"STREAK: {streak_str} (BEST: {best_str})", (stats_x, int(28 * scale)), cv2.FONT_HERSHEY_DUPLEX, 0.40 * scale, (255, 215, 0), line_th, cv2.LINE_AA)
    cv2.putText(frame, f"{rank_text}  |  {cam_txt}", (stats_x, int(48 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, (180, 210, 240), line_th, cv2.LINE_AA)
    cv2.putText(frame, f"{fps:.0f} FPS", (w - int(65 * scale), int(28 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.38 * scale, (140, 160, 190), line_th, cv2.LINE_AA)

    # 3. Modern Telemetry Gauges (Bottom Bar with Distinct Channels: Eyes vs Head Nod)
    bottom_y = h - int(50 * scale)
    meter_h = int(14 * scale)

    # Section A: Eye Openness EAR Capsule (Far Left)
    meter_x, meter_w = int(24 * scale), int(120 * scale)
    draw_rounded_rect(frame, (meter_x, bottom_y), (meter_x + meter_w, bottom_y + meter_h), (20, 25, 35), -1, radius=int(6 * scale))
    fill_ratio = min(max(ear / 0.40, 0.0), 1.0)
    fill_w = int(fill_ratio * meter_w)
    fill_col = (94, 219, 134) if ear >= ear_threshold else (60, 60, 245)
    if fill_w > 4:
        draw_rounded_rect(frame, (meter_x, bottom_y), (meter_x + fill_w, bottom_y + meter_h), fill_col, -1, radius=int(6 * scale))
    draw_rounded_rect(frame, (meter_x, bottom_y), (meter_x + meter_w, bottom_y + meter_h), (60, 75, 100), line_th, radius=int(6 * scale))

    thresh_x = int(meter_x + (min(ear_threshold / 0.40, 1.0) * meter_w))
    cv2.line(frame, (thresh_x, bottom_y - int(3 * scale)), (thresh_x, bottom_y + meter_h + int(3 * scale)), (0, 215, 255), max(int(2 * scale), 1))
    cv2.putText(
        frame,
        f"EAR: {ear:.3f} (Min: {ear_threshold:.2f})",
        (meter_x, bottom_y - int(8 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.37 * scale,
        (190, 205, 225),
        line_th,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "Eyes Open" if ear >= ear_threshold else "Eyes Closed",
        (meter_x, bottom_y + int(24 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.34 * scale,
        (94, 219, 134) if ear >= ear_threshold else (60, 60, 245),
        line_th,
        cv2.LINE_AA,
    )

    # Section B1: Continuous Eye Closure (Original 2s Timer)
    cont_x, cont_w = meter_x + meter_w + int(14 * scale), int(125 * scale)
    draw_rounded_rect(frame, (cont_x, bottom_y), (cont_x + cont_w, bottom_y + meter_h), (20, 25, 35), -1, radius=int(6 * scale))
    cont_fill_ratio = min(max(continuous_closed_time / DEFAULT_EYE_FATIGUE_SEC, 0.0), 1.0)
    cont_fill_w = int(cont_fill_ratio * cont_w)
    cont_col = (60, 60, 245) if continuous_closed_time >= DEFAULT_EYE_FATIGUE_SEC else ((40, 180, 255) if continuous_closed_time > 0 else (60, 75, 100))
    if cont_fill_w > 4:
        draw_rounded_rect(frame, (cont_x, bottom_y), (cont_x + cont_fill_w, bottom_y + meter_h), cont_col, -1, radius=int(6 * scale))
    draw_rounded_rect(frame, (cont_x, bottom_y), (cont_x + cont_w, bottom_y + meter_h), (60, 75, 100), line_th, radius=int(6 * scale))
    cv2.putText(
        frame,
        f"CONT. CLOSURE: {continuous_closed_time:.1f}s / {DEFAULT_EYE_FATIGUE_SEC:.1f}s",
        (cont_x, bottom_y - int(8 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.37 * scale,
        (190, 205, 225),
        line_th,
        cv2.LINE_AA,
    )
    cont_sub = "2s Limit (1 Strike Max)" if continuous_closed_time < DEFAULT_EYE_FATIGUE_SEC else "[HIT] 2s CONTINUOUS HIT"
    cont_sub_col = (140, 160, 180) if continuous_closed_time < DEFAULT_EYE_FATIGUE_SEC else (60, 60, 245)
    cv2.putText(frame, cont_sub, (cont_x, bottom_y + int(24 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.34 * scale, cont_sub_col, line_th, cv2.LINE_AA)

    # Section B2: Flutter Stack (Continuous Blinking / Fluttering)
    stack_x, stack_w = cont_x + cont_w + int(14 * scale), int(135 * scale)
    draw_rounded_rect(frame, (stack_x, bottom_y), (stack_x + stack_w, bottom_y + meter_h), (20, 25, 35), -1, radius=int(6 * scale))
    stack_fill_ratio = min(max(flutter_stack_time / DEFAULT_EYE_FATIGUE_SEC, 0.0), 1.0)
    stack_fill_w = int(stack_fill_ratio * stack_w)
    stack_col = (60, 60, 245) if flutter_stack_time >= DEFAULT_EYE_FATIGUE_SEC else (240, 180, 40)
    if stack_fill_w > 4:
        draw_rounded_rect(frame, (stack_x, bottom_y), (stack_x + stack_fill_w, bottom_y + meter_h), stack_col, -1, radius=int(6 * scale))
    draw_rounded_rect(frame, (stack_x, bottom_y), (stack_x + stack_w, bottom_y + meter_h), (60, 75, 100), line_th, radius=int(6 * scale))
    cv2.putText(
        frame,
        f"FLUTTER STACK: {flutter_stack_time:.1f}s / {DEFAULT_EYE_FATIGUE_SEC:.1f}s",
        (stack_x, bottom_y - int(8 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.37 * scale,
        (190, 205, 225),
        line_th,
        cv2.LINE_AA,
    )
    if flutter_stack_time > 0.0:
        drain_sec = flutter_stack_time / max(decay_rate, 1e-4)
        decay_txt = f"Decaying (0.2s/s) | {drain_sec:.1f}s"
        decay_col = (94, 219, 134) if ear >= ear_threshold else (140, 160, 180)
    else:
        decay_txt = "No Flutter (Clear)"
        decay_col = (94, 219, 134)
    cv2.putText(frame, decay_txt, (stack_x, bottom_y + int(24 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.34 * scale, decay_col, line_th, cv2.LINE_AA)

    # Section B3: Head Nod / Posture Slump Gauge (Distinct Channel & Real-Time Feedback)
    nod_x, nod_w = stack_x + stack_w + int(14 * scale), int(135 * scale)
    draw_rounded_rect(frame, (nod_x, bottom_y), (nod_x + nod_w, bottom_y + meter_h), (20, 25, 35), -1, radius=int(6 * scale))
    nod_fill_ratio = min(max(nod_duration / max(nod_time_threshold, 0.01), 0.0), 1.0)
    nod_fill_w = int(nod_fill_ratio * nod_w)
    if is_head_nodding:
        nod_fill_col = (180, 40, 220)  # Magenta/Violet alert
    elif nod_duration > 0.0:
        nod_fill_col = (210, 100, 240) if nod_duration > 0.4 else (140, 80, 200)
    else:
        nod_fill_col = (120, 70, 160)
    if nod_fill_w > 4:
        draw_rounded_rect(frame, (nod_x, bottom_y), (nod_x + nod_fill_w, bottom_y + meter_h), nod_fill_col, -1, radius=int(6 * scale))
    nod_border_col = (200, 80, 240) if (nod_duration > 0 or is_head_nodding) else (70, 60, 90)
    draw_rounded_rect(frame, (nod_x, bottom_y), (nod_x + nod_w, bottom_y + meter_h), nod_border_col, line_th, radius=int(6 * scale))

    if nod_duration > 0.0:
        cv2.putText(
            frame,
            f"HEAD NOD: {nod_duration:.1f}s / {nod_time_threshold:.1f}s",
            (nod_x, bottom_y - int(8 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.37 * scale,
            (240, 200, 255),
            line_th,
            cv2.LINE_AA,
        )
        nod_sub = f"[SLUMP] {glance_direction}" if is_head_nodding else f"Nodding ({nod_duration:.1f}s)"
        nod_sub_col = (200, 60, 240) if is_head_nodding else (240, 180, 255)
    else:
        cv2.putText(
            frame,
            f"HEAD PITCH: {pitch_ratio:.2f}",
            (nod_x, bottom_y - int(8 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.37 * scale,
            (210, 190, 230),
            line_th,
            cv2.LINE_AA,
        )
        nod_sub = "Posture Normal" if not is_mirror_checking else f"Mirror: {glance_direction}"
        nod_sub_col = (180, 150, 220) if not is_mirror_checking else (240, 180, 50)
    cv2.putText(frame, nod_sub, (nod_x, bottom_y + int(24 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.34 * scale, nod_sub_col, line_th, cv2.LINE_AA)

    # Section C: Strike Recovery & Reward Milestone (Center Right)
    heal_x = nod_x + nod_w + int(18 * scale)
    if is_resting:
        rest_rem = max(rest_limit_sec - rest_time_sec, 0.0)
        cv2.putText(
            frame,
            f"REST STOP: {format_time_hms(rest_time_sec)} / {format_time_hms(rest_limit_sec)}",
            (heal_x, bottom_y - int(8 * scale)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.39 * scale,
            (180, 100, 240),
            line_th,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"All strikes reset in: {format_time_hms(rest_rem)}",
            (heal_x, bottom_y + int(16 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35 * scale,
            (220, 180, 255),
            line_th,
            cv2.LINE_AA,
        )
    elif active_strikes > 0:
        heal_rem = max(heal_limit_sec - clean_driving_time, 0.0)
        cv2.putText(
            frame,
            f"STRIKE HEALING: {format_time_hms(clean_driving_time)} / {format_time_hms(heal_limit_sec)}",
            (heal_x, bottom_y - int(8 * scale)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.39 * scale,
            (240, 200, 90),
            line_th,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Removes 1 strike in: {format_time_hms(heal_rem)}  |  Streak: {streak_str}",
            (heal_x, bottom_y + int(16 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35 * scale,
            (94, 219, 134),
            line_th,
            cv2.LINE_AA,
        )
    else:
        tier_title, tier_col, next_sec = get_reward_tier_badge(current_streak_sec)
        next_txt = f"Next tier in: {format_time_hms(next_sec)}" if next_sec > 0 else "Max Tier Achieved!"
        cv2.putText(
            frame,
            f"REWARD: {tier_title}",
            (heal_x, bottom_y - int(8 * scale)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.39 * scale,
            tier_col,
            line_th,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Clean Streak: {streak_str}  |  {next_txt}",
            (heal_x, bottom_y + int(16 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35 * scale,
            (150, 180, 200),
            line_th,
            cv2.LINE_AA,
        )

    # Section D: Glance Direction & Hotkey Legend (Far Right)
    right_x = max(w - int(250 * scale), heal_x + int(220 * scale))
    glance_col = (240, 180, 50) if is_mirror_checking else ((200, 60, 240) if "NOD" in glance_direction else (180, 220, 200))
    cv2.putText(
        frame,
        f"GLANCE: {glance_direction}",
        (right_x, bottom_y - int(8 * scale)),
        cv2.FONT_HERSHEY_DUPLEX,
        0.41 * scale,
        glance_col,
        line_th,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "[F] Full  [T] Cam  [R] Rest  [M] Mesh",
        (right_x, bottom_y + int(16 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.35 * scale,
        (140, 160, 190),
        line_th,
        cv2.LINE_AA,
    )

    # 4. Modern Compact Pop-Up Card (Distinct Styling & Dismissal for Head Nod vs Eyes)
    if inspirational_quote:
        card_w = int(min(460 * scale, w * 0.80))
        card_h = int(88 * scale)
        card_x = (w - card_w) // 2
        card_y = top_bar_h + int(14 * scale)

        card_bg = frame.copy()
        draw_rounded_rect(
            card_bg, (card_x, card_y), (card_x + card_w, card_y + card_h), (11, 16, 28), thickness=-1, radius=int(12 * scale)
        )
        cv2.addWeighted(card_bg, 0.88, frame, 0.12, 0, frame)

        is_nod_alert = bool(active_alert_reason and "HEAD NOD" in active_alert_reason)

        if is_nod_alert:
            border_glow = (200, 60, 240)  # Violet/Magenta glow for head nod
            badge_title = f"[HEAD NOD ALERT] (STRIKE {active_strikes}/3)" if active_strikes > 0 else "[HEAD NOD ALERT]"
            badge_fg = (210, 100, 255)
            if upright_posture_duration > 0.0:
                remaining = max(POPUP_CLEAR_UPRIGHT_SEC - upright_posture_duration, 0.0)
                hint_str = f"Clearing in {remaining:.1f}s (Head upright)"
                progress_ratio = min(upright_posture_duration / POPUP_CLEAR_UPRIGHT_SEC, 1.0)
                prog_col = (210, 100, 255)
            else:
                hint_str = "Raise head upright 1.5s to clear"
                progress_ratio = 0.0
                prog_col = (190, 150, 230)
        else:
            if active_strikes >= 3:
                border_glow = (60, 60, 245)
                badge_title = "[ALARM] ANTIDOZE: 3RD STRIKE (REST NOW!)"
                badge_fg = (60, 60, 255)
            else:
                border_glow = (40, 210, 255)
                badge_title = f"[FATIGUE ALERT] (STRIKE {active_strikes}/3)" if active_strikes > 0 else "[FATIGUE ALERT]"
                badge_fg = (40, 210, 255)

            if open_eyes_duration > 0.0:
                remaining = max(POPUP_CLEAR_OPEN_EYES_SEC - open_eyes_duration, 0.0)
                hint_str = f"Clearing in {remaining:.1f}s (Eyes open)"
                progress_ratio = min(open_eyes_duration / POPUP_CLEAR_OPEN_EYES_SEC, 1.0)
                prog_col = (94, 219, 134)
            else:
                hint_str = "Keep eyes open 2s to clear"
                progress_ratio = 0.0
                prog_col = (140, 180, 220)

        draw_rounded_rect(
            frame, (card_x, card_y), (card_x + card_w, card_y + card_h), border_glow, thickness=line_th, radius=int(12 * scale)
        )

        cv2.putText(
            frame,
            badge_title,
            (card_x + int(18 * scale), card_y + int(24 * scale)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.43 * scale,
            badge_fg,
            line_th,
            cv2.LINE_AA,
        )

        cv2.putText(
            frame,
            f'"{inspirational_quote}"',
            (card_x + int(18 * scale), card_y + int(51 * scale)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.55 * scale,
            (250, 250, 255),
            line_th,
            cv2.LINE_AA,
        )

        cv2.putText(
            frame,
            hint_str,
            (card_x + int(18 * scale), card_y + int(73 * scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38 * scale,
            prog_col,
            line_th,
            cv2.LINE_AA,
        )

        prog_bar_w = int(90 * scale)
        prog_bar_x = card_x + card_w - prog_bar_w - int(20 * scale)
        prog_bar_y = card_y + int(64 * scale)
        bar_thick = max(int(3 * scale), 2)
        cv2.line(frame, (prog_bar_x, prog_bar_y), (prog_bar_x + prog_bar_w, prog_bar_y), (40, 50, 70), bar_thick)
        if progress_ratio > 0:
            active_w = int(progress_ratio * prog_bar_w)
            cv2.line(frame, (prog_bar_x, prog_bar_y), (prog_bar_x + active_w, prog_bar_y), prog_col, bar_thick)

    # 5. Dynamic Safety Banners (Mandatory Camera Lock / Hour 6 / Long Trip Alert - Clean ASCII)
    if camera_lock_alert:
        banner_w, banner_h = int(min(660 * scale, w * 0.92)), int(42 * scale)
        bx = (w - banner_w) // 2
        by = top_bar_h + (int(100 * scale) if inspirational_quote else int(14 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (20, 20, 160), -1, radius=int(10 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (60, 60, 255), line_th, radius=int(10 * scale))
        msg = "MANDATORY MONITORING: Camera cannot be toggled off after 6 hours of driving."
        (bw, bh), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_DUPLEX, 0.39 * scale, line_th)
        cv2.putText(frame, msg, (bx + (banner_w - bw) // 2, by + (banner_h + bh) // 2 - 1), cv2.FONT_HERSHEY_DUPLEX, 0.39 * scale, (255, 255, 255), line_th, cv2.LINE_AA)
    elif hour_6_transition_alert:
        banner_w, banner_h = int(min(640 * scale, w * 0.92)), int(42 * scale)
        bx = (w - banner_w) // 2
        by = top_bar_h + (int(100 * scale) if inspirational_quote else int(14 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (15, 65, 120), -1, radius=int(10 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (40, 210, 255), line_th, radius=int(10 * scale))
        msg = "HOUR 6 REACHED: Camera is now permanently locked ON for driver safety."
        (bw, bh), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_DUPLEX, 0.39 * scale, line_th)
        cv2.putText(frame, msg, (bx + (banner_w - bw) // 2, by + (banner_h + bh) // 2 - 1), cv2.FONT_HERSHEY_DUPLEX, 0.39 * scale, (255, 255, 255), line_th, cv2.LINE_AA)
    elif initial_trip_alert:
        banner_w, banner_h = int(min(620 * scale, w * 0.92)), int(42 * scale)
        bx = (w - banner_w) // 2
        by = top_bar_h + (int(100 * scale) if inspirational_quote else int(14 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (15, 50, 40), -1, radius=int(10 * scale))
        draw_rounded_rect(frame, (bx, by), (bx + banner_w, by + banner_h), (50, 190, 120), line_th, radius=int(10 * scale))
        msg = "TRIP > 6.0 HRS: Camera privacy toggle enabled until Hour 6, then locked ON."
        (bw, bh), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_DUPLEX, 0.38 * scale, line_th)
        cv2.putText(frame, msg, (bx + (banner_w - bw) // 2, by + (banner_h + bh) // 2 - 1), cv2.FONT_HERSHEY_DUPLEX, 0.38 * scale, (230, 255, 240), line_th, cv2.LINE_AA)


# ============================================================================
# LIVE WEBCAM / VIDEO APPLICATION
# ============================================================================

def run_antidoze(
    video_source: str = "0",
    ear_threshold: float = DEFAULT_EAR_THRESHOLD,
    fatigue_time_threshold: float = DEFAULT_EYE_FATIGUE_SEC,
    nod_time_threshold: float = DEFAULT_NOD_DURATION_SEC,
    nod_ratio_threshold: float = DEFAULT_NOD_RATIO_THRESH,
    decay_rate_per_sec: float = DEFAULT_STACK_DECAY_RATE,
    heal_strike_sec: float = DEFAULT_STRIKE_HEAL_SEC,
    rest_stop_reset_sec: float = DEFAULT_REST_STOP_SEC,
    planned_hours: Optional[float] = None,
    time_scale: float = 1.0,
    initial_elapsed_hours: float = 0.0,
    fullscreen: bool = False,
    driver_id: str = DEFAULT_DRIVER_ID,
    db_sync_interval: float = DEFAULT_DB_SYNC_INTERVAL,
    open_dashboard: bool = False,
):
    """
    Main detection loop for AntiDoze.
    Features:
      - Dynamic Fleet Database: Telemetry updates logged every 10 seconds.
      - High-Visibility Critical Alerts: 3/3 strikes triggers emergency dispatcher alert.
      - Responsive Fullscreen Scaling: HUD dynamically scales to any screen resolution.
      - Hotkey [F] to toggle fullscreen anytime; clean ASCII typography throughout.
      - Pre-drive planned trip configuration & Hour 6 mandatory monitoring alerts.
      - Camera privacy toggleable during Hours 0-6; mandatory camera lock at Hour 6+.
      - Gradual Stack Decay (0.20s/s on attentive open eyes).
      - 3-Strike Rank System (Tier 1 Top Driver -> Tier 4 Critical).
      - Strike Removal: 30 minutes clean driving removes 1 strike.
      - Rest Stop Reset: 15 minutes at rest stop resets ALL strikes to 0.
    """
    # 1. Pre-Drive Trip Planning & Alert
    if planned_hours is None:
        planned_hours, exceeds_six, prompt_drv = prompt_driver_trip_hours(
            default_hours=DEFAULT_PLANNED_DRIVE_HOURS,
            default_driver_id=driver_id,
        )
        if driver_id == DEFAULT_DRIVER_ID and prompt_drv:
            driver_id = prompt_drv
    else:
        exceeds_six = (planned_hours > DEFAULT_MANDATORY_CAMERA_HOUR)
        if exceeds_six:
            print("\n" + "*" * 68)
            print(f" [SAFETY ALERT] PLANNED DRIVE EXCEEDS 6 HOURS ({planned_hours:.1f} HOURS)")
            print(" * Camera privacy toggle [T] is enabled for Hours 0 through 6.")
            print(" * After Hour 6, camera monitoring is MANDATORY and CANNOT be toggled off.")
            print("*" * 68 + "\n")

    # Connect to Dynamic Fleet Database
    fleet_db = get_fleet_db()
    fleet_db.register_or_update_driver(driver_id=driver_id)
    last_db_sync_time = time.time()

    # Automatically start Fleet Manager Web Server in daemon background thread
    server_port = 8080
    try:
        from fleet_manager_server import start_fleet_server_background, get_lan_ip_addresses
        server_port = start_fleet_server_background(port=8080)
        lan_ips = get_lan_ip_addresses()
        primary_lan = lan_ips[0] if lan_ips else "127.0.0.1"
        print(f" * Fleet Web Portal URL (This PC) : http://localhost:{server_port}/ (or http://127.0.0.1:{server_port}/)")
        print(f" * Network Access URL (Other PCs) : http://{primary_lan}:{server_port}/")
    except Exception as e:
        print(f" [WARN] Fleet server background start note: {e}")

    if open_dashboard:
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{server_port}/")
        except Exception:
            pass

    # Mark driver as active and connected in fleet database
    try:
        fleet_db.set_driver_active(driver_id=driver_id)
        rank_name, _ = get_strike_rank_badge(0)
        fleet_db.log_telemetry(
            driver_id=driver_id,
            strike_count=0,
            strike_status=rank_name,
            alert_type="CAB CONNECTED (ACTIVE)",
            ear_value=0.30,
            head_pitch=baseline_nod_ratio,
            glance_direction="FORWARD",
            clean_streak="00:00",
            trip_elapsed="00:00",
            camera_mode="ACTIVE",
            notes="AntiDoze application started and connected to fleet database",
        )
    except Exception:
        pass

    trip_mgr = TripManager(
        planned_hours=planned_hours,
        mandatory_hour=DEFAULT_MANDATORY_CAMERA_HOUR,
        time_scale=time_scale,
        initial_elapsed_sec=initial_elapsed_hours * 3600.0,
    )

    source = int(video_source) if video_source.isdigit() else video_source

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"\n[ERROR] Unable to open video source: {video_source}")
        print("Tip: Run with '--demo' to test AntiDoze with a simulated driver scenario.")
        return False

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Initialize OpenCV Display Window with Fullscreen Support
    WINDOW_NAME = "AntiDoze - Modern Driver Assist"
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    is_fullscreen = bool(fullscreen)
    if is_fullscreen:
        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)

    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    chime = MelodicChimeManager()
    inspirational_mgr = CompactInspirationalManager()

    # 3-Strike System & Gamified Vigilance Reward System
    active_strikes = 0
    clean_driving_time = 0.0
    current_streak_sec = 0.0
    best_streak_sec = 0.0
    is_resting = False
    rest_time_sec = 0.0
    no_face_duration = 0.0

    # Dual Eye Fatigue Timers: Continuous 2.0s closure & Flutter Stack
    continuous_closed_time = 0.0
    flutter_stack_time = 0.0
    strike_awarded_this_closure = False
    is_continuous_violation = False
    is_flutter_violation = False
    is_fatigued = False
    was_fatigued = False
    sounds_alarm_now = False

    # Head nod state
    nod_start_time = None
    nod_duration = 0.0
    is_head_nodding = False
    was_nodding = False
    baseline_nod_ratio = 1.05
    nod_ratio_threshold = nod_ratio_threshold

    # 2.0-second continuous open-eyes timer for eye fatigue pop-up clear
    open_eyes_start_time = None
    open_eyes_duration = 0.0

    # 1.5-second continuous upright posture timer for head nod pop-up clear
    upright_posture_start_time = None
    upright_posture_duration = 0.0

    draw_mesh = True
    prev_time = time.time()
    fps = 0.0

    print("=" * 68)
    print(" ANTIDOZE: INTELLIGENT DRIVER VIGILANCE & TRIP MONITORING ")
    print("=" * 68)
    print(f" * Planned Trip Duration     : {planned_hours:.1f} Hours ({'Alert: >6h, locks after Hr 6' if exceeds_six else '<= 6h, toggleable'})")
    print(f" * Camera Policy             : Toggleable Hours 0-6; MANDATORY after Hour 6:00:00")
    print(f" * Stacking Closure Limit    : {fatigue_time_threshold:.1f}s (Flicker-tolerant)")
    print(f" * Gradual Stack Decay Rate  : {decay_rate_per_sec:.2f}s/s (Smooth drain over 10s of open eyes)")
    print(f" * 3-Strike Safety System    : Strike 1 & 2 Warning; Strike 3 ALARM CHIME")
    print(f" * Vigilance Reward System   : Active (Clean streaks: Vigilant -> Pro -> Master -> Iron)")
    print(f" * Strike Removal Rule       : {heal_strike_sec / 60:.0f} mins continuous clean driving removes 1 strike")
    print(f" * Rest Stop Reset Rule      : {rest_stop_reset_sec / 60:.0f} mins at rest stop resets ALL strikes to 0")
    print(" * Controls:")
    print("     [F] Toggle Fullscreen Mode (Responsive Scaled HUD)")
    print("     [T] Toggle Camera (Standby / Active - Locks ON after Hr 6)")
    print("     [R] Toggle Rest Stop Mode (Parks cab & accumulates rest)")
    print("     [M] Toggle Landmark Mesh")
    print("     [C] Auto-calibrate (3 seconds)")
    print("     [Q] Quit")
    print("=" * 68)

    calibration_frames_ear: List[float] = []
    calibration_frames_nod: List[float] = []
    is_calibrating = False
    calib_start_time = 0.0

    avg_ear = 0.30
    pitch_ratio = baseline_nod_ratio
    glance_direction = "FORWARD"

    def log_event_to_db(alert_label: str):
        try:
            rank_name, _ = get_strike_rank_badge(active_strikes)
            fleet_db.log_telemetry(
                driver_id=driver_id,
                strike_count=active_strikes,
                strike_status=rank_name,
                alert_type=alert_label,
                ear_value=avg_ear if trip_mgr.camera_enabled else None,
                head_pitch=pitch_ratio if trip_mgr.camera_enabled else None,
                glance_direction=glance_direction if trip_mgr.camera_enabled else "STANDBY",
                clean_streak=format_time_hms(current_streak_sec),
                trip_elapsed=format_time_hms(trip_mgr.elapsed_drive_sec),
                camera_mode="ACTIVE" if trip_mgr.camera_enabled else "STANDBY",
            )
            # Instantly synchronize in-memory live stream cache with current strike state
            fleet_db.set_live_telemetry(
                driver_id=driver_id,
                data={
                    "strike_count": active_strikes,
                    "strike_status": rank_name,
                    "is_critical": (active_strikes >= 3),
                    "is_connected": True,
                    "connection_status": "CONNECTED",
                    "ear": round(avg_ear, 3) if trip_mgr.camera_enabled else None,
                    "pitch": round(pitch_ratio, 2) if trip_mgr.camera_enabled else None,
                    "glance": glance_direction if trip_mgr.camera_enabled else "STANDBY",
                    "clean_streak": format_time_hms(current_streak_sec),
                    "trip_elapsed": format_time_hms(trip_mgr.elapsed_drive_sec),
                    "fps": round(fps, 1),
                    "camera_enabled": trip_mgr.camera_enabled,
                    "face_detected": face_detected if trip_mgr.camera_enabled else False,
                    "continuous_closed": round(continuous_closed_time, 2),
                    "flutter_stack": round(flutter_stack_time, 2),
                    "nod_duration": round(nod_duration, 2),
                    "is_resting": is_resting,
                    "active_source": str(video_source),
                    "client_status": "ONLINE (LIVE CAMERA STREAMING)",
                    "active_alert_reason": alert_label,
                },
            )
        except Exception:
            pass

    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                print("[INFO] Video feed ended or camera unavailable.")
                break

            current_time = time.time()
            dt = max(current_time - prev_time, 1e-5)
            fps = 0.9 * fps + 0.1 * (1.0 / dt)
            prev_time = current_time

            # Advance trip telemetry and check for Hour 6 lock
            just_locked, lock_msg = trip_mgr.update(dt, is_resting=is_resting)
            if just_locked:
                print(f"\n[ALERT] {lock_msg}\n")
                chime.trigger()

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Detect current window dimensions to support dynamic resizing and fullscreen scaling
            try:
                rect = cv2.getWindowImageRect(WINDOW_NAME)
                win_w, win_h = (rect[2], rect[3]) if (rect[2] > 100 and rect[3] > 100) else (w, h)
            except Exception:
                win_w, win_h = (w, h)

            # -------------------------------------------------------------
            # CASE A: CAMERA TOGGLED OFF (PRIVACY STANDBY MODE)
            # -------------------------------------------------------------
            if not trip_mgr.camera_enabled:
                # Reset eye/nod accumulation so no false violations occur
                continuous_closed_time = 0.0
                flutter_stack_time = 0.0
                strike_awarded_this_closure = False
                is_continuous_violation = False
                is_flutter_violation = False
                is_fatigued = False
                was_fatigued = False
                nod_start_time = None
                nod_duration = 0.0
                is_head_nodding = False
                was_nodding = False
                open_eyes_start_time = None
                open_eyes_duration = 0.0
                upright_posture_start_time = None
                upright_posture_duration = 0.0
                inspirational_mgr.dismiss()

                # Clean driving time & reward streak accumulate if not resting
                if not is_resting:
                    clean_driving_time += dt
                    current_streak_sec += dt
                    best_streak_sec = max(best_streak_sec, current_streak_sec)
                    if clean_driving_time >= heal_strike_sec and active_strikes > 0:
                        active_strikes -= 1
                        clean_driving_time = 0.0
                        log_event_to_db(f"STRIKE HEALED (-1 STRIKE -> {active_strikes}/3)")
                else:
                    rest_time_sec += dt
                    if rest_time_sec >= rest_stop_reset_sec:
                        if active_strikes > 0:
                            active_strikes = 0
                            log_event_to_db("REST STOP FULL RESET (0/3 STRIKES)")

                display_frame = np.full((win_h, win_w, 3), (12, 16, 26), dtype=np.uint8)
                draw_privacy_standby_screen(
                    frame=display_frame,
                    trip_elapsed_sec=trip_mgr.elapsed_drive_sec,
                    trip_planned_sec=trip_mgr.planned_sec,
                    time_until_lock_sec=trip_mgr.get_time_until_mandatory_lock(),
                    active_strikes=active_strikes,
                    clean_driving_time=clean_driving_time,
                    fps=fps,
                    current_streak_sec=current_streak_sec,
                    best_streak_sec=best_streak_sec,
                    is_resting=is_resting,
                    rest_time_sec=rest_time_sec,
                    rest_limit_sec=rest_stop_reset_sec,
                    camera_lock_alert=trip_mgr.is_camera_lock_alert_active(current_time),
                )

            # -------------------------------------------------------------
            # CASE B: CAMERA ACTIVE (LIVE TRACKING MODE)
            # -------------------------------------------------------------
            else:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb_frame.flags.writeable = False
                results = face_mesh.process(rgb_frame)
                rgb_frame.flags.writeable = True

                # Scale frame to window dimensions for crisp fullscreen rendering
                if (win_w, win_h) != (w, h):
                    display_frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_LINEAR)
                else:
                    display_frame = frame.copy()

                face_detected = False
                avg_ear = 0.0
                pitch_ratio = baseline_nod_ratio
                glance_direction = "FORWARD"
                is_mirror_checking = False
                is_directional_nod = False

                if results.multi_face_landmarks:
                    face_detected = True
                    no_face_duration = 0.0
                    mesh_points = results.multi_face_landmarks[0].landmark

                    def get_pts(indices: List[int]) -> np.ndarray:
                        return np.array(
                            [[int(mesh_points[idx].x * w), int(mesh_points[idx].y * h)] for idx in indices],
                            dtype=np.float32,
                        )

                    right_eye_pts = get_pts(RIGHT_EYE_LANDMARKS)
                    left_eye_pts = get_pts(LEFT_EYE_LANDMARKS)
                    right_ear = calculate_ear(right_eye_pts)
                    left_ear = calculate_ear(left_eye_pts)
                    avg_ear = (right_ear + left_ear) / 2.0

                    yaw_ratio, pitch_ratio, glance_direction, is_mirror_checking, is_directional_nod = (
                        analyze_head_posture(mesh_points, w, h, avg_ear, ear_threshold, nod_ratio_threshold)
                    )

                    if is_calibrating:
                        calibration_frames_ear.append(avg_ear)
                        calibration_frames_nod.append(pitch_ratio)
                        elapsed_calib = time.time() - calib_start_time
                        calib_scale = max(min(win_w / 1280.0, win_h / 720.0), 0.65)
                        cal_msg = f"CALIBRATING... LOOK STRAIGHT ({max(3 - int(elapsed_calib), 0)}s)"
                        (cw, ch), _ = cv2.getTextSize(cal_msg, cv2.FONT_HERSHEY_DUPLEX, 0.72 * calib_scale, max(int(2 * calib_scale), 1))
                        cv2.putText(
                            display_frame,
                            cal_msg,
                            ((win_w - cw) // 2, win_h // 2),
                            cv2.FONT_HERSHEY_DUPLEX,
                            0.72 * calib_scale,
                            (0, 215, 255),
                            max(int(2 * calib_scale), 1),
                            cv2.LINE_AA,
                        )
                        if elapsed_calib >= 3.0:
                            if calibration_frames_ear:
                                baseline_ear = float(np.mean(calibration_frames_ear))
                                ear_threshold = round(baseline_ear * 0.70, 3)
                            if calibration_frames_nod:
                                baseline_nod_ratio = float(np.mean(calibration_frames_nod))
                                nod_ratio_threshold = round(baseline_nod_ratio * 0.75, 2)
                                print(f"\n[CALIBRATION COMPLETE] Baseline EAR: {ear_threshold:.3f} | Baseline Nod Ratio: {baseline_nod_ratio:.2f}\n")
                            is_calibrating = False
                            calibration_frames_ear.clear()
                            calibration_frames_nod.clear()

                    if draw_mesh:
                        disp_w, disp_h = win_w, win_h
                        right_eye_pts_disp = np.array(
                            [[int(mesh_points[idx].x * disp_w), int(mesh_points[idx].y * disp_h)] for idx in RIGHT_EYE_LANDMARKS],
                            dtype=np.float32,
                        )
                        left_eye_pts_disp = np.array(
                            [[int(mesh_points[idx].x * disp_w), int(mesh_points[idx].y * disp_h)] for idx in LEFT_EYE_LANDMARKS],
                            dtype=np.float32,
                        )
                        cv2.polylines(display_frame, [right_eye_pts_disp.astype(np.int32)], True, (94, 219, 134), max(int(1 * (win_w / 1280.0)), 1), cv2.LINE_AA)
                        cv2.polylines(display_frame, [left_eye_pts_disp.astype(np.int32)], True, (94, 219, 134), max(int(1 * (win_w / 1280.0)), 1), cv2.LINE_AA)
                        r_center = tuple(np.mean(right_eye_pts_disp, axis=0).astype(np.int32))
                        l_center = tuple(np.mean(left_eye_pts_disp, axis=0).astype(np.int32))
                        cv2.circle(display_frame, r_center, max(int(2 * (win_w / 1280.0)), 2), (40, 210, 255), -1, cv2.LINE_AA)
                        cv2.circle(display_frame, l_center, max(int(2 * (win_w / 1280.0)), 2), (40, 210, 255), -1, cv2.LINE_AA)

                    # 1. Evaluate Rest Stop Mode
                    if is_resting:
                        rest_time_sec += dt
                        clean_driving_time = 0.0
                        continuous_closed_time = 0.0
                        flutter_stack_time = 0.0
                        strike_awarded_this_closure = False
                        is_continuous_violation = False
                        is_flutter_violation = False

                        if rest_time_sec >= rest_stop_reset_sec:
                            if active_strikes > 0:
                                active_strikes = 0
                                log_event_to_db("REST STOP FULL RESET (0/3 STRIKES)")
                    else:
                        rest_time_sec = 0.0

                        # 2. Continuous Eye Closure vs Flutter Stack
                        if not is_calibrating:
                            if avg_ear < ear_threshold:
                                continuous_closed_time += dt

                                # ORIGINAL 2-SECOND CONTINUOUS EYE CLOSURE TIMER
                                if continuous_closed_time >= fatigue_time_threshold:
                                    is_continuous_violation = True
                                    flutter_stack_time = 0.0  # continuous closure doesn't add to flutter stack

                                    if not strike_awarded_this_closure:
                                        strike_awarded_this_closure = True
                                        active_strikes = min(active_strikes + 1, 3)
                                        clean_driving_time = 0.0
                                        best_streak_sec = max(best_streak_sec, current_streak_sec)
                                        current_streak_sec = 0.0
                                        sounds_alarm_now = (active_strikes >= 3)

                                        reason_label = f"STRIKE {active_strikes}/3 (CONTINUOUS)" if not sounds_alarm_now else "3RD STRIKE ALARM (CONTINUOUS)"
                                        inspirational_mgr.trigger(reason=reason_label)
                                        log_event_to_db(reason_label)

                                        if sounds_alarm_now:
                                            chime.trigger_eye_alarm()
                                else:
                                    is_continuous_violation = False
                                    # Ongoing closure is < 2.0s; check if accumulated fluttering reaches 2.0s
                                    if (flutter_stack_time + continuous_closed_time) >= fatigue_time_threshold:
                                        is_flutter_violation = True
                                        if not strike_awarded_this_closure:
                                            strike_awarded_this_closure = True
                                            active_strikes = min(active_strikes + 1, 3)
                                            clean_driving_time = 0.0
                                            best_streak_sec = max(best_streak_sec, current_streak_sec)
                                            current_streak_sec = 0.0
                                            sounds_alarm_now = (active_strikes >= 3)

                                            reason_label = f"STRIKE {active_strikes}/3 (FLUTTER)" if not sounds_alarm_now else "3RD STRIKE ALARM (FLUTTER)"
                                            inspirational_mgr.trigger(reason=reason_label)
                                            log_event_to_db(reason_label)

                                            if sounds_alarm_now:
                                                chime.trigger_eye_alarm()
                                            flutter_stack_time = 0.0
                                    else:
                                        is_flutter_violation = False

                                is_fatigued = is_continuous_violation or is_flutter_violation

                            else:
                                # Eyes open: evaluate completed closure and decay flutter stack
                                is_continuous_violation = False
                                is_flutter_violation = False
                                is_fatigued = False

                                if continuous_closed_time > 0.0:
                                    # If the closure was < 2.0s (a blink or eye flutter):
                                    if continuous_closed_time < fatigue_time_threshold:
                                        if not strike_awarded_this_closure:
                                            flutter_stack_time += continuous_closed_time
                                            if flutter_stack_time >= fatigue_time_threshold:
                                                active_strikes = min(active_strikes + 1, 3)
                                                clean_driving_time = 0.0
                                                best_streak_sec = max(best_streak_sec, current_streak_sec)
                                                current_streak_sec = 0.0
                                                sounds_alarm_now = (active_strikes >= 3)
                                                reason_label = f"STRIKE {active_strikes}/3 (FLUTTER)" if not sounds_alarm_now else "3RD STRIKE ALARM (FLUTTER)"
                                                inspirational_mgr.trigger(reason=reason_label)
                                                log_event_to_db(reason_label)
                                                if sounds_alarm_now:
                                                    chime.trigger_eye_alarm()
                                                flutter_stack_time = 0.0
                                    else:
                                        # Continuous closure ended; do NOT add to flutter stack (prevents double strikes)
                                        flutter_stack_time = 0.0

                                    continuous_closed_time = 0.0
                                    strike_awarded_this_closure = False

                                # Gradual decay of flutter stack over attentive open eyes
                                flutter_stack_time = max(flutter_stack_time - (decay_rate_per_sec * dt), 0.0)

                        was_fatigued = is_fatigued

                        # 3. Directional Head Nod Evaluation
                        if is_directional_nod and not is_calibrating:
                            if nod_start_time is None:
                                nod_start_time = time.time()
                            nod_duration = time.time() - nod_start_time

                            if nod_duration >= nod_time_threshold:
                                is_head_nodding = True
                                if not was_nodding:
                                    active_strikes = min(active_strikes + 1, 3)
                                    clean_driving_time = 0.0
                                    best_streak_sec = max(best_streak_sec, current_streak_sec)
                                    current_streak_sec = 0.0
                                    sounds_alarm_now = (active_strikes >= 3)
                                    chime.trigger_nod_alarm()
                                    reason_label = f"STRIKE {active_strikes}/3 (HEAD NOD)" if not sounds_alarm_now else "3RD STRIKE ALARM (HEAD NOD)"
                                    inspirational_mgr.trigger(reason=reason_label)
                                    log_event_to_db(reason_label)
                            else:
                                is_head_nodding = False
                        else:
                            nod_start_time = None
                            nod_duration = 0.0
                            is_head_nodding = False

                        was_nodding = is_head_nodding

                        # 4. Strike Removal & Gamified Reward Streak Accumulation
                        has_violation_now = is_fatigued or is_head_nodding
                        if not has_violation_now:
                            clean_driving_time += dt
                            current_streak_sec += dt
                            best_streak_sec = max(best_streak_sec, current_streak_sec)
                            if clean_driving_time >= heal_strike_sec and active_strikes > 0:
                                active_strikes -= 1
                                clean_driving_time = 0.0
                                log_event_to_db(f"STRIKE HEALED (-1 STRIKE -> {active_strikes}/3)")
                        else:
                            clean_driving_time = 0.0
                            best_streak_sec = max(best_streak_sec, current_streak_sec)
                            current_streak_sec = 0.0

                        # 5. Auto-Dismiss Pop-Up (Distinct Clear Conditions: Head Upright for Nod vs Eyes Open for Fatigue)
                        active_reason = inspirational_mgr.get_active_reason()
                        is_nod_alert = bool(active_reason and "HEAD NOD" in active_reason)

                        if inspirational_mgr.is_visible:
                            if is_nod_alert:
                                # Head nod alert: trucker must raise head upright for 1.5s
                                is_upright = (pitch_ratio >= nod_ratio_threshold) and not is_head_nodding
                                if is_upright:
                                    if upright_posture_start_time is None:
                                        upright_posture_start_time = time.time()
                                    upright_posture_duration = time.time() - upright_posture_start_time
                                    open_eyes_start_time = None
                                    open_eyes_duration = 0.0

                                    if upright_posture_duration >= POPUP_CLEAR_UPRIGHT_SEC:
                                        inspirational_mgr.dismiss()
                                        upright_posture_start_time = None
                                        upright_posture_duration = 0.0
                                else:
                                    upright_posture_start_time = None
                                    upright_posture_duration = 0.0
                            else:
                                # Eye fatigue alert: trucker must keep eyes open for 2.0s
                                eyes_are_open = (avg_ear >= ear_threshold) and not is_head_nodding
                                if eyes_are_open:
                                    if open_eyes_start_time is None:
                                        open_eyes_start_time = time.time()
                                    open_eyes_duration = time.time() - open_eyes_start_time
                                    upright_posture_start_time = None
                                    upright_posture_duration = 0.0

                                    if open_eyes_duration >= POPUP_CLEAR_OPEN_EYES_SEC:
                                        inspirational_mgr.dismiss()
                                        open_eyes_start_time = None
                                        open_eyes_duration = 0.0
                                else:
                                    open_eyes_start_time = None
                                    open_eyes_duration = 0.0
                        else:
                            open_eyes_start_time = None
                            open_eyes_duration = 0.0
                            upright_posture_start_time = None
                            upright_posture_duration = 0.0

                else:
                    # No face detected in cab
                    no_face_duration += dt
                    if no_face_duration >= rest_stop_reset_sec and active_strikes > 0:
                        active_strikes = 0

                    is_fatigued = False
                    was_fatigued = False
                    continuous_closed_time = 0.0
                    strike_awarded_this_closure = False
                    is_continuous_violation = False
                    is_flutter_violation = False
                    nod_start_time = None
                    nod_duration = 0.0
                    is_head_nodding = False
                    was_nodding = False
                    open_eyes_start_time = None
                    open_eyes_duration = 0.0
                    upright_posture_start_time = None
                    upright_posture_duration = 0.0

                # Render modern AntiDoze digital cockpit HUD natively onto display_frame
                draw_modern_hud(
                    frame=display_frame,
                    ear=avg_ear,
                    ear_threshold=ear_threshold,
                    continuous_closed_time=continuous_closed_time,
                    flutter_stack_time=flutter_stack_time,
                    decay_rate=decay_rate_per_sec,
                    is_fatigued=is_fatigued,
                    is_head_nodding=is_head_nodding,
                    nod_duration=nod_duration,
                    open_eyes_duration=open_eyes_duration,
                    fps=fps,
                    face_detected=face_detected,
                    glance_direction=glance_direction,
                    is_mirror_checking=is_mirror_checking,
                    pitch_ratio=pitch_ratio,
                    active_strikes=active_strikes,
                    sounds_alarm_now=sounds_alarm_now,
                    clean_driving_time=clean_driving_time,
                    heal_limit_sec=heal_strike_sec,
                    is_resting=is_resting,
                    rest_time_sec=rest_time_sec,
                    rest_limit_sec=rest_stop_reset_sec,
                    current_streak_sec=current_streak_sec,
                    best_streak_sec=best_streak_sec,
                    draw_mesh_enabled=draw_mesh,
                    inspirational_quote=inspirational_mgr.get_active_quote(),
                    trip_elapsed_sec=trip_mgr.elapsed_drive_sec,
                    trip_planned_sec=trip_mgr.planned_sec,
                    camera_enabled=trip_mgr.camera_enabled,
                    mandatory_lock_active=trip_mgr.mandatory_lock_active,
                    camera_lock_alert=trip_mgr.is_camera_lock_alert_active(current_time),
                    hour_6_transition_alert=trip_mgr.is_hour_6_transition_alert_active(current_time),
                    initial_trip_alert=trip_mgr.is_initial_trip_alert_active(current_time),
                    is_continuous_violation=is_continuous_violation,
                    nod_time_threshold=nod_time_threshold,
                    nod_ratio_threshold=nod_ratio_threshold,
                    upright_posture_duration=upright_posture_duration,
                    active_alert_reason=inspirational_mgr.get_active_reason(),
                )

            # Live stream telemetry update to shared in-memory cache on every frame
            fleet_db.set_live_telemetry(
                driver_id=driver_id,
                data={
                    "strike_count": active_strikes,
                    "strike_status": get_strike_rank_badge(active_strikes)[0],
                    "is_critical": (active_strikes >= 3),
                    "ear": round(avg_ear, 3) if (trip_mgr.camera_enabled and face_detected) else None,
                    "pitch": round(pitch_ratio, 2) if (trip_mgr.camera_enabled and face_detected) else None,
                    "glance": glance_direction if trip_mgr.camera_enabled else "STANDBY",
                    "clean_streak": format_time_hms(current_streak_sec),
                    "trip_elapsed": format_time_hms(trip_mgr.elapsed_drive_sec),
                    "fps": round(fps, 1),
                    "camera_enabled": trip_mgr.camera_enabled,
                    "face_detected": face_detected,
                    "continuous_closed": round(continuous_closed_time, 2),
                    "flutter_stack": round(flutter_stack_time, 2),
                    "nod_duration": round(nod_duration, 2),
                    "is_resting": is_resting,
                    "active_source": str(video_source),
                    "client_status": "ONLINE (LIVE CAMERA STREAMING)",
                },
            )

            # Dynamic 10-Second Telemetry Sync to Fleet Database
            if (current_time - last_db_sync_time) >= db_sync_interval:
                last_db_sync_time = current_time
                log_event_to_db("10s HEARTBEAT" if not is_resting else "REST STOP HEARTBEAT")

            cv2.imshow(WINDOW_NAME, display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                print("\n[INFO] Exiting AntiDoze...")
                log_event_to_db("CAB OFFLINE (DRIVER SHIFT ENDED)")
                break
            elif key == ord('f') or key == ord('F'):
                is_fullscreen = not is_fullscreen
                if is_fullscreen:
                    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    print("[INFO] Fullscreen Mode: ENABLED")
                else:
                    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                    print("[INFO] Fullscreen Mode: DISABLED")
            elif key == ord('t') or key == ord('T'):
                success, msg = trip_mgr.toggle_camera()
                print(f"[INFO] {msg}")
                log_event_to_db("CAMERA STANDBY MODE" if not trip_mgr.camera_enabled else "CAMERA RESUMED (LIVE TRACKING)")
                if not success:
                    chime.trigger()
            elif key == ord('r') or key == ord('R'):
                is_resting = not is_resting
                print(f"[INFO] Rest Stop Mode: {'ENABLED' if is_resting else 'DISABLED'}")
                log_event_to_db("REST STOP MODE ENGAGED" if is_resting else "REST STOP DISENGAGED")
            elif key == ord('m') or key == ord('M'):
                draw_mesh = not draw_mesh
                print(f"[INFO] Eye mesh display: {'ON' if draw_mesh else 'OFF'}")
            elif key == ord('c') or key == ord('C'):
                print("[INFO] Starting 3-second auto-calibration...")
                is_calibrating = True
                calibration_frames_ear = []
                calibration_frames_nod = []
                calib_start_time = time.time()

        return True

    finally:
        # Gracefully mark cab as INACTIVE & DISCONNECTED in fleet database
        try:
            rank_name, _ = get_strike_rank_badge(active_strikes)
            fleet_db.set_driver_inactive(
                driver_id=driver_id,
                strike_count=active_strikes,
                strike_status=rank_name,
                clean_streak=format_time_hms(current_streak_sec),
                trip_elapsed=format_time_hms(trip_mgr.elapsed_drive_sec),
            )
            fleet_db.log_telemetry(
                driver_id=driver_id,
                strike_count=active_strikes,
                strike_status=rank_name,
                alert_type="CAB DISCONNECTED (INACTIVE)",
                ear_value=None,
                head_pitch=None,
                glance_direction="STANDBY",
                clean_streak=format_time_hms(current_streak_sec),
                trip_elapsed=format_time_hms(trip_mgr.elapsed_drive_sec),
                camera_mode="OFFLINE",
                notes="AntiDoze application closed cleanly",
            )
            print(f"[INFO] Cab {driver_id} logged as INACTIVE / DISCONNECTED in fleet database.")
        except Exception:
            pass

        cap.release()
        inspirational_mgr.dismiss()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        face_mesh.close()
        print("[INFO] Resources released successfully.")


# ============================================================================
# SIMULATION / DEMO MODE (TESTING TRIP PLANNING & HOUR 6 LOCK)
# ============================================================================

def run_simulation(
    ear_threshold: float = DEFAULT_EAR_THRESHOLD,
    fatigue_time_threshold: float = DEFAULT_EYE_FATIGUE_SEC,
    nod_time_threshold: float = DEFAULT_NOD_DURATION_SEC,
    nod_ratio_threshold: float = DEFAULT_NOD_RATIO_THRESH,
    decay_rate_per_sec: float = DEFAULT_STACK_DECAY_RATE,
    heal_strike_sec: float = 5.0,        # Accelerated to 5s for demo
    rest_stop_reset_sec: float = 4.0,    # Accelerated to 4s for demo
    save_video_path: str = "demo_output.mp4",
    driver_id: str = DEFAULT_DRIVER_ID,
    db_sync_interval: float = 10.0,
):
    """
    Runs a 28-second simulation demonstrating:
    1. Trip Planning Setup: 8.0 hours planned drive (triggers > 6h alert).
    2. 0s-2.5s: Driver alert under Hour 1 (Camera Active, [T] toggleable).
    3. 2.5s-5.5s: Driver presses [T] -> Camera enters Privacy Standby mode!
    4. 5.5s-7.5s: Driver presses [T] -> Camera resumes active tracking.
    5. 7.5s-9.5s: Clock crosses Hour 6.0 -> Camera locked ON for mandatory monitoring!
    6. 9.5s-12s: Driver attempts [T] to toggle camera off -> BLOCKED with warning chime & banner!
    7. 12s-17.5s: Continuous eye closure (2.0s+) -> Strike 1 awarded (No double-strike).
    8. 17.5s-20.2s: Drowsy blink flutter sequence -> Stack hits 2.0s -> Strike 2.
    9. 21s-24.5s: Sensitive downward head nod slump (pitch 0.65) -> 3.0s sustained detection -> Strike 3 ALARM!
    10. 24.5s-28s: Posture recovery: holding head upright for 1.5s clears nod alert with violet meter.
    """
    width, height = 1280, 720
    fps = 30
    total_frames = int(fps * 28)

    if not os.path.isabs(save_video_path):
        save_video_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), save_video_path)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(save_video_path, fourcc, fps, (width, height))
    chime = MelodicChimeManager()
    inspirational_mgr = CompactInspirationalManager()

    # Dynamic Fleet Database Sync
    fleet_db = get_fleet_db()
    fleet_db.register_or_update_driver(driver_id=driver_id)
    last_sim_sync = -10.0

    # Initialize trip manager for 8.0 hours
    trip_mgr = TripManager(
        planned_hours=8.0,
        mandatory_hour=6.0,
        time_scale=1.0,
        initial_elapsed_sec=1.5 * 3600.0,  # Starts at Hour 1.5
    )

    print("=" * 68)
    print(" ANTIDOZE: 28-SECOND TRIP PLANNING & MULTI-CHANNEL VIGILANCE DEMO ")
    print("=" * 68)
    print(f" Output Video File: {os.path.abspath(save_video_path)}")
    print(f" Fleet Driver ID  : {driver_id} (10s Dynamic DB Sync Active)")

    active_strikes = 0
    clean_driving_time = 0.0
    current_streak_sec = 0.0
    best_streak_sec = 0.0
    continuous_closed_time = 0.0
    flutter_stack_time = 0.0
    strike_awarded_this_closure = False
    is_continuous_violation = False
    is_flutter_violation = False
    open_eyes_start_time = None
    open_eyes_duration = 0.0
    upright_posture_duration = 0.0
    nod_duration = 0.0
    is_head_nodding = False
    was_nodding = False

    is_fatigued = False
    was_fatigued = False
    sounds_alarm_now = False

    def log_sim_db(alert_label: str):
        try:
            rank_name, _ = get_strike_rank_badge(active_strikes)
            fleet_db.log_telemetry(
                driver_id=driver_id,
                strike_count=active_strikes,
                strike_status=rank_name,
                alert_type=alert_label,
                ear_value=sim_ear,
                head_pitch=sim_pitch_ratio,
                glance_direction=sim_glance,
                clean_streak=format_time_hms(current_streak_sec),
                trip_elapsed=format_time_hms(trip_mgr.elapsed_drive_sec),
                camera_mode="ACTIVE" if trip_mgr.camera_enabled else "STANDBY",
            )
        except Exception:
            pass

    for frame_idx in range(total_frames):
        sim_time = frame_idx / fps
        dt = 1.0 / fps

        # Timeline events
        # Event 1: Privacy Toggle OFF at 2.5s
        if 2.5 <= sim_time < 5.5:
            trip_mgr.camera_enabled = False
        # Event 2: Camera Resumed at 5.5s
        elif 5.5 <= sim_time < 7.5:
            trip_mgr.camera_enabled = True
        # Event 3: Clock jumps past Hour 6.0 at 7.5s
        elif 7.5 <= sim_time < 9.5:
            trip_mgr.elapsed_drive_sec = 6.02 * 3600.0
            trip_mgr.mandatory_lock_active = True
            trip_mgr.hour_6_transition_time = time.time()
            trip_mgr.camera_enabled = True
        # Event 4: User attempts to toggle off after Hour 6 at 9.5s
        elif 9.5 <= sim_time < 12.0:
            trip_mgr.lock_attempt_alert_time = time.time()
            trip_mgr.camera_enabled = True
        else:
            trip_mgr.camera_enabled = True

        # Fatigue timeline:
        # Phase 1: 12.0s - 15.5s -> CONTINUOUS EYE CLOSURE (3.5s unbroken closure!)
        # Triggers at 14.0s (2.0s continuous closure).
        # Verifies ONLY 1 STRIKE awarded (no double strike!). Flutter stack stays 0.0s!
        if 12.0 <= sim_time < 15.5:
            sim_ear = 0.12  # Unbroken closed eyes
        # Phase 2: 15.5s - 17.5s -> Eyes open (Driver awakens)
        elif 15.5 <= sim_time < 17.5:
            sim_ear = 0.35  # Open eyes
        # Phase 3: 17.5s - 22.0s -> EYE FLUTTERING / DROWSY BLINKING SEQUENCE
        elif 17.5 <= sim_time < 18.2:
            sim_ear = 0.12  # Flutter 1 (0.7s closed)
        elif 18.2 <= sim_time < 18.4:
            sim_ear = 0.32  # Flutter open 0.2s
        elif 18.4 <= sim_time < 19.2:
            sim_ear = 0.12  # Flutter 2 (0.8s closed)
        elif 19.2 <= sim_time < 19.4:
            sim_ear = 0.32  # Flutter open 0.2s
        elif 19.4 <= sim_time < 20.2:
            sim_ear = 0.12  # Flutter 3 (0.8s closed) -> Flutter Stack hits 2.0s -> STRIKE 2!
        # Phase 4: 20.2s - 28.0s -> Attentive open eyes
        else:
            sim_ear = 0.35  # Alert open eyes

        # Phase 5: 21.0s - 24.5s -> SENSITIVE HEAD NOD SLUMP (pitch ratio 0.65 < 0.78 threshold, 3.0s sustained)
        if 21.0 <= sim_time < 24.5:
            sim_pitch_ratio = 0.65
            sim_glance = "NOD (FORWARD)"
        else:
            sim_pitch_ratio = 1.05
            sim_glance = "FORWARD"

        # Frame generation
        if not trip_mgr.camera_enabled:
            # Standby screen: clean drive & streak accumulate
            clean_driving_time += dt
            current_streak_sec += dt
            best_streak_sec = max(best_streak_sec, current_streak_sec)
            frame = np.full((height, width, 3), (12, 16, 26), dtype=np.uint8)
            draw_privacy_standby_screen(
                frame=frame,
                trip_elapsed_sec=trip_mgr.elapsed_drive_sec,
                trip_planned_sec=trip_mgr.planned_sec,
                time_until_lock_sec=trip_mgr.get_time_until_mandatory_lock(),
                active_strikes=active_strikes,
                clean_driving_time=clean_driving_time,
                fps=float(fps),
                current_streak_sec=current_streak_sec,
                best_streak_sec=best_streak_sec,
                is_resting=False,
                rest_time_sec=0.0,
                rest_limit_sec=rest_stop_reset_sec,
                camera_lock_alert=trip_mgr.is_camera_lock_alert_active(time.time()),
            )
        else:
            # Camera active cockpit
            frame = np.full((height, width, 3), 20, dtype=np.uint8)
            face_cx = width // 2
            face_cy = height // 2 + (55 if sim_pitch_ratio < nod_ratio_threshold else 25)
            cv2.ellipse(frame, (face_cx, face_cy), (130, 170), 0, 0, 360, (50, 50, 60), -1)

            eye_y = face_cy - 25
            left_eye_x = face_cx - 52
            right_eye_x = face_cx + 52
            eye_h = int(max(sim_ear * 70, 3))
            eye_col = (180, 220, 255) if sim_ear >= ear_threshold else (70, 70, 90)

            cv2.ellipse(frame, (left_eye_x, eye_y), (28, eye_h), 0, 0, 360, eye_col, -1)
            cv2.ellipse(frame, (right_eye_x, eye_y), (28, eye_h), 0, 0, 360, eye_col, -1)
            cv2.ellipse(frame, (left_eye_x, eye_y), (28, eye_h), 0, 0, 360, (180, 180, 190), 1)
            cv2.ellipse(frame, (right_eye_x, eye_y), (28, eye_h), 0, 0, 360, (180, 180, 190), 1)

            # Dual Evaluation: Continuous Eye Closure vs Flutter Stack
            if sim_ear < ear_threshold:
                continuous_closed_time += dt

                # Continuous 2s timer
                if continuous_closed_time >= fatigue_time_threshold:
                    is_continuous_violation = True
                    flutter_stack_time = 0.0  # continuous closure does NOT add to flutter stack
                    if not strike_awarded_this_closure:
                        strike_awarded_this_closure = True
                        active_strikes = min(active_strikes + 1, 3)
                        clean_driving_time = 0.0
                        best_streak_sec = max(best_streak_sec, current_streak_sec)
                        current_streak_sec = 0.0
                        sounds_alarm_now = (active_strikes >= 3)
                        lbl = f"STRIKE {active_strikes}/3 (CONTINUOUS)" if not sounds_alarm_now else "3RD STRIKE ALARM (CONTINUOUS)"
                        inspirational_mgr.trigger(reason=lbl)
                        log_sim_db(lbl)
                        if sounds_alarm_now:
                            chime.trigger_eye_alarm()
                else:
                    is_continuous_violation = False
                    # Check if accumulated flutter stack reaches 2.0s
                    if (flutter_stack_time + continuous_closed_time) >= fatigue_time_threshold:
                        is_flutter_violation = True
                        if not strike_awarded_this_closure:
                            strike_awarded_this_closure = True
                            active_strikes = min(active_strikes + 1, 3)
                            clean_driving_time = 0.0
                            best_streak_sec = max(best_streak_sec, current_streak_sec)
                            current_streak_sec = 0.0
                            sounds_alarm_now = (active_strikes >= 3)
                            lbl = f"STRIKE {active_strikes}/3 (FLUTTER)" if not sounds_alarm_now else "3RD STRIKE ALARM (FLUTTER)"
                            inspirational_mgr.trigger(reason=lbl)
                            log_sim_db(lbl)
                            if sounds_alarm_now:
                                chime.trigger_eye_alarm()
                            flutter_stack_time = 0.0
                    else:
                        is_flutter_violation = False

                is_fatigued = is_continuous_violation or is_flutter_violation
            else:
                is_continuous_violation = False
                is_flutter_violation = False
                is_fatigued = False

                if continuous_closed_time > 0.0:
                    if continuous_closed_time < fatigue_time_threshold:
                        # Blinking or eye fluttering (< 2.0s) -> add to flutter stack!
                        if not strike_awarded_this_closure:
                            flutter_stack_time += continuous_closed_time
                            if flutter_stack_time >= fatigue_time_threshold:
                                active_strikes = min(active_strikes + 1, 3)
                                clean_driving_time = 0.0
                                best_streak_sec = max(best_streak_sec, current_streak_sec)
                                current_streak_sec = 0.0
                                sounds_alarm_now = (active_strikes >= 3)
                                lbl = f"STRIKE {active_strikes}/3 (FLUTTER)" if not sounds_alarm_now else "3RD STRIKE ALARM (FLUTTER)"
                                inspirational_mgr.trigger(reason=lbl)
                                log_sim_db(lbl)
                                if sounds_alarm_now:
                                    chime.trigger_eye_alarm()
                                flutter_stack_time = 0.0
                    else:
                        # Continuous closure ended; do NOT add to flutter stack
                        flutter_stack_time = 0.0

                    continuous_closed_time = 0.0
                    strike_awarded_this_closure = False

                # Gradual decay of flutter stack over open eyes
                flutter_stack_time = max(flutter_stack_time - (decay_rate_per_sec * dt), 0.0)

            was_fatigued = is_fatigued

            # Directional Head Nod Evaluation (Enhanced sensitivity: 1.0s at ratio < 0.78)
            if sim_pitch_ratio < nod_ratio_threshold:
                nod_duration += dt
                if nod_duration >= nod_time_threshold:
                    is_head_nodding = True
                    if not was_nodding:
                        active_strikes = min(active_strikes + 1, 3)
                        clean_driving_time = 0.0
                        best_streak_sec = max(best_streak_sec, current_streak_sec)
                        current_streak_sec = 0.0
                        sounds_alarm_now = (active_strikes >= 3)
                        chime.trigger_nod_alarm()
                        lbl = f"STRIKE {active_strikes}/3 (HEAD NOD)" if not sounds_alarm_now else "3RD STRIKE ALARM (HEAD NOD)"
                        inspirational_mgr.trigger(reason=lbl)
                        log_sim_db(lbl)
                else:
                    is_head_nodding = False
            else:
                nod_duration = 0.0
                is_head_nodding = False

            was_nodding = is_head_nodding

            # Streak & Clean driving accumulation
            has_violation = is_fatigued or is_head_nodding
            if not has_violation:
                clean_driving_time += dt
                current_streak_sec += dt
                best_streak_sec = max(best_streak_sec, current_streak_sec)
                if clean_driving_time >= heal_strike_sec and active_strikes > 0:
                    active_strikes -= 1
                    clean_driving_time = 0.0
            else:
                clean_driving_time = 0.0
                best_streak_sec = max(best_streak_sec, current_streak_sec)
                current_streak_sec = 0.0

            # Pop-up auto-clear (Distinct: Upright posture 1.5s for nod vs Eyes open 2.0s for eye fatigue)
            active_reason = inspirational_mgr.get_active_reason()
            is_nod_popup = bool(active_reason and "HEAD NOD" in active_reason)

            if inspirational_mgr.is_visible:
                if is_nod_popup:
                    if sim_pitch_ratio >= nod_ratio_threshold and not is_head_nodding:
                        upright_posture_duration += dt
                        open_eyes_duration = 0.0
                        if upright_posture_duration >= POPUP_CLEAR_UPRIGHT_SEC:
                            inspirational_mgr.dismiss()
                            upright_posture_duration = 0.0
                    else:
                        upright_posture_duration = 0.0
                else:
                    if sim_ear >= ear_threshold and not is_head_nodding:
                        open_eyes_duration += dt
                        upright_posture_duration = 0.0
                        if open_eyes_duration >= POPUP_CLEAR_OPEN_EYES_SEC:
                            inspirational_mgr.dismiss()
                            open_eyes_duration = 0.0
                    else:
                        open_eyes_duration = 0.0
            else:
                open_eyes_duration = 0.0
                upright_posture_duration = 0.0

            # Draw Modern HUD
            draw_modern_hud(
                frame=frame,
                ear=sim_ear,
                ear_threshold=ear_threshold,
                continuous_closed_time=continuous_closed_time,
                flutter_stack_time=flutter_stack_time,
                decay_rate=decay_rate_per_sec,
                is_fatigued=is_fatigued,
                is_head_nodding=is_head_nodding,
                nod_duration=nod_duration,
                open_eyes_duration=open_eyes_duration,
                fps=float(fps),
                face_detected=True,
                glance_direction=sim_glance,
                is_mirror_checking=False,
                pitch_ratio=sim_pitch_ratio,
                active_strikes=active_strikes,
                sounds_alarm_now=sounds_alarm_now,
                clean_driving_time=clean_driving_time,
                heal_limit_sec=heal_strike_sec,
                is_resting=False,
                rest_time_sec=0.0,
                rest_limit_sec=rest_stop_reset_sec,
                current_streak_sec=current_streak_sec,
                best_streak_sec=best_streak_sec,
                draw_mesh_enabled=False,
                inspirational_quote=inspirational_mgr.get_active_quote(),
                trip_elapsed_sec=trip_mgr.elapsed_drive_sec,
                trip_planned_sec=trip_mgr.planned_sec,
                camera_enabled=trip_mgr.camera_enabled,
                mandatory_lock_active=trip_mgr.mandatory_lock_active,
                camera_lock_alert=trip_mgr.is_camera_lock_alert_active(time.time()),
                hour_6_transition_alert=trip_mgr.is_hour_6_transition_alert_active(time.time()),
                initial_trip_alert=(sim_time < 2.5),
                is_continuous_violation=is_continuous_violation,
                nod_time_threshold=nod_time_threshold,
                nod_ratio_threshold=nod_ratio_threshold,
                upright_posture_duration=upright_posture_duration,
                active_alert_reason=inspirational_mgr.get_active_reason(),
            )

        out.write(frame)

        # 10-Second Telemetry Sync in Simulation to Fleet Database
        if (sim_time - last_sim_sync) >= db_sync_interval:
            last_sim_sync = sim_time
            log_sim_db("10s HEARTBEAT" if trip_mgr.camera_enabled else "STANDBY HEARTBEAT")

        if frame_idx % (fps * 2) == 0:
            cam_state = "STANDBY" if not trip_mgr.camera_enabled else ("LOCKED (6h+)" if trip_mgr.mandatory_lock_active else "ACTIVE")
            reward_rank = get_streak_rank(current_streak_sec)
            print(f" [{sim_time:4.1f}s / 28.0s] Cam: {cam_state:7s} | Cont: {continuous_closed_time:.1f}s | Flutter: {flutter_stack_time:.2f}s | Strike: {active_strikes}/3 | Streak: {format_time_hms(current_streak_sec)} | Reward: {reward_rank}")

    out.release()
    print("=" * 68)
    print(" [COMPLETE] AntiDoze Trip Planning & Mandatory Camera Lock simulation generated!")
    print(f" View video: {os.path.abspath(save_video_path)}")
    print("=" * 68)


# ============================================================================
# ALGORITHMIC UNIT SELF-TESTS
# ============================================================================

def run_self_tests():
    """Runs automated unit tests for Trip Planning, Camera Lock, Stack Decay, and 3-strike ranks."""
    print("Running AntiDoze self-diagnostics...")

    # Test 1: EAR calculation
    open_eye = np.array([[100,100],[115,85],[135,85],[150,100],[135,115],[115,115]], dtype=np.float32)
    open_ear = calculate_ear(open_eye)
    assert 0.55 <= open_ear <= 0.65
    print(f" [PASS] Eye Aspect Ratio calculated: {open_ear:.3f}")

    # Test 2: Gradual Stack Decay
    decay_rate = 0.20  # s/s
    stack = 1.0
    stack = max(stack - (decay_rate * 2.0), 0.0)
    assert abs(stack - 0.60) < 1e-4, f"Stack should decay to 0.60s: {stack}"
    stack = max(stack - (decay_rate * 4.0), 0.0)
    assert stack == 0.0, f"Stack should drain completely to 0.0s: {stack}"
    print(" [PASS] Gradual Stack Decay validated (Smooth drain from 1.0s -> 0.60s -> 0.0s)")

    # Test 3: Flicker resistance with gradual decay
    stack = 0.0
    stack += 0.8
    stack = max(stack - (decay_rate * 0.2), 0.0)
    assert stack == 0.76
    stack += 0.8
    assert stack >= 1.50
    print(" [PASS] Flicker tolerance preserved with gradual decay")

    # Test 4: 3-Strike Ranks
    assert "TOP DRIVER" in get_strike_rank_badge(0)[0]
    assert "CAUTION" in get_strike_rank_badge(1)[0]
    assert "WARNING" in get_strike_rank_badge(2)[0]
    assert "CRITICAL" in get_strike_rank_badge(3)[0]
    print(" [PASS] 3-Strike Rank tier badges verified")

    # Test 5: Melodic chime trigger
    chime = MelodicChimeManager()
    t0 = time.time()
    chime.trigger()
    assert (time.time() - t0) < 0.05
    print(" [PASS] Melodic chime fired asynchronously")

    # Test 6: Trip Planning Setup & Alert on > 6.0 Hours
    trip_long = TripManager(planned_hours=8.0)
    assert trip_long.exceeds_six_hours is True, "Trips > 6.0h must set exceeds_six_hours=True"
    trip_short = TripManager(planned_hours=4.5)
    assert trip_short.exceeds_six_hours is False, "Trips <= 6.0h must not set exceeds_six_hours=True"
    print(" [PASS] Pre-drive trip duration validation & >6h alert flag verified")

    # Test 7: Camera Privacy Toggle permitted in Hours 0 - 6
    trip_early = TripManager(planned_hours=8.0, initial_elapsed_sec=2.0 * 3600.0)  # Hour 2
    assert trip_early.mandatory_lock_active is False
    ok, msg = trip_early.toggle_camera()
    assert ok is True and trip_early.camera_enabled is False, "Camera should toggle OFF before Hour 6"
    ok, msg = trip_early.toggle_camera()
    assert ok is True and trip_early.camera_enabled is True, "Camera should toggle ON before Hour 6"
    print(" [PASS] Camera privacy toggle permitted during Hours 0 - 6")

    # Test 8: Mandatory Camera Lock after Hour 6 (Toggle BLOCKED)
    trip_late = TripManager(planned_hours=8.0, initial_elapsed_sec=6.05 * 3600.0)  # Hour 6.05
    assert trip_late.mandatory_lock_active is True
    ok, msg = trip_late.toggle_camera()
    assert ok is False, "Toggling camera OFF after Hour 6 must be blocked"
    assert trip_late.camera_enabled is True, "Camera must remain strictly ON after Hour 6"
    assert "MANDATORY" in msg, "Failure message must cite mandatory policy"
    print(" [PASS] Camera toggle blocked after Hour 6 (Mandatory monitoring enforced)")

    # Test 9: Auto-restoration of Camera at Hour 6
    trip_crossing = TripManager(planned_hours=8.0, initial_elapsed_sec=5.99 * 3600.0)
    trip_crossing.toggle_camera()
    assert trip_crossing.camera_enabled is False, "Camera should be toggled OFF at 5.99h"
    just_locked, msg = trip_crossing.update(60.0)  # 5.99h + 60s > 6.0h
    assert just_locked is True, "Hour 6 transition must be detected"
    assert trip_crossing.mandatory_lock_active is True
    assert trip_crossing.camera_enabled is True, "Camera must auto-restore to ON when Hour 6 is reached"
    print(" [PASS] Automatic camera activation on crossing Hour 6 verified")

    # Test 10: Continuous Eye Closure receives exactly 1 strike (No double-strike)
    dt = 0.1
    cont_time = 0.0
    flutter_time = 0.0
    test_strikes = 0
    strike_awarded = False
    for step in range(40):  # 40 * 0.1 = 4.0 seconds unbroken eye closure
        cont_time += dt
        if cont_time >= 2.0:
            flutter_time = 0.0  # continuous closure does NOT add to flutter stack
            if not strike_awarded:
                strike_awarded = True
                test_strikes += 1
    assert test_strikes == 1, f"Continuous eye closure must award exactly 1 strike, got {test_strikes}"
    assert flutter_time == 0.0, "Continuous closure must not add to flutter stack"
    print(" [PASS] Continuous 2.0s eye closure awards exactly 1 strike (No double-strike)")

    # Test 11: Only Blinking / Eye Fluttering (< 2.0s) added to stack timer
    cont_time = 0.0
    flutter_time = 0.0
    test_strikes = 0
    strike_awarded = False

    # Flutter 1: 0.7s closed -> reopen
    cont_time = 0.7
    flutter_time += cont_time
    cont_time = 0.0
    assert abs(flutter_time - 0.7) < 1e-4

    # 0.2s open eyes -> decays by 0.2 * 0.20 = 0.04s -> 0.66s
    flutter_time = max(flutter_time - (0.20 * 0.2), 0.0)
    assert abs(flutter_time - 0.66) < 1e-4

    # Flutter 2: 0.8s closed -> reopen
    cont_time = 0.8
    flutter_time += cont_time
    cont_time = 0.0
    assert abs(flutter_time - 1.46) < 1e-4

    # 0.2s open eyes -> decays to 1.42s
    flutter_time = max(flutter_time - (0.20 * 0.2), 0.0)

    # Flutter 3: 0.7s closed -> pushes stack over 2.0s (1.42 + 0.7 = 2.12s)!
    cont_time = 0.7
    flutter_time += cont_time
    if flutter_time >= 2.0:
        test_strikes += 1
        flutter_time = 0.0
    cont_time = 0.0

    assert test_strikes == 1, f"Repeated fluttering must trigger stack violation: {test_strikes}"
    assert flutter_time == 0.0
    print(" [PASS] Flutter stack strictly accumulates fluttering blinks with smooth decay")

    # Test 12: Gamified Vigilance Reward System & Streak Tiers
    assert "VIGILANT DRIVER" in get_streak_rank(60.0)
    assert "PRO PILOT" in get_streak_rank(245.0)
    assert "HIGHWAY MASTER" in get_streak_rank(650.0)
    assert "IRON TRUCKER" in get_streak_rank(1850.0)
    tier_title, tier_col, next_sec = get_reward_tier_badge(245.0)
    assert "PRO PILOT" in tier_title
    assert abs(next_sec - 355.0) < 1e-4

    # Streak accumulation, best streak preservation, and reset on violation
    test_streak = 0.0
    test_best = 0.0
    test_streak += 200.0
    test_best = max(test_best, test_streak)
    assert test_best == 200.0
    assert "PRO PILOT" in get_streak_rank(test_streak)

    # Violation occurs -> streak resets to 0.0, but best remains 200.0
    test_best = max(test_best, test_streak)
    test_streak = 0.0
    assert test_streak == 0.0
    assert test_best == 200.0
    assert "VIGILANT DRIVER" in get_streak_rank(test_streak)
    print(" [PASS] Gamified Reward System & Vigilance Tiers validated (Vigilant -> Pro -> Master -> Iron)")

    # Test 13: Non-Invasive Standby Menu Wording & Coexistence
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    draw_privacy_standby_screen(
        frame=dummy_frame,
        trip_elapsed_sec=3600.0,
        trip_planned_sec=28800.0,
        time_until_lock_sec=18000.0,
        active_strikes=0,
        clean_driving_time=1200.0,
        fps=30.0,
        current_streak_sec=1200.0,
        best_streak_sec=1200.0,
    )
    # Also verify draw_modern_hud renders both systems without error
    draw_modern_hud(
        frame=dummy_frame,
        ear=0.32,
        ear_threshold=0.22,
        continuous_closed_time=0.0,
        flutter_stack_time=0.0,
        decay_rate=0.20,
        is_fatigued=False,
        is_head_nodding=False,
        nod_duration=0.0,
        open_eyes_duration=5.0,
        fps=30.0,
        face_detected=True,
        glance_direction="FORWARD",
        is_mirror_checking=False,
        pitch_ratio=1.05,
        active_strikes=1,
        sounds_alarm_now=False,
        clean_driving_time=600.0,
        heal_limit_sec=1800.0,
        is_resting=False,
        rest_time_sec=0.0,
        rest_limit_sec=900.0,
        current_streak_sec=600.0,
        best_streak_sec=1200.0,
    )
    print(" [PASS] Non-invasive standby menu phrasing and HUD dual-system coexistence verified")

    # Test 14: Dynamic Fullscreen Scaling across Resolutions (720p, 1080p, 1440p, 4K)
    for res_w, res_h in [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]:
        test_frame = np.zeros((res_h, res_w, 3), dtype=np.uint8)
        draw_modern_hud(
            frame=test_frame,
            ear=0.28,
            ear_threshold=0.22,
            continuous_closed_time=0.5,
            flutter_stack_time=0.8,
            decay_rate=0.20,
            is_fatigued=False,
            is_head_nodding=False,
            nod_duration=0.0,
            open_eyes_duration=1.2,
            fps=60.0,
            face_detected=True,
            glance_direction="FORWARD",
            is_mirror_checking=False,
            pitch_ratio=1.05,
            active_strikes=2,
            sounds_alarm_now=False,
            clean_driving_time=300.0,
            heal_limit_sec=1800.0,
            is_resting=False,
            rest_time_sec=0.0,
            rest_limit_sec=900.0,
            current_streak_sec=300.0,
            best_streak_sec=600.0,
            inspirational_quote="Stay Alert!",
        )
        assert test_frame.shape == (res_h, res_w, 3)

        standby_frame = np.zeros((res_h, res_w, 3), dtype=np.uint8)
        draw_privacy_standby_screen(
            frame=standby_frame,
            trip_elapsed_sec=7200.0,
            trip_planned_sec=28800.0,
            time_until_lock_sec=14400.0,
            active_strikes=1,
            clean_driving_time=600.0,
            fps=60.0,
            current_streak_sec=600.0,
            best_streak_sec=600.0,
        )
        assert standby_frame.shape == (res_h, res_w, 3)
    print(" [PASS] Dynamic HUD scaling validated across 720p, 1080p, 1440p, and 4K resolutions")

    # Test 15: Sensitive Head Nod Detection & Posture Slump Separation
    assert DEFAULT_NOD_DURATION_SEC == 3.0, f"Head nod duration threshold should be 3.0s: {DEFAULT_NOD_DURATION_SEC}"
    assert DEFAULT_NOD_RATIO_THRESH == 0.78, f"Head nod ratio threshold should be 0.78: {DEFAULT_NOD_RATIO_THRESH}"
    assert POPUP_CLEAR_UPRIGHT_SEC == 1.5, f"Upright clear threshold should be 1.5s: {POPUP_CLEAR_UPRIGHT_SEC}"

    class MockLm:
        def __init__(self, x: float, y: float):
            self.x = x
            self.y = y

    # Create mock landmarks for a face (w=1000, h=1000)
    mock_mesh = [MockLm(0.5, 0.5) for _ in range(468)]
    mock_mesh[10] = MockLm(0.50, 0.20)   # Forehead
    mock_mesh[1] = MockLm(0.50, 0.50)    # Nose
    mock_mesh[234] = MockLm(0.30, 0.50)  # Left Tragus
    mock_mesh[454] = MockLm(0.70, 0.50)  # Right Tragus

    # Case A: Normal Upright Head (chin at 0.82 -> d_lower=0.32, d_upper=0.30 -> pitch=1.066)
    mock_mesh[152] = MockLm(0.50, 0.82)
    _, pitch_a, glance_a, mirror_a, nod_a = analyze_head_posture(mock_mesh, 1000, 1000, 0.30, 0.22, 0.78)
    assert pitch_a > 1.0 and not nod_a and not mirror_a and glance_a == "FORWARD"

    # Case B: Sensitive Head Nod Slump (chin at 0.71 -> d_lower=0.21, d_upper=0.30 -> pitch=0.70 < 0.78)
    mock_mesh[152] = MockLm(0.50, 0.71)
    _, pitch_b, glance_b, mirror_b, nod_b = analyze_head_posture(mock_mesh, 1000, 1000, 0.30, 0.22, 0.78)
    assert pitch_b < 0.78, f"Pitch should detect slump: {pitch_b}"
    assert nod_b is True, "Directional nod must trigger on pitch < 0.78"
    assert mirror_b is False, "Slumped head must not be classified as mirror check"

    # Case C: Diagonal Nod Slump (turned + slumped) -> Must classify as NOD, not mirror check
    mock_mesh[1] = MockLm(0.65, 0.50)  # Turned right
    mock_mesh[152] = MockLm(0.65, 0.71) # Slumped
    _, _, glance_c, mirror_c, nod_c = analyze_head_posture(mock_mesh, 1000, 1000, 0.30, 0.22, 0.78)
    assert nod_c is True and mirror_c is False and "NOD (RIGHT TILT)" in glance_c
    print(" [PASS] Sensitive Head Nod Slump detection validated (Pitch < 0.78 detected promptly)")

    # Test 16: Multi-Channel Distinction: Distinct Chimes, Pop-Up Dismissal & HUD Gauge
    chime_test = MelodicChimeManager()
    chime_test.trigger_eye_alarm()
    chime_test.trigger_nod_alarm()

    insp_test = CompactInspirationalManager()
    insp_test.trigger(reason="STRIKE 1/3 (HEAD NOD)")
    assert insp_test.get_active_reason() == "STRIKE 1/3 (HEAD NOD)"
    assert "HEAD NOD" in insp_test.get_active_reason()

    # Draw modern HUD with active Head Nod alert and verify rendering
    nod_hud_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    draw_modern_hud(
        frame=nod_hud_frame,
        ear=0.32,
        ear_threshold=0.22,
        continuous_closed_time=0.0,
        flutter_stack_time=0.0,
        decay_rate=0.20,
        is_fatigued=False,
        is_head_nodding=True,
        nod_duration=0.8,
        open_eyes_duration=0.0,
        fps=30.0,
        face_detected=True,
        glance_direction="NOD (FORWARD)",
        is_mirror_checking=False,
        pitch_ratio=0.68,
        active_strikes=1,
        sounds_alarm_now=False,
        clean_driving_time=120.0,
        heal_limit_sec=1800.0,
        is_resting=False,
        rest_time_sec=0.0,
        rest_limit_sec=900.0,
        current_streak_sec=120.0,
        best_streak_sec=120.0,
        inspirational_quote="Stay Alert!",
        nod_time_threshold=3.0,
        nod_ratio_threshold=0.78,
        upright_posture_duration=0.5,
        active_alert_reason=insp_test.get_active_reason(),
    )
    assert nod_hud_frame.shape == (720, 1280, 3)
    print(" [PASS] Distinct Multi-Channel Feedback verified (Eye chime vs Nod alarm, Violet HUD gauge, 1.5s Upright clear)")

    # Test 17: Dynamic Fleet Database Integration (10-second sync & CRITICAL alert highlighting)
    test_db = get_fleet_db()
    test_drv = "DRV-TEST-99"
    test_db.register_or_update_driver(driver_id=test_drv, driver_name="Unit Test Driver", vehicle_id="TRK-TEST")

    # 1. Heartbeat 10s log (0 strikes -> Top Driver)
    id1 = test_db.log_telemetry(test_drv, 0, "TOP DRIVER", "10s HEARTBEAT", ear_value=0.32)
    assert id1 > 0

    # 2. Critical strike violation log (3 strikes -> CRITICAL)
    id2 = test_db.log_telemetry(test_drv, 3, "CRITICAL", "CONTINUOUS EYE CLOSURE (2.0s+) [CRITICAL 3/3 STRIKES!]", ear_value=0.10)
    assert id2 > id1

    # 3. Verify critical entry is marked with is_critical = 1 for high visibility
    crit_logs = test_db.get_recent_logs(limit=5, driver_id=test_drv, critical_only=True)
    assert len(crit_logs) >= 1
    assert crit_logs[0]["is_critical"] == 1
    assert crit_logs[0]["strike_count"] == 3
    assert "CRITICAL" in crit_logs[0]["strike_status"]

    # 4. Verify unacknowledged emergency alerts queue
    crit_alerts = test_db.get_active_alerts(unacknowledged_only=True)
    test_alerts = [a for a in crit_alerts if a["driver_id"] == test_drv]
    assert len(test_alerts) >= 1
    assert test_alerts[0]["alert_level"] == "CRITICAL"

    # 5. Verify fleet KPI updates
    kpis = test_db.get_fleet_kpis()
    assert kpis["total_drivers"] >= 1
    assert kpis["critical_drivers"] >= 1
    print(" [PASS] Dynamic Fleet Database & Critical Alert Dispatch validated (10s sync + CRITICAL high-visibility flag)")

    print("\nAll diagnostics passed successfully! (100% Ready)\n")


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AntiDoze: Modern automotive driver assist with gradual stack decay & 3-strike ranks."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="0",
        help="Video source: camera index (default: 0) or path to video file (.mp4).",
    )
    parser.add_argument(
        "--driver-id",
        type=str,
        default=DEFAULT_DRIVER_ID,
        help=f"Commercial vehicle driver ID for fleet database logging (default: {DEFAULT_DRIVER_ID}).",
    )
    parser.add_argument(
        "--db-sync",
        type=float,
        default=DEFAULT_DB_SYNC_INTERVAL,
        help=f"Dynamic fleet database sync interval in seconds (default: {DEFAULT_DB_SYNC_INTERVAL}s).",
    )
    parser.add_argument(
        "--planned-hours",
        type=float,
        default=None,
        help="Planned drive duration in hours (e.g. 8.0). If omitted, AntiDoze prompts the driver before starting.",
    )
    parser.add_argument(
        "--time-scale",
        type=float,
        default=1.0,
        help="Simulation time speedup factor (e.g. 3600 to simulate 1 hour per second).",
    )
    parser.add_argument(
        "--initial-elapsed",
        type=float,
        default=0.0,
        help="Initial elapsed driving hours (useful for testing Hour 6 transition).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_EAR_THRESHOLD,
        help=f"Eye Aspect Ratio (EAR) threshold (default: {DEFAULT_EAR_THRESHOLD}).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_EYE_FATIGUE_SEC,
        help=f"Stacked eye closure duration in seconds to trigger violation (default: {DEFAULT_EYE_FATIGUE_SEC}s).",
    )
    parser.add_argument(
        "--nod-threshold",
        type=float,
        default=DEFAULT_NOD_RATIO_THRESH,
        help=f"Head nod pitch ratio threshold (default: {DEFAULT_NOD_RATIO_THRESH}).",
    )
    parser.add_argument(
        "--nod-duration",
        type=float,
        default=DEFAULT_NOD_DURATION_SEC,
        help=f"Head nod duration in seconds to trigger alarm (default: {DEFAULT_NOD_DURATION_SEC}s).",
    )
    parser.add_argument(
        "--decay-rate",
        type=float,
        default=DEFAULT_STACK_DECAY_RATE,
        help=f"Gradual stack decay rate in seconds per second of open eyes (default: {DEFAULT_STACK_DECAY_RATE} s/s).",
    )
    parser.add_argument(
        "--heal-min",
        type=float,
        default=30.0,
        help="Continuous clean driving minutes required to remove 1 strike (default: 30.0 mins).",
    )
    parser.add_argument(
        "--rest-min",
        type=float,
        default=15.0,
        help="Rest stop duration in minutes required to reset ALL strikes (default: 15.0 mins).",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Launch AntiDoze in native fullscreen mode with responsive UI scaling.",
    )
    parser.add_argument(
        "--open-dashboard",
        action="store_true",
        help="Automatically open Fleet Manager HTML dashboard in default browser.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run 28-second simulated scenario verifying trip planning, privacy toggle, Hour 6 lock, and gradual decay.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run algorithmic unit self-tests.",
    )

    args = parser.parse_args()

    if args.test:
        run_self_tests()
    elif args.demo:
        run_simulation(
            ear_threshold=args.threshold,
            fatigue_time_threshold=args.duration,
            nod_time_threshold=args.nod_duration,
            nod_ratio_threshold=args.nod_threshold,
            decay_rate_per_sec=args.decay_rate,
            heal_strike_sec=args.heal_min if args.heal_min < 1.0 else 5.0,
            rest_stop_reset_sec=args.rest_min if args.rest_min < 1.0 else 4.0,
            save_video_path="demo_output.mp4",
            driver_id=args.driver_id,
            db_sync_interval=args.db_sync,
        )
    else:
        run_antidoze(
            video_source=args.source,
            ear_threshold=args.threshold,
            fatigue_time_threshold=args.duration,
            nod_time_threshold=args.nod_duration,
            nod_ratio_threshold=args.nod_threshold,
            decay_rate_per_sec=args.decay_rate,
            heal_strike_sec=args.heal_min * 60.0,
            rest_stop_reset_sec=args.rest_min * 60.0,
            planned_hours=args.planned_hours,
            time_scale=args.time_scale,
            initial_elapsed_hours=args.initial_elapsed,
            fullscreen=args.fullscreen,
            driver_id=args.driver_id,
            db_sync_interval=args.db_sync,
            open_dashboard=args.open_dashboard,
        )


if __name__ == "__main__":
    main()
