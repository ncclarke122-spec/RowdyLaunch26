"""
AntiDoze Fleet Terminal Live Monitor
====================================
Console-based dynamic database viewer for fleet supervisors.
Continuously polls 'antidoze_fleet.db' every 10 seconds and renders
real-time telemetry logs with high-visibility ANSI styling for Critical alerts.

Usage:
  python fleet_terminal_monitor.py                # 10s live database monitor
  python fleet_terminal_monitor.py --critical     # Filter for Critical incidents only
  python fleet_terminal_monitor.py --driver DRV-101
"""

import argparse
import os
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

# ANSI Color Codes
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_ORANGE = "\033[38;5;208m"
CLR_RED = "\033[91m"
CLR_BG_RED = "\033[41m\033[97m\033[1m"  # High-visibility white text on bright red background
CLR_BG_DARK = "\033[48;5;235m"


def clear_console():
    """Clears terminal screen cross-platform."""
    os.system("cls" if os.name == "nt" else "clear")


def format_status_badge(strike_count: int, strike_status: str, is_critical: bool) -> str:
    """Returns ANSI formatted status badge."""
    if is_critical or strike_count >= 3 or "CRITICAL" in strike_status.upper():
        return f"{CLR_BG_RED} [!!! CRITICAL (3/3) !!!] {CLR_RESET}"
    elif strike_count == 2 or "WARNING" in strike_status.upper():
        return f"{CLR_ORANGE} [WARN] WARNING (2/3)    {CLR_RESET}"
    elif strike_count == 1 or "CAUTION" in strike_status.upper():
        return f"{CLR_YELLOW} [CAUTION] CAUTION (1/3) {CLR_RESET}"
    else:
        return f"{CLR_GREEN} [SAFE] TOP DRIVER (0/3) {CLR_RESET}"


def display_dashboard(db, driver_id=None, critical_only=False, limit=15):
    """Renders the dynamic database state in high contrast."""
    kpis = db.get_fleet_kpis()
    logs = db.get_recent_logs(limit=limit, driver_id=driver_id, critical_only=critical_only)
    drivers = db.get_all_drivers()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"{CLR_BOLD}{CLR_CYAN}========================================================================================{CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_CYAN} ANTIDOZE FLEET COMMAND • DYNAMIC DATABASE MONITOR (10-SECOND REFRESH)                {CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_CYAN}========================================================================================{CLR_RESET}")
    print(f" Current System Time : {now_str}  |  Database: {db.db_path}")

    # KPI Summary line
    crit_color = CLR_BG_RED if kpis["critical_drivers"] > 0 else CLR_GREEN
    active_cnt = kpis.get("active_drivers", 0)
    inactive_cnt = kpis.get("inactive_drivers", 0)
    print(
        f" Fleet Drivers : {kpis['total_drivers']} total ({CLR_GREEN}{active_cnt} connected{CLR_RESET}, {CLR_DIM}{inactive_cnt} inactive{CLR_RESET})  |  "
        f"Critical : {crit_color} {kpis['critical_drivers']} {CLR_RESET}  |  "
        f"Warning : {CLR_ORANGE}{kpis['warning_drivers']}{CLR_RESET}  |  "
        f"Caution : {CLR_YELLOW}{kpis['caution_drivers']}{CLR_RESET}  |  "
        f"Top Drivers : {CLR_GREEN}{kpis['top_drivers']}{CLR_RESET}  |  "
        f"Total Logs : {kpis['total_logs']}"
    )
    print(f"{CLR_CYAN}----------------------------------------------------------------------------------------{CLR_RESET}")

    # Emergency Callout if Critical drivers exist
    if kpis["critical_drivers"] > 0:
        print(f"\n{CLR_BG_RED} >>> EMERGENCY ALERT: CRITICAL DRIVER FATIGUE (3/3 STRIKES) DETECTED IN FLEET! <<< {CLR_RESET}")
        for d in drivers:
            if (d["is_critical"] == 1 or d["strike_count"] >= 3) and d.get("is_connected") == 1:
                print(f"{CLR_RED}   * DRIVER {d['driver_id']} ({d['driver_name']}) in {d['vehicle_id']} on {d['route_name']} — STATUS: {d['strike_status']}!{CLR_RESET}")
        print()

    # Active Drivers summary pills
    driver_pills = []
    for d in drivers:
        is_conn = bool(d.get("is_connected") == 1)
        conn_tag = f"{CLR_GREEN}ON{CLR_RESET}" if is_conn else f"{CLR_DIM}OFF{CLR_RESET}"
        if is_conn:
            d_badge = f"{CLR_BG_RED}CRIT{CLR_RESET}" if d["is_critical"] else (f"{CLR_YELLOW}{d['strike_count']}/3{CLR_RESET}" if d["strike_count"] > 0 else f"{CLR_GREEN}0/3{CLR_RESET}")
        else:
            d_badge = f"{CLR_DIM}STANDBY{CLR_RESET}"
        driver_pills.append(f"{d['driver_id']} ({conn_tag}): {d_badge}")
    print(" Active Cab Telemetry: " + "  |  ".join(driver_pills))
    print(f"{CLR_CYAN}----------------------------------------------------------------------------------------{CLR_RESET}")

    # Table Header
    print(f"{CLR_BOLD}{'STATUS':<25} {'DRIVER':<10} {'TIMESTAMP':<20} {'EVENT / ALERT':<24} {'VEHICLE':<10} {'EAR':<6} {'STREAK':<8}{CLR_RESET}")
    print("-" * 105)

    if not logs:
        print(f" {CLR_DIM}No telemetry records found matching filter.{CLR_RESET}")
    else:
        for row in logs:
            is_crit = (row["is_critical"] == 1 or row["strike_count"] >= 3 or "CRITICAL" in str(row["strike_status"]).upper())
            badge = format_status_badge(row["strike_count"], row["strike_status"], is_crit)
            drv_str = f"{CLR_BOLD}{row['driver_id']:<10}{CLR_RESET}"
            ts_str = f"{row['timestamp']:<20}"
            evt_str = f"{row['alert_type'][:23]:<24}"
            veh_str = f"{(row['vehicle_id'] or 'TRK-001'):<10}"
            ear_str = f"{(row['ear_value'] or 0.0):.3f}"
            streak_str = f"{(row['clean_streak'] or '00:00'):<8}"

            if is_crit:
                # Highly visible critical row formatting
                print(
                    f"{badge} {CLR_BG_RED} {row['driver_id']:<8} {row['timestamp']:<19} {row['alert_type'][:22]:<23} {veh_str} {ear_str} {streak_str} {CLR_RESET}"
                )
            else:
                print(f"{badge} {drv_str} {ts_str} {evt_str} {veh_str} {ear_str:<6} {streak_str}")

    print(f"{CLR_CYAN}========================================================================================{CLR_RESET}")
    print(f" [Auto-updating every 10s]  Press Ctrl+C to exit monitor.")


def run_monitor(driver_id=None, critical_only=False, interval_sec=10):
    """Main loop for terminal dynamic database monitor."""
    db = get_fleet_db()
    print("[INFO] Starting AntiDoze Dynamic Terminal Monitor...")

    try:
        while True:
            clear_console()
            display_dashboard(db, driver_id=driver_id, critical_only=critical_only)

            # 10-second countdown in place
            for remaining in range(interval_sec, 0, -1):
                sys.stdout.write(f"\r Next dynamic update in {remaining:2d}s... ")
                sys.stdout.flush()
                time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n[INFO] Monitor stopped by user.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AntiDoze Dynamic Fleet Database Terminal Monitor")
    parser.add_argument("--driver", type=str, default=None, help="Filter by Driver ID (e.g. DRV-101)")
    parser.add_argument("--critical", action="store_true", help="Display only Critical / Emergency alerts")
    parser.add_argument("--interval", type=int, default=10, help="Database refresh interval in seconds (default: 10)")

    args = parser.parse_args()
    run_monitor(driver_id=args.driver, critical_only=args.critical, interval_sec=args.interval)
