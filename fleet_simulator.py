"""
AntiDoze Fleet Dynamic Telemetry Simulator
==========================================
Simulates multiple commercial drivers logging real-time telemetry into
'antidoze_fleet.db' every 10 seconds. Demonstrates normal driving, caution/warning
events, and an escalating CRITICAL fatigue event to verify high-visibility
alerting for the Fleet Manager.

Usage:
  python fleet_simulator.py                # Runs 10-second update cycles continuously
  python fleet_simulator.py --rounds 5     # Run 5 cycles (50s) and exit
  python fleet_simulator.py --fast         # Fast-forward 2-second cycles for testing
"""

import argparse
import random
import sys
import time
from datetime import datetime

# Configure Windows stdout for safe terminal printing
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fleet_database import get_fleet_db


def run_fleet_simulation(rounds: int = 0, interval_sec: float = 10.0):
    """
    Simulates fleet vehicles sending dynamic updates to the database every 10 seconds.
    Demonstrates:
      1. Normal 10-second heartbeats for alert drivers.
      2. Caution (1/3 strikes) for DRV-204 due to blink flutter.
      3. Escalating Warning (2/3) and CRITICAL (3/3) emergency for DRV-308.
      4. Rest stop and clean driving recovery.
    """
    db = get_fleet_db()
    print("=" * 72)
    print(" ANTIDOZE: 10-SECOND DYNAMIC FLEET DATABASE SIMULATOR ")
    print("=" * 72)
    print(f" Database Target  : {db.db_path}")
    print(f" Update Interval  : {interval_sec:.1f} seconds")
    print(f" Total Rounds     : {'Infinite (Ctrl+C to stop)' if rounds <= 0 else f'{rounds} rounds'}")
    print("=" * 72)

    # In-memory driver simulation states
    fleet_state = {
        "DRV-101": {
            "name": "Alex Miller",
            "vehicle": "TRK-9021",
            "route": "Chicago, IL -> Denver, CO (I-80 W)",
            "strikes": 0,
            "status": "TOP DRIVER",
            "streak_sec": 420,
            "trip_sec": 5400,
            "ear": 0.32,
            "pitch": 1.05,
            "location": "I-80 Mile 184",
        },
        "DRV-204": {
            "name": "Sarah Connor",
            "vehicle": "TRK-4412",
            "route": "Dallas, TX -> Atlanta, GA (I-20 E)",
            "strikes": 0,
            "status": "TOP DRIVER",
            "streak_sec": 920,
            "trip_sec": 8100,
            "ear": 0.29,
            "pitch": 1.02,
            "location": "I-20 Mile 312",
        },
        "DRV-308": {
            "name": "Marcus Vance",
            "vehicle": "TRK-8850",
            "route": "Seattle, WA -> Boise, ID (I-84 E)",
            "strikes": 1,
            "status": "CAUTION",
            "streak_sec": 45,
            "trip_sec": 17400,
            "ear": 0.24,
            "pitch": 0.85,
            "location": "I-84 Mile 78",
        },
        "DRV-415": {
            "name": "Elena Rostova",
            "vehicle": "TRK-2209",
            "route": "Los Angeles, CA -> Phoenix, AZ (I-10 E)",
            "strikes": 0,
            "status": "TOP DRIVER",
            "streak_sec": 1820,
            "trip_sec": 6300,
            "ear": 0.34,
            "pitch": 1.08,
            "location": "I-10 Mile 95",
        },
    }

    # Ensure drivers are registered
    for d_id, state in fleet_state.items():
        db.register_or_update_driver(
            driver_id=d_id,
            driver_name=state["name"],
            vehicle_id=state["vehicle"],
            route_name=state["route"],
        )

    current_round = 0

    try:
        while True:
            current_round += 1
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[ROUND {current_round:02d} @ {now_str}] Syncing 10-second telemetry to database...")

            # Scenario Scripted Progression
            for d_id, state in fleet_state.items():
                state["trip_sec"] += int(interval_sec)
                state["streak_sec"] += int(interval_sec)

                # Format times
                trip_hms = f"{state['trip_sec'] // 3600:02d}:{(state['trip_sec'] % 3600) // 60:02d}:{state['trip_sec'] % 60:02d}"
                streak_hms = f"{state['streak_sec'] // 60:02d}:{state['streak_sec'] % 60:02d}"

                alert_type = "10s HEARTBEAT"
                glance = "FORWARD"

                # Scenario specific driver events:
                if d_id == "DRV-101":
                    # Stable alert driving
                    state["ear"] = round(0.30 + random.uniform(-0.03, 0.04), 3)
                    state["pitch"] = round(1.05 + random.uniform(-0.04, 0.04), 2)
                    if random.random() < 0.2:
                        glance = random.choice(["LEFT MIRROR", "RIGHT MIRROR"])
                        alert_type = "MIRROR CHECK"

                elif d_id == "DRV-204":
                    # Round 2: Drowsy blink flutter sequence
                    if current_round == 2:
                        state["strikes"] = 1
                        state["status"] = "CAUTION"
                        state["streak_sec"] = 0
                        state["ear"] = 0.16
                        alert_type = "FLUTTER STACK (2.0s) [STRIKE 1/3]"
                        print(f"  [WARN] [{d_id}] FLUTTER VIOLATION: Escalated to CAUTION (1/3 Strikes)!")
                    elif current_round > 2:
                        state["ear"] = 0.29

                elif d_id == "DRV-308":
                    # Round 2: Head Nod Slump -> Escalate to Warning (2/3)
                    if current_round == 2:
                        state["strikes"] = 2
                        state["status"] = "WARNING"
                        state["streak_sec"] = 0
                        state["pitch"] = 0.68
                        glance = "NOD (FORWARD)"
                        alert_type = "HEAD NOD SLUMP [STRIKE 2/3]"
                        print(f"  [WARN] [{d_id}] HEAD NOD SLUMP: Escalated to WARNING (2/3 Strikes)!")
                    # Round 4: Severe Eye Closure -> Escalate to CRITICAL (3/3 Strikes)!
                    elif current_round == 4:
                        state["strikes"] = 3
                        state["status"] = "CRITICAL"
                        state["streak_sec"] = 0
                        state["ear"] = 0.11
                        alert_type = "CONTINUOUS EYE CLOSURE (2.0s+) [CRITICAL 3/3 STRIKES!]"
                        print(f"\n  [!!! EMERGENCY !!!] [{d_id}] Reached CRITICAL (3/3 Strikes)! Alarm active in cab!\n")
                    elif current_round > 4:
                        # Stays critical until pulled over
                        state["strikes"] = 3
                        state["status"] = "CRITICAL"
                        alert_type = "CRITICAL HEARTBEAT (PULL OVER REQUIRED)"

                elif d_id == "DRV-415":
                    # Round 3: Driver enters Rest Stop
                    if current_round >= 3:
                        alert_type = "REST STOP ACTIVE (PARKED)"
                        state["ear"] = 0.35

                # Log to Dynamic SQLite Database
                log_id = db.log_telemetry(
                    driver_id=d_id,
                    strike_count=state["strikes"],
                    strike_status=state["status"],
                    alert_type=alert_type,
                    ear_value=state["ear"],
                    head_pitch=state["pitch"],
                    glance_direction=glance,
                    clean_streak=streak_hms,
                    trip_elapsed=trip_hms,
                    camera_mode="ACTIVE",
                    vehicle_id=state["vehicle"],
                    location=state["location"],
                    timestamp=now_str,
                )

                crit_tag = " [*** CRITICAL ENTRY RECORDED ***]" if state["strikes"] >= 3 else ""
                print(f"  -> Log #{log_id:04d} | {d_id} ({state['name']}) | Status: {state['status']:<11} | Event: {alert_type:<32}{crit_tag}")

            if rounds > 0 and current_round >= rounds:
                print(f"\n[COMPLETE] Reached planned {rounds} simulation rounds.")
                break

            print(f" Waiting {interval_sec:.1f}s for next dynamic database update...")
            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n[INFO] Simulation stopped by user.")
    finally:
        for d_id, state in fleet_state.items():
            db.set_driver_inactive(driver_id=d_id, strike_count=state["strikes"], strike_status=state["status"])
        print("[INFO] Simulated fleet marked as INACTIVE in database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AntiDoze Dynamic Fleet Database Telemetry Simulator")
    parser.add_argument("--rounds", type=int, default=0, help="Number of 10s cycles to simulate (0 = continuous)")
    parser.add_argument("--interval", type=float, default=10.0, help="Update interval in seconds (default: 10.0)")
    parser.add_argument("--fast", action="store_true", help="Run fast 2-second intervals for quick testing")

    args = parser.parse_args()
    intvl = 2.0 if args.fast else args.interval
    run_fleet_simulation(rounds=args.rounds, interval_sec=intvl)
